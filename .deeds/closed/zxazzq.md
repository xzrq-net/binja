---
blocked-by: [mpsj67]
---
# Complete the minimal open, save, and shutdown workflow

Implement the persistence boundary needed for agent trials. Use readable Python command scripts shipped by the CLI and the existing recoverable request mechanism.

## Work

- Add file/database `open` using the execution layer and the GUI behavior established by the RPC smoke tests. Wait for analysis by default, with an explicit incomplete-analysis override. Opening another file must not redirect an accepted request.
- Add `save` to an explicit BNDB destination. Report success only after serialization succeeds; slow/failed saves remain inspectable after client disconnect. Expose dirty state and last successful save observed by this session where available; unknown stays unknown.
- Finish orderly `stop`: coordinate queued/running work and refuse silent loss of unsaved analysis. Keep forced/discard recovery explicit. Reopening after a process restart is sufficient for MVP persistence verification; per-view `close` comes later.
- Supply compact text, JSON output, target provenance, and actionable errors for this small surface. Update help and the packaged guide with working Python inspection/edit examples, API lookup, deliberate saves, and request recovery.

## Verification

Open two copied binaries, query the intended view, mutate a name/comment through Python, save a BNDB, stop/restart, reopen, and verify persistence and unchanged input bytes. Test failed saves, disconnect during save, stop with unsaved changes/outstanding work, and readiness/override behavior.

Do not add decompile/xrefs, per-view close, navigation, screenshots, or dialog detection here; `zbqnx2` owns those incremental commands. No autosaver or specialized loader workflow.

Closed: Installed open/save/guarded stop workflow passes with two copied binaries, saved comments across restart, failed-save errors, unchanged input hashes, explicit target provenance, and pending/unsaved shutdown refusal. Packaged guide and README describe the usable MVP; operator UX checkpoint precedes trials.
