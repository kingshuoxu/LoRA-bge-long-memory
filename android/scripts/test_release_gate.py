#!/usr/bin/env python3
"""Fast regression checks; run without an Android SDK or external Python packages."""
import hashlib
import itertools
import json
from pathlib import Path
import re
import tempfile
import unittest

from verify_candidate_update import baseline_version, read_candidate, validate_installed, version_code

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/android-release.yml'


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.blob = b'candidate APK fixture'
        self.meta = dict(apk='app-debug.apk', versionName='0.1.33', versionCode=1033,
                         size=len(self.blob), sha256=hashlib.sha256(self.blob).hexdigest())

    def test_candidate_bytes_and_version_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'update.json').write_text(json.dumps(self.meta))
            (root / 'app-debug.apk').write_bytes(self.blob)
            self.assertEqual(read_candidate(root), self.meta)
            (root / 'app-debug.apk').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                read_candidate(root)

    def test_size_mismatch_never_bypasses_sha_verification(self):
        for size, digest in [(0, ''), (1, 'bad'), (self.meta['size'], 'bad'), (1, self.meta['sha256'])]:
            with self.subTest(size=size, digest=digest), self.assertRaises(ValueError):
                validate_installed(self.meta, 1033, '0.1.33', digest, size)
        validate_installed(self.meta, 1033, '0.1.33', self.meta['sha256'], self.meta['size'])

    def test_wrong_version_fails(self):
        for code, name in [(1032, '0.1.33'), (1033, '0.1.32')]:
            with self.assertRaises(ValueError):
                validate_installed(self.meta, code, name, self.meta['sha256'], self.meta['size'])

    def test_baseline_is_strictly_lower_including_version_boundary(self):
        for name in ['0.1.33', '0.2.0', '1.0.0']:
            code = version_code(name)
            self.assertEqual(version_code(baseline_version({'versionCode': code})), code - 1)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        cls.update = cls.text.split('  inapp-update:\n', 1)[1].split('  publish:\n', 1)[0]
        cls.publish = cls.text.split('  publish:\n', 1)[1]

    def test_main_and_pull_requests_are_validated(self):
        push = self.text.split('  push:\n', 1)[1].split('    paths:', 1)[0]
        self.assertIn('      - main\n', push)
        self.assertIn('  pull_request:\n    branches: [main]', self.text)

    def test_gate_uses_candidate_and_does_not_allow_failure(self):
        self.assertIn('    needs: build', self.update)
        self.assertNotIn('continue-on-error:', self.update)
        self.assertIn('name: android-release-apk', self.update)
        self.assertIn('sh android/scripts/inapp_update_candidate.sh', self.update)
        self.assertNotIn('inapp_update_014_to_015.sh', self.update)

    def test_every_failed_skipped_or_cancelled_gate_blocks_publish(self):
        self.assertIn('    needs: [build, upgrade, inapp-update]', self.publish)
        expression = re.search(r'^    if: \$\{\{ (.+) \}\}$', self.publish, re.M)[1]
        for event, build, upgrade, update, success in itertools.product(
            ['push', 'workflow_dispatch', 'pull_request'],
            ['success', 'failure', 'skipped', 'cancelled'],
            ['success', 'failure', 'skipped', 'cancelled'],
            ['success', 'failure', 'skipped', 'cancelled'], [True, False],
        ):
            translated = expression.replace('&&', ' and ').replace('success()', repr(success))
            for key, value in {'github.event_name': event, 'needs.build.result': build,
                               'needs.upgrade.result': upgrade, 'needs.inapp-update.result': update}.items():
                translated = translated.replace(key, repr(value))
            allowed = eval(translated, {'__builtins__': {}}, {})
            expected = success and event != 'pull_request' and build == upgrade == update == 'success'
            self.assertEqual(allowed, expected, (event, build, upgrade, update, success))

    def test_existing_releases_are_not_rewritten(self):
        self.assertNotIn('gh release delete', self.publish)
        self.assertNotIn('--clobber', self.publish)
        self.assertIn('gh release view "$TAG"', self.publish)


if __name__ == '__main__':
    unittest.main()
