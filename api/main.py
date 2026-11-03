"""Fortune Texugo demo API — FastAPI + PostgreSQL, deployable on Railway.
No real prizes are distributed by this service. Phone numbers are not verified.
"""
import hashlib
import hmac
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = ["bananinha", "flor-de-lis", "texugo", "copo", "carta", "ficha"]
SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 name VARCHAR(80) NOT NULL,
 phone_digest CHAR(64) UNIQUE NOT NULL,
 phone_last4 CHAR(4) NOT NULL,
 session_digest CHAR(64) UNIQUE NOT NULL,
 spins_left SMALLINT NOT NULL DEFAULT 3 CHECK (spins_left BETWEEN 0 AND 3),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS spins (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 player_id BIGINT NOT NULL REFERENCES players(id),
 grid JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

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
    with connect() as conn:
        conn.execute(SCHEMA, prepare=False)
    yield

app = FastAPI(title="Fortune Texugo API", version="0.1.0", lifespan=lifespan)

class Registration(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=25)

class SpinRequest(BaseModel):
    session: str = Field(min_length=40, max_length=150)

@app.get("/health")
def health():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "mode": "demo"}

@app.get("/api/config")
def config():
    return {"demo": True, "stock": 5, "max_spins": 3, "ticket_url": "https://www.guicheweb.com.br/64-calourada-da-engenharia-ufes_56060"}

@app.post("/api/register", status_code=201)
def register(body: Registration):
    name = body.name.strip()
    phone = re.sub(r"\D", "", body.phone)
    if phone.startswith("55") and len(phone) in (12, 13):
        phone = phone[2:]
    if len(name) < 2 or not re.fullmatch(r"[1-9]\d{9,10}", phone):
        raise HTTPException(422, "Informe nome e WhatsApp com DDD válido")
    phone_digest = digest(os.environ["PHONE_PEPPER"] + ":" + phone)
    token = secrets.token_urlsafe(48)
    session_digest = digest(token)
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO players (name, phone_digest, phone_last4, session_digest) VALUES (%s,%s,%s,%s)",
                (name, phone_digest, phone[-4:], session_digest)
            )
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "Este WhatsApp já foi cadastrado")
    return {"session": token, "spins_left": 3, "stock": 5, "demo": True}

@app.get("/api/session")
def session(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Sessão ausente")
    with connect() as conn:
        player = conn.execute("SELECT spins_left FROM players WHERE session_digest=%s", (digest(token),)).fetchone()
    if not player:
        raise HTTPException(401, "Sessão inválida")
    return {"spins_left": player["spins_left"], "stock": 5, "demo": True}

@app.post("/api/spin")
def spin(body: SpinRequest):
    # All credit accounting is server-side and atomic.
    # This service deliberately has NO prize distribution path.
    with connect() as conn:
        player = conn.execute(
            "SELECT id,spins_left FROM players WHERE session_digest=%s FOR UPDATE",
            (digest(body.session),)
        ).fetchone()
        if not player:
            raise HTTPException(401, "Sessão inválida")
        if player["spins_left"] <= 0:
            raise HTTPException(409, "Seus giros acabaram")
        grid = [[secrets.choice(SYMBOLS) for _ in range(3)] for _ in range(3)]
        conn.execute("UPDATE players SET spins_left=spins_left-1 WHERE id=%s", (player["id"],))
        from psycopg.types.json import Jsonb
        conn.execute("INSERT INTO spins (player_id,grid) VALUES (%s,%s)", (player["id"], Jsonb(grid)))
    return {"grid": grid, "spins_left": player["spins_left"] - 1, "stock": 5, "won": False, "demo": True}

@app.get("/api/admin/stats")
def admin_stats(x_admin_key: str = Header(default="")):
    expected = os.environ.get("ADMIN_API_KEY", "")
    if not expected or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(403, "Acesso negado")
    with connect() as conn:
        players = conn.execute("SELECT count(*) AS n FROM players").fetchone()["n"]
        spins = conn.execute("SELECT count(*) AS n FROM spins").fetchone()["n"]
    return {"players": players, "spins": spins, "stock": 5, "mode": "demo"}

app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")

@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")

@app.get("/admin.html")
def admin():
    return FileResponse(ROOT / "admin.html")
