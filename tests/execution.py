#!/usr/bin/env python3
"""Condition wakeups and readiness cancellation without Binary Ninja."""
from collections import OrderedDict, deque
from pathlib import Path
import shlex
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules['binja.targets'] = types.SimpleNamespace(on_ui=lambda f: f())
from binja.execution import Execution, script_traceback
import binja.execution as execution_module
from binja.common import Error


class TracebackTests(unittest.TestCase):
    def render(self, source):
        # A wrapper frame with the same filename as the real plugin executor.
        wrapper = compile("exec(compile(source, 'probe.py', 'exec'))",
                          execution_module.__file__, "exec")
        try:
            exec(wrapper, {"source": source})
        except BaseException as exc:
            # Start at the wrapper, as Execution.execute does.
            exc.__traceback__ = exc.__traceback__.tb_next
            return script_traceback(exc)

    def test_script_and_inner_frames(self):
        text = self.render("def inner():\n    raise ValueError('marker')\ninner()")
        self.assertIn('File "probe.py", line 3', text.splitlines()[1])
        self.assertIn('File "probe.py", line 2, in inner', text)
        self.assertNotIn(execution_module.__file__, text)

    def test_chain_and_syntax_location(self):
        text = self.render("try: 1/0\nexcept Exception as e: raise ValueError('outer') from e")
        self.assertIn("ZeroDivisionError", text)
        self.assertIn("direct cause", text)
        self.assertIn("ValueError: outer", text)
        self.assertNotIn(execution_module.__file__, text)
        text = self.render("if :")
        self.assertIn('File "probe.py", line 1', text)
        self.assertIn("SyntaxError", text)
        self.assertNotIn(execution_module.__file__, text)


class WaitTests(unittest.TestCase):
    def setUp(self):
        self.execution = e = Execution.__new__(Execution)
        e.bridge = types.SimpleNamespace(generation='abcdef123456')
        e.lock = threading.RLock()
        e.changed = threading.Condition(e.lock)
        e.records = OrderedDict()
        e.rejections = deque(maxlen=execution_module.KEEP_REJECTIONS)
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

    def test_hold_resume_names_retained_target_and_quotes_state_path(self):
        e = self.execution
        e.bridge.state = Path("/tmp/agent's workspace/.binja")
        record = e.records[self.rid]
        record['target_snapshot'] = dict(handle='abcdef123456:v2')
        view = types.SimpleNamespace(analysis_state=e.bn.AnalysisState.HoldState, view_type='ELF')
        with self.assertRaises(Error) as raised:
            e.wait_ready(view, record)
        command = str(raised.exception).splitlines()[1]
        self.assertEqual(shlex.split(command), ['binja', '--state-dir', str(e.bridge.state),
            'py', '--target', 'abcdef123456:v2', '--allow-incomplete', '-c',
            'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'])

    def test_pruning_keeps_newest_completion_after_later_cancellations(self):
        e = self.execution
        e.bridge.state = Path("/unused")
        newest = e.records[self.rid]
        # Submitted first, but completes after 65 later requests were cancelled.
        for i in range(65):
            rid = f"cancel{i}"
            e.records[rid] = dict(id=rid, status="cancelled", finished=i)
        work = iter([newest])
        e.work = types.SimpleNamespace(get=lambda: next(work))
        e.execute = lambda record: record.update(status="completed", finished=100, result="latest")
        with self.assertRaises(StopIteration):
            e.run()
        self.assertEqual(newest["result"], "latest")
        self.assertFalse(newest.get("output_pruned", False))
        self.assertTrue(e.records["cancel0"]["output_pruned"])
        self.assertTrue(e.records["cancel1"]["output_pruned"])
        self.assertFalse(e.records["cancel2"].get("output_pruned", False))

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
        retained = e.bridge.generation + ':rreject6'
        aged_out = e.bridge.generation + ':rreject5'
        for lookup in (e.get, lambda rid: e.wait(rid, 10), e.cancel):
            with self.assertRaisesRegex(Error, 'rejected at capacity and never executed.*Safe to resubmit'):
                lookup(retained)
            with self.assertRaisesRegex(Error, 'Unknown request ID.*Do not blindly resubmit'):
                lookup(aged_out)
        # Once the same ID is accepted, its record takes precedence over history.
        e.records[retained] = dict(id=retained, status='queued', submitted=time.time())
        self.assertEqual(e.get(retained)['status'], 'queued')
        self.assertEqual(e.wait(retained, 0)['status'], 'queued')
        self.assertEqual(e.cancel(retained)['status'], 'cancelled')
        duplicate = e.submit(dict(id=self.rid, source='pass', filename='different.py'))
        self.assertTrue(duplicate['admission_existing'])
        self.assertEqual(e.rejected_total, 70)


class CloseTests(unittest.TestCase):
    def setUp(self):
        self.execution = e = Execution.__new__(Execution)
        e.lock = threading.RLock()
        e.records = OrderedDict()
        self.target = dict(handle='abcdef123456:v1', file_id=7)
        self.raw = dict(handle='abcdef123456:v2', file_id=7)
        self.other = dict(handle='abcdef123456:v3', file_id=8)
        self.closed = []
        e.bridge = types.SimpleNamespace(targets=types.SimpleNamespace(
            resolve=lambda handle: (object(), self.target),
            close=lambda target, force: self.closed.append((target, force))))

    def record(self, rid, kind, target, status):
        value = dict(id=rid, kind=kind, target_snapshot=target, status=status)
        self.execution.records[rid] = value
        return value

    def test_close_refuses_all_pending_states_for_sibling_views(self):
        e = self.execution
        closing = self.record('close', 'close', self.target, 'running')
        for state in ('queued', 'running', 'waiting_analysis'):
            self.record('work', 'py', self.raw, state)
            with self.assertRaisesRegex(Error, 'Outstanding requests.*work'):
                e.check_close(self.target, 'close', 'close')
            for force in (False, True):
                with self.assertRaisesRegex(Error, '--force only discards unsaved changes'):
                    e.close(closing, force)
        self.assertEqual(self.closed, [])
        e.records['work']['status'] = 'cancelled'
        self.record('other', 'py', self.other, 'running')
        self.record('unbound', 'py', None, 'queued')
        e.close(closing, True)
        self.assertEqual(self.closed, [(self.target, True)])

    def test_pending_close_blocks_new_work_but_not_other_files(self):
        e = self.execution
        closing = self.record('close', 'close', self.raw, 'queued')
        for kind in ('py', 'save', 'close'):
            with self.assertRaisesRegex(Error, 'Close pending.*close'):
                e.check_close(self.target, kind)
        e.check_close(self.other, 'py')
        e.check_close(None, 'py')
        closing['status'] = 'cancelled'
        e.check_close(self.target, 'py')


if __name__ == '__main__':
    unittest.main()
