---
blocked-by: [zxazzq, 2ggtpn]
---
# Verify the MVP and run initial subagent review and usability trials

This is the first feedback checkpoint, not final acceptance of every feature in [the design](../docs/design.md). The CLI skeleton supplies `--help` and `skill`; maintain that guide alongside implemented commands before this task starts.

## Operator checkpoint

The user requested: “Once you have the MVP, I'd like to vibe check the UX before
we proceed with subagent reviews and trials.” The installed MVP and reproducible
smoke checks are complete. Wait for the operator's UX feedback before spawning
review or usability agents. Keep this issue and r2neck open until those trials
and their resulting fixes are complete.

## Work

- Provide a reproducible smoke workflow using copied benign samples and runtime license injection. Use installed commands from outside the repository.
- Verify private-session startup, matching API lookup, two explicit targets, Python query/mutation, analysis readiness, request recovery after disconnect, database save/reopen across a restart, and orderly shutdown. Check unchanged input bytes, stale/ambiguous targets, independent state directories, and placement of writes/sockets.
- Run bounded subagent implementation review focused on ownership, target lifetime, UI/worker scheduling, request recovery, and persistence. Assign specific review scopes.
- Separately run usability agents without repository design context. Use isolated copied samples and state directories. Supply an ordinary task, the sample path, and state/license configuration; let them discover `binja --help`, `binja skill`, and API lookup. Example: inspect a function, annotate it, save a database, then verify the annotation after reopening.
- Record task completion, wrong turns, errors, and manual interventions. Fix blockers and revise help/guide/output from observed friction. File nonblocking findings against the follow-up deeds rather than expanding the MVP command inventory.
- Write actual installation and first-session commands in README. Mark delivered behavior and limitations accurately; desktop/VNC and deferred commands are not implied to work.

## Done when

The smoke workflow passes and a fresh agent completes the basic task through the installed interface. Record review findings and their disposition, remaining usability friction, and exact unverified portions in the investigation log. Review may validly produce no findings; name its coverage. Close `r2neck` when all MVP parts meet their criteria, commit locally, and finalize with `jj new`.
