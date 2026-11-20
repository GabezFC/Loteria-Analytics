"""Infra compartilhada dos workers: conexão, heartbeat e fila de jobs."""
from __future__ import annotations

import os
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb  # noqa: F401  (reexportado para handlers)

HEARTBEAT_FILE = Path(os.environ.get("WORKER_HEARTBEAT_FILE", "/tmp/worker-heartbeat"))
HEARTBEAT_MAX_AGE_S = 600


def connect(name: str = "cassino-worker", autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(connect_timeout=5, application_name=name, autocommit=autocommit)


def heartbeat() -> None:
    try:
        HEARTBEAT_FILE.write_text(str(time.time()))
    except OSError:
        pass


def heartbeat_fresh() -> bool:
    try:
        return time.time() - float(HEARTBEAT_FILE.read_text()) < HEARTBEAT_MAX_AGE_S
    except (OSError, ValueError):
        return False


def reset_stale_jobs(conn: psycopg.Connection, kinds: list[str]) -> int:
    """Jobs 'running' de um processo anterior (queda/reinício) voltam para 'pending'."""
    with conn.transaction():
        cur = conn.execute("UPDATE job SET status='pending', started_at=NULL WHERE status='running' AND kind = ANY(%s)", (kinds,))
        return cur.rowcount


def claim_job(conn: psycopg.Connection, kinds: list[str]):
    """Reivindica o job pendente mais antigo (SKIP LOCKED). Retorna (id, kind, slug, params) ou None."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE job SET status='running', started_at=now(), attempts=attempts+1 WHERE job_id = ("
            " SELECT job_id FROM job WHERE status='pending' AND kind = ANY(%s) ORDER BY created_at, job_id FOR UPDATE SKIP LOCKED LIMIT 1)"
            " RETURNING job_id, kind, lottery_slug, params",
            (kinds,),
        ).fetchone()
    return row


def finish_job(conn: psycopg.Connection, job_id: int, error: str | None = None) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE job SET status=%s, finished_at=now(), error=%s WHERE job_id=%s",
            ("failed" if error else "succeeded", error[:1000] if error else None, job_id),
        )
