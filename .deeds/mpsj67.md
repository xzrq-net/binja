---
blocked-by: [skn8je]
---
# Execute Python with recoverable request results

Implement [RPC and Python execution](../docs/design.md#rpc-and-python-execution) for custom Python and bundled command scripts.

## Work

- Accept source, a useful filename, separate JSON arguments, target requirements, and a request ID. Do not interpolate arguments into source.
- Supply fresh locals with `bn`, `bv`, `args`, `result`, and a UI-thread helper. Use one execution worker initially, retaining the target and keeping status retrieval responsive.
- Capture script stdout/stderr, results, and tracebacks with bounded output/artifacts. Avoid capturing unrelated GUI output; define non-JSON result behavior explicitly.
- Add CLI Python input from file/stdin and request status/result retrieval. Retain results across client disconnects within the GUI lifetime.
- Duplicate IDs return the existing request/result; conflicting reuse fails. Never automatically resubmit after timeout.
- Define queued/running/interrupted states and cancellation honestly. Do not terminate Python threads inside native calls or imply arbitrary scripts roll back.

## Verification

Demonstrate live API access, fresh locals, persistent edits, source-line tracebacks, large-output handling, and UI callbacks. Disconnect after submitting a mutation, retrieve its result, and prove the same request ID cannot apply it twice. Inspect status during work and handle restart with incomplete requests.

Reference banteg/bn's `python_exec.py` and transport, borrowing useful small pieces rather than the full operation catalog.
