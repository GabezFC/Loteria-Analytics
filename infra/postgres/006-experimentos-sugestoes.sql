-- Etapa 05: experimentos (backtest walk-forward, Monte Carlo) e conjuntos de sugestões experimentais.
-- Aplicar como superusuário: docker exec -i cassino-postgres-1 psql -U postgres -d cassino -v ON_ERROR_STOP=1 < infra/postgres/006-experimentos-sugestoes.sql
BEGIN;

CREATE TABLE experiment (
    experiment_id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('backtest', 'montecarlo')),
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    config jsonb NOT NULL,
    config_hash char(32) NOT NULL,
    seed bigint NOT NULL,
    models text[] NOT NULL DEFAULT '{}',
    train_cutoff_contest integer,
    test_start_contest integer,
    test_end_contest integer,
    n_hypotheses integer,
    code_version text,
    data_fingerprint char(64),
    progress jsonb,
    conclusion jsonb,
    error text,
    job_id bigint REFERENCES job(job_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz
);
CREATE INDEX experiment_lookup_idx ON experiment(lottery_slug, kind, status, experiment_id DESC);

CREATE TABLE experiment_result (
    experiment_id bigint NOT NULL REFERENCES experiment(experiment_id) ON DELETE CASCADE,
    model_name text NOT NULL,
    metric_name text NOT NULL,
    value double precision,
    ci_low double precision,
    ci_high double precision,
    baseline_value double precision,
    baseline_ci_low double precision,
    baseline_ci_high double precision,
    p_value double precision,
    q_value double precision,
    verdict text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (experiment_id, model_name, metric_name)
);

CREATE TABLE suggestion_set (
    set_id bigserial PRIMARY KEY,
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    strategy text NOT NULL CHECK (strategy IN ('uniform_random', 'diversity', 'frequency_weighted', 'delay_weighted')),
    seed bigint NOT NULL,
    budget numeric(12,2),
    ticket_count integer NOT NULL CHECK (ticket_count BETWEEN 1 AND 200),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    based_on_contest integer,
    explanation jsonb,
    evidence jsonb,
    total_cost numeric(12,2),
    job_id bigint REFERENCES job(job_id),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);
CREATE INDEX suggestion_set_lookup_idx ON suggestion_set(lottery_slug, set_id DESC);

CREATE TABLE suggestion (
    set_id bigint NOT NULL REFERENCES suggestion_set(set_id) ON DELETE CASCADE,
    position smallint NOT NULL,
    numbers smallint[] NOT NULL,
    heuristic_score double precision NOT NULL CHECK (heuristic_score BETWEEN 0 AND 1),
    score_interpretation text NOT NULL,
    jackpot_numerator numeric NOT NULL,
    jackpot_denominator numeric NOT NULL,
    cost numeric(10,2) NOT NULL,
    PRIMARY KEY (set_id, position)
);

GRANT SELECT ON experiment, experiment_result, suggestion_set, suggestion TO cassino_api, cassino_inspect, cassino_worker;
GRANT INSERT ON experiment, suggestion_set TO cassino_api;
GRANT SELECT, INSERT, UPDATE ON experiment, suggestion_set TO cassino_worker;
GRANT INSERT, DELETE ON experiment_result, suggestion TO cassino_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cassino_worker;
GRANT USAGE ON SEQUENCE experiment_experiment_id_seq, suggestion_set_set_id_seq TO cassino_api;
-- cassino_api só enfileira jobs de experimento/sugestão, via INSERT já concedido em 003.

INSERT INTO schema_migration(name) VALUES ('006-experimentos-sugestoes');
COMMIT;
