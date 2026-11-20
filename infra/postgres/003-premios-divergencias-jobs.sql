-- Etapa 03 (conclusão): premiações por faixa, dados financeiros, quarentena, divergências e fila de jobs.
-- Aplicar uma vez no banco cassino após 002-ingest.sql (como superusuário):
--   docker exec -i cassino-postgres-1 psql -U postgres -d cassino -v ON_ERROR_STOP=1 < infra/postgres/003-premios-divergencias-jobs.sql
BEGIN;

CREATE TABLE IF NOT EXISTS schema_migration (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_migration(name) VALUES ('002-ingest') ON CONFLICT DO NOTHING;

CREATE TABLE draw_prize_tier (
    draw_id bigint NOT NULL REFERENCES lottery_draw(draw_id) ON DELETE CASCADE,
    hits smallint NOT NULL CHECK (hits > 0),
    winners integer CHECK (winners >= 0),
    payout_amount numeric(18,2) CHECK (payout_amount >= 0),
    PRIMARY KEY (draw_id, hits)
);

-- Dados financeiros e de origem do concurso (opcionais; NULL = ausente na fonte).
CREATE TABLE draw_extra (
    draw_id bigint PRIMARY KEY REFERENCES lottery_draw(draw_id) ON DELETE CASCADE,
    winner_locations text,
    accumulated_main numeric(18,2) CHECK (accumulated_main >= 0),
    total_collected numeric(18,2) CHECK (total_collected >= 0),
    next_estimate numeric(18,2) CHECK (next_estimate >= 0),
    special_accumulated numeric(18,2) CHECK (special_accumulated >= 0),
    observation text
);

ALTER TABLE ingest_run
    ADD COLUMN quarantined_count integer NOT NULL DEFAULT 0 CHECK (quarantined_count >= 0),
    ADD COLUMN divergent_count integer NOT NULL DEFAULT 0 CHECK (divergent_count >= 0),
    ADD COLUMN prize_changed_count integer NOT NULL DEFAULT 0 CHECK (prize_changed_count >= 0);

ALTER TABLE ingest_draw_change DROP CONSTRAINT ingest_draw_change_action_check;
ALTER TABLE ingest_draw_change ADD CONSTRAINT ingest_draw_change_action_check
    CHECK (action IN ('reconciled', 'prize_reconciled'));

-- Linhas rejeitadas da fonte: nunca entram em lottery_draw.
CREATE TABLE ingest_quarantine (
    quarantine_id bigserial PRIMARY KEY,
    ingest_run_id bigint NOT NULL REFERENCES ingest_run(ingest_run_id),
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    contest integer,
    source_line integer NOT NULL,
    kind text NOT NULL CHECK (kind IN ('draw', 'prize')),
    reason text NOT NULL,
    raw_row jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ingest_quarantine_slug_idx ON ingest_quarantine(lottery_slug, contest);

-- Divergência: a fonte trouxe dezenas/data diferentes de um concurso já validado. O valor válido
-- é preservado até decisão explícita (accepted/rejected).
CREATE TABLE ingest_divergence (
    divergence_id bigserial PRIMARY KEY,
    ingest_run_id bigint NOT NULL REFERENCES ingest_run(ingest_run_id),
    draw_id bigint NOT NULL REFERENCES lottery_draw(draw_id),
    previous_value jsonb NOT NULL,
    current_value jsonb NOT NULL,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'rejected')),
    detected_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolution_note text,
    CHECK ((status = 'open') = (resolved_at IS NULL))
);
CREATE UNIQUE INDEX ingest_divergence_open_uniq ON ingest_divergence(draw_id, md5(current_value::text)) WHERE status = 'open';

-- Lacunas de concursos por modalidade (concursos ausentes entre o menor e o maior importado).
CREATE VIEW draw_gap AS
SELECT t.slug AS lottery_slug, g.contest
  FROM lottery_type t
  CROSS JOIN LATERAL (
      SELECT generate_series(min(d.contest), max(d.contest)) AS contest
        FROM lottery_draw d WHERE d.lottery_slug = t.slug
  ) g
 WHERE NOT EXISTS (SELECT 1 FROM lottery_draw d WHERE d.lottery_slug = t.slug AND d.contest = g.contest);

-- Fila interna de jobs (analisador, experimentos). O coletor enfileira na mesma transação do NOTIFY.
CREATE TABLE job (
    job_id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind ~ '^[a-z_]{1,40}$'),
    lottery_slug text REFERENCES lottery_type(slug),
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    ingest_run_id bigint REFERENCES ingest_run(ingest_run_id),
    attempts integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    error text
);
CREATE INDEX job_status_idx ON job(status, created_at);
-- No máximo um job pendente por tipo+modalidade+parâmetros (evita enfileirar a mesma análise N vezes).
CREATE UNIQUE INDEX job_pending_uniq ON job(kind, COALESCE(lottery_slug, ''), md5(params::text)) WHERE status = 'pending';

GRANT SELECT ON draw_prize_tier, draw_extra, ingest_quarantine, ingest_divergence, draw_gap, job, schema_migration TO cassino_api, cassino_inspect;
GRANT SELECT, INSERT, UPDATE ON draw_prize_tier, draw_extra, ingest_quarantine, ingest_divergence, job TO cassino_worker;
GRANT SELECT ON draw_gap, schema_migration TO cassino_worker;
GRANT DELETE ON draw_prize_tier TO cassino_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cassino_worker;
GRANT INSERT ON job TO cassino_api;  -- POST /api/experiments enfileira jobs (etapa 05)
GRANT USAGE ON SEQUENCE job_job_id_seq TO cassino_api;

INSERT INTO schema_migration(name) VALUES ('003-premios-divergencias-jobs');
COMMIT;
