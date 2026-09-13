# Keep database saving available when request IDs are exhausted

`Execution.submit` refuses every new execution after `MAX_IDS` distinct IDs,
including the scripts behind `save`. Its error says “Save work and restart,” but
at that point the CLI cannot save. The existing smoke check reaches the limit
without a dirty view and misses this recovery failure.

Remove the arbitrary lifetime request cap. Retain fingerprints until restart so
expired IDs cannot re-execute; pending requests and full results remain bounded.
The user questioned why the limit was not effectively unlimited, such as `2**64`.

Verify saving a dirty target with more than 4096 historical IDs, normal shutdown,
and persistence after restart. Keep guide limits consistent with this behavior.

Closed: Removed the lifetime request cap; fingerprints persist until restart. The live suite verified saving beyond 4096 historical IDs, expiry without replay, and persistence across restart.
