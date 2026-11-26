"""Fail-closed inventory and SHA-256 for the local Stage 15 build tree."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import stat

PAYLOAD = frozenset({
    'CassinoLauncher.exe',
    'app/compose.yaml',
    'app/compose.admin.yaml',
    'app/infra/postgres/001-base.sh',
    'app/infra/postgres/002-ingest.sql',
    'app/infra/postgres/003-premios-divergencias-jobs.sql',
    'app/infra/postgres/004-collector-status.sql',
    'app/infra/postgres/005-probabilidades-estatistica.sql',
    'app/infra/postgres/006-experimentos-sugestoes.sql',
    'app/lan/README.md',
    'app/lan/bootstrap.py',
    'app/lan/compose.lan.yaml',
    'app/lan/compose.local.yaml',
    'app/lan/local.conf',
    'app/lan/proxy.inc',
    'app/lan/tls.conf.template',
})
OUTPUT = frozenset({'Cassino-Setup.exe', 'SHA256SUMS.txt'})


def metadata(path):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError('Package contains a symlink or reparse point.')
    return info


def check_tree(root, expected):
    """Validate names and types before reading any payload content."""
    directories = {p.as_posix() for name in expected for p in PurePosixPath(name).parents} - {'.'}
    files = {}

    def walk(directory, prefix=''):
        for child in directory.iterdir():
            relative = prefix + child.name
            if relative not in expected and relative not in directories:
                raise ValueError('Package contains an entry outside the allowlist.')
            info = metadata(child)
            if relative in directories and stat.S_ISDIR(info.st_mode):
                walk(child, relative + '/')
            elif (relative in expected and stat.S_ISREG(info.st_mode)
                  and info.st_size > 0 and info.st_nlink == 1):
                files[relative] = child
            else:
                raise ValueError('Package contains an invalid file or directory.')

    if not stat.S_ISDIR(metadata(root).st_mode):
        raise ValueError('Package root must be a directory.')
    walk(root)
    if files.keys() != expected:
        raise ValueError('Package is missing one or more allowlisted files.')
    return files


def check_payload(root):
    return check_tree(root, PAYLOAD)


def write_checksums(root):
    expected = {f'payload/{name}' for name in PAYLOAD} | {f'output/{name}' for name in OUTPUT}
    files = check_tree(root, expected)
    lines = []
    for name, path in sorted(files.items()):
        with path.open('rb') as stream:
            lines.append(f'{hashlib.file_digest(stream, "sha256").hexdigest()}  {name}\n')
    manifest = root / 'SHA256SUMS.txt'
    with manifest.open('x', encoding='ascii', newline='\n') as stream:
        stream.writelines(lines)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('payload', 'checksums'))
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        if args.operation == 'payload':
            print(f'Validated {len(check_payload(args.directory))} payload files.')
        else:
            print(f'Wrote {write_checksums(args.directory).name}.')
    except ValueError as exc:
        parser.exit(1, f'Package rejected: {exc}\n')
    except OSError:
        parser.exit(1, 'Package rejected: unable to access the package tree.\n')
