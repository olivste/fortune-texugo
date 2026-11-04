"""Cookie-authenticated accounts and transactional spin wallet, integrated with existing players."""
import csv
import hashlib
import hmac
import io
import os
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Optional, Literal

import psycopg
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator
from api import security, participation

COOKIE = 'fortune_account'
DEADLINE = datetime(2026, 12, 5, 3, tzinfo=timezone.utc)


def now():
    return datetime.now(timezone.utc)


def referral_limit():
    return None  # Every eligible new referral earns one spin; no invitation cap.


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(main, request, write=False):
    token = request.cookies.get(COOKIE, '')
    with main.connect() as conn:
        user = conn.execute("SELECT a.*,s.csrf_token,s.token_digest FROM account_sessions s JOIN accounts a ON a.id=s.account_id "
                            'WHERE s.token_digest=%s AND s.expires_at>now()', (fingerprint(token),)).fetchone()
    if not token or not user:
        raise HTTPException(401, 'Faça login para continuar')
    if user['status'] != 'active':
        raise HTTPException(403, 'Conta suspensa. Entre em contato com a organização.')
    if write and not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), user['csrf_token']):
        raise HTTPException(403, 'Sessão de segurança inválida. Recarregue a página.')
    return user


def cookie_session(conn, response, account_id):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    conn.execute('DELETE FROM account_sessions WHERE expires_at<=now()')
    conn.execute('INSERT INTO account_sessions(token_digest,account_id,csrf_token) VALUES(%s,%s,%s)',
                 (fingerprint(token), account_id, csrf))
    response.set_cookie(COOKIE, token, max_age=604800, httponly=True,
                        secure=os.environ.get('COOKIE_SECURE', 'true').lower() == 'true', samesite='lax', path='/')
    return csrf


def lock_account(conn, account_id):
    user = conn.execute('SELECT p.*,a.instagram,a.status FROM players p JOIN accounts a ON a.id=p.id WHERE p.id=%s FOR UPDATE OF p,a',
                        (account_id,)).fetchone()
    if not user or user['status'] != 'active':
        raise HTTPException(403, 'Conta indisponível ou suspensa')
    return user


def movement(conn, player_id, kind, amount, source, operation, allow_winner=False):
    player = conn.execute('SELECT spins_left FROM players WHERE id=%s FOR UPDATE', (player_id,)).fetchone()
    previous = conn.execute('SELECT balance,kind,amount,source FROM spin_ledger WHERE player_id=%s AND operation_id=%s', (player_id, operation)).fetchone()
    if previous:
        if (previous['kind'],previous['amount'],previous['source']) != (kind,amount,source):
            raise HTTPException(409,'Identificador de operação já utilizado com outros dados')
        return previous['balance']
    if amount > 0 and not allow_winner and conn.execute('SELECT id FROM prizes WHERE player_id=%s', (player_id,)).fetchone():
        raise HTTPException(409, 'Quem já ganhou não recebe novos giros')
    balance = player['spins_left'] + amount
    if balance < 0 or balance > 1000000:
        raise HTTPException(409, 'Saldo insuficiente ou limite de saldo atingido')
    conn.execute('UPDATE players SET spins_left=%s WHERE id=%s', (balance, player_id))
    conn.execute('INSERT INTO spin_ledger(player_id,kind,amount,balance,source,operation_id) VALUES(%s,%s,%s,%s,%s,%s)',
                 (player_id, kind, amount, balance, source, operation))
    return balance


def withdrawal_code(conn, player):
    account = conn.execute('SELECT cpf_cipher FROM accounts WHERE id=%s', (player['id'],)).fetchone()
    # After scheduled CPF erasure, preserve the opaque identifier already assigned.
    if not account or not account['cpf_cipher']:
        return player['claim_code_base']
    cpf = security.decrypt_cpf(account['cpf_cipher'])
    plain = unicodedata.normalize('NFKD',player['name']).encode('ascii','ignore').decode().lower()
    base = (re.sub(r'[^a-z]','',plain) or 'participante') + cpf[-3:]
    code = base
    # Equal names and CPF suffixes can coincide. Keep all issued codes unambiguous.
    suffix = 0
    while conn.execute('SELECT id FROM prizes WHERE lower(claim_code)=lower(%s) OR lower(legacy_claim_code)=lower(%s)', (code,code)).fetchone():
        suffix += 1
        code = base + 'id' + str(player['id']) + (str(suffix) if suffix>1 else '')
    conn.execute('UPDATE players SET claim_code_base=%s WHERE id=%s',(code,player['id']))
    return code


