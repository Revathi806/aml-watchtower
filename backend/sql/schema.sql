CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS core.bank (
  bank_id BIGSERIAL PRIMARY KEY, bank_name TEXT NOT NULL, bank_location TEXT NOT NULL,
  UNIQUE(bank_name, bank_location)
);
CREATE TABLE IF NOT EXISTS core.customer (
  customer_id BIGSERIAL PRIMARY KEY, customer_ref TEXT UNIQUE NOT NULL,
  risk_rating TEXT NOT NULL DEFAULT 'Unknown' CHECK (risk_rating IN ('Low','Medium','High','Unknown')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.account (
  account_id TEXT PRIMARY KEY, customer_id BIGINT REFERENCES core.customer(customer_id),
  bank_id BIGINT REFERENCES core.bank(bank_id), created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.laundering_typology (
  typology_id BIGSERIAL PRIMARY KEY, typology_name TEXT UNIQUE NOT NULL, is_suspicious BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS core.transaction (
  transaction_id BIGINT PRIMARY KEY, event_time TIMESTAMPTZ NOT NULL, amount NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
  payment_currency TEXT, received_currency TEXT, payment_type TEXT, sender_bank_location TEXT,
  receiver_bank_location TEXT, source_label BOOLEAN, typology_id BIGINT REFERENCES core.laundering_typology(typology_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.transaction_acc_id (
  transaction_id BIGINT PRIMARY KEY REFERENCES core.transaction(transaction_id) ON DELETE CASCADE,
  sender_account_id TEXT NOT NULL REFERENCES core.account(account_id),
  receiver_account_id TEXT NOT NULL REFERENCES core.account(account_id),
  CHECK(sender_account_id <> '')
);
CREATE TABLE IF NOT EXISTS core.analyst (
  analyst_id BIGSERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('analyst','admin')), active BOOLEAN NOT NULL DEFAULT true,
  password_hash TEXT
);
ALTER TABLE core.analyst ADD COLUMN IF NOT EXISTS password_hash TEXT;
CREATE TABLE IF NOT EXISTS core.rule_config (
  rule_name TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT true,
  weight INTEGER NOT NULL CHECK(weight BETWEEN 0 AND 100), threshold JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.alert (
  alert_id BIGSERIAL PRIMARY KEY, transaction_id BIGINT NOT NULL REFERENCES core.transaction(transaction_id),
  risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100), matched_rules TEXT[] NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Assigned','Resolved','Escalated')),
  assigned_to BIGINT REFERENCES core.analyst(analyst_id), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(transaction_id)
);
CREATE TABLE IF NOT EXISTS core.alert_note (
  note_id BIGSERIAL PRIMARY KEY, alert_id BIGINT NOT NULL REFERENCES core.alert(alert_id) ON DELETE CASCADE,
  analyst_id BIGINT REFERENCES core.analyst(analyst_id), note TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.alert_audit (
  audit_id BIGSERIAL PRIMARY KEY, alert_id BIGINT NOT NULL REFERENCES core.alert(alert_id) ON DELETE CASCADE,
  changed_by TEXT NOT NULL, old_status TEXT, new_status TEXT NOT NULL, details JSONB NOT NULL DEFAULT '{}'::jsonb,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS core.detected_rule (
  detected_rule_id BIGSERIAL PRIMARY KEY, transaction_id BIGINT NOT NULL REFERENCES core.transaction(transaction_id) ON DELETE CASCADE,
  rule_name TEXT NOT NULL REFERENCES core.rule_config(rule_name), detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(transaction_id, rule_name)
);
CREATE INDEX IF NOT EXISTS ix_transaction_time ON core.transaction(event_time);
CREATE INDEX IF NOT EXISTS ix_transaction_type ON core.transaction(payment_type);
CREATE INDEX IF NOT EXISTS ix_edge_sender ON core.transaction_acc_id(sender_account_id);
CREATE INDEX IF NOT EXISTS ix_edge_receiver ON core.transaction_acc_id(receiver_account_id);
CREATE INDEX IF NOT EXISTS ix_alert_status_score ON core.alert(status, risk_score DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_alert_rules ON core.alert USING GIN(matched_rules);

INSERT INTO core.laundering_typology(typology_name,is_suspicious) VALUES
 ('structuring',true),('fan_in',true),('fan_out',true),('deposit_send',true),('cycle',true),('behavioural_change',true),('legitimate',false)
ON CONFLICT(typology_name) DO NOTHING;
INSERT INTO core.rule_config(rule_name, enabled, weight, threshold) VALUES
 ('structuring',true,40,'{"min_count":3,"min_amount":800,"max_amount":1000,"window_hours":24}'),
 ('fan_in',true,30,'{"min_accounts":4}'),('fan_out',true,30,'{"min_accounts":4}'),
 ('deposit_send',true,35,'{"ratio":0.9,"window_hours":6}'),('cycle',true,50,'{"max_depth":4,"max_gap_hours":24}'),
 ('behavioural_change',true,20,'{"baseline_multiplier":3}')
ON CONFLICT(rule_name) DO NOTHING;

CREATE OR REPLACE FUNCTION core.audit_alert_status() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO core.alert_audit(alert_id, changed_by, old_status, new_status)
    VALUES(NEW.alert_id, COALESCE(current_setting('app.user_email', true),'system'), OLD.status, NEW.status);
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_alert_status_audit ON core.alert;
CREATE TRIGGER trg_alert_status_audit BEFORE UPDATE ON core.alert FOR EACH ROW EXECUTE FUNCTION core.audit_alert_status();

CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.kpi_daily AS
SELECT date_trunc('day', t.event_time)::date AS day, count(*) AS transaction_count,
       count(a.alert_id) AS flagged_count, count(*) FILTER (WHERE a.status='Open') AS open_alert_count
FROM core.transaction t LEFT JOIN core.alert a ON a.transaction_id=t.transaction_id
GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_kpi_daily_day ON analytics.kpi_daily(day);
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.typology_daily AS
SELECT date_trunc('day', a.created_at)::date AS day, rule_name AS typology, count(*) AS alert_count
FROM core.alert a CROSS JOIN LATERAL unnest(a.matched_rules) AS rule_name GROUP BY 1,2;
CREATE UNIQUE INDEX IF NOT EXISTS ux_typology_daily ON analytics.typology_daily(day,typology);
CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.geo_flagged AS
SELECT COALESCE(t.sender_bank_location,'Unknown') AS bank_location, count(*) AS flagged_count
FROM core.alert a JOIN core.transaction t USING(transaction_id) GROUP BY 1;
CREATE UNIQUE INDEX IF NOT EXISTS ux_geo_flagged ON analytics.geo_flagged(bank_location);
