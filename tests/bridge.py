#!/usr/bin/env python3
"""Live protocol-3 checks without a CLI. Pass --package /nix/store/...-binja-... ."""
import argparse
import json
import os
from pathlib import Path
import socket
import shutil
import sys
import tempfile
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--package', required=True, type=Path)
p.add_argument('--sample', required=True, type=Path)
a = p.parse_args()
sys.path.insert(0, str(a.package / 'lib'))
os.environ['PYTHONPATH'] = str(a.package / 'lib')
from binja.common import PROTOCOL, MAX_REQUEST, MAX_RESPONSE, receive, send
from binja import session

state = Path(tempfile.mkdtemp(prefix='binja-protocol-')) / '.binja'
sample = state.parent / 'sample'
shutil.copy2(a.sample, sample)
seq = 0
def connect():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    s.settimeout(20)
    s.connect(str(state / 'runtime/rpc.sock'))
    return s

def message(op, **params):
    return dict(protocol=PROTOCOL, generation=generation, op=op, **params)

def rpc(op, **params):
    with connect() as s:
        send(s, message(op, **params), MAX_REQUEST)
        events = [receive(s, MAX_RESPONSE)]
        while not events[-1]['final']:
            events.append(receive(s, MAX_RESPONSE))
    for event in events:
        assert event['protocol'] == 3 and event['generation'] == generation
        assert 'error' not in event, event
    return events

def spec(source='result=42', **params):
    global seq
    seq += 1
    return dict(id=f'{generation}:rtest{seq}', source=source, filename='<live test>',
        no_target=True, kind='py', **params)

def submit(source='result=42', wait=5, **params):
    return rpc('submit', spec=spec(source, **params), wait=wait)