def profile(main, conn, account_id):
    player = lock_account(conn, account_id)
    account = conn.execute('SELECT terms_version,privacy_version,accepted_at,cpf_last2,cpf_deleted_at FROM accounts WHERE id=%s', (account_id,)).fetchone()
    prize = conn.execute('SELECT claim_code,redeemed_at,prize_name,prize_symbol FROM prizes WHERE player_id=%s', (account_id,)).fetchone()
    counts = conn.execute("SELECT count(*) AS total,count(*) FILTER(WHERE status='credited') AS credited,"
                          "count(*) FILTER(WHERE status='pending') AS pending FROM account_referrals WHERE referrer_id=%s", (account_id,)).fetchone()
    extra = conn.execute("SELECT coalesce(sum(amount),0) AS n FROM spin_ledger WHERE player_id=%s AND kind='CODIGO_PROMOCIONAL'", (account_id,)).fetchone()['n']
    return {**main.campaign_state(conn), 'authenticated': True, 'user': {'id': account_id, 'name': player['name'],
            'instagram': player['instagram'], 'cpf_masked': '***.***.***-' + account['cpf_last2'] if account['cpf_last2'] else 'Eliminado',
            'status': player['status'], **{k: account[k] for k in ('terms_version','privacy_version','accepted_at')}},
            'spins_left': 0 if prize else player['spins_left'], 'max_spins': 3+counts['credited']+extra,
            'referral_code': '@'+player['instagram'], 'referrals_total': counts['total'], 'referrals_pending': counts['pending'],
            'bonus_spins_earned': counts['credited'], 'referral_bonus_limit': referral_limit(),
            'referral_bonus_remaining': None,
            'verification_required': False, 'phone_verified': True, 'prize': prize, 'unlimited_spins': False}


