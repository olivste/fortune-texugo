"""Promotional spins with atomic inventory and cookie-authenticated accounts."""
import asyncio
import sys
import hashlib
import hmac
import os
import re
import secrets
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4
from decimal import Decimal
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import FileResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from api import participation, accounts, retention, legal

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = ["bananinha", "flor-de-lis", "texugo", "copo", "carta", "ficha", "wild"]
SCHEMA = (ROOT / "api/sql/schema.sql").read_text()

def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=8)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not os.environ.get("PHONE_PEPPER") or len(os.environ["PHONE_PEPPER"]) < 32:
        raise RuntimeError("PHONE_PEPPER must contain at least 32 characters")
    validate_campaign_settings()
    with connect() as conn:
        conn.execute(SCHEMA, prepare=False)
        conn.execute((ROOT / "api/sql/accounts.sql").read_text(), prepare=False)
    await asyncio.to_thread(retention.cleanup, connect)
    async def retention_loop():
        while True:
            await asyncio.sleep(3600)
            try:
                await asyncio.to_thread(retention.cleanup, connect)
            except Exception:
                # No personal data or connection details in operational logs.
                import logging
                logging.getLogger(__name__).error('CPF retention task failed; operator review required')
    task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="Fortune Texugo API", version="0.1.0", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def invalid_input(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':'Confira os campos obrigatórios, formatos e confirmações informados.',
                         'fields':['.'.join(map(str,item['loc'])) for item in error.errors()]}, status_code=422)


class Registration(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=25)
    referral_code: str = Field(default="", max_length=16, pattern=r"^[A-Fa-f0-9]{0,16}$")

class SpinRequest(BaseModel):
    session: str = Field(default="", max_length=150)
    request_id: UUID

def prizes_enabled() -> bool:
    return os.environ.get("PRIZES_ENABLED", "false").lower() == "true"


def unlimited_demo() -> bool:
    return not prizes_enabled() and os.environ.get("DEMO_UNLIMITED_SPINS", "false").lower() == "true"


def validate_campaign_settings():
    if prizes_enabled():
        if not os.environ.get("AUTHORIZATION_REFERENCE", "").strip():
            raise RuntimeError("AUTHORIZATION_REFERENCE is required when prizes are enabled")
        if len(os.environ.get("ADMIN_API_KEY", "")) < 32:
            raise RuntimeError("ADMIN_API_KEY must contain at least 32 characters when prizes are enabled")


def campaign_state(conn):
    settings = conn.execute("SELECT probability_bps FROM campaign WHERE id=1").fetchone()
    items = conn.execute(
        "SELECT id,name,symbol,total_quantity,stock,priority,chance_multiplier FROM prize_types WHERE active=true ORDER BY priority,id"
    ).fetchall()
    eligible = [item for item in items if item['stock']>0]
    total_weight = sum(item['chance_multiplier'] for item in eligible)
    base = settings['probability_bps']/10000
    for item in items:
        share = item['chance_multiplier']/total_weight if item['stock']>0 and total_weight else 0
        item['selection_probability'] = share
        item['probability'] = base*share
    return {"stock": sum(item["stock"] for item in items),
            "total_stock": sum(item["total_quantity"] for item in items),
            "prize_options": items, "current_prize": None, "base_probability": base,
            "probability": base if eligible else 0, "selection_mode": "random_weighted",
            "demo": not prizes_enabled(), "unlimited_spins": unlimited_demo()}


def random_prize(available):
    ticket = secrets.randbelow(sum(item['chance_multiplier'] for item in available))
    for item in available:
        if ticket < item['chance_multiplier']:
            return item
        ticket -= item['chance_multiplier']
    raise RuntimeError('Invalid prize selection')


@app.get("/health")
def health():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "mode": "live" if prizes_enabled() else "demo"}


