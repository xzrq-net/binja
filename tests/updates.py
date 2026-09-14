#!/usr/bin/env python3
"""Update notices without Binary Ninja or a network connection."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binja import updates

# Both releases came from release-personal metadata on 2026-09-13. The
# available case models an older installation, not an invented future release.
LATEST = '6.0.10601 personal'
OLDER = '5.3.9757'


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        (self.state / 'cache').mkdir()
        self.path = self.state / 'cache/updates.json'
        self.bn = SimpleNamespace(core_version=lambda: '6.0.10601 Personal',
            update=SimpleNamespace(are_auto_updates_enabled=lambda: False,
                UpdateChannel={updates.CHANNEL: SimpleNamespace(latest_version_num=LATEST)}))

    def read(self):
        return json.loads(self.path.read_text())

    def test_available_current_and_unknown_are_cached(self):
        for installed, expected in ((OLDER, 'available'), ('6.0.10601', 'current')):
            with self.subTest(expected=expected):
                self.bn.core_version = lambda: installed + ' Personal'
                updates.check(self.state, self.bn)
                value = self.read()
                self.assertEqual(value['status'], expected)
                self.assertEqual(value['latest_stable'], LATEST)
                self.assertEqual(value['installed'], installed)
                self.assertIsNone(value['error'])
                self.assertEqual(value['expires_at'] - value['checked_at'], updates.CACHE_SECONDS)
                with patch.object(updates, 'query', side_effect=AssertionError('cache was ignored')):
                    updates.check(self.state, self.bn)
                self.assertEqual(self.read(), value)
        self.path.unlink()
        with patch.object(updates, 'query', side_effect=OSError('offline')):
            updates.check(self.state, self.bn)
        value = self.read()
        self.assertEqual(value['status'], 'unknown')
        self.assertIsNone(value['latest_stable'])
        self.assertIn('offline', value['error'])
        self.assertEqual(value['expires_at'] - value['checked_at'], updates.ERROR_SECONDS)
        with patch.object(updates, 'query', side_effect=AssertionError('cache was ignored')):
            updates.check(self.state, self.bn)
        self.assertEqual(self.read(), value)

    def test_expired_wrong_version_and_malformed_caches_are_refreshed(self):
        updates.check(self.state, self.bn)
        valid = self.read()
        for value in ({**valid, 'expires_at': 0}, {**valid, 'installed': OLDER},
                {**valid, 'checked_at': time.time() + 100}, {}, [], None):
            with self.subTest(value=value):
                self.path.write_text(json.dumps(value))
                with patch.object(updates, 'query', return_value=LATEST) as query:
                    updates.check(self.state, self.bn)
                    query.assert_called_once_with(self.bn)
                self.assertEqual(self.read()['status'], 'current')
        self.path.write_text('broken json')
        updates.check(self.state, self.bn)
        self.assertEqual(self.read()['status'], 'current')

    def test_timeout_is_unknown_and_late_result_cannot_overwrite_it(self):
        release, finished = threading.Event(), threading.Event()
        def stalled(_):
            release.wait(2)
            finished.set()
            return LATEST
        with patch.object(updates, 'query', side_effect=stalled), patch.object(updates, 'CHECK_SECONDS', .02):
            before = time.monotonic()
            updates.check(self.state, self.bn)
            self.assertLess(time.monotonic() - before, .5)
            value = self.read()
            self.assertEqual(value['status'], 'unknown')
            self.assertIn('timed out', value['error'])
            release.set()
            self.assertTrue(finished.wait(1))
        self.assertEqual(self.read(), value)

    def test_enabled_auto_updates_and_unrecognized_versions_remain_unknown(self):
        self.bn.update.are_auto_updates_enabled = lambda: True
        # No channel lookup should happen while auto updates are enabled.
        del self.bn.update.UpdateChannel
        updates.check(self.state, self.bn)
        self.assertIn('Automatic updates are enabled', self.read()['error'])
        self.path.unlink()
        with patch.object(updates, 'query', return_value='6.1.10653-dev personal'):
            updates.check(self.state, self.bn)
        self.assertEqual(self.read()['status'], 'unknown')
        self.assertIsNone(self.read()['latest_stable'])


if __name__ == '__main__':
    unittest.main()
