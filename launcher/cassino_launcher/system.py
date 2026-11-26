"""Execução de comandos e verificação de dependências."""
from __future__ import annotations
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass


def run(args, timeout=120, check=False, input_bytes=None, cwd=None):
    p = subprocess.run(args, capture_output=True, timeout=timeout, input=input_bytes, cwd=cwd)
    if check and p.returncode:
        raise RuntimeError(f"{' '.join(args[:3])} falhou: {p.stderr.decode(errors='replace').strip()[:400]}")
    return p


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def port_free(port: int, host="127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) != 0


def _decode(b: bytes) -> str:
    # wsl.exe imprime UTF-16LE
    return b.decode("utf-16-le", errors="ignore") if b[1:2] == b"\x00" else b.decode(errors="replace")


def check_dependencies(ports, project_dir=".", runner=run, free=port_free, disk=shutil.disk_usage,
                       machine=platform.machine, system=platform.system, min_gb=10, ports_owned=()):
    res = []
    res.append(Check("Windows x64", system() == "Windows" and machine().lower() in ("amd64", "x86_64"),
                     f"{system()} {machine()}"))
    try:
        p = runner(["docker", "version", "--format", "{{.Server.Version}}"], timeout=20)
        ok = p.returncode == 0 and bool(p.stdout.strip())
        res.append(Check("Docker Engine", ok, p.stdout.decode().strip() if ok else "daemon não responde (Docker Desktop iniciado?)"))
    except (OSError, subprocess.TimeoutExpired):
        res.append(Check("Docker Engine", False, "docker não encontrado ou sem resposta"))
    try:
        p = runner(["docker", "compose", "version", "--short"], timeout=20)
        res.append(Check("Docker Compose v2", p.returncode == 0, p.stdout.decode().strip() or "ausente"))
    except (OSError, subprocess.TimeoutExpired):
        res.append(Check("Docker Compose v2", False, "ausente"))
    # WSL2 é informativo: o Docker Desktop pode usar outro backend.
    try:
        p = runner(["wsl", "--status"], timeout=15)
        res.append(Check("WSL2", p.returncode == 0, "disponível" if p.returncode == 0 else "não detectado", required=False))
    except (OSError, subprocess.TimeoutExpired):
        res.append(Check("WSL2", False, "wsl.exe não encontrado", required=False))
    free_gb = disk(project_dir).free / 2**30
    res.append(Check("Espaço em disco", free_gb >= min_gb, f"{free_gb:.1f} GB livres (mínimo {min_gb})"))
    for name, port in ports.items():
        is_free = free(port)
        ok = is_free or port in ports_owned
        res.append(Check(f"Porta {port} ({name})", ok,
                         "livre" if is_free else ("em uso pelo próprio Cassino" if ok else "ocupada por outro processo")))
    return res
