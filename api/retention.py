"""Auditable CPF erasure. External backup copies require an operator-confirmed review."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from psycopg.types.json import Jsonb
from api.accounts import DEADLINE


def cleanup(connect, clock=None):
    clock = clock or datetime.now(timezone.utc)
    if clock < DEADLINE:
        return {'due': False, 'deleted': 0}
    backup_report = {'managed_deleted': 0, 'errors': [], 'external_backups': 'pending_operator_review',
                     'logs': 'Application does not log CPF or request bodies; inspect proxy/APM exports separately.'}
    root_value = os.environ.get('MANAGED_BACKUP_DIRECTORY')
    if root_value:
        root = Path(root_value).resolve()
        # Only application-managed archives with explicit manifests; never arbitrary files.
        for manifest in root.glob('*.fortune-backup.json'):
            try:
                metadata = json.loads(manifest.read_text())
                archive = root / metadata['archive']
                if archive.resolve().parent != root or archive.is_symlink() or manifest.is_symlink():
                    raise ValueError('Unsafe backup path')
                expiry = datetime.fromisoformat(metadata['expires_at'])
                if expiry.tzinfo is None:
                    raise ValueError('Missing timezone')
                if expiry <= clock or clock >= DEADLINE:
                    archive.unlink(missing_ok=True)
                    manifest.unlink()
                    backup_report['managed_deleted'] += 1
            except (OSError, ValueError, KeyError, TypeError):
                backup_report['errors'].append('Managed archive requires operator review')
    with connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(726389105)')
        result = conn.execute('UPDATE accounts a SET cpf_cipher=NULL,cpf_lookup=NULL,cpf_last2=NULL,cpf_deleted_at=%s '
                              'WHERE cpf_cipher IS NOT NULL AND NOT EXISTS (SELECT 1 FROM cpf_retention_holds h WHERE h.account_id=a.id AND h.until_at>%s) RETURNING id',
                              (clock,clock)).fetchall()
        conn.execute("DELETE FROM request_limits WHERE scope IN ('account-register-cpf','login-account')")
        conn.execute("UPDATE spins SET response=response-'user' WHERE response ? 'user' AND player_id IN (SELECT id FROM accounts WHERE cpf_cipher IS NULL)")
        held = conn.execute('SELECT count(*) AS n FROM accounts WHERE cpf_cipher IS NOT NULL').fetchone()['n']
        backup_report['retained_under_documented_hold'] = held
        conn.execute('INSERT INTO retention_runs(deleted_count,backup_report) VALUES(%s,%s)',(len(result),Jsonb(backup_report)))
    return {'due':True,'deleted':len(result),'backup_report':backup_report}
