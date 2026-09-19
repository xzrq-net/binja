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

## Plan (2026-09-18)

The request is sound. The lane boundary is the file (`bv.file.session_id`, the
`file_id` close already uses): undo history, modification flags, and close all
live there, so Raw and PE views of one file must never reorder against each
other. In Binary Ninja terms the file is the database; per-view lanes would put
two requests on one undo history.

Decisions:

1. One executor thread stays. Only readiness waits leave it. Python and native
   calls from submitted scripts remain strictly one at a time, so the undo-group
   concurrency warning is not exercised. Concurrent execution stays a separate
   question.
2. Lanes: each unfinished request belongs to the lane of its
   `target_snapshot.file_id`; untargeted requests share one session lane. Within
   a lane, strict submission order, including behind a parked `open`. Across
   lanes, the executor runs the earliest-submitted lane head whose readiness is
   satisfied. A head whose analysis is on hold runs and fails with the existing
   resume error.
3. A lane head whose view is still analyzing is parked with status
   `waiting_analysis` and stays cancellable. `started` is set when the executor
   first probes the request, whether it runs or parks. Queue time includes
   waiting for executor pickup, even at a lane head; execution time includes
   readiness and any subsequent wait for the executor. Cancellation before
   pickup keeps execution time null. (Timing clarified in commit review.)
4. `open` splits: the script loads, attaches, starts analysis, and records the
   `open`-stage snapshot; the request then parks in its file's lane and
   completes with the readiness-time `describe` result. The `open` result and
   its `analysis: IdleState` are unchanged. Cancelling a parked `open` leaves the
   file open; its handle is in the record's target snapshot.
5. `queue_position` and `waits_behind` become lane-relative, naming what the
   request actually waits for. The global pending cap of 8 is unchanged; parked
   requests count.
6. Untargeted requests are not a barrier. With one executor nothing interleaves,
   and barrier semantics would stall cheap session-level scripts behind parked
   opens, which is the reported friction again.

Non-goals: per-file executor threads, event-driven readiness (100 ms polling
stays), changing the cap, and `--allow-incomplete` bypassing a parked lane head.

Verification: unit coverage in `tests/execution.py` for lane selection, parking,
hold, and cancellation; a smoke phase reproducing the reported scenario (two
files analyzing, a query on the first completes while the second still
analyzes, order within a file preserved); `docs/design.md`, `binja/guide.md`,
and `docs/log.md` updated.

## Outcome (2026-09-18)

Implemented the plan with no user-facing contract deviations. One executor
selects file-lane heads in submission order and parks readiness waits;
untargeted requests have their own non-barrier lane. Open retains its loaded
view and captured output across parking, then returns the readiness-time
description. Its snapshot remains available after cancellation. The cap is
still 8, including parked requests, and protocol 3 remains compatible with
the Rust client's use of the queue fields.

Review details resolved: derive lanes from ordered request records to preserve
order when an open acquires its file identity; restart selection when a
concurrent cancellation promotes a head; keep readiness probes and all undo
actions on the existing executor; distinguish parked waits from running work
in human status. Existing bridge condition waits need no protocol changes.

Verified with 18 Binary-Ninja-free execution tests, 10 Rust tests, API-index (5),
framing (5), updates (4), `nix build`, the installed live bridge suite, and the
full default installed smoke suite. The new smoke phase observed native
analysis on a second file while ready-file queries completed in order across
analyzed and Raw views; cancellation, pending guards, and untargeted progress
also passed. The initial smoke display-fixture failure was fixed and the
suite rerun successfully. Optional desktop-mode smoke was not selected because
no desktop display is configured. Repository-wide rustfmt checks still flag
pre-existing formatting outside the changed lines. Details and evidence paths
are in the dated investigation-log entry. Issue left open for user review.

### Review follow-up (2026-09-18)

Review of `2b48822e` clarified that `started` means first executor pickup,
not becoming a lane head. Removed promotion-time timestamps and set `started`
at the first readiness probe. A head waiting for the executor keeps accumulating
queue time; cancellation before pickup keeps execution time null. Parking keeps
the original timestamp, so readiness and later executor waits remain execution
time. The plan, design, and guide now state those semantics.

Adopted the suggested one-second revalidation interval per parked head, using
a monotonic clock. The 100 ms analysis-state polls run off the UI thread; the
first-probe and immediate pre-execution handle checks remain on the UI thread.

Passed 21 execution tests, 10 Rust tests, API-index (5), framing (5), updates
(4), `nix build`, and the full default installed smoke suite. New unit cases
verify pickup timing and cancellation, timestamps across parking, periodic UI
dispatches, and handle revalidation when readiness changes inside the interval.
The live smoke regression still passed with another file in native analysis.
Evidence is in `temp/h8v9cz-review-smoke.log` and the dated investigation-log
entry. Optional desktop smoke was not selected; issue remains open.
