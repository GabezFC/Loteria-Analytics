"""Coletor agendado: coleta incremental por modalidade, sem sobreposição, resiliente a falhas externas.

Agenda: a cada COLLECT_INTERVAL_MINUTES (padrão 360) por modalidade; em falha, backoff exponencial
(COLLECT_RETRY_MINUTES, padrão 15, teto = intervalo). Disparo manual: job kind='ingest' (lottery_slug
opcional) criado via API. O lock por modalidade é o advisory lock de ingest.py; falha da Caixa só
atualiza collector_status e nunca interrompe API/dashboard.
"""
from __future__ import annotations

import os
import signal
from datetime import datetime, timedelta, timezone
from threading import Event

import psycopg

import common
import ingest

INTERVAL = timedelta(minutes=int(os.environ.get("COLLECT_INTERVAL_MINUTES", "360")))
RETRY_BASE = timedelta(minutes=int(os.environ.get("COLLECT_RETRY_MINUTES", "15")))
STARTUP_DELAY = timedelta(seconds=int(os.environ.get("COLLECT_STARTUP_DELAY_S", "20")))
POLL_S = 30


def next_after_failure(failures: int) -> timedelta:
    return min(INTERVAL, RETRY_BASE * (2 ** max(0, failures - 1)))


def record_attempt(conn: psycopg.Connection, slug: str, ok: bool, error: str | None, now: datetime) -> datetime:
    with conn.transaction():
        row = conn.execute("SELECT consecutive_failures FROM collector_status WHERE lottery_slug=%s FOR UPDATE", (slug,)).fetchone()
        failures = 0 if ok else (row[0] if row else 0) + 1
        nxt = now + (INTERVAL if ok else next_after_failure(failures))
        conn.execute(
            "INSERT INTO collector_status(lottery_slug,last_attempt_at,last_success_at,last_error,consecutive_failures,next_attempt_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (lottery_slug) DO UPDATE SET last_attempt_at=EXCLUDED.last_attempt_at, "
            "last_success_at=COALESCE(EXCLUDED.last_success_at, collector_status.last_success_at), last_error=EXCLUDED.last_error, "
            "consecutive_failures=EXCLUDED.consecutive_failures, next_attempt_at=EXCLUDED.next_attempt_at",
            (slug, now, now if ok else None, None if ok else (error or "falha")[:500], failures, nxt),
        )
    return nxt


def collect_and_record(conn: psycopg.Connection, slug: str) -> datetime:
    error: str | None = None
    try:
        lottery = ingest.LOTTERIES[slug]
        data, url = ingest.download(lottery)
        r = ingest.ingest_one(lottery, data, url)
        print(
            f"coletor {slug}: run={r['run_id']} inseridos={r['inserted']} inalterados={r['unchanged']} premios_alterados={r['prize_changed']} "
            f"divergencias={r['divergent']} quarentena={r['quarantined']} analise_enfileirada={r['analysis_enqueued']}",
            flush=True,
        )
    except Exception as exc:  # falha externa/validação: registrar e seguir
        error = f"{type(exc).__name__}: {exc}"
        print(f"coletor {slug}: falhou ({error[:300]}); nova tentativa agendada", flush=True)
    return record_attempt(conn, slug, error is None, error, datetime.now(timezone.utc))


def seed_schedule(conn: psycopg.Connection, now: datetime) -> dict[str, datetime]:
    due: dict[str, datetime] = {}
    rows = {r[0]: r for r in conn.execute("SELECT lottery_slug, last_success_at, next_attempt_at FROM collector_status").fetchall()}
    for slug in ingest.LOTTERIES:
        r = rows.get(slug)
        start = now + STARTUP_DELAY
        if r and r[2]:
            start = max(r[2], start) if r[2] > now else start
        due[slug] = start
    return due


def run_forever(stop: Event) -> None:
    conn = common.connect("cassino-coletor", autocommit=True)
    common.reset_stale_jobs(conn, ["ingest"])
    due = seed_schedule(conn, datetime.now(timezone.utc))
    print(f"coletor iniciado: intervalo={INTERVAL} retry_base={RETRY_BASE}", flush=True)
    while not stop.is_set():
        common.heartbeat()
        try:
            if conn.closed:
                conn = common.connect("cassino-coletor", autocommit=True)
            job = common.claim_job(conn, ["ingest"])
            if job:
                job_id, _, slug, _ = job
                targets = [slug] if slug else list(ingest.LOTTERIES)
                for s in targets:
                    due[s] = collect_and_record(conn, s)
                    common.heartbeat()
                common.finish_job(conn, job_id)
            now = datetime.now(timezone.utc)
            for slug in ingest.LOTTERIES:
                if now >= due[slug] and not stop.is_set():
                    due[slug] = collect_and_record(conn, slug)
                    common.heartbeat()
        except psycopg.Error as exc:
            print(f"coletor: banco indisponível ({type(exc).__name__}); aguardando", flush=True)
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
