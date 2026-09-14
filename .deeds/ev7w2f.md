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
