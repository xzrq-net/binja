#!/usr/bin/env python3
"""Target liveness during deferred GUI deletion, without Binary Ninja or Qt."""
import ctypes
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ui = SimpleNamespace()
sys.modules['binaryninja'] = SimpleNamespace()
sys.modules['binaryninjaui'] = ui
sys.modules['PySide6.QtCore'] = SimpleNamespace(QTimer=None)
sys.modules['PySide6.QtWidgets'] = SimpleNamespace(QApplication=None, QMessageBox=None)
from binja.common import Error
from binja.targets import Targets


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.targets = Targets('abcdef123456')
        file = SimpleNamespace(session_id=7, filename='/sample', modified=False, analysis_changed=False)
        self.view = SimpleNamespace(file=file, view_type='ELF', handle=ctypes.c_void_p(1),
            analysis_state=SimpleNamespace(name='IdleState'))
        self.raw = SimpleNamespace(file=file, view_type='Raw', handle=ctypes.c_void_p(2),
            analysis_state=SimpleNamespace(name='InitialState'))
        self.tabs = [object()]
        frame = SimpleNamespace(getCurrentBinaryView=lambda: self.view)
        self.context = SimpleNamespace(getCurrentViewFrame=lambda: frame if self.tabs else None,
            getTabs=lambda: self.tabs, getAllViewFramesForTab=lambda tab: [frame])
        ui.UIContext = SimpleNamespace(allContexts=lambda: [self.context], activeContext=lambda: self.context)
        file_context = SimpleNamespace(getMetadata=lambda: file, getAllDataViews=lambda: [self.view, self.raw])
        # The native file context intentionally survives tab removal.
        ui.FileContext = SimpleNamespace(getOpenFileContexts=lambda: [file_context])

    def test_closing_tab_expires_all_views_before_native_deletion(self):
        before = self.targets.refresh()
        self.assertEqual({t['view_type'] for t in before}, {'ELF', 'Raw'})
        self.assertIs(self.targets.resolve('/sample')[0], self.view)
        self.tabs.clear()
        self.assertEqual(self.targets.refresh(), [])
        self.assertEqual(self.targets.views, {})
        for target in before:
            with self.assertRaisesRegex(Error, 'handle expired.*Run binja targets'):
                self.targets.resolve(target['handle'])
        self.tabs.append(object())
        after = self.targets.refresh()
        self.assertTrue({t['handle'] for t in before}.isdisjoint(t['handle'] for t in after))

    def test_unknown_handle_and_missing_path_have_inline_guidance(self):
        with self.assertRaisesRegex(Error, 'handle expired or unknown'):
            self.targets.resolve('oldgeneration:v1')
        with self.assertRaisesRegex(Error, 'No live target.*run binja targets'):
            self.targets.resolve('/missing')


if __name__ == '__main__':
    unittest.main()
