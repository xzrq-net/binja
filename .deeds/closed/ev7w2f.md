# Make requests --all a usable forensic export

The stress subject dumped `requests --all --json` before stopping, as asked,
and found it could not explain its own run: rows carry only id, status, phase,
timestamps, elapsed, and target snapshot. No error text, no `output_pruned`
flag, no request kind (py/open/save) or script filename, and rejected
submissions leave no trace. Add the truncated error and the pruned flag to
listing rows, a kind/filename field, and consider a counter or ring of
rejected-at-cap events. Also report queue wait and execution time as separate
fields; `elapsed_seconds` changes meaning by phase and the subject had to
recompute `started - submitted` to quantify queueing.

## Implementation handoff

Phase A: requests returns an envelope with requests, finished_total,
finished_shown, rejected_total, and a 64-event cap-rejection ring (oldest
first). Rows include kind/filename, error, output_pruned, queue_wait_seconds,
and execution_seconds (worker occupancy including readiness; null before
pickup). Rejected attempts remain outside accepted records. Live checks cover
cap rejection and a history export above 128 KiB. Rust rendering/JSON and smoke
migration remain in B.

Closed: Rust renders the forensic envelope, explicit queue/worker timings, errors, pruning, kind/filename, totals, and separate cap-rejection history. Default human output summarizes rejections; --all prints retained events. Full JSON export above 4096 rows passes live.
