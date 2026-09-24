"""Distribution regressions use generated fixtures, never real user identifiers."""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release_audit import AuditError, source_entries, scan, zip_entries, wheel_entries, verify_setup
from build_release import normalize_sdist
from verify_release import verify
from quack_actual import config
from quack_actual.bridge import audio_command
from quack_actual.cli import main, doctor


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        values = {'pyproject.toml': b'[project]\nname="quack-actual"\nversion="0.5.0"\n',
                  'uv.lock': b'version = 1\n', 'README.md': b'Example',
                  'install.ps1': b'', 'install.sh': b'', 'launch.ps1': b'', 'launch.sh': b''}
        names = sorted([*values, 'RELEASE-FILES.txt'])
        values['RELEASE-FILES.txt'] = ('\n'.join(names) + '\n').encode()
        for name, data in values.items():
            (self.root / name).write_bytes(data)
        return values

    def test_source_allowlist_ignores_unreviewed_files(self):
        expected = self.fixture()
        (self.root / 'private-notes.md').write_text('not a release file')
        self.assertEqual(source_entries(self.root), expected)

    def test_source_requires_lockfile(self):
        self.fixture()
        (self.root / 'uv.lock').unlink()
        with self.assertRaises(AuditError):
            source_entries(self.root)

    def test_source_rejects_symlink(self):
        self.fixture()
        file = self.root / 'README.md'
        file.unlink()
        target = self.root / 'notes.txt'
        target.write_text('not public')
        try:
            file.symlink_to(target)
        except OSError:
            self.skipTest('Symlink creation unavailable to this test account')
        with self.assertRaises(AuditError):
            source_entries(self.root)

    def test_scan_targeted_terms_not_printed(self):
        term = 'fixture-' + 'private-identity'
        with patch.dict(os.environ, {'QUACK_ACTUAL_AUDIT_TERMS_JSON': json.dumps([term])}):
            with self.assertRaises(AuditError) as caught:
                scan({'test.txt': term.encode()})
        self.assertNotIn(term, str(caught.exception))

    def test_scan_rejects_home_and_credential_shapes(self):
        for content in (b'/ho' + b'me/' + b'sampleperson/work', b'ghp_' + b'A' * 36):
            with self.assertRaises(AuditError):
                scan({'example.txt': content})

    def test_private_dependency_rejected(self):
        self.fixture()
        (self.root / 'uv.lock').write_text('[[package]]\nname="example"\nsource={path="../private"}\n')
        with self.assertRaises(AuditError):
            source_entries(self.root)

    def test_zip_traversal_and_duplicates_rejected(self):
        for names in (['../escape'], ['file', 'file'], ['C:' + '/escape']):
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as z:
                for name in names:
                    z.writestr(name, b'x')
            with self.assertRaises(AuditError):
                zip_entries(data.getvalue())

    def test_empty_checksum_manifest_rejected(self):
        (self.root / 'SHA256SUMS.txt').write_text('')
        with self.assertRaises(AuditError):
            verify(self.root)

    def test_duplicate_checksum_manifest_rejected(self):
        (self.root / 'file.txt').write_bytes(b'data')
        line = hashlib.sha256(b'data').hexdigest() + '  file.txt\n'
        (self.root / 'SHA256SUMS.txt').write_text(line * 2)
        with self.assertRaises(AuditError):
            verify(self.root)

    def test_setup_unmanifested_file_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('package/FILE-MANIFEST.json', '{}')
            z.writestr('package/unexpected.txt', b'x')
        with self.assertRaises(AuditError):
            verify_setup(data.getvalue())

    def test_stale_wheel_rejected(self):
        source = self.fixture()
        source['src/quack_actual/__init__.py'] = b'new source'
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr('quack_actual/__init__.py', b'old source')
            for name in ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt'):
                z.writestr('quack_actual-0.5.0.dist-info/' + name, b'')
        with self.assertRaisesRegex(AuditError, 'differs'):
            wheel_entries(data.getvalue(), source)

    def test_sdist_owner_metadata_removed(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as z:
            info = tarfile.TarInfo('package/file.txt')
            info.uid = info.gid = 123
            info.uname = info.gname = 'fixture-builder'
            info.mtime = 111
            info.size = 1
            z.addfile(info, io.BytesIO(b'x'))
        cleaned = normalize_sdist(data.getvalue())
        self.assertEqual(cleaned, normalize_sdist(data.getvalue()))
        with tarfile.open(fileobj=io.BytesIO(cleaned), mode='r:gz') as z:
            info = z.getmembers()[0]
            self.assertEqual((info.uid, info.gid, info.uname, info.gname, info.mtime), (0, 0, '', '', 0))

    def test_config_path_honors_environment(self):
        path = self.root / 'custom-settings.json'
        with patch.dict(os.environ, {'QUACK_ACTUAL_CONFIG': str(path)}):
            output = io.StringIO()
            with patch('sys.stdout', output):
                self.assertEqual(main(['config', 'path']), 0)
            self.assertEqual(output.getvalue().strip(), str(path))

    def test_empty_config_base_not_current_directory(self):
        env = {'XDG_CONFIG_HOME': '', 'LOCALAPPDATA': ''}
        with patch.dict(os.environ, env):
            self.assertTrue(config.default_path().is_absolute())

    def test_config_type_validation(self):
        for key, value in (('microphone', True), ('windows_python', []), ('wake_model', None), ('device', {})):
            cfg = copy.deepcopy(config.DEFAULTS)
            cfg[key] = value
            with self.assertRaises(ValueError):
                config.validate(cfg)

    def test_doctor_checks_selected_backend_by_default(self):
        with patch('quack_actual.cli.resolve_command', side_effect=RuntimeError('not installed')):
            with patch('sys.stdout', io.StringIO()):
                self.assertEqual(doctor(config.DEFAULTS, text_only=True), 1)

    def test_wsl_wheel_uses_environment_sibling(self):
        interpreter = self.root / '.venv/Scripts/python.exe'
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()
        with patch('quack_actual.bridge.is_wsl', return_value=True):
            with patch('quack_actual.bridge.sys.prefix', str(self.root / '.venv-wsl')):
                with patch.dict(os.environ, {'QUACK_ACTUAL_WINDOWS_PYTHON': ''}):
                    self.assertEqual(audio_command()[0], str(interpreter))


if __name__ == '__main__':
    unittest.main()
