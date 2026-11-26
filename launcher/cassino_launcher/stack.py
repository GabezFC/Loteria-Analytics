"""Ciclo de vida das duas stacks (principal e admin) via docker compose -p/-f existentes."""
from __future__ import annotations
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from .config import Config
from .system import run

CORE = ("postgres", "backend", "frontend")
WORKERS = ("coletor", "analisador")
DEFAULT_PORTS = {"app": 3000, "cloudbeaver": 8978, "portainer": 9443}
DOCKER_DESKTOP = ("ProgramFiles", r"Docker\Docker\Docker Desktop.exe")


class StackError(RuntimeError):
    pass


class Stack:
    def __init__(self, project_dir: Path, cfg: Config, runner=run):
        self.dir = Path(project_dir)
        self.cfg = cfg
        self.run = runner

    # ---- comandos compose ------------------------------------------------
    def main_args(self) -> list[str]:
        a = ["docker", "compose", "-p", self.cfg.project, "-f", str(self.dir / "compose.yaml")]
        if self.cfg.lan["enabled"]:
            a += ["-f", str(self.dir / "compose.lan.yaml")]
        rel = self.dir / "compose.release.yaml"  # presente só em pacotes de release (imagens GHCR versionadas)
        if rel.exists():
            a += ["-f", str(rel)]
        return a

    def admin_args(self) -> list[str]:
        return ["docker", "compose", "-p", self.cfg.admin_project, "-f", str(self.dir / "infra" / "portainer" / "compose.yaml")]

    def services(self) -> list[str]:
        s: list[str] = list(CORE + WORKERS)
        if self.cfg.optional["cloudbeaver"]:
            s.append("cloudbeaver")
        return s

    def preflight(self):
        """Valida arquivos/porta/LAN antes de qualquer comando que altere estado."""
        for f in ("compose.yaml",):
            if not (self.dir / f).exists():
                raise StackError(f"arquivo ausente: {self.dir / f}")
        if self.cfg.optional["portainer"] and not (self.dir / "infra" / "portainer" / "compose.yaml").exists():
            raise StackError("infra/portainer/compose.yaml ausente")
        if dict(self.cfg.ports) != DEFAULT_PORTS:
            raise StackError("portas diferentes do padrão ainda não são suportadas pelos compose.yaml atuais (fixas em 3000/8978/9443)")
        if self.cfg.lan["enabled"]:
            lan = self.dir / "compose.lan.yaml"
            if not lan.exists():
                raise StackError("LAN habilitada, mas compose.lan.yaml ausente")
            if self.cfg.lan["bind_address"] not in lan.read_text(encoding="utf-8"):
                raise StackError("lan.bind_address não consta em compose.lan.yaml; ajuste o arquivo de forma explícita (o launcher não o reescreve)")

    def validate_compose(self) -> list[str]:
        """`docker compose config -q` das duas stacks. Devolve erros (vazio = ok). Não imprime variáveis."""
        errs = []
        for name, args in (("principal", self.main_args()), ("admin", self.admin_args())):
            p = self.run(args + ["config", "-q"], timeout=60, cwd=str(self.dir))
            if p.returncode:
                errs.append(f"{name}: {p.stderr.decode(errors='replace').strip()[:300]}")
        return errs

    # ---- ações -----------------------------------------------------------
    def up(self, dry_run=False):
        extra = ["--dry-run"] if dry_run else []
        p = self.run(self.main_args() + extra + ["up", "-d"] + self.services(), timeout=1800, cwd=str(self.dir))
        if p.returncode:
            raise StackError("falha ao subir a stack principal: " + p.stderr.decode(errors="replace")[-400:])
        if self.cfg.optional["portainer"]:
            p = self.run(self.admin_args() + extra + ["up", "-d"], timeout=600, cwd=str(self.dir))
            if p.returncode:
                raise StackError("falha ao subir a stack admin: " + p.stderr.decode(errors="replace")[-400:])

    def stop(self):
        """Para sem remover contêineres nem volumes (nunca `down -v`)."""
        self.run(self.main_args() + ["stop"], timeout=300, cwd=str(self.dir))

    def stop_admin(self):
        self.run(self.admin_args() + ["stop"], timeout=120, cwd=str(self.dir))

    def ps(self, args=None) -> list[dict]:
        p = self.run((args or self.main_args()) + ["ps", "--all", "--format", "json"], timeout=60, cwd=str(self.dir))
        out = []
        for line in p.stdout.decode(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                out.append(json.loads(line))
        return out

    def status(self) -> list[dict]:
        rows = []
        for stack, args in (("principal", self.main_args()), ("admin", self.admin_args())):
            for c in self.ps(args):
                rows.append({"stack": stack, "service": c.get("Service"), "state": c.get("State"),
                             "health": c.get("Health") or "-", "status": c.get("Status")})
        return rows

    def logs(self, service: str, tail=100) -> str:
        if service not in self.services() + ["portainer"]:
            raise StackError(f"serviço desconhecido: {service}")
        args = self.admin_args() if service == "portainer" else self.main_args()
        p = self.run(args + ["logs", "--no-color", "--tail", str(int(tail)), service], timeout=60, cwd=str(self.dir))
        return (p.stdout + p.stderr).decode(errors="replace")

    def container_id(self, service: str) -> str:
        p = self.run(self.main_args() + ["ps", "-q", service], timeout=30, cwd=str(self.dir))
        cid = p.stdout.decode().strip().splitlines()
        if not cid:
            raise StackError(f"contêiner de {service} não está em execução")
        return cid[0]

    def wait_healthy(self, timeout=300, interval=3, sleep=time.sleep, clock=time.monotonic):
        end = clock() + timeout
        want = set(self.services())
        while True:
            by = {c["Service"]: c for c in self.ps()}
            pending = []
            for s in want:
                c = by.get(s)
                if not c or c.get("State") != "running" or c.get("Health") not in ("", "healthy", None):
                    pending.append(s)
            if not pending:
                return
            if clock() >= end:
                raise StackError("tempo esgotado aguardando: " + ", ".join(sorted(pending)))
            sleep(interval)


def http_ok(url: str, timeout=5) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def docker_desktop_path() -> Path | None:
    base = os.environ.get(DOCKER_DESKTOP[0])
    if base:
        p = Path(base) / DOCKER_DESKTOP[1]
        if p.exists():
            return p
    return None


def ensure_docker_running(runner=run, popen=subprocess.Popen, timeout=240, sleep=time.sleep, clock=time.monotonic,
                          desktop=docker_desktop_path) -> str:
    """Se o daemon não responde, inicia o Docker Desktop (já instalado) e aguarda. Nunca instala nada."""
    def alive():
        try:
            return runner(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    if alive():
        return "já em execução"
    exe = desktop()
    if not exe:
        raise StackError("Docker Desktop não encontrado. Instale-o em docker.com (o Cassino Launcher não o instala).")
    popen([str(exe)], close_fds=True)
    end = clock() + timeout
    while clock() < end:
        if alive():
            return "iniciado"
        sleep(3)
    raise StackError("Docker Desktop iniciado, mas o daemon não respondeu a tempo")
