# Keep database saving available when request IDs are exhausted

`Execution.submit` refuses every new execution after `MAX_IDS` distinct IDs,
including the scripts behind `save`. Its error says “Save work and restart,” but
at that point the CLI cannot save. The existing smoke check reaches the limit
without a dirty view and misses this recovery failure.

Provide a way to save unsaved analysis before requiring a restart without
breaking the bounded deduplication ledger or allowing expired IDs to re-execute.
Verify the boundary with a dirty target: reach a reduced limit, save successfully,
stop normally, reopen, and recover the edit. Keep guide limits and error advice
consistent with the chosen behavior.
