"""Phone verification, shared rate limits and exactly-once referral credits."""
import base64
import hashlib
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException


def verification_required():
    return os.environ.get('PHONE_VERIFICATION_REQUIRED', 'true').lower() == 'true'


def provider_ready():
    return bool(re.fullmatch(r'AC[0-9a-fA-F]{32}', os.environ.get('TWILIO_ACCOUNT_SID', ''))
                and re.fullmatch(r'VA[0-9a-fA-F]{32}', os.environ.get('TWILIO_VERIFY_SERVICE_SID', ''))
                and os.environ.get('TWILIO_AUTH_TOKEN'))


def provider_call(resource, data):
    if not provider_ready():
        raise HTTPException(503, 'A confirmação por SMS está indisponível. Entre em contato com a organização.')
    account = os.environ['TWILIO_ACCOUNT_SID']
    secret = os.environ['TWILIO_AUTH_TOKEN']
    service = os.environ['TWILIO_VERIFY_SERVICE_SID']
    auth = base64.b64encode((account + ':' + secret).encode()).decode()
    request = Request(f'https://verify.twilio.com/v2/Services/{service}/{resource}',
                      data=urlencode(data).encode(), headers={'Authorization': 'Basic ' + auth,
                      'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404 and resource == 'VerificationCheck':
            return {'status': 'expired'}
        if error.code == 429:
            raise HTTPException(429, 'Aguarde antes de tentar novamente.', headers={'Retry-After': '60'})
        raise HTTPException(502, 'Não foi possível confirmar o telefone. Tente novamente mais tarde.')
    except (URLError, TimeoutError, ValueError):
        raise HTTPException(502, 'O serviço de confirmação está temporariamente indisponível.')


def send_code(phone):
    data = provider_call('Verifications', {'To': '+55' + phone, 'Channel': 'sms', 'Locale': 'pt-BR'})
    if data.get('status') != 'pending' or not re.fullmatch(r'VE[0-9a-fA-F]{32}', data.get('sid', '')):
        raise HTTPException(502, 'Não foi possível enviar o código de confirmação.')
    return data['sid']


def check_code(sid, code):
    data = provider_call('VerificationCheck', {'VerificationSid': sid, 'Code': code})
    return data.get('status') == 'approved' and data.get('sid') == sid


def limit(connect, scope, key, maximum, seconds):
    if os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() != 'true':
        return
    stamp = int(time.time())
    bucket = stamp // seconds
    key_hash = hashlib.sha256((os.environ['PHONE_PEPPER'] + ':' + str(key)).encode()).hexdigest()
    with connect() as conn:
        row = conn.execute(
            'INSERT INTO request_limits (scope,key_digest,bucket,attempts,expires_at) '
            "VALUES (%s,%s,%s,1,now()+(%s * interval '1 second')) "
            'ON CONFLICT (scope,key_digest,bucket) DO UPDATE SET attempts=request_limits.attempts+1 RETURNING attempts',
            (scope, key_hash, bucket, seconds * 2)).fetchone()
        conn.execute('DELETE FROM request_limits WHERE expires_at<now()')
    if row['attempts'] > maximum:
        raise HTTPException(429, 'Muitas tentativas. Aguarde antes de tentar novamente.',
                            headers={'Retry-After': str(seconds - stamp % seconds)})


def serialize_referrals(conn):
    # All multi-player referral / verification updates share one transaction lock.
    # Spins lock one player only, then campaign, and never acquire this lock.
    conn.execute('SELECT pg_advisory_xact_lock(726389104)')


def bonus_limit():
    return min(1000, max(1, int(os.environ.get('REFERRAL_MAX_BONUS_SPINS', '20'))))


def award_referrals(conn, player_id):
    rows = conn.execute(
        "SELECT r.referred_id,r.referrer_id FROM referrals r "
        'JOIN players a ON a.id=r.referrer_id JOIN players b ON b.id=r.referred_id '
        "WHERE r.status='pending' AND (r.referrer_id=%s OR r.referred_id=%s) "
        'AND a.phone_verified_at IS NOT NULL AND b.phone_verified_at IS NOT NULL '
        'ORDER BY r.referrer_id,r.referred_id', (player_id, player_id)).fetchall()
    for row in rows:
        parent = conn.execute('SELECT id,bonus_spins_earned FROM players WHERE id=%s FOR UPDATE', (row['referrer_id'],)).fetchone()
        won = conn.execute('SELECT id FROM prizes WHERE player_id=%s', (parent['id'],)).fetchone()
        if won or parent['bonus_spins_earned'] >= bonus_limit():
            conn.execute("UPDATE referrals SET status='blocked' WHERE referred_id=%s", (row['referred_id'],))
            continue
        conn.execute('UPDATE players SET spins_left=spins_left+1,bonus_spins_earned=bonus_spins_earned+1 WHERE id=%s', (parent['id'],))
        conn.execute("UPDATE referrals SET status='credited',credited_at=now() WHERE referred_id=%s", (row['referred_id'],))


def referral_state(conn, player):
    pending = conn.execute("SELECT count(*) AS n FROM referrals WHERE referrer_id=%s AND status='pending'", (player['id'],)).fetchone()['n']
    return {'phone_verified': player.get('phone_verified_at') is not None,
            'verification_required': verification_required(),
            'referral_code': player.get('referral_code'), 'bonus_spins_earned': player.get('bonus_spins_earned', 0),
            'referrals_pending': pending, 'referral_bonus_limit': bonus_limit()}
