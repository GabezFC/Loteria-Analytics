"""Configuração local do launcher (JSON). Validação estrita; nada de segredos aqui."""
from __future__ import annotations
import ipaddress
import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = {
    "version": 1,
    "project_name": "cassino",
    "admin_project_name": "cassino-admin",
    "ports": {"app": 3000, "cloudbeaver": 8978, "portainer": 9443},
    "optional_services": {"cloudbeaver": True, "portainer": True},
    "lan": {"enabled": False, "bind_address": "", "acknowledged": False},
    "release": {"repo": "", "channel": "stable"},
}


class ConfigError(ValueError):
    pass


def _copy(d):
    return json.loads(json.dumps(d))


@dataclass
class Config:
    data: dict = field(default_factory=lambda: _copy(DEFAULTS))

    @property
    def ports(self): return self.data["ports"]
    @property
    def lan(self): return self.data["lan"]
    @property
    def optional(self): return self.data["optional_services"]
    @property
    def project(self): return self.data["project_name"]
    @property
    def admin_project(self): return self.data["admin_project_name"]


def _merge(base: dict, over: dict, path="") -> dict:
    for k, v in over.items():
        if k not in base:
            raise ConfigError(f"chave desconhecida: {path}{k}")
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise ConfigError(f"{path}{k} deve ser objeto")
            _merge(base[k], v, f"{path}{k}.")
        else:
            if type(v) is not type(base[k]):
                raise ConfigError(f"{path}{k}: tipo inválido ({type(v).__name__})")
            base[k] = v
    return base


def validate(cfg: Config) -> Config:
    d = cfg.data
    if d["version"] != 1:
        raise ConfigError("version não suportada")
    for k in ("project_name", "admin_project_name"):
        v = d[k]
        if not v or not all(c.islower() or c.isdigit() or c in "-_" for c in v):
            raise ConfigError(f"{k} inválido (use minúsculas, dígitos, - e _)")
    if d["project_name"] == d["admin_project_name"]:
        raise ConfigError("as stacks principal e admin devem ter projetos distintos")
    seen = {}
    for name, p in d["ports"].items():
        if isinstance(p, bool) or not isinstance(p, int) or not 1024 <= p <= 65535:
            raise ConfigError(f"porta {name} fora de 1024-65535")
        if p in seen:
            raise ConfigError(f"porta {p} repetida em {seen[p]} e {name}")
        seen[p] = name
    lan = d["lan"]
    if lan["enabled"]:
        if not lan["acknowledged"]:
            raise ConfigError("LAN exige lan.acknowledged=true (habilitação explícita; o launcher não altera o firewall)")
        try:
            ip = ipaddress.ip_address(lan["bind_address"])
        except ValueError:
            raise ConfigError("lan.bind_address deve ser um IP privado informado pelo usuário")
        if ip.is_unspecified or ip.is_loopback or not ip.is_private:
            raise ConfigError("lan.bind_address não pode ser 0.0.0.0, loopback ou IP público")
    return cfg


def parse(text: str) -> Config:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"JSON inválido: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("raiz deve ser objeto")
    return validate(Config(_merge(_copy(DEFAULTS), raw)))


def load(path: Path) -> Config:
    if not path.exists():
        return validate(Config())
    return parse(path.read_text(encoding="utf-8"))
