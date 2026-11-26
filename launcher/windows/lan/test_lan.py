"""Isolated LAN acceptance. Only publishes ephemeral IPv4 loopback ports."""
import base64
import contextlib
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'integration'))
from stage_assets import OWNER_LABEL, stage  # type: ignore[import-not-found]


def run(*cmd, env=None, data=None):
    result = subprocess.run(cmd, env=env, input=data, capture_output=True, timeout=120)
    if result.returncode:
        # Don't dump Compose environments or bootstrap inputs.
        raise RuntimeError(f'{cmd[0]} {cmd[1]} failed (exit {result.returncode})')
    return result.stdout


def certs(root):
    ca, cert, key, csr, ext = [root / n for n in ('ca.pem', 'cert.pem', 'key.pem', 'req.pem', 'ext.txt')]
    cakey = root / 'ca-key.pem'
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=Cassino test CA', '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', str(cakey), '-out', str(ca))
    run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=Cassino test',
        '-keyout', str(key), '-out', str(csr))
    ext.write_text('subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\n'
                   'authorityKeyIdentifier=keyid\nsubjectKeyIdentifier=hash\n', encoding='ascii')
    run('openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca), '-CAkey', str(cakey),
        '-CAcreateserial', '-days', '1', '-extfile', str(ext), '-out', str(cert))
    return cert, key, ca


def ports():
    with contextlib.ExitStack() as stack:
        listeners = [stack.enter_context(socket.socket()) for _ in range(2)]
        for listener in listeners:
            listener.bind(('127.0.0.1', 0))
        return [listener.getsockname()[1] for listener in listeners]


def env_for_test():
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(
        ('CASSINO_', 'COMPOSE_', 'DOCKER_')) and not k.upper().endswith('_PASSWORD')}


