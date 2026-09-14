#!/usr/bin/env python3
"""Bounded UI status probes without Binary Ninja or Qt."""
from pathlib import Path
import sys
import threading
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
bn = types.SimpleNamespace()
application = types.SimpleNamespace(activeModalWidget=lambda: object())
sys.modules['binaryninja'] = bn
sys.modules['PySide6.QtWidgets'] = types.SimpleNamespace(QApplication=application)
sys.modules['binja.targets'] = types.SimpleNamespace(Targets=None, on_ui=lambda f: f())
from binja.bridge import Bridge


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge.__new__(Bridge)
        self.bridge.ui_probe = None
        self.bridge.ui_probe_lock = threading.Lock()
        self.bridge.targets = types.SimpleNamespace(refresh=lambda: [])

    def test_stuck_ui_shares_one_pending_probe_and_recovers(self):
        callbacks = []
        bn.execute_on_main_thread = callbacks.append
        for _ in range(2):
            value = self.bridge.gui_status()
            self.assertIsNone(value['modal_open'])
            self.assertIsNone(value['targets'])
            self.assertIn('timed out', value['gui_error'])
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        # A completed probe must not become a stale cached status.
        self.bridge.targets.refresh = lambda: [{'handle': 'new'}]
        bn.execute_on_main_thread = lambda callback: callback()
        value = self.bridge.gui_status()
        self.assertEqual(value, {'targets': [{'handle': 'new'}], 'modal_open': True})

    def test_probe_errors_remain_unknown(self):
        def broken():
            raise RuntimeError('refresh unavailable')
        self.bridge.targets.refresh = broken
        bn.execute_on_main_thread = lambda callback: callback()
        value = self.bridge.gui_status()
        self.assertIsNone(value['modal_open'])
        self.assertIn('refresh unavailable', value['gui_error'])


if __name__ == '__main__':
    unittest.main()
