#!/bin/sh
set -eu
psql -X --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv api API_PASSWORD
\getenv worker WORKER_PASSWORD
\getenv inspect INSPECT_PASSWORD
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CONNECT ON DATABASE cassino FROM PUBLIC;
CREATE ROLE cassino_api LOGIN PASSWORD :'api';
CREATE ROLE cassino_worker LOGIN PASSWORD :'worker';
CREATE ROLE cassino_inspect LOGIN PASSWORD :'inspect';
GRANT CONNECT ON DATABASE cassino TO cassino_api, cassino_worker, cassino_inspect;
GRANT USAGE ON SCHEMA public TO cassino_api, cassino_worker, cassino_inspect;
CREATE TABLE lottery_type (
    slug text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    pool_size smallint NOT NULL CHECK (pool_size > 0),
    draw_size smallint NOT NULL CHECK (draw_size BETWEEN 1 AND pool_size)
);
INSERT INTO lottery_type VALUES ('megasena','Mega-Sena',60,6),('lotofacil','Lotofácil',25,15),('quina','Quina',80,5);
GRANT SELECT ON lottery_type TO cassino_api, cassino_worker, cassino_inspect;
COMMIT;
SQL
