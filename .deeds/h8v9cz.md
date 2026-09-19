---
tier: objective
---
# User feedback: analysis waits block work on unrelated files

Feedback from Codex as a binja CLI user, using Binary Ninja Personal 6.0.10601
for the honglass 0.12.8 patch investigation on 2026-09-18.

## Observed friction

I submitted opens for `k2.dll` and `shared.dll`. Their analysis took about
143 and 71 seconds respectively. The second open waited behind the first;
once k2 was ready, my queries against it waited behind shared's analysis.
The single worker remained occupied during readiness waits even though the
queued query concerned an independently loaded, fully analyzed file.

Request IDs, queue visibility, and timeout recovery worked. I could recover
results without repeating work, but I could not make progress on the ready
file through the CLI while another file was analyzing.

I want unrelated files to make progress independently, while operations on
the same file retain predictable ordering. Concurrent scripts or automatic
rollback are not requirements of this feedback.

## Possible direction to assess

- Queue by opened-file identity (`file_id` / `bv.file.session_id`), grouping
  Raw and PE views of the same file. Existing close checks already use this
  boundary in `binja/execution.py`.
- Preserve FIFO ordering within a file, but park analysis waits so ready work
  for other files can proceed. Splitting `open` into opening/registering the
  view and waiting for analysis would address the observed case. One active
  request executor may be sufficient initially.
- Evaluate actual concurrent request execution separately. `Execution.execute`
  currently opens an undo group even for reads. Arbitrary Python can also
  touch other files or session state, so its target handle is not enforced
  isolation.

Binary Ninja's [FileMetadata API documentation](https://rust.binary.ninja/binaryninja/file_metadata/struct.FileMetadata.html#method.begin_undo_actions)
warns against concurrent undo operations. An [upstream discussion](https://github.com/Vector35/binaryninja-api/issues/6325)
also describes undo groups capturing actions from other threads or the GUI.
Separate file queues should not be taken as proof that concurrent undo groups
are safe. Keeping partial edits applied and undoable on failure has been a
usable contract for me.

The concrete scenario to improve: open A and B, then inspect A as soon as its
analysis finishes while B is still analyzing, without bypassing readiness or
reordering requests within A. The scheduling design is left for assessment.
