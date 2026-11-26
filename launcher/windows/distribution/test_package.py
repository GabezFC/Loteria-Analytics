import hashlib
from pathlib import Path
import tempfile
import unittest

from check_package import PAYLOAD, check_payload, write_checksums


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in PAYLOAD:
            self.put(f'payload/{relative}')
        self.put('output/Cassino-Setup.exe')
        self.put('output/SHA256SUMS.txt')

    def put(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
        return path

    def test_exact_payload_and_checksums(self):
        self.assertEqual(set(check_payload(self.root / 'payload')), PAYLOAD)
        manifest = write_checksums(self.root)
        digest = hashlib.sha256(b'fixture').hexdigest()
        expected = {'output/Cassino-Setup.exe', 'output/SHA256SUMS.txt'} | {f'payload/{p}' for p in PAYLOAD}
        self.assertEqual(manifest.read_text().splitlines(), [f'{digest}  {p}' for p in sorted(expected)])
        with self.assertRaises(ValueError):
            write_checksums(self.root)

    def test_missing_file_rejected(self):
        (self.root / 'payload/app/compose.yaml').unlink()
        with self.assertRaises(ValueError):
            check_payload(self.root / 'payload')

    def test_unexpected_entries_rejected_without_disclosing_name(self):
        for relative in ('.env.fixture', 'app/secret.pfx', 'app/debug.log', 'backup.dump', 'source.cs'):
            with self.subTest(relative=relative):
                path = self.put(f'payload/{relative}')
                with self.assertRaises(ValueError) as caught:
                    check_payload(self.root / 'payload')
                self.assertNotIn(relative, str(caught.exception))
                path.unlink()

    def test_unexpected_directory_rejected(self):
        (self.root / 'payload/cache').mkdir()
        with self.assertRaises(ValueError):
            check_payload(self.root / 'payload')

    def test_output_extra_file_prevents_checksum_creation(self):
        self.put('output/export.dmp')
        with self.assertRaises(ValueError):
            write_checksums(self.root)
        self.assertFalse((self.root / 'SHA256SUMS.txt').exists())

    def test_symlink_or_junction_rejected(self):
        path = self.root / 'payload/app'
        target = self.root / 'outside'
        path.rename(target)
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            # Windows developer mode is not required; mklink /J needs no elevation.
            import os
            import subprocess
            if os.name != 'nt':
                raise
            subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(path), str(target)],
                           check=True, capture_output=True)
        with self.assertRaises(ValueError):
            check_payload(self.root / 'payload')
