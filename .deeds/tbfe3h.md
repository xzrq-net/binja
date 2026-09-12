---
blocked-by: [cmgxfc]
---
# Manage workspace state and desktop or private Wayland sessions

Implement [State and session lifecycle](../docs/design.md#state-and-session-lifecycle) and [Display modes](../docs/design.md#display-modes).

## Work

- Resolve `--state-dir` before `BINJA_STATE_DIR`; normalize paths and fail helpfully when neither is set.
- Create private Binja/XDG/temp/log/artifact directories and inject the license at runtime. The existing dotfile may be the license default. Suppress onboarding, manage plugin loading, and prevent self-installing updates.
- Add initial start/status and explicit forced cleanup, exclusive state ownership, generation metadata, logs, and failed-start cleanup. Verify ownership before reuse or termination. Database-aware graceful stop is completed in zxazzq.
- Force a new GUI process. Desktop mode captures the supplied Wayland socket before redirecting XDG runtime state; private mode starts labwc. Both set `QT_QPA_PLATFORM=wayland`.
- Borrow optional wayvnc plumbing, with its Unix socket under state. The bridge later supplies RPC readiness; the final workflow task exercises viewing/input.

## Verification

Launch packaged Personal and confirm version/bundled Python. Test failed-start cleanup, duplicate ownership, and independent state directories. Check application/Qt writes land in state and the installation remains unchanged. Exercise desktop startup if possible; otherwise record the missing validation. No silent X11 fallback.

Avoid fixed VNC sockets and relative installation assumptions. Keep smoke inputs disposable and forced cleanup distinct from saving work.
