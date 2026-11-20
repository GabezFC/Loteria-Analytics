"""Analisador: consome NOTIFY cassino_analysis_ready e a fila `job`.

NOTIFY apenas acorda o laço; a fonte da verdade é a tabela job (sobrevive a quedas e notificações
perdidas). Handlers são registrados em HANDLERS[kind]; etapas seguintes adicionam kinds sem alterar
o laço. Jobs só leem dados validados.
"""
from __future__ import annotations

import select
import signal
import traceback
from threading import Event
from typing import Callable

import psycopg

import common

HANDLERS: dict[str, Callable[[psycopg.Connection, int, str | None, dict], None]] = {}
POLL_S = 30


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


@handler("analyze")
def analyze(conn: psycopg.Connection, job_id: int, slug: str | None, params: dict) -> None:
    """Placeholder da etapa 03: confirma que o evento chegou sobre dados validados.
    A etapa 04 substitui por cálculo de estatísticas (módulo stats)."""
    row = conn.execute("SELECT count(*), max(contest) FROM lottery_draw WHERE lottery_slug=%s", (slug,)).fetchone()
    print(f"analisador: job {job_id} analyze {slug}: {row[0]} concursos validados, último {row[1]}", flush=True)


def load_optional_handlers() -> None:
    for name in ("stats_jobs", "experiment_jobs"):
        try:
            __import__(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise


def process_pending(conn: psycopg.Connection, stop: Event) -> int:
    done = 0
    while not stop.is_set():
        job = common.claim_job(conn, list(HANDLERS))
        if job is None:
            break
        job_id, kind, slug, params = job
        try:
            HANDLERS[kind](conn, job_id, slug, params or {})
            common.finish_job(conn, job_id)
        except Exception as exc:
            traceback.print_exc()
            common.finish_job(conn, job_id, f"{type(exc).__name__}: {exc}")
        done += 1
        common.heartbeat()
    return done


def run_forever(stop: Event) -> None:
    load_optional_handlers()
    conn = common.connect("cassino-analisador", autocommit=True)
    conn.execute("LISTEN cassino_analysis_ready")
    print(f"analisador iniciado: handlers={sorted(HANDLERS)}", flush=True)
    common.reset_stale_jobs(conn, list(HANDLERS))
    while not stop.is_set():
        common.heartbeat()
        try:
            if conn.closed:
                conn = common.connect("cassino-analisador", autocommit=True)
                conn.execute("LISTEN cassino_analysis_ready")
            process_pending(conn, stop)
            # Espera notificação (ou timeout de varredura).
            for _ in conn.notifies(timeout=POLL_S, stop_after=1):
                break
        except psycopg.Error as exc:
            print(f"analisador: banco indisponível ({type(exc).__name__}); aguardando", flush=True)
            try:
                conn.close()
            except psycopg.Error:
                pass
            stop.wait(POLL_S)


def main() -> None:
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run_forever(stop)


if __name__ == "__main__":
    main()
