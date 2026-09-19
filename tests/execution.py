#!/usr/bin/env python3
"""File lanes, readiness, cancellation, and recovery without Binary Ninja."""
from collections import OrderedDict, deque
from pathlib import Path
import io
import shlex
import tempfile
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

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


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.views = {}
        self.execution = e = Execution.__new__(Execution)
        e.bridge = types.SimpleNamespace(generation='abcdef123456', state=Path(self.directory.name))
        (e.bridge.state / 'artifacts').mkdir()
        e.bridge.execution = e
        e.bridge.targets = types.SimpleNamespace(resolve=self.resolve, describe=self.describe)
        e.lock = threading.RLock()
        e.changed = threading.Condition(e.lock)
        e.records = OrderedDict()
        e.rejections = deque(maxlen=execution_module.KEEP_REJECTIONS)
        e.rejected_total = 0
        e.stopping = False
        e.bn = types.SimpleNamespace(AnalysisState=types.SimpleNamespace(IdleState=0, InitialState=1, HoldState=2))
        e.stdout = execution_module.ThreadOutput(io.StringIO())
        e.stderr = execution_module.ThreadOutput(io.StringIO())
        original = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = e.stdout, e.stderr
        self.addCleanup(lambda: setattr(sys, 'stdout', original[0]))
        self.addCleanup(lambda: setattr(sys, 'stderr', original[1]))
        self.a = self.view(7)
        self.raw = self.view(7, 'Raw', 1)
        self.b = self.view(8)

    def view(self, file_id, view_type='ELF', state=0):
        handle = f'abcdef123456:v{len(self.views) + 1}'
        view = types.SimpleNamespace(file_id=file_id, handle=handle,
            view_type=view_type, analysis_state=state,
            begin_undo_actions=lambda: 'undo', commit_undo_actions=lambda undo: None)
        self.views[handle] = view
        return view

    def describe(self, view):
        return dict(handle=view.handle, file_id=view.file_id, view_type=view.view_type,
            analysis=view.analysis_state)

    def resolve(self, handle):
        if handle not in self.views:
            raise Error('Target handle expired')
        view = self.views[handle]
        return view, self.describe(view)

    def submit(self, view=None, source='result = 42', **flags):
        e = self.execution
        spec = dict(id=f'abcdef123456:r{len(e.records)}', source=source, filename='probe.py',
            no_target=view is None, target=view.handle if view else None, **flags)
        return e.records[e.submit(spec)['id']]

    def step(self, expected):
        record = self.execution.select()
        self.assertIs(record, expected)
        if record is not None:
            self.execution.execute(record)
        return record

    def test_file_lanes_and_earliest_ready_head(self):
        e = self.execution
        self.a.analysis_state = 3
        first = self.submit(self.a)
        sibling = self.submit(self.raw, allow_incomplete=True)
        other = self.submit(self.b)
        session = self.submit()
        session_tail = self.submit()
        self.assertNotIn('started', sibling)
        self.assertNotIn('started', session_tail)
        self.assertNotIn('started', other)
        self.assertEqual(e.snapshot(sibling)['waits_behind'], first['id'])
        self.assertEqual(e.snapshot(sibling)['queue_position'], 2)
        self.assertIsNone(e.snapshot(other)['waits_behind'])
        self.assertEqual(e.snapshot(session_tail)['waits_behind'], session['id'])
        self.step(other)
        self.assertEqual(first['status'], 'waiting_analysis')
        self.assertIn('started', first)
        self.assertIn('started', other)
        self.assertNotIn('started', session)
        self.assertEqual(e.snapshot(sibling)['queue_position'], 1)
        # Untargeted requests aren't a barrier and don't wait for parked files.
        self.step(session)
        self.step(session_tail)
        self.step(None)
        self.a.analysis_state = 0
        self.step(first)
        self.assertNotIn('started', sibling)
        self.step(sibling)
        self.assertLessEqual(first['finished'], sibling['started'])
        self.assertEqual(first['result'], 42)

    def test_unpicked_lane_head_keeps_accumulating_queue_time(self):
        e = self.execution
        with patch.object(execution_module.time, 'time', return_value=100) as clock:
            running = self.submit(self.a)
            self.assertIs(e.select(), running)
            queued = self.submit(self.b)
            for now in (105, 110):
                clock.return_value = now
                snapshot = e.get(queued['id'])
                self.assertEqual(snapshot['status'], 'queued')
                self.assertEqual(snapshot['queue_position'], 1)
                self.assertIsNone(snapshot['waits_behind'])
                self.assertNotIn('started', snapshot)
                self.assertEqual(snapshot['queue_wait_seconds'], now - 100)
                self.assertEqual(snapshot['elapsed_seconds'], now - 100)
                self.assertIsNone(snapshot['execution_seconds'])
            cancelled = e.cancel(queued['id'])
            self.assertIsNone(cancelled['execution_seconds'])
            self.assertEqual(cancelled['queue_wait_seconds'], 10)
            self.assertEqual(cancelled['elapsed_seconds'], 10)
            e.execute(running)

    def test_parked_timing_survives_later_wait_for_executor(self):
        e = self.execution
        self.a.analysis_state = 3
        with patch.object(execution_module.time, 'time', return_value=100) as clock:
            parked = self.submit(self.a)
            clock.return_value = 105
            self.step(None)
            self.assertEqual(parked['started'], 105)
            clock.return_value = 106
            other = self.submit(self.b)
            self.assertIs(e.select(), other)
            self.a.analysis_state = 0
            clock.return_value = 110
            snapshot = e.get(parked['id'])
            self.assertEqual(snapshot['queue_wait_seconds'], 5)
            self.assertEqual(snapshot['execution_seconds'], 5)
            self.assertEqual(snapshot['elapsed_seconds'], 5)
            e.execute(other)
            clock.return_value = 112
            self.step(parked)
            snapshot = e.get(parked['id'])
            self.assertEqual(snapshot['started'], 105)
            self.assertEqual(snapshot['queue_wait_seconds'], 5)
            self.assertEqual(snapshot['execution_seconds'], 7)
            self.assertEqual(snapshot['elapsed_seconds'], 7)

    def test_readiness_cancel_wakes_waiters_and_promotes_sibling(self):
        e = self.execution
        self.a.analysis_state = 3
        record = self.submit(self.a)
        sibling = self.submit(self.raw)
        self.step(None)
        self.assertEqual(record['status'], 'waiting_analysis')
        results = []
        waiters = [threading.Thread(target=lambda: results.append(e.wait(record['id'], 10))) for _ in range(3)]
        for thread in waiters:
            thread.start()
        e.cancel(record['id'])
        for thread in waiters:
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 3)
        self.assertTrue(all(r['status'] == 'cancelled' and r['execution_seconds'] > 0 for r in results))
        self.assertNotIn('_bv', record)
        self.assertEqual(e.wait(record['id'], 10)['status'], 'cancelled')
        self.step(sibling)  # Raw InitialState needs no pipeline.

    def test_deadline_and_unstarted_cancellation(self):
        e = self.execution
        head = self.submit(self.a)
        record = self.submit(self.a)
        before = time.monotonic()
        result = e.wait(record['id'], .01)
        self.assertGreaterEqual(time.monotonic() - before, .009)
        self.assertTrue(result['client_wait_expired'])
        cancelled = e.cancel(record['id'])
        self.assertIsNone(cancelled['execution_seconds'])
        self.assertGreater(cancelled['queue_wait_seconds'], 0)
        self.assertNotIn('client_wait_expired', e.wait(record['id'], 0))
        self.assertIs(e.select(), head)
        with self.assertRaisesRegex(Error, 'Only queued'):
            e.cancel(head['id'])

    def test_hold_runs_and_fails_with_resume_command(self):
        e = self.execution
        e.bridge.state = Path(self.directory.name) / "agent's workspace"
        (e.bridge.state / 'artifacts').mkdir(parents=True)
        self.a.analysis_state = 3
        record = self.submit(self.a, "raise AssertionError('must not run')")
        self.step(None)
        self.a.analysis_state = 2
        self.step(record)
        self.assertEqual(record['status'], 'failed')
        command = record['error'].splitlines()[1]
        self.assertEqual(shlex.split(command), ['binja', '--state-dir', str(e.bridge.state),
            'py', '--target', self.a.handle, '--allow-incomplete', '-c',
            'bv.set_analysis_hold(False); bv.update_analysis_and_wait()'])
        self.step(self.submit(self.a, allow_incomplete=True))

    def open_request(self, view):
        self.execution.bridge.loaded = view
        return self.submit(source="print('load output'); bridge.execution.opened(request, bridge.loaded, bridge.targets.describe(bridge.loaded))",
            kind='open')

    def test_open_parks_in_file_lane_and_describes_at_readiness(self):
        e = self.execution
        self.a.analysis_state = 3
        opened = self.open_request(self.a)
        self.step(opened)
        started = opened['started']
        snapshot = dict(opened['target_snapshot'])
        sibling = self.submit(self.raw, allow_incomplete=True)
        other = self.submit(self.b)
        self.step(other)
        self.assertEqual(opened['status'], 'waiting_analysis')
        self.assertNotIn('finished', opened)
        self.assertNotIn('result', opened)
        self.assertEqual(opened['target_snapshot_stage'], 'open')
        self.assertEqual(e.snapshot(sibling)['waits_behind'], opened['id'])
        self.a.analysis_state = 0
        self.step(opened)
        self.assertEqual(opened['started'], started)
        self.assertEqual(opened['result']['analysis'], 0)
        self.assertEqual(opened['target_snapshot'], snapshot)
        self.assertEqual(opened['stdout']['text'], 'load output\n')
        artifact = e.bridge.state / 'artifacts' / opened['id'] / 'stdout.txt'
        self.assertEqual(artifact.read_text(), 'load output\n')
        self.step(sibling)

    def test_open_joins_existing_file_in_submission_order(self):
        self.a.analysis_state = 3
        older = self.submit(self.a)
        opened = self.open_request(self.a)
        newer = self.submit(self.raw, allow_incomplete=True)
        self.step(opened)  # Load stage may proceed in the session lane.
        self.step(None)
        e = self.execution
        self.assertEqual(e.snapshot(opened)['waits_behind'], older['id'])
        self.assertEqual(e.snapshot(newer)['waits_behind'], opened['id'])
        self.a.analysis_state = 0
        self.step(older)
        self.step(opened)
        self.step(newer)

    def test_cancel_parked_open_keeps_target_and_output(self):
        e = self.execution
        self.a.analysis_state = 3
        record = self.open_request(self.a)
        self.step(record)
        self.step(None)
        with self.assertRaisesRegex(Error, 'Outstanding'):
            e.prepare_stop()
        cancelled = e.cancel(record['id'])
        self.assertEqual(cancelled['target_snapshot']['handle'], self.a.handle)
        self.assertEqual(cancelled['stdout']['text'], 'load output\n')
        self.assertIn(self.a.handle, self.views)
        self.assertNotIn('_bv', record)
        self.assertNotIn('_spec', record)
        self.step(None)

    def test_parked_handle_revalidation_is_throttled(self):
        e = self.execution
        self.a.analysis_state = 3
        record = self.submit(self.a)
        with patch.object(execution_module.time, 'monotonic', return_value=10) as clock:
            # Count UI dispatches, not just resolve calls. Ordinary polls must
            # stay off the UI thread, while expired parked views still fail.
            with patch.object(execution_module, 'on_ui', wraps=lambda f: f()) as ui:
                self.step(None)
                self.assertEqual(ui.call_count, 1)
                for now in (10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9):
                    clock.return_value = now
                    self.step(None)
                self.assertEqual(ui.call_count, 1)
                clock.return_value = 11
                self.step(None)
                self.assertEqual(ui.call_count, 2)
                del self.views[self.a.handle]
                clock.return_value = 11.9
                self.step(None)
                self.assertEqual(ui.call_count, 2)
                clock.return_value = 12
                self.step(record)
                self.assertEqual(ui.call_count, 3)
        self.assertIn('handle expired', record['error'])
        self.assertNotIn('_next_revalidation', record)

    def test_readiness_revalidates_even_before_periodic_check_is_due(self):
        e = self.execution
        self.a.analysis_state = 3
        record = self.submit(self.a)
        with patch.object(execution_module.time, 'monotonic', return_value=10):
            self.step(None)
            e.bridge.targets.resolve = Mock(wraps=self.resolve)
            self.a.analysis_state = 0
            self.assertIs(e.select(), record)
            e.bridge.targets.resolve.assert_not_called()
            del self.views[self.a.handle]
            e.execute(record)
            e.bridge.targets.resolve.assert_called_once_with(self.a.handle)
        self.assertIn('handle expired', record['error'])
        record = self.submit(self.b)
        self.assertIs(e.select(), record)
        del self.views[self.b.handle]
        e.execute(record)
        self.assertIn('handle expired', record['error'])

    def test_cancel_during_probe_never_executes_or_resurrects(self):
        e = self.execution
        record = self.submit(self.a)
        def resolve(handle):
            e.cancel(record['id'])
            return self.resolve(handle)
        e.bridge.targets.resolve = resolve
        self.step(None)
        self.assertEqual(record['status'], 'cancelled')
        self.assertNotIn('result', record)
        self.assertNotIn('_next_revalidation', record)

    def test_cancel_during_other_probe_reconsiders_promoted_head(self):
        e = self.execution
        self.a.analysis_state = 3
        first = self.submit(self.a)
        sibling = self.submit(self.raw)
        other = self.submit(self.b)
        def resolve(handle):
            if handle == self.b.handle and first['status'] != 'cancelled':
                e.cancel(first['id'])
            return self.resolve(handle)
        e.bridge.targets.resolve = resolve
        self.step(None)
        self.step(sibling)
        self.step(other)

    def test_close_skips_readiness_on_hold(self):
        self.a.analysis_state = 2
        closing = self.submit(self.a, kind='close')
        self.step(closing)
        self.assertEqual(closing['status'], 'completed')

    def test_parked_requests_count_toward_cap(self):
        e = self.execution
        for i in range(8):
            self.submit(self.view(20 + i, state=3))
        self.step(None)
        self.assertTrue(all(r['status'] == 'waiting_analysis' for r in e.records.values()))
        with self.assertRaisesRegex(Error, 'pending cap 8'):
            self.submit()

    def test_pruning_keeps_newest_completion_after_later_cancellations(self):
        e = self.execution
        newest = self.submit(self.a)
        for i in range(65):
            rid = f'cancel{i}'
            e.records[rid] = dict(id=rid, status='cancelled', finished=i)
        self.step(newest)
        self.assertEqual(newest['result'], 42)
        self.assertFalse(newest.get('output_pruned', False))
        self.assertTrue(e.records['cancel0']['output_pruned'])
        self.assertTrue(e.records['cancel1']['output_pruned'])
        self.assertFalse(e.records['cancel2'].get('output_pruned', False))

    def test_rejection_ring_does_not_admit_or_count_duplicates(self):
        e = self.execution
        first = self.submit(self.a)
        self.rid = first['id']
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
