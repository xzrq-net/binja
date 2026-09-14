---
blocked-by: [2nbgtk]
---
# Report available Binary Ninja updates without installing them

User request: “I'm going to forget to upgrade. If there is a convenient opportunity, consider adding a check ... that gets communicated to the model.”

## Work

- Probe cache/network behavior and disabled-auto-installation interaction for `UpdateChannel.updates_available`, `latest_version`, `latest_version_num`, `get_time_since_last_update_check`, and `is_update_installation_pending`.
- Cache installed/latest stable versions, check time, and explicit unknown/error status under state. Surface it at startup/status.
- Keep metadata checks bounded and out of the serialized analysis path. Never call download/install functions or confuse pending installation with release availability.
- If the native metadata path cannot be used without updater side effects, report unknown and document why. This optional notice must not become a second distribution updater.

## Verification

Establish which calls contact the network and leave the immutable installation untouched. Exercise cached available/current/unknown states and offline failure without delaying analysis. Do not invent a newer release to demonstrate output.

The experiment found the auto-update flag true while network update checks were disabled; handle those controls separately. Update the packaged guide to relay useful notices when this feature lands. Update notices do not gate the MVP trials; disabling automatic download/installation remains part of initial session management.

Closed: Cached stable-release notice in cache/updates.json via UpdateChannel[release-personal].latest_version_num on a daemon thread; surfaced by start/status even when GUI RPC is down. 24h success / 1h error reuse, 5s reporting deadline, no download/install calls. See docs/log.md 2026-09-13.
