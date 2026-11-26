"""Exercise the built launcher against a fresh, disposable Docker Compose project."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4

from stage_assets import LOCAL_IMAGES, OWNER_LABEL, replace_once, stage


def run(args, env, *, timeout=45, expected_exit=0):
    result = subprocess.run(args, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode != expected_exit:
        # Never print captured CLI logs or rendered Compose (may contain credentials).
        step = args[-1] if args[-1] in {'start', 'stop', 'status', 'health', 'logs'} else args[1]
        raise RuntimeError(f'{Path(args[0]).name} {step}: exit {result.returncode}, expected {expected_exit}.')
    return (result.stderr if expected_exit else result.stdout).strip()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def reserve_ports():
    with ExitStack() as sockets:
        ports = []
        for _ in range(3):
            s = sockets.enter_context(socket.socket())
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(('127.0.0.1', 0))
            ports.append(s.getsockname()[1])
        return ports


def api_health(port):
    opener = build_opener(ProxyHandler({}))
    try:
        response = opener.open(f'http://127.0.0.1:{port}/api/health', timeout=8)
    except HTTPError as exc:
        response = exc
    with response:
        return response.code, json.load(response)


def exercise(cli_exe, context, consoles):
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(
        ('COMPOSE_', 'CASSINO_', 'DOCKER_')) and k.upper() not in
        {'POSTGRES_PASSWORD', 'API_PASSWORD', 'WORKER_PASSWORD', 'INSPECT_PASSWORD', 'PGPASSWORD'}}
    env['DOCKER_CONTEXT'] = context

    def docker(*args):
        return run(['docker', *args], env)

    endpoint = docker('context', 'inspect', context, '--format', '{{.Endpoints.docker.Host}}')
    require(endpoint in {'npipe:////./pipe/dockerDesktopLinuxEngine', 'npipe:////./pipe/docker_engine'},
            'A local Docker Desktop context is required.')
    require(docker('info', '--format', '{{.OSType}}') == 'linux', 'Start the local Linux Docker engine first.')
    for ref in LOCAL_IMAGES.values():
        docker('image', 'inspect', '--format', '{{.Id}}', ref)

    project = 'cassino-it-' + uuid4().hex[:24]
    admin = project + '-admin'
    def project_resources(name):
        label = f'label=com.docker.compose.project={name}'
        for obj in ('container', 'network', 'volume'):
            all_containers = ['--all'] if obj == 'container' else []
            for ident in docker(obj, 'ls', *all_containers, '--quiet', '--filter', label).splitlines():
                yield obj, ident

    for name in (project, admin):
        require(not list(project_resources(name)), f'Fixture project name is already in use: {name}.')

    root = Path(tempfile.mkdtemp(prefix=project + '-'))
    home, assets = root / 'home', root / 'app'
    home.mkdir()
    stage(assets)
    # Use the production worker images and healthchecks, but defer external collection.
    main = assets / 'compose.yaml'
    main.write_text(replace_once(main.read_text(encoding='utf-8'), '      WORKER_ROLE: coletor\n',
                                 '      WORKER_ROLE: coletor\n      COLLECT_STARTUP_DELAY_S: "86400"\n'),
                    encoding='utf-8', newline='\n')
    app_port, cloud_port, admin_port = reserve_ports()
    (home / 'config.json').write_text(json.dumps(dict(project=project, adminProject=admin, appPort=app_port,
        cloudBeaverPort=cloud_port, portainerPort=admin_port, cloudBeaver=consoles, portainer=consoles)),
        encoding='utf-8')
    print(f'Fixture: project={project} admin={admin} home={home} assets={assets}', flush=True)

    def cli(command, *, fails=False):
        print(f'Launcher: {command}' + (' (expect rejection)' if fails else ''), flush=True)
        return run([str(cli_exe), '--home', str(home), '--assets', str(assets), command], env,
                   timeout=1200, expected_exit=int(fails))

    def compose(*args, admin_stack=False):
        name = admin if admin_stack else project
        file = 'compose.admin.yaml' if admin_stack else 'compose.yaml'
        return docker('compose', '--project-directory', str(assets), '-p', name, '-f', str(assets / file),
                      '--env-file', str(home / '.env'), '--env-file', str(home / 'runtime.env'), *args)

    def psql(sql):
        return compose('exec', '-T', 'postgres', 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres',
                       '-d', 'cassino', '-Atqc', sql)

    def down(*, include_admin=False):
        # Refuse to clean up a project that gained resources from another installation.
        for is_admin in ([True, False] if consoles and include_admin else [False]):
            name = admin if is_admin else project
            resources = list(project_resources(name))
            if not any(kind != 'volume' for kind, _ in resources):
                continue  # Nothing to remove. Preserve owned volumes even after containers are gone.
            owner = (home / 'installation-id').read_text(encoding='ascii').strip()
            require(re.fullmatch(r'[0-9a-f]{32}', owner), 'Missing or invalid fixture owner.')
            for kind, ident in resources:
                labels = '.Config.Labels' if kind == 'container' else '.Labels'
                template = f'{{{{ index {labels} "{OWNER_LABEL}" }}}}'
                require(docker(kind, 'inspect', '--format', template, ident) == owner,
                        f'Cleanup refused: {name} has resources with a different owner.')
            # Include the explicit identity in case a same-named network has no Compose labels.
            networks = docker('network', 'ls', '--format', '{{.Name}}').splitlines()
            if name + '_default' in networks:
                template = f'{{{{ index .Labels "{OWNER_LABEL}" }}}}'
                require(docker('network', 'inspect', '--format', template, name + '_default') == owner,
                        f'Cleanup refused: {name} default network belongs to a different owner.')
            compose('down', admin_stack=is_admin)

    try:
        with socket.socket() as blocker:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                blocker.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            blocker.bind(('127.0.0.1', app_port))
            blocker.listen(1)
            rejection = cli('start', fails=True)
            require(f'Porta local {app_port} ocupada' in rejection, 'Start failed for a reason other than the occupied port.')
            for name in (project, admin):
                require(not docker('container', 'ls', '--all', '--quiet', '--filter',
                                   f'label=com.docker.compose.project={name}'), 'Port failure left containers.')

        cli('start')
        statuses = {row['Service']: row for row in json.loads(cli('status'))}
        cli('health')
        cli('logs')
        healthy = (200, {'status': 'ok', 'database': 'up'})
        require(api_health(app_port) == healthy, 'Proxy /api/health is not healthy.')
        for service in ('postgres', 'backend', 'frontend', 'coletor', 'analisador'):
            require(statuses.get(service, {}).get('Health') == 'healthy', f'CLI did not report {service} healthy.')
            cid = compose('ps', '--quiet', service)
            require(bool(cid) and docker('inspect', '--format', '{{.State.Health.Status}}', cid) == 'healthy',
                    f'Unhealthy fixture service: {service}.')
        if consoles:
            require(bool(compose('ps', '--quiet', 'cloudbeaver')), 'CloudBeaver did not start.')
            require(bool(compose('ps', '--quiet', 'portainer', admin_stack=True)), 'Portainer did not start.')
        markers = psql("SELECT string_agg(name, ',' ORDER BY name) FROM schema_migration;")
        expected = ','.join(p.stem for p in sorted((assets / 'infra/postgres').glob('*.sql')))
        require(markers == expected and psql('SELECT count(*) FROM lottery_type;') == '3',
                'Migration markers or base seed data do not match staged migrations.')
        psql("CREATE TABLE launcher_fixture_sentinel (value text); "
             "INSERT INTO launcher_fixture_sentinel VALUES ('preserved');")

        backup_parent = root / 'backups'
        backup_parent.mkdir()
        result = run([str(cli_exe), '--home', str(home), '--assets', str(assets), 'backup', str(backup_parent)], env, timeout=240)
        bundle = Path(result)
        require(bundle.parent == backup_parent and (bundle / 'cassino.dump').is_file(), 'Backup bundle not found.')
        counts = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))['tableCounts']
        require(counts['lottery_type'] == 3 and counts['schema_migration'] == 5, 'Unexpected restored counts.')
        run([str(cli_exe), '--home', str(home), '--assets', str(assets), 'verify-backup', str(bundle)], env, timeout=240)
        print('PASS: backup verified twice in isolated PostgreSQL', flush=True)

        compose('stop', 'postgres')
        require(api_health(app_port) == (503, {'status': 'degraded', 'database': 'down'}),
                'Stopping fixture Postgres did not degrade the API.')
        cli('health', fails=True)

        cli('stop')
        require(not compose('ps', '--quiet'), 'Launcher stop left main services running.')
        if consoles:
            require(bool(compose('ps', '--quiet', 'portainer', admin_stack=True)),
                    'Launcher stop also stopped the separate Portainer project.')
        down()  # Test recreation from the owned volume, not just waking stopped containers.
        cli('start')
        cli('health')
        require(api_health(app_port) == healthy, 'Proxy health did not recover.')
        require(psql('SELECT value FROM launcher_fixture_sentinel;') == 'preserved', 'Fixture data was lost.')
        require(psql("SELECT string_agg(name, ',' ORDER BY name) FROM schema_migration;") == expected,
                'Migration markers changed on restart.')
        print('PASS: port rejection, health, schema, service failure, and persistence', flush=True)
    finally:
        try:
            down(include_admin=True)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(f'Fixture cleanup incomplete: {exc} Home preserved: {home}', flush=True)
            raise
        print(f'Fixture cleanup complete; no volumes removed. Home preserved: {home}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True, help='Published CassinoLauncher.Cli.exe')
    parser.add_argument('--context', default='desktop-linux', choices=('desktop-linux', 'default'))
    parser.add_argument('--consoles', action='store_true', help='Also start both consoles; Portainer mounts Docker socket')
    args = parser.parse_args()
    if not args.cli.is_file() or args.cli.suffix.lower() != '.exe':
        parser.error('Published CLI executable does not exist; no Docker commands were run.')
    try:
        exercise(args.cli.resolve(), args.context, args.consoles)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        parser.exit(1, f'Fixture failed: {exc}\n')


if __name__ == '__main__':
    main()