@app.get("/api/config")
def config():
    with connect() as conn:
        return {**campaign_state(conn), "max_spins": 3,
                "ticket_url": "https://www.guicheweb.com.br/64-calourada-da-engenharia-ufes_56060",
                "verification_required": False, "sms_available": participation.provider_ready(), "accounts_enabled": True,
                "terms_version": os.environ.get('TERMS_VERSION','2026-11-04'), "privacy_version": os.environ.get('PRIVACY_VERSION','2026-11-04'),
                "account_referral_limit": accounts.referral_limit()}


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\D", "", value)
    if phone.startswith("55") and len(phone) in (12, 13):
        phone = phone[2:]
    if not re.fullmatch(r"[1-9]\d{9,10}", phone):
        raise HTTPException(422, "Informe WhatsApp com DDD válido")
    return phone


def readable_code(name: str, phone: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z]", "", plain) or "participante") + phone


def player_state(conn, player, prize=None):
    verified = player.get("phone_verified_at") is not None
    blocked = prize or (participation.verification_required() and not verified)
    return {"spins_left": 0 if blocked else (3 if unlimited_demo() else player["spins_left"]),
            "max_spins": 3 + player.get("bonus_spins_earned", 0), **campaign_state(conn),
            **participation.referral_state(conn, player), "prize": prize,
            "sms_available": participation.provider_ready()}


@app.post("/api/register", status_code=201)
def register(body: Registration, request: Request):
    if os.environ.get('LEGACY_ACCOUNTS_ENABLED','false').lower() != 'true':
        raise HTTPException(410, 'Use o cadastro de conta com telefone e Instagram')
    name = body.name.strip()
    phone = normalize_phone(body.phone)
    if len(name) < 2:
        raise HTTPException(422, "Informe nome e WhatsApp com DDD válido")
    phone_digest = digest(os.environ["PHONE_PEPPER"] + ":" + phone)
    participation.limit(connect, 'register-ip', request.client.host, 60, 3600)
    participation.limit(connect, 'register-phone', phone_digest, 6, 3600)
    token = secrets.token_urlsafe(48)
    with connect() as conn:
        participation.serialize_referrals(conn)
        parent = None
        if body.referral_code:
            parent = conn.execute("SELECT id,phone_digest FROM players WHERE referral_code=%s", (body.referral_code.upper(),)).fetchone()
            if not parent:
                raise HTTPException(422, "Código de indicação inválido")
            if parent["phone_digest"] == phone_digest:
                raise HTTPException(422, "Você não pode usar seu próprio código de indicação")
        try:
            player = conn.execute(
                "INSERT INTO players (name,phone_digest,phone_last4,session_digest,claim_code_base,referral_code) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,spins_left,referral_code,phone_verified_at,bonus_spins_earned",
                (name, phone_digest, phone[-4:], digest(token), readable_code(name, phone), secrets.token_hex(8).upper())
            ).fetchone()
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "Este WhatsApp já foi cadastrado")
        if parent:
            conn.execute("INSERT INTO referrals (referred_id,referrer_id) VALUES (%s,%s)", (player["id"], parent["id"]))
        state = player_state(conn, player)
    return {"session": token, **state}

@app.get("/api/session")
def session(authorization: str = Header(default="")):
    if os.environ.get('LEGACY_ACCOUNTS_ENABLED','false').lower() != 'true':
        raise HTTPException(401, 'Faça login na sua conta')
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(401, "Sessão ausente")
    token = authorization[7:].strip()
    with connect() as conn:
        player = conn.execute("SELECT id,spins_left,claim_code_base,phone_verified_at,referral_code,bonus_spins_earned FROM players WHERE session_digest=%s", (digest(token),)).fetchone()
        if not player:
            raise HTTPException(401, "Sessão inválida")
        prize = conn.execute("SELECT claim_code,redeemed_at,prize_name,prize_symbol FROM prizes WHERE player_id=%s", (player["id"],)).fetchone()
        return {**player_state(conn, player, prize), "needs_phone_confirmation": player["claim_code_base"] is None}


