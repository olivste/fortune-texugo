
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

-- Additive migration: preserves participants and spins from the demo backend.
ALTER TABLE spins ADD COLUMN IF NOT EXISTS request_id UUID;
ALTER TABLE spins ADD COLUMN IF NOT EXISTS response JSONB;
ALTER TABLE spins ADD COLUMN IF NOT EXISTS authorization_reference TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS spins_player_request ON spins(player_id, request_id);
CREATE TABLE IF NOT EXISTS campaign (
 id SMALLINT PRIMARY KEY CHECK (id = 1),
 stock SMALLINT NOT NULL DEFAULT 5 CHECK (stock BETWEEN 0 AND 5)
);
INSERT INTO campaign (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS prizes (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 player_id BIGINT UNIQUE NOT NULL REFERENCES players(id),
 claim_code VARCHAR(32) UNIQUE NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 redeemed_at TIMESTAMPTZ
);

-- Configurable prize catalog, preserving the original five-cup campaign.
ALTER TABLE campaign ADD COLUMN IF NOT EXISTS probability_bps INTEGER NOT NULL DEFAULT 200
 CHECK (probability_bps BETWEEN 0 AND 10000);
ALTER TABLE campaign ADD COLUMN IF NOT EXISTS settings_version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS prize_types (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 catalog_key TEXT UNIQUE NOT NULL,
 name VARCHAR(80) NOT NULL CHECK (length(trim(name)) >= 2),
 symbol TEXT NOT NULL CHECK (symbol IN ('bananinha','flor-de-lis','texugo','copo','carta','ficha')),
 total_quantity INTEGER NOT NULL CHECK (total_quantity BETWEEN 0 AND 10000),
 stock INTEGER NOT NULL CHECK (stock >= 0 AND stock <= total_quantity),
 active BOOLEAN NOT NULL DEFAULT true
);
DO $$
DECLARE legacy_stock INTEGER := 5;
BEGIN
 IF EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='campaign'::regclass AND attname='stock' AND NOT attisdropped) THEN
  EXECUTE 'SELECT stock FROM campaign WHERE id=1' INTO legacy_stock;
 END IF;
 INSERT INTO prize_types (catalog_key,name,symbol,total_quantity,stock)
 VALUES ('original-cup','Copo Risca Faca','copo',5,legacy_stock) ON CONFLICT (catalog_key) DO NOTHING;
END $$;
ALTER TABLE campaign DROP COLUMN IF EXISTS stock;
ALTER TABLE prizes ADD COLUMN IF NOT EXISTS prize_type_id BIGINT REFERENCES prize_types(id);
ALTER TABLE prizes ADD COLUMN IF NOT EXISTS prize_name TEXT NOT NULL DEFAULT 'Copo Risca Faca';
ALTER TABLE prizes ADD COLUMN IF NOT EXISTS prize_symbol TEXT NOT NULL DEFAULT 'copo';
UPDATE prizes SET prize_type_id=(SELECT id FROM prize_types WHERE catalog_key='original-cup') WHERE prize_type_id IS NULL;
CREATE TABLE IF NOT EXISTS admin_changes (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 action TEXT NOT NULL,
 details JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Deterministic prize sequence: migrate once without overwriting later admin edits.
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='prize_types'::regclass AND attname='priority' AND NOT attisdropped) THEN
  ALTER TABLE prize_types ADD COLUMN priority INTEGER NOT NULL DEFAULT 100 CHECK (priority BETWEEN 1 AND 10000);
  UPDATE prize_types SET priority=1 WHERE catalog_key='original-cup';
 END IF;
END $$;

ALTER TABLE prize_types ADD COLUMN IF NOT EXISTS chance_multiplier INTEGER NOT NULL DEFAULT 1
 CHECK (chance_multiplier BETWEEN 1 AND 100);

-- Human-readable claim codes; existing phones must be confirmed, never guessed.
ALTER TABLE players ADD COLUMN IF NOT EXISTS claim_code_base VARCHAR(100);
ALTER TABLE prizes ALTER COLUMN claim_code TYPE VARCHAR(100);
ALTER TABLE prizes ADD COLUMN IF NOT EXISTS legacy_claim_code VARCHAR(100) UNIQUE;
CREATE UNIQUE INDEX IF NOT EXISTS prizes_claim_code_ci ON prizes(lower(claim_code));
UPDATE players p SET spins_left=0 WHERE spins_left<>0 AND EXISTS (SELECT 1 FROM prizes r WHERE r.player_id=p.id);

-- Verified referrals: no credit from an unverified phone, no credit twice.
ALTER TABLE players DROP CONSTRAINT IF EXISTS players_spins_left_check;
ALTER TABLE players ADD CONSTRAINT players_spins_left_check CHECK (spins_left BETWEEN 0 AND 1000000);
ALTER TABLE players ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMPTZ;
ALTER TABLE players ADD COLUMN IF NOT EXISTS verification_method TEXT;
ALTER TABLE players ADD COLUMN IF NOT EXISTS referral_code VARCHAR(16);
ALTER TABLE players ADD COLUMN IF NOT EXISTS bonus_spins_earned INTEGER NOT NULL DEFAULT 0 CHECK (bonus_spins_earned BETWEEN 0 AND 1000);
UPDATE players SET referral_code=upper(substr(md5('fortune-ref:'||id::text||session_digest),1,16)) WHERE referral_code IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS players_referral_code_unique ON players(referral_code);
CREATE TABLE IF NOT EXISTS referrals (
 referred_id BIGINT PRIMARY KEY REFERENCES players(id),
 referrer_id BIGINT NOT NULL REFERENCES players(id),
 status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','credited','blocked')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 credited_at TIMESTAMPTZ,
 CHECK (referred_id<>referrer_id)
);
CREATE INDEX IF NOT EXISTS referrals_referrer ON referrals(referrer_id);
CREATE TABLE IF NOT EXISTS phone_verifications (
 player_id BIGINT PRIMARY KEY REFERENCES players(id),
 provider_sid VARCHAR(34) NOT NULL,
 sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 expires_at TIMESTAMPTZ NOT NULL DEFAULT now()+interval '10 minutes',
 attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5)
);
CREATE TABLE IF NOT EXISTS request_limits (
 scope TEXT NOT NULL,
 key_digest CHAR(64) NOT NULL,
 bucket BIGINT NOT NULL,
 attempts INTEGER NOT NULL CHECK (attempts>0),
 expires_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (scope,key_digest,bucket)
);
CREATE INDEX IF NOT EXISTS request_limits_expiry ON request_limits(expires_at);
