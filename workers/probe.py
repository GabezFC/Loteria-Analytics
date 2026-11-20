"""Entrypoint dos workers. `--health`: healthcheck (banco + heartbeat do laço).
Sem argumentos: executa o papel definido em WORKER_ROLE (coletor | analisador)."""
import os
import sys

import psycopg

import common


def probe():
    with psycopg.connect(connect_timeout=2) as conn:
        return conn.execute("SELECT count(*) FROM lottery_type").fetchone() == (3,)


def ready():
    try:
        return probe()
    except psycopg.Error:
        return False


if __name__ == "__main__":
    if "--health" in sys.argv:
        sys.exit(0 if ready() and common.heartbeat_fresh() else 1)
    role = os.environ["WORKER_ROLE"]
    if role == "coletor":
        import coletor
        coletor.main()
    elif role == "analisador":
        import analisador
        analisador.main()
    else:
        sys.exit(f"WORKER_ROLE desconhecido: {role}")
