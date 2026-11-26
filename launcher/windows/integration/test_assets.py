"""Offline Compose contract checks; never connects to an Engine."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from stage_assets import CANONICAL, stage

OWNER_LABEL = 'io.cassino.launcher.owner'
OWNER = 'abcdef0123456789abcdef0123456789'


class AssetsTest(unittest.TestCase):
    def test_packaged_compose_contract(self):
        with tempfile.TemporaryDirectory(prefix='cassino-offline-') as directory:
            root = Path(directory)
            assets = root / 'app with spaces'
            stage(assets)
            stage(assets)  # Packaging can be repeated.
            postgres = assets / 'infra' / 'postgres'
            expected = {p.name: p.read_bytes() for p in CANONICAL.joinpath('infra/postgres').glob('*.sql')}
            expected['001-base.sh'] = CANONICAL.joinpath('infra/postgres/001-base.sh').read_bytes()
            self.assertEqual({p.name: p.read_bytes() for p in postgres.iterdir()}, expected)
            self.assertNotIn(b'\r', expected['001-base.sh'])
            fake = root / 'fake-secrets.txt'
            fake.write_text('POSTGRES_PASSWORD=fake-one\nAPI_PASSWORD=fake-two\n'
                            'WORKER_PASSWORD=fake-three\nINSPECT_PASSWORD=fake-four\n', encoding='ascii')
            runtime = root / 'fake-runtime.txt'
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
                ('CASSINO_', 'COMPOSE_', 'DOCKER_')) and not k.upper().endswith('_PASSWORD')}
            env['DOCKER_HOST'] = 'tcp://127.0.0.1:1'

            def model(file, project, *overlays):
                files = [arg for name in (file, *overlays) for arg in ('-f', str(assets / name))]
                cmd = ['docker', 'compose', '-p', project, *files,
                       '--env-file', str(fake), '--env-file', str(runtime), 'config']
                for options in (['--quiet'], ['--format', 'json']):
                    result = subprocess.run(cmd + options, env=env, capture_output=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
                return json.loads(result.stdout)

            for overrides in (False, True):
                runtime.write_text(f'CASSINO_LAUNCHER_OWNER={OWNER}\n' + (
                    'CASSINO_APP_PORT=19030\nCASSINO_CLOUDBEAVER_PORT=19031\nCASSINO_PORTAINER_PORT=19032\n'
                    'CASSINO_WORKERS_IMAGE=cassino-example/workers:9.0.0-local\n' if overrides else ''),
                    encoding='ascii')
                main = model('compose.yaml', 'cassino-offline', 'lan/compose.local.yaml')
                admin = model('compose.admin.yaml', 'cassino-offline-admin')
                self.assertEqual(set(main['services']), {'postgres', 'backend', 'frontend',
                                                        'coletor', 'analisador', 'cloudbeaver'})
                self.assertEqual(set(admin['services']), {'portainer'})
                self.assertEqual(set(main['volumes']), {'postgres_data', 'cloudbeaver_workspace'})
                self.assertEqual(set(admin['volumes']), {'portainer_data'})
                for graph in (main, admin):
                    self.assertEqual(set(graph['networks']), {'default'})
                    for name, resource in (graph['volumes'] | graph['networks']).items():
                        self.assertEqual(resource['labels'][OWNER_LABEL], OWNER)
                        self.assertEqual(resource['name'], graph['name'] + '_' + name)
                    for service in graph['services'].values():
                        self.assertEqual(service.get('labels', {}).get(OWNER_LABEL), OWNER)
                actual = {}
                for service, rule in (main['services'] | admin['services']).items():
                    self.assertNotIn('build', rule)
                    for port in rule.get('ports', []):
                        self.assertNotIn(service, actual)
                        actual[service] = (port['host_ip'], int(port['published']), port['target'])
                self.assertEqual(actual, {
                    'frontend': ('127.0.0.1', 19030 if overrides else 3000, 80),
                    'cloudbeaver': ('127.0.0.1', 19031 if overrides else 8978, 8978),
                    'portainer': ('127.0.0.1', 19032 if overrides else 9443, 9443),
                })
                for service, image in {'backend': 'backend', 'frontend': 'frontend',
                                       'coletor': 'workers', 'analisador': 'workers'}.items():
                    rule = main['services'][service]
                    expected_image = f'cassino-launcher/{image}:0.1.0-local'
                    if overrides and image == 'workers':
                        expected_image = 'cassino-example/workers:9.0.0-local'
                    self.assertEqual(rule['image'], expected_image)
                    self.assertEqual(rule['pull_policy'], 'never')
                pg = main['services']['postgres']
                frontend = main['services']['frontend']
                self.assertEqual({v['target'] for v in frontend['volumes']},
                                 {'/etc/nginx/conf.d/default.conf', '/etc/nginx/cassino-proxy.inc'})
                self.assertTrue(all(Path(v['source']).is_file() and v['read_only'] for v in frontend['volumes']))
                self.assertIn('lottery_type', ' '.join(pg['healthcheck']['test']))
                init = [v for v in pg['volumes'] if v['type'] == 'bind']
                self.assertEqual(len(init), 1)
                self.assertEqual(Path(init[0]['source']), postgres / '001-base.sh')
                self.assertTrue(init[0]['read_only'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
