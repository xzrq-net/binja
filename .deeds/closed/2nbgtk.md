---
blocked-by: [zxazzq, 2ggtpn]
---
# Verify the MVP and run initial subagent review and usability trials

Verify the installed interface before adding convenience commands and alternate display modes. Keep `--help` and the packaged guide current with implemented commands.

## Operator checkpoint

The user requested: “Once you have the MVP, I'd like to vibe check the UX before
we proceed with subagent reviews and trials.” The installed MVP and reproducible
smoke checks are complete. The subsequent preliminary documentation review is
tracked in `a7m7vd`; the user explicitly said “don't run subagent tests yet.”
Wait for approval to proceed with review or usability agents. Keep this issue and
r2neck open until those trials and their resulting fixes are complete.

## Work

- Provide a reproducible smoke workflow using copied benign samples and runtime license injection. Use installed commands from outside the repository.
- Verify private-session startup, matching API lookup, two explicit targets, Python query/mutation, analysis readiness, request recovery after disconnect, database save/reopen across a restart, and orderly shutdown. Check unchanged input bytes, stale/ambiguous targets, independent state directories, and placement of writes/sockets.
- [x] Run bounded subagent implementation review focused on ownership, target lifetime, UI/worker scheduling, request recovery, and persistence. Assign specific review scopes.
- Separately run usability agents without repository design context. Use isolated copied samples and state directories. Supply an ordinary task, the sample path, and state/license configuration; let them discover `binja --help`, `binja skill`, and API lookup. Example: inspect a function, annotate it, save a database, then verify the annotation after reopening.
- Record task completion, wrong turns, errors, and manual interventions. Fix blockers and revise help/guide/output from observed friction. File nonblocking findings against the follow-up deeds rather than expanding the MVP command inventory.
- Write actual installation and first-session commands in README. Mark delivered behavior and limitations accurately; desktop/VNC and deferred commands are not implied to work.

## Done when

The smoke workflow passes and a fresh agent completes the basic task through the installed interface. Record review findings and their disposition, remaining usability friction, and exact unverified portions in the investigation log. Review may validly produce no findings; name its coverage. Close `r2neck` when all MVP parts meet their criteria, commit locally, and finalize with `jj new`.

## Status

Usability trials ran on 2026-09-13 with three GPT subjects; all tasks succeeded
through the installed interface. Findings are filed as `r23mma`, `nvafxz`,
`6jqt5a`, `rcxvky`, with queueing observations on `t87ez9`. Still open here:
the bounded subagent implementation review, and the fixes from those findings.
Stress trial ran on 2026-09-13 against the queue change; findings filed as
`vf2ttr`, `9353hf`, `ev7w2f`, `9wkssd`, `8vftez`.

## Implementation handoff

The earlier operator-approval paragraph is historical: trials have run and the
user explicitly authorized the planned bounded adversarial review in phase C.
It is not a new approval checkpoint. Phase A uses focused protocol/plugin
checks; installed CLI smoke is migrated in B, followed by guide recipe
validation and the scoped implementation review in C.

Independent implementation review completed and accepted by the user. All four
findings are fixed: group shutdown waits for ESRCH after escalation/reaping,
direct children receive parent-death SIGKILL, competing starts wait for the
winner's readiness, and pruning orders records by completion. Live smoke covers
concurrent/late starts, resistant descendants, and supervisor SIGKILL; focused
Rust/Python tests cover exited group leaders and out-of-order completion pruning.
Live bridge checks remain green. Findings and dispositions are in the
2026-09-13 log entry. The milestone's review and remediation work is complete.

Closed: Independent review completed; all four findings fixed and covered by live smoke or focused regression checks. Findings, dispositions, and remaining verification limits recorded in docs/log.md.