class PhoneConfirmation(BaseModel):
    session: str = Field(min_length=40, max_length=150)
    phone: str = Field(min_length=10, max_length=25)


@app.post("/api/session/confirm-phone")
def confirm_phone(body: PhoneConfirmation):
    if os.environ.get('LEGACY_ACCOUNTS_ENABLED','false').lower() != 'true':
        raise HTTPException(410, 'Cadastro legado encerrado; procure a organização')
    phone = normalize_phone(body.phone)
    with connect() as conn:
        player = conn.execute("SELECT id,name,phone_digest,claim_code_base FROM players WHERE session_digest=%s FOR UPDATE",
                              (digest(body.session),)).fetchone()
        if not player:
            raise HTTPException(401, "Sessão inválida")
        if not hmac.compare_digest(player["phone_digest"], digest(os.environ["PHONE_PEPPER"] + ":" + phone)):
            raise HTTPException(422, "Informe o mesmo telefone usado no cadastro")
        if not player["claim_code_base"]:
            code = readable_code(player["name"], phone)
            collision = conn.execute("SELECT id FROM prizes WHERE player_id<>%s AND (lower(claim_code)=%s OR lower(legacy_claim_code)=%s)",
                                     (player["id"], code, code)).fetchone()
            if collision:
                raise HTTPException(409, "Não foi possível atualizar o código; procure a organização")
            conn.execute("UPDATE players SET claim_code_base=%s WHERE id=%s", (code, player["id"]))
            # Keep the previously issued code redeemable for screenshots / messages already sent.
            conn.execute("UPDATE prizes SET legacy_claim_code=claim_code,claim_code=%s WHERE player_id=%s", (code, player["id"]))
    return session("Bearer " + body.session)


def line_matches(values):
    """WILD substitutes any symbol, including an all-WILD winning line."""
    return len({value for value in values if value != "wild"}) <= 1


def make_grid(won: bool, symbol: str = "copo"):
    grid = [[secrets.choice(SYMBOLS) for _ in range(3)] for _ in range(3)]
    if won:
        for column in grid:
            column[1] = symbol
        # A stacked Riquelme WILD substitutes the selected prize on the middle line.
        grid[secrets.choice([0, 1, 2])] = ["wild"] * 3
    elif line_matches([column[1] for column in grid]):
        regular = [value for value in SYMBOLS if value != "wild"]
        grid[0][1] = secrets.choice(regular)
        grid[2][1] = secrets.choice([value for value in regular if value != grid[0][1]])
    return grid


