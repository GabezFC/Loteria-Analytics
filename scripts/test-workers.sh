#!/usr/bin/env bash
# Testes dos workers contra um PostgreSQL DESCARTÁVEL (container efêmero; nunca toca o banco do Cassino).
# Aplica 001-base.sh e todas as migrations infra/postgres/0NN-*.sql em ordem.
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=cassino-test-pg-$$
PW=testpw
MOUNTS=(-v "$PWD/infra/postgres/001-base.sh:/docker-entrypoint-initdb.d/001-base.sh:ro")
for f in infra/postgres/0*.sql; do
  MOUNTS+=(-v "$PWD/$f:/docker-entrypoint-initdb.d/$(basename "$f"):ro")
done
docker run -d --rm --name "$NAME" -p 127.0.0.1:55432:5432 \
  -e POSTGRES_DB=cassino -e POSTGRES_PASSWORD=$PW -e API_PASSWORD=$PW -e WORKER_PASSWORD=$PW -e INSPECT_PASSWORD=$PW \
  "${MOUNTS[@]}" postgres:17-alpine >/dev/null
trap 'docker stop "$NAME" >/dev/null 2>&1 || true' EXIT
# O entrypoint inicia um servidor temporário durante o init; esperar o servidor definitivo.
for i in $(seq 1 90); do
  if docker logs "$NAME" 2>&1 | grep -q "PostgreSQL init process complete" && docker exec "$NAME" pg_isready -U postgres -d cassino -h 127.0.0.1 >/dev/null 2>&1; then break; fi
  sleep 1
done
cd workers
TEST_ADMIN_DSN="host=127.0.0.1 port=55432 dbname=cassino user=postgres password=$PW" \
PGHOST=127.0.0.1 PGPORT=55432 PGDATABASE=cassino PGUSER=cassino_worker PGPASSWORD=$PW \
  uv run --with 'psycopg[binary]==3.2.13' --with-requirements requirements.txt \
  python -m unittest discover -p '*_test.py' -v "$@"
