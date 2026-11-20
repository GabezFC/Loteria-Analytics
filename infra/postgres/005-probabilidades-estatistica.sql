-- Etapa 04: regras/preços parametrizados, tabela de probabilidades exatas e persistência das análises.
-- Aplicar como superusuário: docker exec -i cassino-postgres-1 psql -U postgres -d cassino -v ON_ERROR_STOP=1 < infra/postgres/005-probabilidades-estatistica.sql
BEGIN;

ALTER TABLE lottery_type
    ADD COLUMN min_bet_size smallint,
    ADD COLUMN max_bet_size smallint,
    ADD COLUMN simple_price numeric(8,2) CHECK (simple_price > 0),
    ADD COLUMN price_source text,
    ADD COLUMN price_checked_on date;
UPDATE lottery_type SET min_bet_size=6,  max_bet_size=20, simple_price=6.00, price_source='Especificação técnica (nov/2026); confirmar na CAIXA antes de usar custos', price_checked_on='2026-11-20' WHERE slug='megasena';
UPDATE lottery_type SET min_bet_size=15, max_bet_size=20, simple_price=3.50, price_source='Especificação técnica (nov/2026); confirmar na CAIXA antes de usar custos', price_checked_on='2026-11-20' WHERE slug='lotofacil';
UPDATE lottery_type SET min_bet_size=5,  max_bet_size=15, simple_price=3.00, price_source='Especificação técnica (nov/2026); confirmar na CAIXA antes de usar custos', price_checked_on='2026-11-20' WHERE slug='quina';
ALTER TABLE lottery_type
    ALTER COLUMN min_bet_size SET NOT NULL, ALTER COLUMN max_bet_size SET NOT NULL, ALTER COLUMN simple_price SET NOT NULL,
    ADD CONSTRAINT lottery_type_bet_range CHECK (min_bet_size <= max_bet_size AND max_bet_size <= pool_size AND min_bet_size >= draw_size);

-- P(exatamente r acertos) = C(b,r)·C(N-b,k-r)/C(N,k), com frações exatas (texto) e double para exibição.
CREATE TABLE probability_table (
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    bet_size smallint NOT NULL,
    hits smallint NOT NULL CHECK (hits >= 0),
    is_prize_tier boolean NOT NULL,
    exact_numerator numeric NOT NULL,
    exact_denominator numeric NOT NULL,
    at_least_numerator numeric NOT NULL,
    probability double precision NOT NULL,
    at_least_probability double precision NOT NULL,
    simple_games numeric NOT NULL,
    cost numeric(14,2) NOT NULL,
    formula_version text NOT NULL,
    PRIMARY KEY (lottery_slug, bet_size, hits)
);

CREATE TABLE analysis_run (
    analysis_run_id bigserial PRIMARY KEY,
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    method text NOT NULL,
    window_label text NOT NULL,
    window_size integer,
    window_start_contest integer NOT NULL,
    window_end_contest integer NOT NULL,
    sample_size integer NOT NULL CHECK (sample_size > 0),
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    params_hash char(32) NOT NULL,
    code_version text NOT NULL,
    seed bigint,
    data_fingerprint char(64) NOT NULL,
    status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    error text,
    job_id bigint REFERENCES job(job_id),
    UNIQUE (lottery_slug, method, window_label, params_hash, code_version, data_fingerprint)
);
CREATE INDEX analysis_run_lookup_idx ON analysis_run(lottery_slug, method, window_label, window_end_contest DESC) WHERE status = 'succeeded';

CREATE TABLE number_stat (
    analysis_run_id bigint NOT NULL REFERENCES analysis_run(analysis_run_id) ON DELETE CASCADE,
    number smallint NOT NULL,
    frequency integer NOT NULL,
    relative_frequency double precision NOT NULL,
    expected_frequency double precision NOT NULL,
    z_score double precision NOT NULL,
    ci_low double precision NOT NULL,
    ci_high double precision NOT NULL,
    current_delay integer NOT NULL,
    max_delay integer NOT NULL,
    mean_gap double precision,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (analysis_run_id, number)
);

CREATE TABLE combination_stat (
    analysis_run_id bigint NOT NULL REFERENCES analysis_run(analysis_run_id) ON DELETE CASCADE,
    combo_size smallint NOT NULL CHECK (combo_size BETWEEN 2 AND 4),
    numbers smallint[] NOT NULL,
    observed integer NOT NULL,
    expected double precision NOT NULL,
    lift double precision NOT NULL,
    z_score double precision NOT NULL,
    p_value double precision NOT NULL,
    q_value double precision NOT NULL,
    sample_size integer NOT NULL,
    PRIMARY KEY (analysis_run_id, combo_size, numbers)
);

CREATE TABLE analysis_result (
    analysis_run_id bigint NOT NULL REFERENCES analysis_run(analysis_run_id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind ~ '^[a-z_0-9]{1,40}$'),
    payload jsonb NOT NULL,
    PRIMARY KEY (analysis_run_id, kind)
);

GRANT SELECT ON probability_table, analysis_run, number_stat, combination_stat, analysis_result TO cassino_api, cassino_inspect, cassino_worker;
GRANT SELECT, INSERT, UPDATE ON analysis_run TO cassino_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON probability_table TO cassino_worker;
GRANT INSERT ON number_stat, combination_stat, analysis_result TO cassino_worker;
GRANT DELETE ON number_stat, combination_stat, analysis_result, analysis_run TO cassino_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cassino_worker;

INSERT INTO schema_migration(name) VALUES ('005-probabilidades-estatistica');
COMMIT;
