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
- Duplicate IDs return the existing request/result; conflicting reuse fails. Never automatically resubmit after timeout.
- Define queued/running/interrupted states and cancellation honestly. Do not terminate Python threads inside native calls or imply arbitrary scripts roll back.
- Start with the vendor API and standard library; do not build a dependency manager or generalized undo system.

## Verification

Demonstrate live API access, fresh locals, persistent edits, source-line tracebacks, large-output handling, and UI callbacks. Disconnect after submitting a mutation, retrieve its result, and prove the same request ID cannot apply it twice. Inspect status during work and handle restart with incomplete requests.

Exercise readiness both when a request is submitted and after it has waited in the queue. Verify custom Python does not run on incomplete analysis by default and that the explicit override works. Edits inside a script may require additional API waits; document that boundary.

Reference banteg/bn's `python_exec.py` and transport, borrowing useful small pieces rather than the full operation catalog.