class BootstrapTest(unittest.TestCase):
    def test_missing_explicit_consent_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'lan'
            result = subprocess.run([sys.executable, str(HERE / 'bootstrap.py'), '--output', str(path)],
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(path.exists())

    def test_certificate_for_different_ip_is_rejected(self):
        from bootstrap import verify_tls
        with tempfile.TemporaryDirectory() as folder:
            cert, key, ca = certs(Path(folder))
            with self.assertRaises(ValueError):
                verify_tls(cert, key, ca, '127.0.0.2')


class LanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bootstrap import provision
        directory = tempfile.TemporaryDirectory(prefix='cassino-lan-')
        cls.addClassCleanup(directory.cleanup)
        root = Path(directory.name)
        cert, key, ca = certs(root)
        cls.local, cls.tls = ports()
        cls.authority = f'127.0.0.1:{cls.tls}'
        cls.context = ssl.create_default_context(cafile=str(ca))
        password = secrets.token_urlsafe(24)
        cls.auth = 'Basic ' + base64.b64encode(f'lan-test:{password}'.encode()).decode()
        runtime = provision(root / 'lan payload', '127.0.0.1', cls.tls, cert, key, ca, 'lan-test', password)
        assets = root / 'app assets'
        stage(assets)
        # Use actual backend + DB. No volumes, workers, consoles, outbound feeds, or live project.
        fixture = HERE / 'compose.test.yaml'
        owner = secrets.token_hex(16)
        project = f'cassino-lan-check-{owner[:12]}'
        fake = root / 'db.env'
        fake.write_text(''.join(f'{key}_PASSWORD={secrets.token_hex(20)}\n' for key in (
            'POSTGRES', 'API', 'WORKER', 'INSPECT')), encoding='ascii')
        base_runtime = root / 'runtime.env'
        base_runtime.write_text(f'CASSINO_LAUNCHER_OWNER={owner}\nCASSINO_APP_PORT={cls.local}\n', encoding='ascii')
        cls.env = env_for_test()
        base = ['docker', 'compose', '--project-directory', str(assets), '-p', project,
                '--env-file', str(fake), '--env-file', str(base_runtime),
                '-f', str(assets / 'compose.yaml'), '-f', str(assets / 'lan/compose.local.yaml')]
        cls.cmd = base + ['--env-file', str(runtime), '-f', str(assets / 'lan/compose.lan.yaml')]
        base_model = json.loads(run(*base, 'config', '--format', 'json', env=cls.env))
        assert len(base_model['services']['frontend']['ports']) == 1
        model = json.loads(run(*cls.cmd, 'config', '--format', 'json', env=cls.env))
        pubs = {name: sorted((p['host_ip'], int(p['published']), p['target']) for p in svc.get('ports', []))
                for name, svc in model['services'].items() if svc.get('ports')}
        assert pubs == {'frontend': sorted([('127.0.0.1', cls.local, 80), ('127.0.0.1', cls.tls, 8443)]),
                        'cloudbeaver': [('127.0.0.1', 8978, 8978)]}, pubs
        assert all(svc['labels'][OWNER_LABEL] == owner for svc in model['services'].values())
        cls.cmd += ['-f', str(fixture)]
        cls.compose('config', '--quiet')
        isolated = json.loads(cls.compose('config', '--format', 'json'))
        assert not isolated.get('volumes')
        assert not any(v['type'] == 'volume' for s in isolated['services'].values() for v in s.get('volumes', []))
        cls.addClassCleanup(cls.dispose, project, owner)
        lan_cmd = cls.cmd
        cls.cmd = base + ['-f', str(fixture)]
        cls.compose('up', '-d', '--wait', '--pull', 'never', 'postgres')
        for migration in sorted((assets / 'infra/postgres').glob('*.sql')):
            cls.compose('exec', '-T', 'postgres', 'psql', '-X', '-q', '-U', 'postgres', '-d', 'cassino',
                        '-v', 'ON_ERROR_STOP=1', data=migration.read_bytes())
        cls.compose('up', '-d', '--wait', '--pull', 'never', 'backend', 'frontend')
        local_nginx = cls.compose('exec', '-T', 'frontend', 'nginx', '-T')
        assert b'listen 8080' not in local_nginx and b'listen 8443' not in local_nginx
        cls.cmd = lan_cmd
        cls.compose('up', '-d', '--wait', '--pull', 'never', '--no-deps', 'frontend')
        cls.compose('exec', '-T', 'frontend', 'nginx', '-t')
        nginx = cls.compose('exec', '-T', 'frontend', 'nginx', '-T')
        assert b'listen 8080' not in nginx
        assert b'proxy_set_header Authorization "";' in nginx

    @classmethod
    def compose(cls, *args, data=None):
        return run(*cls.cmd, *args, env=cls.env, data=data)

    @classmethod
    def dispose(cls, project, owner):
        owned = run('docker', 'ps', '-aq', '--filter', f'label={OWNER_LABEL}={owner}', '--filter',
                    f'label=com.docker.compose.project={project}', env=cls.env).decode().split()
        if owned:
            run('docker', 'rm', '-f', *owned, env=cls.env)
        networks = run('docker', 'network', 'ls', '-q', '--filter', f'label={OWNER_LABEL}={owner}',
                       '--filter', f'label=com.docker.compose.project={project}', env=cls.env).decode().split()
        if networks:
            run('docker', 'network', 'rm', *networks, env=cls.env)

    def request(self, method, path, *, auth: bool | str = True, headers=(), payload=None, tls=True, context=None):
        conn = (http.client.HTTPSConnection('127.0.0.1', self.tls, timeout=10, context=context or self.context)
                if tls else http.client.HTTPConnection('127.0.0.1', self.local, timeout=10))
        with contextlib.closing(conn):
            conn.putrequest(method, path, skip_host=True)
            if not any(k.lower() == 'host' for k, _ in headers):
                conn.putheader('Host', self.authority if tls else f'127.0.0.1:{self.local}')
            if auth:
                conn.putheader('Authorization', auth if isinstance(auth, str) else self.auth)
            for name, value in headers:
                conn.putheader(name, value)
            body = json.dumps(payload).encode() if payload is not None else None
            if body is not None:
                conn.putheader('Content-Type', 'application/json')
                conn.putheader('Content-Length', str(len(body)))
            conn.endheaders(body)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_tls_and_local_access(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.request('GET', '/', auth=False, context=ssl.create_default_context())
        with contextlib.closing(http.client.HTTPConnection('127.0.0.1', self.tls, timeout=10)) as plain:
            plain.request('GET', '/')
            response = plain.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIsNone(response.getheader('WWW-Authenticate'))
        self.assertEqual(self.request('GET', '/api/health', auth=False, tls=False)[0], 200)
        self.assertEqual(self.request('GET', '/api/ingestion/status', auth=False, tls=False)[0], 200)
        self.assertEqual(self.request('GET', '/', headers=(('Host', 'unexpected.invalid'),))[0], 421)

    def test_lan_requires_credentials(self):
        for path in ('/', '/assets/missing.js', '/api/health', '/api/suggestions'):
            with self.subTest(path=path):
                status, headers, _ = self.request('GET', path, auth=False)
                self.assertEqual(status, 401)
                self.assertIn('Basic', headers['WWW-Authenticate'])
        self.assertEqual(self.request('GET', '/', auth='Basic ' + base64.b64encode(b'lan-test:wrong').decode())[0], 401)
        self.assertEqual(self.request('GET', '/')[0], 200)
        self.assertEqual(self.request('HEAD', '/api/lotteries')[0], 200)

    def test_admin_and_unknown_routes_denied(self):
        for path in ('/api/admin/ingestion', '/api/ingestion/status', '/api/ingestion/runs',
                     '/api/ingestion/divergences', '/api/ingestion/quarantine', '/api/jobs', '/api/other'):
            for method in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.request(method, path, headers=self.csrf())[0], 403)

    def csrf(self):
        return [('Origin', f'https://{self.authority}'), ('X-Requested-With', 'cassino')]

    def test_write_auth_csrf_and_readback(self):
        for path, payload in {
            '/api/suggestions': {'lottery': 'megasena', 'strategy': 'uniform_random', 'tickets': 1},
            '/api/experiments': {'lottery': 'megasena', 'kind': 'montecarlo', 'tickets_per_contest': 1,
                                 'contests': 1, 'replicates': 10},
        }.items():
            with self.subTest(path=path):
                good = self.csrf()
                origin = good[0][1]
                wrong = [('Origin', v) for v in ('null', f'http://{self.authority}', origin + '.invalid',
                                                  origin + ', ' + origin, origin + ' ' + origin)]
                for headers in ([], good[:1], good[1:], good + good[:1], good + good[1:],
                                [good[0], ('X-Requested-With', 'Cassino')], *[[x, good[1]] for x in wrong]):
                    self.assertEqual(self.request('POST', path, headers=headers, payload=payload)[0], 403, headers)
                self.assertEqual(self.request('POST', path, auth=False, headers=good, payload=payload)[0], 401)
                for method in ('PUT', 'PATCH', 'DELETE', 'OPTIONS'):
                    self.assertEqual(self.request(method, path, headers=good)[0], 403)
                status, _, body = self.request('POST', path, headers=good, payload=payload)
                self.assertEqual(status, 202, body)
                created = json.loads(body)
                key, wrapper = ('experiment_id', 'experiment') if path.endswith('experiments') else ('suggestion_set_id', 'set')
                ident = created[key]
                status, _, body = self.request('GET', f'{path}/{ident}')
                self.assertEqual(status, 200, body)
                self.assertEqual(str(json.loads(body)[wrapper]['id']), str(ident))
                self.assertEqual(self.request('GET', path + '?limit=1')[0], 200)


if __name__ == '__main__':
    if not __debug__:
        sys.exit('Execute sem -O: pré-condições de isolamento usam assert.')
    unittest.main(verbosity=2, failfast=True)