class Signup(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    cpf: str = Field(min_length=11, max_length=18)
    instagram: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(min_length=8, max_length=128)
    referral_instagram: str = Field(default='', max_length=40)
    terms_accepted: bool
    adult: bool
    terms_version: str = Field(max_length=40)
    privacy_version: str = Field(max_length=40)

    @model_validator(mode='after')
    def validate_account(self):
        self.name = ' '.join(self.name.split())
        if len(self.name.split()) < 2:
            raise ValueError('Informe nome completo')
        if self.password != self.password_confirmation:
            raise ValueError('As senhas não conferem')
        if not self.terms_accepted or not self.adult:
            raise ValueError('Aceite os termos e declare ter pelo menos 18 anos')
        return self


class Login(BaseModel):
    cpf: str = Field(default='', max_length=18)
    instagram: str = Field(default='', max_length=40)
    password: str = Field(min_length=1, max_length=128)


class PromoRedeem(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    operation_id: UUID


def normalize_code(value):
    value = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9_-]{3,40}', value):
        raise HTTPException(422, 'Código deve ter de 3 a 40 letras, números, traços ou sublinhados')
    return value


class PromoSettings(BaseModel):
    code: str = Field(default='', max_length=40)
    spins: int = Field(ge=1, le=1000, strict=True)
    max_redemptions: int = Field(ge=1, le=1000000, strict=True)
    starts_at: datetime = Field(default_factory=lambda: now())
    expires_at: Optional[datetime] = None
    active: bool = True
    description: str = Field(default='', max_length=200)
    version: int = Field(default=1, ge=1)

    @model_validator(mode='after')
    def dates(self):
        if self.starts_at.tzinfo is None or (self.expires_at is not None and (self.expires_at.tzinfo is None or self.expires_at <= self.starts_at)):
            raise ValueError('Informe datas com fuso e expiração posterior ao início')
        return self


class Adjustment(BaseModel):
    amount: int = Field(ge=-1000000, le=1000000, strict=True)
    reason: str = Field(min_length=5, max_length=200)
    operation_id: UUID


class AccountStatus(BaseModel):
    status: str = Field(pattern='^(active|suspended)$')
    reason: str = Field(min_length=5, max_length=200)


class CampaignReset(BaseModel):
    confirmation: Literal['RESETAR CAMPANHA']
    understood: Literal[True]
    reason: str = Field(min_length=5, max_length=200)
    operation_id: UUID
    version: int = Field(ge=1)


class RetentionHold(BaseModel):
    reason: str = Field(min_length=10, max_length=200)
    legal_basis: str = Field(min_length=5, max_length=200)
    until_at: datetime

    @field_validator('until_at')
    @classmethod
    def valid_deadline(cls,value):
        if value.tzinfo is None or value<=now():
            raise ValueError('Informe prazo futuro com fuso horário')
        return value


class BackupReview(BaseModel):
    evidence: str = Field(min_length=10,max_length=1000)


class ReferralReview(BaseModel):
    action: str = Field(pattern='^(approve|reject)$')
    reason: str = Field(min_length=5, max_length=200)


def credit_referral(conn, referred_id):
    row = conn.execute('SELECT * FROM account_referrals WHERE referred_id=%s FOR UPDATE', (referred_id,)).fetchone()
    if not row or row['status'] != 'pending':
        return False
    parent = lock_account(conn, row['referrer_id'])
    if conn.execute('SELECT id FROM prizes WHERE player_id=%s', (parent['id'],)).fetchone():
        conn.execute("UPDATE account_referrals SET status='rejected',reason='Participação encerrada após vitória',reviewed_at=now() WHERE referred_id=%s", (referred_id,))
        return False
    movement(conn, parent['id'], 'INDICACAO', 1, f'Cadastro indicado #{referred_id}', f'referral:{referred_id}')
    conn.execute("UPDATE account_referrals SET status='credited',reviewed_at=now() WHERE referred_id=%s", (referred_id,))
    return True


def install(main):
    router = APIRouter()
    admin = [Depends(main.require_admin)]

    def limited(request, scope, key=None, maximum=30, seconds=3600):
        participation.limit(main.connect, scope, key or request.client.host, maximum, seconds)

    def audit(conn, action, details):
        conn.execute('INSERT INTO admin_changes(action,details) VALUES(%s,%s)', (action, Jsonb(details)))

    @router.post('/api/account/register', status_code=201)
    def register(body: Signup, request: Request, response: Response):
        limited(request, 'account-register', maximum=20)
        if now() >= DEADLINE:
            raise HTTPException(409, 'O período de cadastro com CPF foi encerrado')
        cpf = security.cpf(body.cpf)
        lookup = security.cpf_lookup(cpf)
        limited(request, 'account-register-cpf', lookup, 5)
        instagram = security.instagram(body.instagram)
        referral = security.instagram(body.referral_instagram) if body.referral_instagram.strip() else ''
        if referral == instagram:
            raise HTTPException(422, 'Você não pode indicar a si mesmo')
        if body.terms_version != os.environ.get('TERMS_VERSION','2026-11-04') or body.privacy_version != os.environ.get('PRIVACY_VERSION','2026-11-04'):
            raise HTTPException(409, 'Os documentos foram atualizados. Recarregue e leia novamente.')
        encrypted = security.encrypt_cpf(cpf)
        password_hash = security.PASSWORDS.hash(body.password)
        with main.connect() as conn:
            participation.serialize_referrals(conn)
            parent = conn.execute("SELECT id FROM accounts WHERE instagram=%s AND status='active'", (referral,)).fetchone() if referral else None
            if referral and not parent:
                raise HTTPException(422, 'Instagram do indicador não está cadastrado ou disponível')
            try:
                player_id = conn.execute('INSERT INTO players(name,session_digest,claim_code_base,spins_left) VALUES(%s,%s,%s,0) RETURNING id',
                                         (body.name, fingerprint(secrets.token_urlsafe(48)), 'FT'+secrets.token_hex(12).upper())).fetchone()['id']
                conn.execute('INSERT INTO accounts(id,cpf_lookup,cpf_cipher,cpf_last2,instagram,password_hash,terms_version,privacy_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                             (player_id,lookup,encrypted,cpf[-2:],instagram,password_hash,body.terms_version,body.privacy_version))
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409, 'CPF ou Instagram já cadastrado. Faça login.')
            movement(conn, player_id, 'CADASTRO', 3, 'Cadastro gratuito', 'signup')
            if parent:
                conn.execute('INSERT INTO account_referrals(referred_id,referrer_id) VALUES(%s,%s)', (player_id,parent['id']))
                credit_referral(conn, player_id)
            csrf = cookie_session(conn,response,player_id)
            return {**profile(main,conn,player_id), 'csrf_token':csrf}

    @router.post('/api/account/login')
    def login(body: Login, request: Request, response: Response):
        limited(request,'login-ip', maximum=30, seconds=900)
        if body.cpf:
            lookup = security.cpf_lookup(security.cpf(body.cpf))
            query, key = 'cpf_lookup', lookup
        else:
            query, key = 'instagram', security.instagram(body.instagram)
        limited(request,'login-account',key, 8, 900)
        with main.connect() as conn:
            user = conn.execute('SELECT id,password_hash,status FROM accounts WHERE '+query+'=%s', (key,)).fetchone()
            try:
                valid = security.PASSWORDS.verify(user['password_hash'] if user else security.DUMMY_HASH, body.password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not user or not valid:
                raise HTTPException(401,'CPF/Instagram ou senha incorretos')
            if user['status'] != 'active':
                raise HTTPException(403,'Conta suspensa. Entre em contato com a organização.')
            # Serialize with suspension; a concurrent suspension cannot leave a usable session.
            lock_account(conn,user['id'])
            if security.PASSWORDS.check_needs_rehash(user['password_hash']):
                conn.execute('UPDATE accounts SET password_hash=%s WHERE id=%s',(security.PASSWORDS.hash(body.password),user['id']))
            old = request.cookies.get(COOKIE,'')
            conn.execute('DELETE FROM account_sessions WHERE token_digest=%s',(fingerprint(old),))
            csrf = cookie_session(conn,response,user['id'])
            return {**profile(main,conn,user['id']), 'csrf_token':csrf}

    @router.get('/api/account/me')
    def me(request: Request):
        user=authenticate(main,request)
        with main.connect() as conn:
            return {**profile(main,conn,user['id']), 'csrf_token':user['csrf_token']}

    @router.post('/api/account/logout')
    def logout(request: Request,response: Response):
        user=authenticate(main,request,True)
        with main.connect() as conn:
            conn.execute('DELETE FROM account_sessions WHERE token_digest=%s',(user['token_digest'],))
        response.delete_cookie(COOKIE,path='/',secure=os.environ.get('COOKIE_SECURE','true').lower()=='true',httponly=True,samesite='lax')
        return {'logged_out':True}

    @router.get('/api/account/history')
    def history(request: Request):
        user=authenticate(main,request)
        with main.connect() as conn:
            return conn.execute('SELECT kind,amount,balance,source,created_at FROM spin_ledger WHERE player_id=%s ORDER BY id DESC LIMIT 200',(user['id'],)).fetchall()

    @router.post('/api/account/redeem')
    def redeem(body: PromoRedeem,request: Request):
        user=authenticate(main,request,True)
        limited(request,'promo-ip',maximum=60,seconds=900)
        limited(request,'promo-account',str(user['id']),20,900)
        code=normalize_code(body.code)
        with main.connect() as conn:
            lock_account(conn,user['id'])
            prior=conn.execute('SELECT promo_id FROM promo_redemptions WHERE player_id=%s AND operation_id=%s',(user['id'],body.operation_id)).fetchone()
            if prior:
                original=conn.execute('SELECT code FROM promo_codes WHERE id=%s',(prior['promo_id'],)).fetchone()
                if original['code']!=code:
                    raise HTTPException(409,'Identificador de operação já utilizado')
                return {**profile(main,conn,user['id']), 'replayed':True}
            promo=conn.execute('SELECT * FROM promo_codes WHERE code=%s FOR UPDATE',(code,)).fetchone()
            if not promo or not promo['active'] or promo['starts_at']>now():
                raise HTTPException(404,'Esse código não existe ou não está disponível.')
            if conn.execute('SELECT id FROM promo_redemptions WHERE player_id=%s AND promo_id=%s',(user['id'],promo['id'])).fetchone():
                raise HTTPException(409,'Você já resgatou esse código.')
            if promo['expires_at'] is not None and promo['expires_at']<=now():
                raise HTTPException(409,'Esse código expirou.')
            if promo['redeemed_count']>=promo['max_redemptions']:
                raise HTTPException(409,'Esse código atingiu o limite de resgates.')
            movement(conn,user['id'],'CODIGO_PROMOCIONAL',promo['spins'],'Código '+code,'promo:'+str(body.operation_id))
            conn.execute('INSERT INTO promo_redemptions(promo_id,player_id,spins,operation_id) VALUES(%s,%s,%s,%s)',(promo['id'],user['id'],promo['spins'],body.operation_id))
            conn.execute('UPDATE promo_codes SET redeemed_count=redeemed_count+1,version=version+1 WHERE id=%s',(promo['id'],))
            return {**profile(main,conn,user['id']),'credited':promo['spins'],'message':f"Código resgatado! Você recebeu {promo['spins']} giros extras."}

    @router.get('/api/admin/codes',dependencies=admin)
    def codes():
        with main.connect() as conn:
            rows=conn.execute('SELECT *,max_redemptions-redeemed_count AS remaining FROM promo_codes ORDER BY id DESC').fetchall()
            metrics=conn.execute("SELECT count(*) AS total,count(*) FILTER(WHERE active AND starts_at<=now() AND (expires_at IS NULL OR expires_at>now())) AS active,"
                                 "count(*) FILTER(WHERE expires_at<=now()) AS expired FROM promo_codes").fetchone()
            totals=conn.execute('SELECT count(*) AS redemptions,coalesce(sum(spins),0) AS spins FROM promo_redemptions').fetchone()
            return {'items':rows,'metrics':{**metrics,**totals}}

    @router.post('/api/admin/codes',dependencies=admin,status_code=201)
    def create_code(body: PromoSettings):
        code=normalize_code(body.code) if body.code else secrets.token_hex(8).upper()
        with main.connect() as conn:
            try:
                row=conn.execute('INSERT INTO promo_codes(code,spins,max_redemptions,starts_at,expires_at,active,description) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                                 (code,body.spins,body.max_redemptions,body.starts_at,body.expires_at,body.active,body.description)).fetchone()
            except psycopg.errors.UniqueViolation:
                raise HTTPException(409,'Código já cadastrado')
            audit(conn,'promo_create',{'id':row['id'],'code':code})
            return {'id':row['id'],'code':code}

    @router.put('/api/admin/codes/{code_id}',dependencies=admin)
    def update_code(code_id:int,body:PromoSettings):
        with main.connect() as conn:
            row=conn.execute('SELECT * FROM promo_codes WHERE id=%s FOR UPDATE',(code_id,)).fetchone()
            if not row:
                raise HTTPException(404,'Código não encontrado')
            if row['version']!=body.version:
                raise HTTPException(409,'Código alterado. Atualize o painel.')
            if body.code and normalize_code(body.code)!=row['code']:
                raise HTTPException(409,'O código não pode ser renomeado; crie outro código')
            if body.max_redemptions<row['redeemed_count']:
                raise HTTPException(409,'O limite não pode excluir resgates já realizados')
            conn.execute('UPDATE promo_codes SET spins=%s,max_redemptions=%s,starts_at=%s,expires_at=%s,active=%s,description=%s,version=version+1 WHERE id=%s',
                         (body.spins,body.max_redemptions,body.starts_at,body.expires_at,body.active,body.description,code_id))
            audit(conn,'promo_update',{'id':code_id,'changes':body.model_dump(mode='json')})
            return {'updated':True}

    def redemption_rows(conn,code_id=None):
        return conn.execute('SELECT r.id,c.code,r.player_id,p.name,a.instagram,r.spins,r.created_at FROM promo_redemptions r '
                            'JOIN promo_codes c ON c.id=r.promo_id JOIN accounts a ON a.id=r.player_id JOIN players p ON p.id=r.player_id '+
                            ('WHERE c.id=%s ' if code_id is not None else '')+'ORDER BY r.id DESC', (code_id,) if code_id is not None else ()).fetchall()

    @router.get('/api/admin/codes/{code_id}/redemptions',dependencies=admin)
    def redemptions(code_id:int):
        with main.connect() as conn:
            return redemption_rows(conn,code_id)

    @router.get('/api/admin/code-redemptions.csv',dependencies=admin)
    def export():
        with main.connect() as conn:
            rows=redemption_rows(conn)
        out=io.StringIO(); writer=csv.writer(out);writer.writerow(['ID','Código','Participante ID','Nome','Instagram','Giros','Data'])
        for row in rows:
            # Neutralize spreadsheet formulas in all user-controlled text.
            writer.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r')) else v for v in row.values()])
        return StreamingResponse(iter([out.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="resgates.csv"'})

    @router.get('/api/admin/users',dependencies=admin)
    def users(q:str=''):
        with main.connect() as conn:
            return conn.execute("SELECT p.id,p.name,a.instagram,a.status,a.created_at,p.spins_left,"
                                "CASE WHEN a.cpf_last2 IS NULL THEN 'Eliminado' ELSE '***.***.***-'||a.cpf_last2 END AS cpf_masked,"
                                "(SELECT count(*) FROM spins s WHERE s.player_id=p.id) AS spins_played,"
                                "(SELECT coalesce(sum(amount),0) FROM spin_ledger l WHERE l.player_id=p.id AND kind='INDICACAO') AS referral_spins,"
                                "(SELECT coalesce(sum(amount),0) FROM spin_ledger l WHERE l.player_id=p.id AND kind='CODIGO_PROMOCIONAL') AS promo_spins "
                                'FROM players p JOIN accounts a ON a.id=p.id WHERE p.name ILIKE %s OR a.instagram ILIKE %s ORDER BY p.id DESC LIMIT 100',
                                ('%'+q[:80]+'%','%'+q[:80]+'%')).fetchall()

    @router.get('/api/admin/users/{user_id}/history',dependencies=admin)
    def user_history(user_id:int):
        with main.connect() as conn:
            return {'ledger':conn.execute('SELECT * FROM spin_ledger WHERE player_id=%s ORDER BY id DESC LIMIT 500',(user_id,)).fetchall(),
                    'redemptions':conn.execute('SELECT r.*,c.code FROM promo_redemptions r JOIN promo_codes c ON c.id=r.promo_id WHERE r.player_id=%s ORDER BY r.id DESC',(user_id,)).fetchall(),
                    'spins':conn.execute('SELECT id,created_at,response FROM spins WHERE player_id=%s ORDER BY id DESC LIMIT 200',(user_id,)).fetchall()}

    @router.post('/api/admin/users/{user_id}/balance',dependencies=admin)
    def adjust(user_id:int,body:Adjustment):
        with main.connect() as conn:
            if not conn.execute('SELECT id FROM accounts WHERE id=%s',(user_id,)).fetchone():
                raise HTTPException(404,'Conta não encontrada')
            balance=movement(conn,user_id,'AJUSTE_ADMINISTRATIVO',body.amount,body.reason,'admin:'+str(body.operation_id))
            audit(conn,'balance_adjustment',{'user_id':user_id,'amount':body.amount,'reason':body.reason,'operation_id':str(body.operation_id)})
            return {'spins_left':balance}

    @router.put('/api/admin/users/{user_id}/status',dependencies=admin)
    def status(user_id:int,body:AccountStatus):
        with main.connect() as conn:
            row=conn.execute('SELECT id FROM players WHERE id=%s FOR UPDATE',(user_id,)).fetchone()
            if not row or not conn.execute('UPDATE accounts SET status=%s WHERE id=%s RETURNING id',(body.status,user_id)).fetchone():
                raise HTTPException(404,'Conta não encontrada')
            if body.status=='suspended':
                conn.execute('DELETE FROM account_sessions WHERE account_id=%s',(user_id,))
            audit(conn,'account_status',{'user_id':user_id,'status':body.status,'reason':body.reason})
            return {'updated':True}

    @router.get('/api/admin/referrals',dependencies=admin)
    def referrals():
        with main.connect() as conn:
            return conn.execute('SELECT r.*,a.instagram AS referrer,b.instagram AS referred FROM account_referrals r '
                                'JOIN accounts a ON a.id=r.referrer_id JOIN accounts b ON b.id=r.referred_id ORDER BY created_at DESC LIMIT 500').fetchall()

    @router.post('/api/admin/referrals/{referred_id}/review',dependencies=admin)
    def review(referred_id:int,body:ReferralReview):
        with main.connect() as conn:
            participation.serialize_referrals(conn)
            row=conn.execute('SELECT * FROM account_referrals WHERE referred_id=%s FOR UPDATE',(referred_id,)).fetchone()
            if not row:
                raise HTTPException(404,'Indicação não encontrada')
            if row['status']!='pending':
                raise HTTPException(409,'Indicação já processada; ajustes devem usar o histórico de saldo')
            if body.action=='approve':
                credit_referral(conn,referred_id)
            else:
                conn.execute("UPDATE account_referrals SET status='rejected',reviewed_at=now(),reason=%s WHERE referred_id=%s",(body.reason,referred_id))
            audit(conn,'referral_review',{'referred_id':referred_id,**body.model_dump()})
            return {'reviewed':True}

    @router.get('/api/admin/audit',dependencies=admin)
    def audit_list():
        with main.connect() as conn:
            return conn.execute('SELECT * FROM admin_changes ORDER BY id DESC LIMIT 300').fetchall()

    @router.get('/api/admin/suspicious',dependencies=admin)
    def suspicious():
        with main.connect() as conn:
            return {'rate_limits':conn.execute('SELECT scope,attempts,expires_at FROM request_limits WHERE attempts>=5 ORDER BY expires_at DESC LIMIT 100').fetchall(),
                    'referral_bursts':conn.execute("SELECT referrer_id,count(*) AS registrations FROM account_referrals WHERE created_at>now()-interval '1 hour' GROUP BY referrer_id HAVING count(*)>=3").fetchall()}

    def reset_summary(conn):
        return {'players':conn.execute('SELECT count(*) AS n FROM players').fetchone()['n'],
                'spins':conn.execute('SELECT count(*) AS n FROM spins').fetchone()['n'],
                'prizes':conn.execute('SELECT count(*) AS n FROM prizes').fetchone()['n'],
                'redemptions':conn.execute('SELECT count(*) AS n FROM promo_redemptions').fetchone()['n'],
                'restored_stock':conn.execute('SELECT coalesce(sum(total_quantity),0) AS n FROM prize_types').fetchone()['n'],
                'version':conn.execute('SELECT settings_version FROM campaign WHERE id=1').fetchone()['settings_version']}

    @router.get('/api/admin/reset-preview',dependencies=admin)
    def reset_preview():
        with main.connect() as conn:
            return reset_summary(conn)

    @router.post('/api/admin/reset-campaign',dependencies=admin)
    def reset_campaign(body:CampaignReset):
        try:
            with main.connect() as conn:
                conn.execute("SET LOCAL lock_timeout='8s'")
                participation.serialize_referrals(conn)
                previous=conn.execute("SELECT details FROM admin_changes WHERE action='campaign_reset' AND details->>'operation_id'=%s",(str(body.operation_id),)).fetchone()
                if previous:
                    if previous['details']['reason']!=body.reason or previous['details']['summary']['version']!=body.version:
                        raise HTTPException(409,'Identificador de reset já utilizado com outros dados')
                    return {'reset':True,'replayed':True,'summary':previous['details']['summary']}
                # EXCLUSIVE blocks mutations and row-locking reads while ordinary reads can finish.
                # Existing participant operations finish before any stock or campaign locks are taken.
                conn.execute('LOCK TABLE players,accounts,account_sessions,referrals,phone_verifications,account_referrals,spin_ledger,'
                             'promo_redemptions,cpf_retention_holds,spins,prizes,promo_codes,prize_types,campaign IN EXCLUSIVE MODE')
                summary=reset_summary(conn)
                if summary['version']!=body.version:
                    raise HTTPException(409,'A campanha foi alterada. Atualize o resumo antes de confirmar o reset.')
                held=conn.execute('SELECT count(*) AS n FROM cpf_retention_holds WHERE until_at>now()').fetchone()['n']
                if held:
                    raise HTTPException(409,'Há CPFs com conservação excepcional documentada. Revise essa conservação antes de apagar os participantes.')
                # Explicit order; no CASCADE, no schema deletion, no identity reuse.
                for table in ('promo_redemptions','account_referrals','account_sessions','cpf_retention_holds','phone_verifications',
                              'referrals','spin_ledger','spins','prizes','accounts','players'):
                    conn.execute('DELETE FROM '+table)
                conn.execute('UPDATE promo_codes SET redeemed_count=0,version=version+1')
                conn.execute('UPDATE prize_types SET stock=total_quantity')
                conn.execute('UPDATE campaign SET settings_version=settings_version+1 WHERE id=1')
                audit(conn,'campaign_reset',{'operation_id':str(body.operation_id),'reason':body.reason,'summary':summary,
                                             'stock_restored':True,'coupons_preserved':True})
                return {'reset':True,'replayed':False,'summary':summary}
        except (psycopg.errors.LockNotAvailable,psycopg.errors.DeadlockDetected):
            raise HTTPException(409,'A campanha está ocupada. Nenhum reset foi confirmado; tente novamente com a mesma operação.')

    @router.post('/api/admin/retention/run',dependencies=admin)
    def retention_run():
        from api import retention
        return retention.cleanup(main.connect)

    @router.get('/api/admin/retention',dependencies=admin)
    def retention_report():
        with main.connect() as conn:
            return {'runs':conn.execute('SELECT * FROM retention_runs ORDER BY id DESC LIMIT 30').fetchall(),
                    'holds':conn.execute('SELECT * FROM cpf_retention_holds ORDER BY until_at').fetchall(),
                    'deadline':DEADLINE,
                    'backup_reviews':conn.execute("SELECT created_at,details FROM admin_changes WHERE action='backup_retention_review' ORDER BY id DESC LIMIT 20").fetchall()}

    @router.put('/api/admin/users/{user_id}/cpf-hold',dependencies=admin)
    def retention_hold(user_id:int,body:RetentionHold):
        with main.connect() as conn:
            if not conn.execute('SELECT id FROM accounts WHERE id=%s AND cpf_cipher IS NOT NULL FOR UPDATE',(user_id,)).fetchone():
                raise HTTPException(409,'CPF indisponível ou já eliminado')
            conn.execute('INSERT INTO cpf_retention_holds(account_id,reason,legal_basis,until_at) VALUES(%s,%s,%s,%s) '
                         'ON CONFLICT(account_id) DO UPDATE SET reason=EXCLUDED.reason,legal_basis=EXCLUDED.legal_basis,until_at=EXCLUDED.until_at',
                         (user_id,body.reason,body.legal_basis,body.until_at))
            audit(conn,'cpf_retention_hold',{'user_id':user_id,**body.model_dump(mode='json')})
            return {'recorded':True}

    @router.post('/api/admin/retention/backup-review',dependencies=admin)
    def backup_review(body:BackupReview):
        with main.connect() as conn:
            audit(conn,'backup_retention_review',body.model_dump())
        return {'recorded':True,'note':'Registro da conferência operacional; não executa exclusão no provedor.'}

    main.app.include_router(router)
