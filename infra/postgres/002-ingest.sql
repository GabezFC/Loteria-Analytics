-- Etapa 03. Aplicar uma vez no banco cassino após 001-base.sh.
BEGIN;

CREATE TABLE lottery_draw (
    draw_id bigserial PRIMARY KEY,
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    contest integer NOT NULL CHECK (contest > 0),
    draw_date date NOT NULL,
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    ingest_run_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lottery_slug, contest),
    UNIQUE (draw_id, lottery_slug)
);

CREATE TABLE draw_number (
    draw_id bigint NOT NULL REFERENCES lottery_draw(draw_id) ON DELETE CASCADE,
    number smallint NOT NULL CHECK (number > 0),
    PRIMARY KEY (draw_id, number)
);

CREATE TABLE ingest_run (
    ingest_run_id bigserial PRIMARY KEY,
    lottery_slug text NOT NULL REFERENCES lottery_type(slug),
    source_url text NOT NULL,
    source_sha256 char(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    source_bytes bigint NOT NULL CHECK (source_bytes > 0),
    adapter_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','succeeded','failed')),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    row_count integer NOT NULL CHECK (row_count >= 0),
    checkpoint_contest integer,
    inserted_count integer NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    updated_count integer NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
    unchanged_count integer NOT NULL DEFAULT 0 CHECK (unchanged_count >= 0),
    error_message text,
    CHECK ((status = 'running' AND completed_at IS NULL) OR (status <> 'running' AND completed_at IS NOT NULL))
);

ALTER TABLE lottery_draw ADD CONSTRAINT lottery_draw_run_fk
    FOREIGN KEY (ingest_run_id) REFERENCES ingest_run(ingest_run_id);

CREATE TABLE ingest_draw_change (
    change_id bigserial PRIMARY KEY,
    ingest_run_id bigint NOT NULL REFERENCES ingest_run(ingest_run_id),
    draw_id bigint NOT NULL REFERENCES lottery_draw(draw_id),
    action text NOT NULL CHECK (action = 'reconciled'),
    previous_value jsonb NOT NULL,
    current_value jsonb NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX lottery_draw_date_idx ON lottery_draw(lottery_slug, draw_date, contest);
CREATE INDEX ingest_run_status_idx ON ingest_run(status, started_at DESC);

GRANT SELECT ON lottery_draw, draw_number, ingest_run, ingest_draw_change TO cassino_api, cassino_inspect;
GRANT SELECT, INSERT, UPDATE ON lottery_draw, draw_number, ingest_run, ingest_draw_change TO cassino_worker;
GRANT DELETE ON draw_number TO cassino_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cassino_worker;

COMMIT;
