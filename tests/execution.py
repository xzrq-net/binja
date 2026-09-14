#!/usr/bin/env python3
"""Condition wakeups and readiness cancellation without Binary Ninja."""
from collections import OrderedDict, deque
from pathlib import Path
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules['binja.targets'] = types.SimpleNamespace(on_ui=lambda f: f())
from binja.execution import Execution
from binja.common import Error


class WaitTests(unittest.TestCase):
    def setUp(self):
        self.execution = e = Execution.__new__(Execution)
        e.bridge = types.SimpleNamespace(generation='abcdef123456')
        e.lock = threading.RLock()
        e.changed = threading.Condition(e.lock)
        e.records = OrderedDict()
        e.bn = types.SimpleNamespace(AnalysisState=types.SimpleNamespace(IdleState=0, InitialState=1, HoldState=2))
        self.rid = e.bridge.generation + ':rwait'
        e.records[self.rid] = dict(id=self.rid, status='running', submitted=time.time()-.5,
            started=time.time()-.2, allow_incomplete=False)

    def test_readiness_cancel_wakes_all_waiters(self):
        e = self.execution
        record = e.records[self.rid]
        view = types.SimpleNamespace(analysis_state=3, view_type='ELF')
        results, readiness_errors = [], []
        def ready():
            try:
                e.wait_ready(view, record)
            except Error as exc:
                readiness_errors.append(str(exc))
        readiness = threading.Thread(target=ready)
        readiness.start()
        deadline = time.monotonic() + 2
        while record['status'] != 'waiting_analysis':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.001)
        waiters = [threading.Thread(target=lambda: results.append(e.wait(self.rid, 10))) for _ in range(3)]
        for thread in waiters:
            thread.start()
        e.cancel(self.rid)
        for thread in waiters + [readiness]:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r['status'] == 'cancelled' and r['execution_seconds'] > 0 for r in results))
        self.assertEqual(readiness_errors, ['Request cancelled before execution.'])
        # Terminal-before-wait must return immediately too (no lost notification).
        self.assertEqual(e.wait(self.rid, 10)['status'], 'cancelled')

    def test_deadline_and_unstarted_cancellation(self):
        e = self.execution
        before = time.monotonic()
        result = e.wait(self.rid, .01)
        self.assertGreaterEqual(time.monotonic() - before, .009)
        self.assertTrue(result['client_wait_expired'])
        record = e.records[self.rid]
        record.pop('started')
        record['status'] = 'queued'
        cancelled = e.cancel(self.rid)
        self.assertIsNone(cancelled['execution_seconds'])
        self.assertGreater(cancelled['queue_wait_seconds'], 0)
        self.assertNotIn('client_wait_expired', e.wait(self.rid, 0))

    def test_rejection_ring_does_not_admit_or_count_duplicates(self):
        e = self.execution
        e.stopping = False
        e.rejected_total = 0
        e.rejections = deque(maxlen=64)
        for i in range(7):
            rid = e.bridge.generation + ':rqueued' + str(i)
            e.records[rid] = dict(id=rid, status='queued', submitted=time.time())
        for i in range(70):
            spec = dict(id=e.bridge.generation + ':rreject' + str(i), source='pass', filename='probe.py')
            with self.assertRaisesRegex(Error, 'not accepted and will not execute'):
                e.submit(spec)
        self.assertEqual(len(e.records), 8)
        self.assertEqual(e.rejected_total, 70)
        self.assertEqual(len(e.rejections), 64)
        self.assertTrue(e.rejections[0]['id'].endswith('reject6'))
        duplicate = e.submit(dict(id=self.rid, source='pass', filename='different.py'))
        self.assertTrue(duplicate['admission_existing'])
        self.assertEqual(e.rejected_total, 70)


if __name__ == '__main__':
    unittest.main()
