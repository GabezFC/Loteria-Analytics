"""Backup (pg_dump) e verificação de restauração (pg_restore em contêiner descartável)."""
from __future__ import annotations
import hashlib
import json
import secrets
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .system import run

COUNT_SQL = (
    "select table_schema||'.'||table_name||'='||"
    "(xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text "
    "from information_schema.tables where table_schema not in ('pg_catalog','information_schema') "
    "and table_type='BASE TABLE' order by 1"
)
TEST_IMAGE = "postgres:17-alpine"


class BackupError(RuntimeError):
    pass


def parse_counts(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.rsplit("=", 1)
            out[k.strip()] = int(v)
    return out


def row_counts(container: str, db="cassino", user="postgres", runner=run) -> dict:
    p = runner(["docker", "exec", container, "psql", "-U", user, "-d", db, "-Atc", COUNT_SQL], timeout=120)
    if p.returncode:
        raise BackupError("contagem falhou: " + p.stderr.decode(errors="replace")[:300])
    return parse_counts(p.stdout.decode())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(container: str, dest_dir: Path, db="cassino", user="postgres", runner=run, now=datetime.now) -> Path:
    """pg_dump -Fc em modo somente leitura; transmite para o host. Não altera o banco."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"cassino-{now():%Y%m%d-%H%M%S}.dump"
    counts = row_counts(container, db, user, runner)
    tmp = out.with_suffix(".dump.part")
    with open(tmp, "wb") as f:
        p = subprocess.run(["docker", "exec", container, "pg_dump", "-U", user, "-d", db, "-Fc"],
                           stdout=f, stderr=subprocess.PIPE, timeout=3600)
    if p.returncode:
        tmp.unlink(missing_ok=True)
        raise BackupError("pg_dump falhou: " + p.stderr.decode(errors="replace")[:300])
    if tmp.stat().st_size < 1024:
        tmp.unlink(missing_ok=True)
        raise BackupError("dump suspeitamente pequeno; descartado")
    tmp.replace(out)
    digest = sha256_file(out)
    manifest = {"file": out.name, "sha256": digest, "bytes": out.stat().st_size, "database": db,
                "created": now().isoformat(timespec="seconds"), "row_counts": counts}
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def verify_restore(dump: Path, expected: dict | None = None, db="cassino", runner=run, image=TEST_IMAGE,
                   keep=False) -> dict:
    """Restaura o dump em contêiner PostgreSQL descartável (tmpfs, sem volume, sem portas) e compara contagens."""
    manifest_path = dump.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if manifest.get("sha256") and manifest["sha256"] != sha256_file(dump):
        raise BackupError("SHA-256 do dump difere do manifesto (arquivo corrompido ou alterado)")
    expected = expected if expected is not None else manifest.get("row_counts")
    if not expected:
        raise BackupError("sem contagens esperadas (manifesto ausente)")
    name = f"cassino-restore-test-{secrets.token_hex(4)}"
    pw = secrets.token_hex(16)  # senha descartável, só vive neste contêiner
    runner(["docker", "run", "-d", "--rm", "--name", name, "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
            "-e", f"POSTGRES_PASSWORD={pw}", image], timeout=300, check=True)
    try:
        for _ in range(60):
            if runner(["docker", "exec", name, "pg_isready", "-U", "postgres"], timeout=10).returncode == 0:
                # a imagem reinicia o servidor após o init; confirme duas leituras seguidas
                time.sleep(2)
                if runner(["docker", "exec", name, "pg_isready", "-U", "postgres"], timeout=10).returncode == 0:
                    break
            time.sleep(1)
        else:
            raise BackupError("PostgreSQL descartável não ficou pronto")
        runner(["docker", "exec", name, "createdb", "-U", "postgres", db], timeout=30, check=True)
        runner(["docker", "cp", str(dump), f"{name}:/tmp/restore.dump"], timeout=600, check=True)
        r = runner(["docker", "exec", name, "pg_restore", "-U", "postgres", "-d", db, "--no-owner", "--no-privileges",
                    "--exit-on-error", "/tmp/restore.dump"], timeout=1800)
        if r.returncode:
            raise BackupError("pg_restore falhou: " + r.stderr.decode(errors="replace")[:300])
        got = row_counts(name, db, "postgres", runner)
    finally:
        if not keep:
            runner(["docker", "rm", "-f", "-v", name], timeout=60)
    diff = {t: (expected.get(t), got.get(t)) for t in set(expected) | set(got) if expected.get(t) != got.get(t)}
    return {"ok": not diff, "tables": len(got), "rows": sum(got.values()), "diff": diff, "counts": got}
