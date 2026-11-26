"""Prepare only the versioned launcher-local application image tags."""
import argparse
import re
import subprocess

from stage_assets import CANONICAL, LOCAL_IMAGES


def docker(context, *args):
    return subprocess.check_output(['docker', '--context', context, *args], text=True, timeout=1800).strip()


def image(context, ref):
    return docker(context, 'image', 'inspect', '--format', '{{.Id}} {{.Os}}/{{.Architecture}}', ref).split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', default='desktop-linux')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('build', help='Build the three canonical contexts as linux/amd64')
    tag = actions.add_parser('tag', help='Tag each operator-verified immutable local image ID')
    for name in LOCAL_IMAGES:
        tag.add_argument(f'--{name}', required=True, metavar='SHA256_ID')
    args = parser.parse_args()
    endpoint = docker(args.context, 'context', 'inspect', args.context, '--format', '{{.Endpoints.docker.Host}}')
    if not endpoint.lower().startswith('npipe:////./pipe/'):
        parser.error('Use a local Windows named-pipe Docker context.')
    if args.action == 'tag':
        # Validate every input before mutating any tags. An ID proves identity, not provenance.
        sources = {name: getattr(args, name) for name in LOCAL_IMAGES}
        for source in sources.values():
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', source):
                parser.error('Provide full immutable sha256 image IDs from a verified local build.')
            if image(args.context, source) != [source, 'linux/amd64']:
                parser.error('Each supplied ID must exist locally and be a linux/amd64 image.')
        for name, target in LOCAL_IMAGES.items():
            docker(args.context, 'image', 'tag', sources[name], target)
    else:
        for name, target in LOCAL_IMAGES.items():
            subprocess.run(['docker', '--context', args.context, 'build', '--platform', 'linux/amd64',
                            '--tag', target, str(CANONICAL / name)], check=True, timeout=1800)
    for target in LOCAL_IMAGES.values():
        ident, platform = image(args.context, target)
        print(f'{target} {ident} {platform}')


if __name__ == '__main__':
    main()
