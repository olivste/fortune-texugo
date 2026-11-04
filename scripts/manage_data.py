#!/usr/bin/env python3
"""Auditable CPF cleanup and encrypted, expiring application-managed backups."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['cleanup','backup'])
    parser.add_argument('--env-file')
    args=parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file)
    from api.main import connect
    from api import retention,accounts
    if args.action=='cleanup':
        print(json.dumps(retention.cleanup(connect),default=str))
        return
    if datetime.now(timezone.utc)>=accounts.DEADLINE:
        raise SystemExit('CPF backup window closed; run cleanup and review external backups.')
    from cryptography.fernet import Fernet
    key=os.environ.get('BACKUP_ENCRYPTION_KEY')
    root=os.environ.get('MANAGED_BACKUP_DIRECTORY')
    if not key or not root:
        raise SystemExit('Configure BACKUP_ENCRYPTION_KEY and MANAGED_BACKUP_DIRECTORY.')
    folder=Path(root).resolve()
    if folder==ROOT/'assets' or ROOT/'assets' in folder.parents:
        raise SystemExit('Managed backups must be outside public assets.')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    # DATABASE_URL never appears in command arguments or console output.
    result=subprocess.run(['pg_dump','--no-owner','--no-acl','--format=custom'],
                          env={**os.environ,'PGDATABASE':os.environ['DATABASE_URL']},capture_output=True)
    if result.returncode:
        raise SystemExit('pg_dump failed; no backup saved. Check local PostgreSQL tooling and access.')
    identifier=uuid4().hex
    path=folder/(identifier+'.ftbackup')
    path.write_bytes(Fernet(key.encode()).encrypt(result.stdout));path.chmod(0o600)
    manifest=folder/(identifier+'.fortune-backup.json')
    manifest.write_text(json.dumps({'archive':path.name,'created_at':datetime.now(timezone.utc).isoformat(),
                                    'expires_at':accounts.DEADLINE.isoformat()}));manifest.chmod(0o600)
    print('Encrypted managed backup created with expiry manifest. No plaintext dump was written.')


if __name__=='__main__':
    main()
