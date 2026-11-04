-- Versioned, additive account migration; existing players and prizes are preserved.
CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());
ALTER TABLE players ALTER COLUMN phone_digest DROP NOT NULL;
ALTER TABLE players ALTER COLUMN phone_last4 DROP NOT NULL;
ALTER TABLE players DROP CONSTRAINT IF EXISTS players_spins_left_check;
ALTER TABLE players ALTER COLUMN spins_left TYPE INTEGER;
ALTER TABLE players ADD CONSTRAINT players_spins_left_check CHECK(spins_left BETWEEN 0 AND 1000000);
CREATE TABLE IF NOT EXISTS accounts(
 id BIGINT PRIMARY KEY REFERENCES players(id),
 cpf_lookup CHAR(64) UNIQUE,
 cpf_cipher TEXT,
 cpf_last2 CHAR(2),
 cpf_deleted_at TIMESTAMPTZ,
 instagram VARCHAR(30) UNIQUE NOT NULL,
 password_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
 terms_version TEXT NOT NULL,
 privacy_version TEXT NOT NULL,
 accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 adult_declared_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(instagram=lower(instagram)),
 CHECK((cpf_lookup IS NULL)=(cpf_cipher IS NULL))
);
CREATE TABLE IF NOT EXISTS account_sessions(
 token_digest CHAR(64) PRIMARY KEY,
 account_id BIGINT NOT NULL REFERENCES accounts(id),
 csrf_token VARCHAR(80) NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '7 days',
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS account_sessions_user ON account_sessions(account_id);
CREATE TABLE IF NOT EXISTS spin_ledger(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 player_id BIGINT NOT NULL REFERENCES players(id),
 kind TEXT NOT NULL CHECK(kind IN ('CADASTRO','INDICACAO','CODIGO_PROMOCIONAL','GIRO_REALIZADO','AJUSTE_ADMINISTRATIVO')),
 amount INTEGER NOT NULL,
 balance INTEGER NOT NULL CHECK(balance>=0),
 source TEXT NOT NULL,
 operation_id TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(player_id,operation_id)
);
-- Baseline is imported once. Never replenish balances when reapplying migrations.
INSERT INTO spin_ledger(player_id,kind,amount,balance,source,operation_id)
 SELECT id,'AJUSTE_ADMINISTRATIVO',spins_left,spins_left,'Saldo legado importado; histórico anterior em spins','migration:accounts-baseline' FROM players p WHERE NOT EXISTS(SELECT 1 FROM accounts a WHERE a.id=p.id)
 ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS account_referrals(
 referred_id BIGINT PRIMARY KEY REFERENCES accounts(id),
 referrer_id BIGINT NOT NULL REFERENCES accounts(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','credited','rejected')),
 reason TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 reviewed_at TIMESTAMPTZ,
 CHECK(referred_id<>referrer_id)
);
CREATE INDEX IF NOT EXISTS account_referrer ON account_referrals(referrer_id);
CREATE TABLE IF NOT EXISTS promo_codes(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 code VARCHAR(40) UNIQUE NOT NULL,
 spins INTEGER NOT NULL CHECK(spins BETWEEN 1 AND 1000),
 max_redemptions INTEGER NOT NULL CHECK(max_redemptions BETWEEN 1 AND 1000000),
 redeemed_count INTEGER NOT NULL DEFAULT 0 CHECK(redeemed_count>=0 AND redeemed_count<=max_redemptions),
 starts_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 active BOOLEAN NOT NULL DEFAULT true,
 description VARCHAR(200) NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CHECK(expires_at>starts_at),
 CHECK(code=upper(code))
);
CREATE TABLE IF NOT EXISTS promo_redemptions(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 promo_id BIGINT NOT NULL REFERENCES promo_codes(id),
 player_id BIGINT NOT NULL REFERENCES accounts(id),
 spins INTEGER NOT NULL CHECK(spins>0),
 operation_id UUID NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(promo_id,player_id), UNIQUE(player_id,operation_id)
);
CREATE TABLE IF NOT EXISTS cpf_retention_holds(
 account_id BIGINT PRIMARY KEY REFERENCES accounts(id),
 reason TEXT NOT NULL,
 legal_basis TEXT NOT NULL,
 until_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS retention_runs(
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 deleted_count INTEGER NOT NULL,
 backup_report JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO schema_migrations(version) VALUES('002-accounts-ledger-promos') ON CONFLICT DO NOTHING;

-- Coupons created without dates are immediately available and have no expiry.
ALTER TABLE promo_codes ALTER COLUMN expires_at DROP NOT NULL;