@app.post("/api/spin")
def spin(body: SpinRequest, request: Request):
    participation.limit(connect, 'spin-ip', request.client.host, 300, 60)
    account_user = None
    if request.cookies.get(accounts.COOKIE):
        account_user = accounts.authenticate(sys.modules[__name__], request, True)
    elif os.environ.get('LEGACY_ACCOUNTS_ENABLED','false').lower() != 'true':
        raise HTTPException(401, 'Faça login para girar')
    with connect() as conn:
        # Every path locks player first, then global inventory, to avoid deadlocks.
        if account_user:
            player = accounts.lock_account(conn, account_user['id'])
        else:
            player = conn.execute(
                "SELECT id,spins_left,claim_code_base,phone_verified_at,referral_code,bonus_spins_earned FROM players WHERE session_digest=%s FOR UPDATE",
                (digest(body.session),)
            ).fetchone()
            if player and conn.execute('SELECT id FROM accounts WHERE id=%s',(player['id'],)).fetchone():
                raise HTTPException(401, 'Faça login na conta')
        if not player:
            raise HTTPException(401, "Sessão inválida")
        previous = conn.execute(
            "SELECT response FROM spins WHERE player_id=%s AND request_id=%s",
            (player["id"], body.request_id)
        ).fetchone()
        if previous:
            return previous["response"]
        already_won = conn.execute("SELECT id FROM prizes WHERE player_id=%s", (player["id"],)).fetchone()
        if already_won:
            raise HTTPException(409, "Você já ganhou um prêmio e não pode girar novamente")
        if not account_user and participation.verification_required() and not player["phone_verified_at"]:
            raise HTTPException(403, "Confirme seu telefone antes de girar")
        if not player["claim_code_base"] and prizes_enabled():
            raise HTTPException(409, "Confirme seu telefone para gerar o código do prêmio antes de girar")
        if player["spins_left"] <= 0 and (account_user or not unlimited_demo()):
            raise HTTPException(409, "Seus giros acabaram")
        campaign = conn.execute("SELECT probability_bps FROM campaign WHERE id=1 FOR UPDATE").fetchone()
        available = conn.execute("SELECT id,name,symbol,stock,chance_multiplier FROM prize_types WHERE active=true AND stock>0 ORDER BY priority,id").fetchall()
        stock = sum(item["stock"] for item in available)
        chance_bps = campaign["probability_bps"] if available else 0
        demo = not prizes_enabled()
        won = (not demo and stock > 0 and not already_won
               and secrets.randbelow(10000) < chance_bps)
        code = None
        awarded = None
        if won:
            code = accounts.withdrawal_code(conn, player) if account_user else player["claim_code_base"]
            # Weighted random type selection after the global win draw; stock is locked.
            awarded = random_prize(available)
            conn.execute(
                "INSERT INTO prizes (player_id,claim_code,prize_type_id,prize_name,prize_symbol) VALUES (%s,%s,%s,%s,%s)",
                (player["id"], code, awarded["id"], awarded["name"], awarded["symbol"]))
            conn.execute("UPDATE prize_types SET stock=stock-1 WHERE id=%s", (awarded["id"],))
        grid = make_grid(won, awarded["symbol"] if awarded else "copo")
        if account_user:
            balance = accounts.movement(conn, player['id'], 'GIRO_REALIZADO', -1, 'Giro da máquina', 'spin:'+str(body.request_id))
            if won and balance:
                accounts.movement(conn, player['id'], 'AJUSTE_ADMINISTRATIVO', -balance, 'Participação encerrada após vitória', 'winner:'+str(body.request_id))
        elif won:
            conn.execute("UPDATE players SET spins_left=0 WHERE id=%s", (player["id"],))
        elif not unlimited_demo():
            conn.execute("UPDATE players SET spins_left=spins_left-1 WHERE id=%s", (player["id"],))
        result = {**campaign_state(conn), **participation.referral_state(conn, player),
                  "max_spins": 3 + player["bonus_spins_earned"], "grid": grid, "spins_left": 0 if won else (3 if unlimited_demo() else player["spins_left"] - 1),
                  "won": bool(won), "demo": demo, "claim_code": code,
                  "spin_probability": chance_bps / 10000,
                  "prize_selection_probability": awarded["chance_multiplier"]/sum(item["chance_multiplier"] for item in available) if awarded else None,
                  "prize_name": awarded["name"] if awarded else None,
                  "prize_symbol": awarded["symbol"] if awarded else None}
        if account_user:
            result.update({key:value for key,value in accounts.profile(sys.modules[__name__], conn, player['id']).items() if key != 'user'})
            result.pop('prize', None)  # A newly won result is presented by the existing victory flow.
            result = jsonable_encoder(result)
        conn.execute(
            "INSERT INTO spins (player_id,grid,request_id,response,authorization_reference) VALUES (%s,%s,%s,%s,%s)",
            (player["id"], Jsonb(grid), body.request_id, Jsonb(result),
             os.environ.get("AUTHORIZATION_REFERENCE", "").strip() if not demo else None)
        )
    return result


def require_admin(x_admin_key: str = Header(default="")):
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected or not hmac.compare_digest(x_admin_key.encode(), expected.encode()):
        raise HTTPException(403, "Acesso negado")


