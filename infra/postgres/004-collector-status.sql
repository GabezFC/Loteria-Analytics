-- Etapa 03: estado operacional do coletor por modalidade (falhas de download não geram ingest_run).
-- Aplicar como superusuário: docker exec -i cassino-postgres-1 psql -U postgres -d cassino -v ON_ERROR_STOP=1 < infra/postgres/004-collector-status.sql
BEGIN;
CREATE TABLE collector_status (
    lottery_slug text PRIMARY KEY REFERENCES lottery_type(slug),
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    last_error text,
    consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    next_attempt_at timestamptz
);
INSERT INTO collector_status(lottery_slug) SELECT slug FROM lottery_type;
GRANT SELECT ON collector_status TO cassino_api, cassino_inspect;
GRANT SELECT, INSERT, UPDATE ON collector_status TO cassino_worker;
INSERT INTO schema_migration(name) VALUES ('004-collector-status');
COMMIT;
