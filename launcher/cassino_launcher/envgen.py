"""Geração idempotente do .env com senhas únicas por instalação."""
from __future__ import annotations
import os
import secrets
from pathlib import Path

REQUIRED = ("POSTGRES_PASSWORD", "API_PASSWORD", "WORKER_PASSWORD", "INSPECT_PASSWORD")
# Só letras e dígitos: seguro em .env, URLs e shell. 32 caracteres ~ 190 bits.
_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def strong_password(n: int = 32) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def parse_env(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def ensure_env(path: Path, version: str | None = None) -> list[str]:
    """Cria/completa o .env. Nunca sobrescreve valor existente. Devolve NOMES gerados (nunca valores)."""
    text = path.read_text(encoding="utf-8") if path.exists() else None
    existing = parse_env(text) if text else {}
    missing = [k for k in REQUIRED if not existing.get(k)]
    if version and not existing.get("CASSINO_VERSION"):
        missing.append("CASSINO_VERSION")
    if not missing:
        return []
    if text is not None:
        lines = [l for l in text.splitlines() if l.split("=", 1)[0].strip() not in missing]
    else:
        lines = ["# Gerado pelo Cassino Launcher. Não versionar nem compartilhar."]
    for k in missing:
        lines.append(f"{k}={version if k == 'CASSINO_VERSION' else strong_password()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return missing


def check_env(path: Path) -> list[str]:
    """Lista NOMES de variáveis ausentes/fracas (sem expor valores)."""
    if not path.exists():
        return list(REQUIRED)
    env = parse_env(path.read_text(encoding="utf-8"))
    bad = [k for k in REQUIRED if len(env.get(k, "")) < 16]
    vals = [env[k] for k in REQUIRED if env.get(k)]
    if len(set(vals)) != len(vals):
        bad.append("(senhas repetidas)")
    return bad
