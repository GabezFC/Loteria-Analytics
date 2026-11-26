"""Provision LAN files locally. Never invokes Docker or changes networking."""
import argparse
import csv
import getpass
import ipaddress
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import warnings

HERE = Path(__file__).resolve().parent
PRIVATE = tuple(ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def verify_tls(cert, key, ca, ip):
    # A service key must load without a terminal prompt and match the leaf certificate.
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key, password='')
    except (OSError, ValueError) as exc:
        raise ValueError('Certificado/chave incompatíveis ou chave não utilizável sem senha.') from exc
    result = subprocess.run(['openssl', 'verify', '-x509_strict', '-purpose', 'sslserver', '-verify_ip', ip,
                             '-CAfile', str(ca), '-no-CApath', '-no-CAstore', '-untrusted', str(cert), str(cert)],
                            capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError('Cadeia TLS inválida para a CA fornecida, expirada ou sem SAN IP correspondente.')


def restrict_dir(path):
    if os.name == 'nt':
        row = subprocess.check_output(['whoami.exe', '/user', '/fo', 'csv', '/nh'], timeout=10)
        sid = next(csv.reader([row.decode(errors='replace').strip()]))[-1]
        if not re.fullmatch(r'S-1-(?:\d+-)*\d+', sid):
            raise ValueError('Não foi possível identificar o SID do usuário local.')
        subprocess.run(['icacls.exe', str(path), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F',
                        '*S-1-5-18:(OI)(CI)F'], check=True, capture_output=True, timeout=15)


def provision(out, ip, port, cert, key, ca, user, password):
    import bcrypt  # type: ignore[import-not-found]  # dependency supplied by uv

    addr = ipaddress.IPv4Address(ip)
    if str(addr) != ip or not (ip == '127.0.0.1' or any(addr in net for net in PRIVATE)):
        raise ValueError('Use IPv4 privado RFC 1918; 127.0.0.1 é reservado ao teste local.')
    if not (1 <= port <= 65535 and port not in {3001, 5432, 8080, 8978, 9443}):
        raise ValueError('Porta TLS inválida ou reservada.')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,32}', user):
        raise ValueError('Usuário inválido (1–32 caracteres ASCII alfanuméricos, ponto, hífen ou _).')
    secret = password.encode('ascii', errors='strict')
    if not 20 <= len(secret) <= 72 or not all(33 <= c <= 126 for c in secret):
        raise ValueError('Use 20–72 caracteres ASCII visíveis sem espaços, de preferência aleatórios.')
    hashed = bcrypt.hashpw(secret, bcrypt.gensalt(rounds=12))
    authority = ip if port == 443 else f'{ip}:{port}'
    out = out.resolve()
    path = out.as_posix()
    # Avoid special characters in Compose dotenv interpolation (spaces are supported).
    if any(c in path for c in "'\"$#\r\n\\"):
        raise ValueError('Caminho de saída incompatível com arquivo de runtime do Compose.')
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        restrict_dir(out)
        secret_dir = out / 'credentials'
        # Worker needs htpasswd; parent protects these files from other host users on POSIX.
        secret_dir.mkdir(mode=0o755)
        for source, name, mode in ((cert, 'cert.pem', 0o644), (key, 'key.pem', 0o600)):
            dest = secret_dir / name
            with os.fdopen(os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode), 'wb') as f:
                f.write(source.read_bytes())
        verify_tls(secret_dir / 'cert.pem', secret_dir / 'key.pem', ca, ip)
        authfile = secret_dir / 'htpasswd'
        authfile.write_bytes(user.encode('ascii') + b':' + hashed + b'\n')
        authfile.chmod(0o644)
        nginx = (HERE / 'tls.conf.template').read_text(encoding='ascii')
        nginx = nginx.replace('@AUTHORITY@', authority).replace('@ORIGIN_PATTERN@', authority.replace('.', r'\.'))
        (out / 'tls.conf').write_text(nginx, encoding='ascii', newline='\n')
        runtime = out / 'lan.runtime.env'
        runtime.write_text(f"CASSINO_LAN_IP={ip}\nCASSINO_LAN_PORT={port}\nCASSINO_LAN_STATE='{path}'\n",
                           encoding='utf-8', newline='\n')
        return runtime
    except BaseException:
        shutil.rmtree(out)
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--consent', action='store_true', required=True, help='Confirma o provisionamento local; não abre porta.')
    p.add_argument('--output', type=Path, required=True, help='Nova pasta privada, fora do código e do pacote.')
    p.add_argument('--ip', required=True)
    p.add_argument('--port', type=int, default=8443)
    p.add_argument('--cert', type=Path, required=True)
    p.add_argument('--key', type=Path, required=True)
    p.add_argument('--ca', type=Path, required=True)
    p.add_argument('--user', required=True)
    args = p.parse_args()
    if not os.isatty(0):
        p.error('É necessário um terminal interativo para informar a senha local.')
    # Resolve the actual path, not a user-selected symlink, before checking containment.
    if not os.environ.get('LOCALAPPDATA') or not args.output.resolve().is_relative_to(Path(os.environ['LOCALAPPDATA']).resolve()):
        p.error('Escolha uma nova subpasta em LOCALAPPDATA.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Senha LAN: ')
            confirmation = getpass.getpass('Confirme a senha LAN: ')
        if password != confirmation:
            raise ValueError('As senhas não coincidem.')
        runtime = provision(args.output, args.ip, args.port, args.cert, args.key, args.ca, args.user, password)
    except UnicodeError:
        p.error('Use uma senha com caracteres ASCII.')
    except ValueError as exc:
        p.error(str(exc))
    except (OSError, subprocess.SubprocessError, ImportError, getpass.GetPassWarning, EOFError):
        p.error('Bootstrap falhou. Confira OpenSSL 3, bcrypt, terminal, permissões e caminhos; nada foi ativado.')
    print(f'Provisionado (não ativado): {runtime}')


if __name__ == '__main__':
    main()
