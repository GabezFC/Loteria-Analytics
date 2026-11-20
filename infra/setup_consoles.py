"""Initialize only the loopback consoles; never print credentials or responses."""
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPCookieProcessor, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
PORT = 'https://127.0.0.1:9443'
CLOUD = 'http://127.0.0.1:8978/api/gql'
ADMIN = ['docker', 'compose', '-f', 'infra/portainer/compose.yaml']
# The Portainer first-run certificate is self-signed and the endpoint is fixed to loopback.
cookies = http.cookiejar.CookieJar()
opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(cookies))


def request(url, payload=None, headers=None):
    if isinstance(payload, dict):
        payload = json.dumps(payload).encode()
    try:
        client = (build_opener(ProxyHandler({}), HTTPSHandler(context=ssl._create_unverified_context()))
                  if url.startswith(PORT) else opener)
        with client.open(Request(url, data=payload, headers=headers or {'Content-Type': 'application/json'}), timeout=12) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        return exc.code, None


def gql(query, variables=None):
    code, obj = request(CLOUD, {'query': query, 'variables': variables or {}})
    if code != 200 or not obj or obj.get('errors'):
        errors = (obj or {}).get('errors', [])
        classifications = [item.get('extensions', {}).get('classification') for item in errors]

        raise RuntimeError(f'CloudBeaver: operação GraphQL não concluída (HTTP {code}; {classifications})')
    return obj['data']


def main():
    os.chdir(ROOT)
    target = ROOT / '.env.consoles'
    if not target.exists():
        with target.open('x', encoding='ascii') as f:
            for key in ('PORTAINER_ADMIN_PASSWORD', 'CLOUDBEAVER_ADMIN_PASSWORD'):
                f.write(f'{key}=Aa1-{secrets.token_urlsafe(24)}\n')
    passwords = dict(line.split('=', 1) for line in target.read_text(encoding='ascii').splitlines() if line)
    user = 'cassino-admin'
    port_login = {'Username': user, 'Password': passwords['PORTAINER_ADMIN_PASSWORD']}
    if request(PORT + '/api/users/admin/check')[0] == 404:
        logs = subprocess.check_output(ADMIN + ['logs', '--no-color', 'portainer'], text=True, encoding='utf-8', errors='replace')
        tokens = re.findall(r'setup_token=([A-Za-z0-9_-]+)', re.sub(r'\x1b\[[0-9;]*m', '', logs), re.I)
        if not tokens:
            raise RuntimeError('Portainer: token de setup não localizado nos logs locais')
        code, _ = request(PORT + '/api/users/admin/init', port_login, {'Content-Type': 'application/json', 'X-Setup-Token': tokens[-1]})
        if code != 200:
            raise RuntimeError(f'Portainer: setup retornou HTTP {code}; confira/reinicie o assistente local')
    code, auth = request(PORT + '/api/auth', port_login)
    if code != 200 or not auth or not auth.get('jwt'):
        raise RuntimeError(f'Portainer: login falhou (HTTP {code}); não redefina uma conta existente')
    headers = {'Authorization': f"Bearer {auth['jwt']}", 'Origin': PORT, 'Referer': PORT + '/'}
    with_no_cookies = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl._create_unverified_context()))
    try:
        with with_no_cookies.open(PORT + '/api/endpoints', timeout=5) as response:
            raise RuntimeError(f'Portainer: acesso sem login retornou HTTP {response.status}')
    except HTTPError as exc:
        if exc.code not in (401, 403):
            raise RuntimeError(f'Portainer: acesso sem login retornou HTTP {exc.code}') from None
    code, endpoints = request(PORT + '/api/endpoints', headers=headers)
    if code != 200 or not isinstance(endpoints, list):
        raise RuntimeError(f'Portainer: listar ambientes retornou HTTP {code}')
    local = next((ep for ep in endpoints if ep.get('URL') == 'unix:///var/run/docker.sock'), None)
    if local is None:
        boundary = 'cassino-setup-local'
        data = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k, v in {'Name': 'Docker local', 'EndpointCreationType': '1', 'ContainerEngine': 'docker'}.items()) + f'--{boundary}--\r\n'
        code, local = request(PORT + '/api/endpoints', data.encode(), {**headers, 'Content-Type': f'multipart/form-data; boundary={boundary}'})
        if code not in (200, 201) or not isinstance(local, dict):
            raise RuntimeError(f'Portainer: criar ambiente local retornou HTTP {code}')
    code, containers = request(f"{PORT}/api/endpoints/{local['Id']}/docker/containers/json", headers=headers)
    if code != 200 or not isinstance(containers, list) or not any(c.get('Labels', {}).get('com.docker.compose.project') == 'cassino' for c in containers):
        raise RuntimeError('Portainer: contêineres do Cassino não visíveis pelo socket')
    print('Portainer: login válido, ambiente local e contêineres Cassino confirmados.')
    cloud_password = passwords['CLOUDBEAVER_ADMIN_PASSWORD']
    config = gql('{serverConfig{configurationMode anonymousAccessEnabled}}')['serverConfig']
    if config['configurationMode']:
        ok = gql('query($c:ServerConfigInput!){configureServer(configuration:$c)}', {'c': {'serverName':'Cassino SQL', 'adminName':user, 'adminPassword':cloud_password, 'anonymousAccessEnabled':False, 'customConnectionsEnabled':False}})
        if not ok['configureServer']:
            raise RuntimeError('CloudBeaver: configuração inicial rejeitada')
    config = gql('{serverConfig{configurationMode anonymousAccessEnabled}}')['serverConfig']
    if config != {'configurationMode': False, 'anonymousAccessEnabled': False}:
        raise RuntimeError('CloudBeaver: configuração segura não comprovada')
    cookies.clear()
    # CloudBeaver's own client sends uppercase MD5 for its local password parameter.
    client_password = hashlib.md5(cloud_password.encode(), usedforsecurity=False).hexdigest().upper()
    result = gql('query($c:Object){authLogin(provider:"local",credentials:$c){userTokens{userId}}}', {'c': {'user': user, 'password': client_password}})
    if not any(token['userId'] == user for token in result['authLogin']['userTokens']):
        raise RuntimeError('CloudBeaver: login não comprovado')
    print('CloudBeaver: login válido e acesso anônimo desativado.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as exc:
        print(str(exc) if type(exc) is RuntimeError else f'Falha nos consoles: {type(exc).__name__}', file=sys.stderr)
        sys.exit(1)