@app.middleware("http")
async def private_responses(request, call_next):
    if request.method in ('POST','PUT','PATCH','DELETE') and request.url.path.startswith('/api/'):
        from fastapi.responses import JSONResponse
        expected = os.environ.get('PUBLIC_ORIGIN') or str(request.base_url).rstrip('/')
        origin = request.headers.get('origin')
        if (origin and origin != expected) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'Origem não autorizada'}, status_code=403)
        if (request.url.path.startswith('/api/account/') or request.url.path=='/api/spin') and not request.headers.get('content-type','').startswith('application/json'):
            return JSONResponse({'detail':'Use JSON'},status_code=415)
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats():
    with connect() as conn:
        players = conn.execute("SELECT count(*) AS n FROM players").fetchone()["n"]
        spins = conn.execute("SELECT count(*) AS n FROM spins").fetchone()["n"]
        return {"players": players, "spins": spins, **campaign_state(conn),
                "mode": "live" if prizes_enabled() else "demo"}


@app.get("/api/admin/prizes", dependencies=[Depends(require_admin)])
def admin_prizes():
    with connect() as conn:
        return conn.execute(
            "SELECT p.name,p.phone_last4,r.claim_code,r.prize_name,r.created_at,r.redeemed_at "
            "FROM prizes r JOIN players p ON p.id=r.player_id ORDER BY r.id"
        ).fetchall()


class CampaignSettings(BaseModel):
    version: int = Field(ge=1)
    probability_percent: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)


class PrizeTypeUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=80)
    symbol: Literal["bananinha", "flor-de-lis", "texugo", "copo", "carta", "ficha"]
    total_quantity: int = Field(ge=0, le=10000, strict=True)
    active: bool = True
    priority: int = Field(default=100, ge=1, le=10000, strict=True)
    chance_multiplier: int = Field(default=1, ge=1, le=100, strict=True)

    @field_validator("name")
    @classmethod
    def trimmed_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Informe um nome de prêmio válido")
        return value


def lock_settings(conn, version):
    settings = conn.execute("SELECT settings_version FROM campaign WHERE id=1 FOR UPDATE").fetchone()
    if settings["settings_version"] != version:
        raise HTTPException(409, "Configuração alterada em outra consulta. Atualize o painel e tente novamente.")


def log_change(conn, action, details):
    conn.execute("UPDATE campaign SET settings_version=settings_version+1 WHERE id=1")
    conn.execute("INSERT INTO admin_changes (action,details) VALUES (%s,%s)", (action, Jsonb(details)))


def admin_settings_data(conn):
    settings = conn.execute("SELECT probability_bps,settings_version FROM campaign WHERE id=1").fetchone()
    items = conn.execute("SELECT id,name,symbol,total_quantity,stock,active,priority,chance_multiplier FROM prize_types ORDER BY priority,id").fetchall()
    return {"version": settings["settings_version"], "probability_percent": settings["probability_bps"] / 100,
            "items": items, "demo": not prizes_enabled(), "selection_mode": "random_weighted"}


@app.get("/api/admin/settings", dependencies=[Depends(require_admin)])
def admin_settings():
    with connect() as conn:
        return admin_settings_data(conn)


@app.put("/api/admin/settings", dependencies=[Depends(require_admin)])
def update_settings(body: CampaignSettings):
    with connect() as conn:
        lock_settings(conn, body.version)
        conn.execute("UPDATE campaign SET probability_bps=%s WHERE id=1", (int(body.probability_percent * 100),))
        log_change(conn, "probability", {"probability_percent": str(body.probability_percent)})
        return admin_settings_data(conn)


@app.post("/api/admin/prize-types", status_code=201, dependencies=[Depends(require_admin)])
def create_prize_type(body: PrizeTypeUpdate):
    with connect() as conn:
        lock_settings(conn, body.version)
        item = conn.execute(
            "INSERT INTO prize_types (catalog_key,name,symbol,total_quantity,stock,active,priority,chance_multiplier) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (str(uuid4()), body.name, body.symbol, body.total_quantity, body.total_quantity, body.active, body.priority, body.chance_multiplier)
        ).fetchone()
        log_change(conn, "create_prize_type", {"id": item["id"], **body.model_dump()})
        return admin_settings_data(conn)


