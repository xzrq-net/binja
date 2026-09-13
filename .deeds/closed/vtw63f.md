---
tier: objective
---
# Simplify request bookkeeping: drop fingerprints, expiry, and the ID ledger

The user asked for a second opinion on the request system in `binja/execution.py`
and decided to simplify it before deciding queue semantics (`t87ez9`).

## Findings behind the change

Binary Ninja locks per API call and offers no isolation above that: no
transactions, interleaved undo actions, and `create_database` warns against
holding locks across its main-thread work. A script is the unit of agent intent,
so one serial worker per session is the right scale; parallel work belongs in
separate state directories. Within that model the following bookkeeping carries
no guarantee that a plain record dictionary does not already carry:

- Content fingerprints (SHA-256 of every spec, kept forever) and the
  "same ID, different content" refusal. Same ID returns the existing record.
- The "expired" status and the separate ID ledger. They existed so an evicted ID
  could not re-execute; the earlier 4096-entry cap on that ledger blocked `save`.

## Change

- Keep terminal record metadata for the GUI lifetime: id, status, target,
  timestamps, truncated error. Prune only artifact directories and inline output
  beyond the retained window. Replay protection then needs no second structure.
- Remove `fingerprints`, `expired`, and content matching from submit/get, the
  CLI's status handling, the guide, the design doc, and the smoke test.
- Leave the single worker, pre-emitted request IDs, `request ID --wait`,
  cancel, the pending cap, and shutdown refusal alone. Queue depth is `t87ez9`.

## Done when

`nix build`, Python compilation, and `tests/smoke.py` pass against a live
session; the guide and design describe the reduced model without the removed
concepts.

Closed: Request records retain session metadata and mark pruned outputs with output_pruned. Duplicate IDs return the existing record; the serial worker and pending cap are unchanged. nix build, Python compilation, and the installed live smoke suite passed, including 4096 historical records.