started = False
try:
    print(f'Live workspace: {state.parent}', flush=True)
    info = session.start(state, None)
    started = True
    generation = info['generation']
    events = submit()
    assert len(events) == 2 and events[0]['event'] == 'accepted' and not events[0]['final']
    assert events[0]['data']['waits_behind'] is None
    assert events[-1]['data']['result'] == 42
    assert events[-1]['data']['execution_seconds'] >= 0
    first = events[-1]['data']
    duplicate = rpc('submit', spec=dict(spec('raise AssertionError()'), id=first['id']), wait=5)
    assert duplicate[0]['existing'] and duplicate[-1]['data']['result'] == 42
    assert len(submit(wait=0)) == 1
    for seconds in (-1, True, "5"):
        invalid = spec()
        with connect() as sock:
            send(sock, message('submit', spec=invalid, wait=seconds), MAX_REQUEST)
            assert 'error' in receive(sock, MAX_RESPONSE)
        with connect() as sock:
            send(sock, message('request', id=invalid['id']), MAX_REQUEST)
            assert 'Unknown request' in receive(sock, MAX_RESPONSE)['error']
    partial = spec('raise AssertionError("incomplete source executed")')
    with connect() as sock:
        sock.send(b'\x01' + json.dumps(message('submit', spec=partial)).encode())
    time.sleep(.05)
    with connect() as sock:
        send(sock, message('request', id=partial['id']), MAX_REQUEST)
        assert 'Unknown request' in receive(sock, MAX_RESPONSE)['error']
    print('Admission, completion, duplicate recovery', flush=True)

    # A 1 MiB inline source crosses many packets; the result remains an artifact.
    large = submit('# padding\n' * 100000 + 'print("x" * 20000); result=list(range(20000))')[-1]['data']
    artifact = Path(large['result_artifact'])
    assert len(json.loads(artifact.read_text())) == 20000
    assert large['stdout']['bytes'] == 20001 and len(large['stdout']['text']) == 16384
    assert session.start(state, None)['generation'] == generation
    assert artifact.exists(), 'reuse must not retire artifacts'

    # Receipt must arrive while the worker is occupied, before the blocking result.
    blocker = submit('import time; time.sleep(2)', wait=0)[0]['data']
    with connect() as s:
        queued_spec = spec('result="queued"')
        send(s, message('submit', spec=queued_spec, wait=10), MAX_REQUEST)
        accepted = receive(s, MAX_RESPONSE)
        assert accepted['data']['waits_behind'] == blocker['id']
        cancelled = rpc('cancel', id=queued_spec['id'])[-1]['data']
        assert cancelled['status'] == 'cancelled' and cancelled['execution_seconds'] is None
        woke = receive(s, MAX_RESPONSE)
        assert woke['data']['status'] == 'cancelled'
    pending = [submit(wait=0)[0]['data'] for _ in range(7)]
    with connect() as s:
        rejected = spec()
        send(s, message('submit', spec=rejected, wait=0), MAX_REQUEST)
        assert 'not accepted and will not execute' in receive(s, MAX_RESPONSE)['error']
    history = rpc('requests', all=True)[-1]['data']
    assert history['rejected_total'] == 1 and history['rejections'][0]['id'] == rejected['id']
    assert rejected['id'] not in {r['id'] for r in history['requests']}
    assert rpc('submit', spec=dict(spec(), id=blocker['id']), wait=0)[0]['existing']
    expired = rpc('request', id=blocker['id'], wait=.01)[-1]['data']
    assert expired['client_wait_expired']
    rpc('request', id=pending[-1]['id'], wait=10)
    print('Queue receipt, cancellation wakeup, cap rejection, wait expiry', flush=True)

    # Disconnect after complete submission must neither cancel nor replay it.
    disconnected = spec('from pathlib import Path; p=bridge.state / "once"; p.write_text(p.read_text()+"x" if p.exists() else "x"); result=1')
    with connect() as s:
        send(s, message('submit', spec=disconnected, wait=5), MAX_REQUEST)
    time.sleep(.1)
    assert rpc('request', id=disconnected['id'], wait=5)[-1]['data']['result'] == 1
    rpc('submit', spec=disconnected, wait=5)
    assert (state / 'once').read_text() == 'x'
    failed = submit('raise ValueError("intentional")')[-1]['data']
    assert failed['status'] == 'failed' and 'intentional' in failed['error']
    infrastructure = spec()
    (state / 'artifacts' / infrastructure['id']).mkdir()
    assert rpc('submit', spec=infrastructure, wait=5)[-1]['data']['status'] == 'failed'

    submit('import binja.execution as e; e.KEEP_RESULTS=2')
    for _ in range(3):
        submit()
    pruned = rpc('request', id=large['id'])[-1]['data']
    assert pruned['output_pruned'] and 'text' not in pruned['stdout']
    assert Path(pruned['stdout']['artifact']).is_file() and Path(pruned['result_artifact']).is_file()
    assert 'result' not in rpc('request', id=first['id'])[-1]['data']
    assert json.loads(Path(rpc('request', id=first['id'])[-1]['data']['result_artifact']).read_text()) == 42

    # Enough real metadata to exceed the former suggested 128 KiB cap.
    submit('''
with bridge.execution.lock:
    for i in range(400):
        rid = bridge.generation + ':rhistory' + str(i)
        bridge.execution.records[rid] = dict(id=rid, status='failed', submitted=0, finished=1,
            kind='py', filename='history.py', error='forensic error ' * 100, output_pruned=True)
''')
    history = rpc('requests', all=True)[-1]['data']
    assert len(json.dumps(history)) > 128 * 1024
    assert history['finished_shown'] == history['finished_total']
    assert any(r.get('error') == failed['error'] for r in history['requests'])
    assert rpc('requests')[-1]['data']['finished_shown'] == 5
    print('Disconnect, failures, pruning retention, multi-packet forensic export', flush=True)

    # Exercise target-bound Python and save/reopen using the shipped command scripts.
    def command(kind, path, target=None):
        script = a.package / 'lib/binja/commands' / (kind + '.py')
        request = spec(script.read_text(), args={'path': str(path)})
        request.update(kind=kind, filename=str(script), no_target=kind == 'open', target=target)
        return rpc('submit', spec=request, wait=30)[-1]['data']
    opened = command('open', sample)
    assert opened['status'] == 'completed'
    target = opened['result']['handle']
    mutation = spec('bv.set_comment_at(bv.entry_point, "protocol3")')
    mutation.update(no_target=False, target=target)
    assert rpc('submit', spec=mutation, wait=5)[-1]['data']['status'] == 'completed'
    saved = command('save', state.parent / 'saved.bndb', target)
    assert saved['status'] == 'completed' and saved['kind'] == 'save'
    session.stop(state)
    started = False
    assert not list((state / 'artifacts').iterdir())
    (state / 'artifacts/stale').write_text('old lifetime')
    generation = session.start(state, None)['generation']
    started = True
    assert not list((state / 'artifacts').iterdir())
    reopened = command('open', state.parent / 'saved.bndb')
    check = spec('result=bv.get_comment_at(bv.entry_point)')
    check.update(no_target=False, target=reopened['result']['handle'])
    assert rpc('submit', spec=check, wait=5)[-1]['data']['result'] == 'protocol3'
    print('Live target mutation, save/reopen, stop/start cleanup', flush=True)
finally:
    if started:
        session.stop(state, force=True)
print('Protocol 3 live checks passed', flush=True)
