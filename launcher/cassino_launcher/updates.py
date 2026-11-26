"""Verificação de atualizações: somente leitura da API pública de releases do GitHub."""
from __future__ import annotations
import json
import re
import urllib.request

API = "https://api.github.com/repos/{repo}/releases/latest"
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def parse_version(v: str):
    m = _SEMVER.match(v.strip())
    if not m:
        raise ValueError(f"versão inválida: {v!r}")
    a, b, c, pre = m.groups()
    # pré-lançamento < estável
    return (int(a), int(b), int(c), 0 if pre else 1, pre or "")


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def check(repo: str, current: str, opener=None) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise ValueError("release.repo ausente/ inválido (formato dono/repositório)")
    req = urllib.request.Request(API.format(repo=repo), headers={"Accept": "application/vnd.github+json",
                                                                 "User-Agent": "cassino-launcher"})
    with (opener or urllib.request.urlopen)(req, timeout=15) as r:
        rel = json.loads(r.read())
    tag = rel.get("tag_name", "")
    return {"current": current, "latest": tag, "update_available": is_newer(tag, current),
            "url": rel.get("html_url"), "prerelease": bool(rel.get("prerelease")),
            "assets": [a["name"] for a in rel.get("assets", [])]}
