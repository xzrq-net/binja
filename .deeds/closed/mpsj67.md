---
blocked-by: [skn8je]
---
# Execute Python with recoverable request results

Implement [RPC and Python execution](../docs/design.md#rpc-and-python-execution) for custom Python and bundled command scripts.

## Work

- Accept source, a useful filename, separate JSON arguments, target requirements, and a request ID. Do not interpolate arguments into source.
- Supply fresh locals with `bn`, `bv`, `args`, `result`, and a UI-thread helper. Use one execution worker initially, retaining the target and keeping status retrieval responsive.
- Gate target-bound execution on completed analysis when the request runs. Require an explicit per-request incomplete-analysis override, visible in results. Expose analysis waits without blocking diagnostics; a timeout or paused analysis must not silently permit partial execution. Follow [readiness semantics](../docs/design.md#analysis-readiness-and-addresses).
- Capture script stdout/stderr, results, and tracebacks with bounded output/artifacts. Avoid capturing unrelated GUI output; define non-JSON result behavior explicitly.
- Add CLI Python input from file/stdin and request status/result retrieval. Retain results across client disconnects within the GUI lifetime.
- Generate the request ID in the client before submission and make it available before waiting (including machine-readable submission output). A connection lost before acknowledgement leaves an inspectable ID; an unknown request is not proof a mutation ran or did not run. Duplicate IDs return the existing request/result; conflicting reuse fails. Never automatically resubmit after timeout.
- Choose and document finite result/artifact retention. Eviction must not permit an old ID to execute again in the same generation: retain minimal deduplication records and refuse further submissions if that bound is reached. Report expired/unknown/old-generation requests explicitly; no durable cross-restart execution journal is required.
- Define queued/running/completed/failed states and report prior-generation outcomes as unknown/interrupted without claiming rollback. Queued cancellation is sufficient initially; reject unsupported running cancellation explicitly. Do not terminate Python threads inside native calls or imply arbitrary scripts roll back.
- Start with the vendor API and standard library; do not build a dependency manager or generalized undo system.

## Verification

Demonstrate live API access, fresh locals, persistent edits, source-line tracebacks, large-output handling, and UI callbacks. Disconnect after submitting a mutation, retrieve its result, and prove the same request ID cannot apply it twice. Inspect status during work and handle restart with incomplete requests.

Exercise readiness both when a request is submitted and after it has waited in the queue. Verify custom Python does not run on incomplete analysis by default and that the explicit override works. Edits inside a script may require additional API waits; document that boundary.

As soon as execution works, prove targeted Python access and a save/reopen round trip with a small API script before expanding command wrappers. This exposes worker/UI and persistence assumptions early.

Reference banteg/bn's `python_exec.py` and transport, borrowing useful small pieces rather than the full operation catalog.

Closed: Live smoke checks pass for serialized Python, fresh scopes, UI callbacks, readiness after queueing, queued cancellation, bounded output/results, source tracebacks, non-JSON errors, disconnect recovery, exact-ID deduplication, expiry tombstones, and submission cap. Early API save/restart/reopen probe passed.
