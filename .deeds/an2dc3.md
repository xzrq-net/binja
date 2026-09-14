---
blocked-by: [2nbgtk]
---
# Complete desktop Wayland and optional visual access

Extend the verified private-session lifecycle to desktop Wayland and optional human viewing/input. Follow [Display modes](../docs/design.md#display-modes).

- Capture the supplied desktop Wayland socket before redirecting XDG runtime state; account for container access. Select native Qt Wayland explicitly, with no silent X11 fallback.
- Verify the same analysis/save interface in desktop mode. Display choice remains a startup property; attaching to unmanaged GUIs or moving a live process between compositors is outside scope.
- Add optional wayvnc under the private state directory, with owned startup/cleanup and a Unix socket. Verify viewing/input; screenshot and input CLI work belongs to `scpm34`.
- Document actual commands and mode limitations. If desktop socket access is unavailable, record the exact missing validation rather than claiming a passing test.

Avoid fixed socket paths or working-directory assumptions. Check state isolation and cleanup for both display modes.

Progress 2026-09-14: headless wayvnc (always on, `runtime/vnc.sock`) and
`start --display desktop` are implemented, documented, and headless-verified;
see the log entry of that date. Remaining validation: run
`python3 tests/smoke.py --binja ./result/bin/binja --sample temp/samples/a/sample --desktop`
on a host Wayland session (it opens the GUI on the ambient display), then close.