@app.put("/api/admin/prize-types/{item_id}", dependencies=[Depends(require_admin)])
def update_prize_type(item_id: int, body: PrizeTypeUpdate):
    with connect() as conn:
        lock_settings(conn, body.version)
        item = conn.execute("SELECT total_quantity,stock FROM prize_types WHERE id=%s", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Prêmio não encontrado")
        awarded_count = item["total_quantity"] - item["stock"]
        if body.total_quantity < awarded_count:
            raise HTTPException(409, f"A quantidade total não pode ser menor que os {awarded_count} prêmios já concedidos.")
        conn.execute("UPDATE prize_types SET name=%s,symbol=%s,total_quantity=%s,stock=%s,active=%s,priority=%s,chance_multiplier=%s WHERE id=%s",
                     (body.name, body.symbol, body.total_quantity, body.total_quantity - awarded_count, body.active, body.priority, body.chance_multiplier, item_id))
        log_change(conn, "update_prize_type", {"id": item_id, **body.model_dump()})
        return admin_settings_data(conn)


class VerificationStart(BaseModel):
    session: str = Field(min_length=40, max_length=150)
    phone: str = Field(min_length=10, max_length=25)


class VerificationCheck(BaseModel):
    session: str = Field(min_length=40, max_length=150)
    code: str = Field(pattern=r"^[0-9]{6}$")


def verification_player(conn, token, lock=False):
    player = conn.execute("SELECT id,name,phone_digest,phone_verified_at,claim_code_base FROM players WHERE session_digest=%s" +
                          (" FOR UPDATE" if lock else ""), (digest(token),)).fetchone()
    if not player:
        raise HTTPException(401, "Sessão inválida")
    return player


@app.post("/api/verification/start")
def start_verification(body: VerificationStart, request: Request):
    phone = normalize_phone(body.phone)
    participation.limit(connect, 'sms-ip', request.client.host, 20, 3600)
    participation.limit(connect, 'sms-phone', digest(phone), 3, 600)
    participation.limit(connect, 'sms-daily', 'campaign', 100, 86400)
    with connect() as conn:
        participation.serialize_referrals(conn)
        player = verification_player(conn, body.session, True)
        if not hmac.compare_digest(player['phone_digest'], digest(os.environ['PHONE_PEPPER'] + ':' + phone)):
            raise HTTPException(422, "Informe o telefone usado no cadastro")
        if player['phone_verified_at']:
            return {"phone_verified": True}
        recent = conn.execute("SELECT provider_sid,attempts,sent_at>now()-interval '60 seconds' AS cooling,expires_at>now() AS valid "
                              "FROM phone_verifications WHERE player_id=%s", (player['id'],)).fetchone()
        if recent and (recent['cooling'] or (recent['valid'] and recent['attempts']>=5)):
            raise HTTPException(429, "Aguarde antes de pedir outro código", headers={'Retry-After': '60'})
        sid = participation.send_code(phone)
        conn.execute("INSERT INTO phone_verifications (player_id,provider_sid) VALUES (%s,%s) "
                     "ON CONFLICT (player_id) DO UPDATE SET provider_sid=EXCLUDED.provider_sid,sent_at=now(),"
                     "attempts=CASE WHEN phone_verifications.provider_sid=EXCLUDED.provider_sid THEN phone_verifications.attempts ELSE 0 END,"
                     "expires_at=CASE WHEN phone_verifications.provider_sid=EXCLUDED.provider_sid THEN phone_verifications.expires_at ELSE now()+interval '10 minutes' END",
                     (player['id'], sid))
    return {"sent": True, "retry_after": 60}


@app.post("/api/verification/check")
def check_verification(body: VerificationCheck, request: Request):
    participation.limit(connect, 'sms-check-ip', request.client.host, 100, 3600)
    with connect() as conn:
        player = verification_player(conn, body.session)
        if player['phone_verified_at']:
            return session('Bearer ' + body.session)
        challenge = conn.execute("UPDATE phone_verifications SET attempts=attempts+1 WHERE player_id=%s AND attempts<5 AND expires_at>now() "
                                 "RETURNING provider_sid", (player['id'],)).fetchone()
        if not challenge:
            raise HTTPException(422, "Código expirado ou limite de tentativas atingido. Solicite outro código.")
    # The attempt is committed BEFORE an incorrect code is rejected.
    if not participation.check_code(challenge['provider_sid'], body.code):
        raise HTTPException(422, "Código incorreto ou expirado")
    with connect() as conn:
        participation.serialize_referrals(conn)
        player = verification_player(conn, body.session, True)
        current = conn.execute("SELECT provider_sid FROM phone_verifications WHERE player_id=%s", (player['id'],)).fetchone()
        if not current or current['provider_sid'] != challenge['provider_sid']:
            raise HTTPException(422, "Solicite e confirme o código mais recente")
        conn.execute("UPDATE players SET phone_verified_at=coalesce(phone_verified_at,now()),verification_method='sms' WHERE id=%s", (player['id'],))
        participation.award_referrals(conn, player['id'])
    return session('Bearer ' + body.session)


class ManualVerification(BaseModel):
    player_id: int = Field(ge=1)
    phone: str = Field(min_length=10, max_length=25)
    checked: Literal[True]
    note: str = Field(min_length=5, max_length=200)


@app.get("/api/admin/participants", dependencies=[Depends(require_admin)])
def participants():
    with connect() as conn:
        return conn.execute("SELECT id,name,phone_last4,phone_verified_at,verification_method,referral_code,bonus_spins_earned "
                            "FROM players ORDER BY id DESC LIMIT 100").fetchall()


@app.post("/api/admin/verify-phone", dependencies=[Depends(require_admin)])
def manual_verification(body: ManualVerification):
    phone = normalize_phone(body.phone)
    with connect() as conn:
        participation.serialize_referrals(conn)
        player = conn.execute("SELECT id,phone_digest,phone_verified_at FROM players WHERE id=%s FOR UPDATE", (body.player_id,)).fetchone()
        if not player or not hmac.compare_digest(player['phone_digest'], digest(os.environ['PHONE_PEPPER'] + ':' + phone)):
            raise HTTPException(422, "Participante e telefone não conferem")
        if not player['phone_verified_at']:
            conn.execute("UPDATE players SET phone_verified_at=now(),verification_method='manual' WHERE id=%s", (player['id'],))
            conn.execute("INSERT INTO admin_changes (action,details) VALUES ('manual_phone_verification',%s)",
                         (Jsonb({'player_id': player['id'], 'note': body.note}),))
        participation.award_referrals(conn, player['id'])
    return {"verified": True}


class Redemption(BaseModel):
    claim_code: str = Field(pattern=r"^[A-Za-z0-9]{2,100}$")


@app.post("/api/admin/redeem", dependencies=[Depends(require_admin)])
def redeem(body: Redemption):
    with connect() as conn:
        prize = conn.execute(
            "UPDATE prizes SET redeemed_at=now() WHERE (lower(claim_code)=lower(%s) OR lower(legacy_claim_code)=lower(%s)) AND redeemed_at IS NULL "
            "RETURNING claim_code,redeemed_at", (body.claim_code, body.claim_code)
        ).fetchone()
        if not prize:
            raise HTTPException(409, "Código inválido ou prêmio já retirado")
    return prize


accounts.install(sys.modules[__name__])

app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/admin.html")
def admin():
    return FileResponse(ROOT / "admin.html")


@app.get('/termos')
def terms_page():
    return legal.page('termos')


@app.get('/privacidade')
def privacy_page():
    return legal.page('privacidade')
