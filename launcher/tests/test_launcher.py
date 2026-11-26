"""Testes sem Docker real: runners e relógios simulados. Execute: python -m unittest discover -s launcher/tests"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cassino_launcher import backup, config, envgen, stack as stk, system, updates  # noqa: E402


def cp(out=b"", code=0, err=b""):
    return SimpleNamespace(returncode=code, stdout=out, stderr=err)


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        c = config.parse("{}")
        self.assertEqual(c.ports, {"app": 3000, "cloudbeaver": 8978, "portainer": 9443})
        self.assertFalse(c.lan["enabled"])

    def test_missing_file_gives_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(config.load(Path(d) / "x.json").project, "cassino")

    def test_rejects(self):
        bad = ['{', '[]', '{"foo":1}', '{"ports":{"app":"3000"}}', '{"ports":{"app":80}}',
               '{"ports":{"app":3000,"portainer":3000}}', '{"project_name":"A b"}',
               '{"admin_project_name":"cassino"}', '{"ports":{"app":true}}']
        for t in bad:
            with self.assertRaises(config.ConfigError, msg=t):
                config.parse(t)

    def test_lan_requires_explicit_ack_and_private_ip(self):
        for lan in ({"enabled": True}, {"enabled": True, "acknowledged": True},
                    {"enabled": True, "acknowledged": True, "bind_address": "0.0.0.0"},
                    {"enabled": True, "acknowledged": True, "bind_address": "127.0.0.1"},
                    {"enabled": True, "acknowledged": True, "bind_address": "8.8.8.8"},
                    {"enabled": True, "acknowledged": False, "bind_address": "192.168.1.5"}):
            with self.assertRaises(config.ConfigError, msg=str(lan)):
                config.parse(json.dumps({"lan": lan}))
        ok = config.parse(json.dumps({"lan": {"enabled": True, "acknowledged": True, "bind_address": "10.1.2.3"}}))
        self.assertTrue(ok.lan["enabled"])


class EnvTests(unittest.TestCase):
    def test_generate_unique_strong_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            self.assertEqual(envgen.ensure_env(p, "1.2.3"), list(envgen.REQUIRED) + ["CASSINO_VERSION"])
            env = envgen.parse_env(p.read_text())
            pw = [env[k] for k in envgen.REQUIRED]
            self.assertTrue(all(len(x) == 32 and x.isalnum() for x in pw))
            self.assertEqual(len(set(pw)), 4)
            before = p.read_text()
            self.assertEqual(envgen.ensure_env(p, "1.2.3"), [])
            self.assertEqual(p.read_text(), before)
            self.assertEqual(envgen.check_env(p), [])

    def test_two_installs_differ(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            envgen.ensure_env(a); envgen.ensure_env(b)
            self.assertNotEqual(envgen.parse_env(a.read_text()), envgen.parse_env(b.read_text()))

    def test_preserves_existing_and_fills_blank(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("POSTGRES_PASSWORD=keepkeepkeepkeepkeep\nAPI_PASSWORD=\nOTHER=x\n")
            gen = envgen.ensure_env(p)
            self.assertEqual(set(gen), {"API_PASSWORD", "WORKER_PASSWORD", "INSPECT_PASSWORD"})
            env = envgen.parse_env(p.read_text())
            self.assertEqual(env["POSTGRES_PASSWORD"], "keepkeepkeepkeepkeep")
            self.assertEqual(env["OTHER"], "x")

    def test_check_env_flags_weak_and_repeated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("\n".join(f"{k}=short" for k in envgen.REQUIRED))
            self.assertEqual(set(envgen.check_env(p)) & set(envgen.REQUIRED), set(envgen.REQUIRED))
            same = "x" * 20
            p.write_text("\n".join(f"{k}={same}" for k in envgen.REQUIRED))
            self.assertIn("(senhas repetidas)", envgen.check_env(p))

    def test_package_never_embeds_env(self):
        root = Path(__file__).resolve().parents[1]
        for f in root.rglob("*.py"):
            self.assertNotRegex(f.read_text(encoding="utf-8"), r"(?m)^\s*(POSTGRES|API|WORKER|INSPECT)_PASSWORD=\w{8}")


class DependencyTests(unittest.TestCase):
    def run_checks(self, **kw):
        base = dict(runner=lambda a, timeout=0: cp(b"29.0.0\n"), free=lambda p: True,
                    disk=lambda p: SimpleNamespace(free=50 * 2**30), machine=lambda: "AMD64", system=lambda: "Windows")
        base.update(kw)
        return {c.name: c for c in system.check_dependencies({"app": 3000}, ".", **base)}

    def test_ok(self):
        r = self.run_checks()
        self.assertTrue(all(c.ok for c in r.values()), r)

    def test_failures(self):
        self.assertFalse(self.run_checks(machine=lambda: "ARM64")["Windows x64"].ok)
        self.assertFalse(self.run_checks(system=lambda: "Linux")["Windows x64"].ok)
        self.assertFalse(self.run_checks(free=lambda p: False)["Porta 3000 (app)"].ok)
        self.assertTrue(self.run_checks(free=lambda p: False, ports_owned={3000})["Porta 3000 (app)"].ok)
        self.assertFalse(self.run_checks(disk=lambda p: SimpleNamespace(free=2**30))["Espaço em disco"].ok)

        def boom(a, timeout=0): raise FileNotFoundError
        r = self.run_checks(runner=boom)
        self.assertFalse(r["Docker Engine"].ok); self.assertFalse(r["Docker Compose v2"].ok)
        self.assertFalse(r["WSL2"].ok); self.assertFalse(r["WSL2"].required)


class StackTests(unittest.TestCase):
    def mk(self, cfg_json="{}", runner=None):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        root = Path(d.name)
        (root / "infra" / "portainer").mkdir(parents=True)
        (root / "compose.yaml").write_text("services: {}"); (root / "infra/portainer/compose.yaml").write_text("services: {}")
        return stk.Stack(root, config.parse(cfg_json), runner or (lambda *a, **k: cp())), root

    def test_separate_projects_and_no_destructive_flags(self):
        s, _ = self.mk()
        m, a = s.main_args(), s.admin_args()
        self.assertEqual(m[3:5], ["cassino", "-f"]); self.assertEqual(a[3], "cassino-admin")
        self.assertNotIn("-v", m + a); self.assertNotIn("down", m + a)

    def test_services_and_optional(self):
        s, _ = self.mk('{"optional_services":{"cloudbeaver":false}}')
        self.assertNotIn("cloudbeaver", s.services())

    def test_preflight(self):
        s, root = self.mk(); s.preflight()
        (root / "compose.yaml").unlink()
        with self.assertRaises(stk.StackError): s.preflight()
        s, _ = self.mk('{"ports":{"app":3100}}')
        with self.assertRaises(stk.StackError): s.preflight()

    def test_lan_needs_matching_file(self):
        lan = '{"lan":{"enabled":true,"acknowledged":true,"bind_address":"192.168.7.7"}}'
        s, root = self.mk(lan)
        with self.assertRaises(stk.StackError): s.preflight()
        (root / "compose.lan.yaml").write_text("ports: ['10.0.0.1:3000:80']")
        with self.assertRaises(stk.StackError): s.preflight()
        (root / "compose.lan.yaml").write_text("ports: ['192.168.7.7:3000:80']")
        s.preflight(); self.assertIn("compose.lan.yaml", " ".join(s.main_args()))

    def test_wait_healthy(self):
        states = [
            [{"Service": "postgres", "State": "running", "Health": "starting"}],
            [{"Service": x, "State": "running", "Health": "healthy" if x in stk.CORE + stk.WORKERS else ""}
             for x in ("postgres", "backend", "frontend", "coletor", "analisador", "cloudbeaver")],
        ]
        s, _ = self.mk()
        it = iter(states); s.ps = lambda args=None: next(it)
        s.wait_healthy(sleep=lambda x: None)
        s.ps = lambda args=None: [{"Service": "postgres", "State": "running", "Health": "unhealthy"}]
        t = iter(range(0, 1000, 100))
        with self.assertRaises(stk.StackError): s.wait_healthy(timeout=250, sleep=lambda x: None, clock=lambda: next(t))

    def test_ps_parses_ndjson(self):
        line = json.dumps({"Service": "backend", "State": "running", "Health": "healthy"}).encode()
        s, _ = self.mk(runner=lambda *a, **k: cp(line + b"\n" + line))
        self.assertEqual(len(s.ps()), 2)

    def test_ensure_docker_starts_desktop_once(self):
        calls = {"alive": 0, "popen": 0}
        def runner(a, timeout=0):
            calls["alive"] += 1
            return cp(code=0 if calls["alive"] > 3 else 1)
        def popen(a, **k): calls["popen"] += 1
        r = stk.ensure_docker_running(runner, popen, sleep=lambda x: None, desktop=lambda: Path("DD.exe"))
        self.assertEqual((r, calls["popen"]), ("iniciado", 1))
        with self.assertRaises(stk.StackError):
            stk.ensure_docker_running(lambda a, timeout=0: cp(code=1), popen, desktop=lambda: None)

    def test_logs_rejects_unknown_service(self):
        s, _ = self.mk()
        with self.assertRaises(stk.StackError): s.logs("x; rm -rf /")


class BackupTests(unittest.TestCase):
    def test_parse_counts(self):
        self.assertEqual(backup.parse_counts("public.a=3\npublic.b=0\n"), {"public.a": 3, "public.b": 0})

    def test_verify_detects_divergence_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d) / "x.dump"; dump.write_bytes(b"0" * 2048)
            calls = []
            def runner(a, timeout=0, check=False, **k):
                calls.append(a)
                if "psql" in a: return cp(b"public.a=2\n")
                return cp()
            r = backup.verify_restore(dump, {"public.a": 3}, runner=runner)
            self.assertFalse(r["ok"]); self.assertEqual(r["diff"], {"public.a": (3, 2)})
            self.assertEqual(calls[-1][:3], ["docker", "rm", "-f"])
            run_cmd = next(c for c in calls if c[:2] == ["docker", "run"])
            self.assertIn("none", run_cmd); self.assertNotIn("-p", run_cmd); self.assertNotIn("-v", run_cmd)

    def test_verify_rejects_tampered_dump(self):
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d) / "x.dump"; dump.write_bytes(b"0" * 2048)
            dump.with_suffix(".json").write_text(json.dumps({"sha256": "0" * 64, "row_counts": {"a": 1}}))
            with self.assertRaises(backup.BackupError): backup.verify_restore(dump, runner=lambda *a, **k: cp())


class UpdateTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(updates.is_newer("v1.2.0", "1.1.9"))
        self.assertFalse(updates.is_newer("1.0.0-rc1", "1.0.0"))
        self.assertTrue(updates.is_newer("1.0.0", "1.0.0-rc1"))
        with self.assertRaises(ValueError): updates.parse_version("latest")

    def test_check_uses_get_only(self):
        seen = {}
        class R:
            def __enter__(s): return s
            def __exit__(s, *a): pass
            def read(s): return json.dumps({"tag_name": "v0.2.0", "html_url": "u", "assets": [{"name": "Cassino-Setup.exe"}]}).encode()
        def opener(req, timeout=0): seen["m"] = req.get_method(); seen["u"] = req.full_url; return R()
        r = updates.check("o/r", "0.1.0", opener)
        self.assertTrue(r["update_available"]); self.assertEqual(seen["m"], "GET")
        self.assertIn("api.github.com/repos/o/r/", seen["u"])
        with self.assertRaises(ValueError): updates.check("bad repo", "0.1.0", opener)


if __name__ == "__main__":
    unittest.main()
