"""CLI do Cassino Launcher. Uso: python -m cassino_launcher <comando> [opções]."""
from __future__ import annotations
import argparse
import logging
import os
import sys
import webbrowser
from pathlib import Path

from . import __version__, backup as bk, envgen, updates
from .config import ConfigError, load
from .stack import Stack, StackError, ensure_docker_running, http_ok
from .system import check_dependencies

APP_URL = "http://localhost:3000"


def default_home() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "Cassino"


def setup_logging(home: Path):
    (home / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(home / "logs" / "launcher.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")


def say(msg=""):
    print(msg, flush=True)


def print_checks(checks) -> bool:
    ok = True
    for c in checks:
        mark = "OK " if c.ok else ("AVISO" if not c.required else "FALHA")
        say(f"  [{mark}] {c.name}: {c.detail}")
        ok &= c.ok or not c.required
    return ok


def own_ports(stack: Stack) -> set:
    ports = set()
    try:
        if any(r["state"] == "running" for r in stack.status() if r["stack"] == "principal"):
            ports |= {3000, 8978}
        if any(r["state"] == "running" for r in stack.status() if r["stack"] == "admin"):
            ports.add(9443)
    except Exception:
        pass
    return ports


def cmd_init(a, stack: Stack, home: Path, cfg) -> int:
    """Fluxo idempotente: pode ser repetido sem efeito colateral além do necessário."""
    say("1/7 Docker")
    say(f"  Docker Desktop: {ensure_docker_running()}")
    say("2/7 Dependências")
    if not print_checks(check_dependencies(cfg.ports, str(home), ports_owned=own_ports(stack))):
        say("Corrija os itens FALHA e execute novamente."); return 2
    say("3/7 Configuração local")
    stack.preflight(); say("  config.json válida; arquivos de compose presentes")
    say("4/7 Segredos (.env)")
    env = stack.dir / ".env"
    if a.dry_run:
        say(f"  (dry-run) variáveis ausentes/fracas: {envgen.check_env(env) or 'nenhuma'}")
    else:
        gen = envgen.ensure_env(env)
        say(f"  geradas: {', '.join(gen)}" if gen else "  .env já completo; nada alterado")
        weak = envgen.check_env(env)
        if weak:
            say(f"  .env com variáveis fracas/repetidas: {weak}"); return 2
    say("5/7 Validação dos compose")
    errs = stack.validate_compose()
    if errs:
        for e in errs: say("  " + e)
        return 2
    say("  docker compose config: OK (principal e admin)")
    say("6/7 Subindo stacks (principal e admin separadas)")
    stack.up(dry_run=a.dry_run)
    if a.dry_run:
        say("(dry-run) nada foi alterado."); return 0
    stack.wait_healthy(timeout=a.timeout)
    say("7/7 Confirmação")
    states = {r["service"]: r for r in stack.status()}
    for s in ("postgres", "backend", "frontend"):
        say(f"  {s}: {states[s]['state']}/{states[s]['health']}")
    if not http_ok(APP_URL + "/api/health"):
        say("  /api/health não respondeu"); return 3
    say(f"  {APP_URL}: pronto")
    if not a.no_browser:
        webbrowser.open(APP_URL)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cassino-launcher")
    ap.add_argument("--home", type=Path, default=default_home(), help="pasta de estado (config, logs, backups)")
    ap.add_argument("--project-dir", type=Path, help="pasta com compose.yaml (padrão: <home>/app)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="verifica, configura, sobe e abre o Cassino")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--no-browser", action="store_true")
    p.add_argument("--timeout", type=int, default=300)
    sub.add_parser("check", help="dependências do sistema")
    sub.add_parser("validate", help="config.json + docker compose config -q")
    sub.add_parser("stop", help="para as stacks sem remover dados")
    sub.add_parser("restart", help="reinicia a stack principal")
    sub.add_parser("status", help="estado e saúde dos contêineres")
    p = sub.add_parser("logs"); p.add_argument("service"); p.add_argument("--tail", type=int, default=100)
    p = sub.add_parser("backup"); p.add_argument("--out", type=Path)
    p = sub.add_parser("verify-backup", help="restaura em contêiner descartável e compara contagens")
    p.add_argument("dump", type=Path)
    p = sub.add_parser("update-check"); p.add_argument("--repo")
    a = ap.parse_args(argv)

    home = a.home
    setup_logging(home)
    try:
        cfg = load(home / "config.json")
    except ConfigError as e:
        say(f"config.json inválido: {e}"); return 2
    project_dir = a.project_dir or home / "app"
    stack = Stack(project_dir, cfg)
    log = logging.getLogger("launcher")
    log.info("comando %s", a.cmd)
    try:
        if a.cmd == "init":
            return cmd_init(a, stack, home, cfg)
        if a.cmd == "check":
            return 0 if print_checks(check_dependencies(cfg.ports, str(home), ports_owned=own_ports(stack))) else 2
        if a.cmd == "validate":
            stack.preflight()
            errs = stack.validate_compose()
            say("compose inválido:\n" + "\n".join(errs) if errs else "config.json e compose: OK")
            return 2 if errs else 0
        if a.cmd == "stop":
            stack.stop(); stack.stop_admin(); say("Parado (contêineres e volumes preservados)."); return 0
        if a.cmd == "restart":
            stack.stop(); stack.up(); stack.wait_healthy(); say("Reiniciado."); return 0
        if a.cmd == "status":
            for r in stack.status():
                say(f"{r['stack']:<10} {r['service']:<12} {r['state']:<10} {r['health']:<10} {r['status']}")
            return 0
        if a.cmd == "logs":
            say(stack.logs(a.service, a.tail)); return 0
        if a.cmd == "backup":
            out = bk.backup(stack.container_id("postgres"), a.out or home / "backups")
            say(f"Backup: {out}\nSHA-256: {bk.sha256_file(out)}"); return 0
        if a.cmd == "verify-backup":
            r = bk.verify_restore(a.dump)
            say(f"restauração em contêiner descartável: {'OK' if r['ok'] else 'DIVERGENTE'} — {r['tables']} tabelas, {r['rows']} linhas")
            for t, (e, g) in r["diff"].items(): say(f"  {t}: esperado {e}, obtido {g}")
            return 0 if r["ok"] else 4
        if a.cmd == "update-check":
            repo = a.repo or cfg.data["release"]["repo"]
            r = updates.check(repo, os.environ.get("CASSINO_VERSION", __version__))
            say(f"instalada {r['current']} · última {r['latest']} · {'ATUALIZAÇÃO DISPONÍVEL' if r['update_available'] else 'em dia'}")
            return 0
    except (StackError, bk.BackupError, ValueError, RuntimeError, OSError) as e:
        log.error("%s: %s", a.cmd, e)
        say(f"Erro: {e}"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
