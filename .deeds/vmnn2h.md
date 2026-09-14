# Add per-view close

`close HANDLE|PATH [--force]`: close one view through the managed interface.
Only whole-session `stop` exists today, so a long session cannot retire a
target.

Must coordinate: refuse while requests for that target are queued or running
(or cancel queued ones explicitly); refuse unsaved changes without `--force`;
invalidate the handle so retained-target requests fail with a clear message
instead of touching a dead view; close the file's other views (redundant Raw)
with it; keep `targets` and `status` counts consistent. Close on the UI thread
the same way `open` attaches. A bare `bv.file.close()` from `py` does none of
this; document that.

Verify: close with pending work refused; close with unsaved edits refused, then
forced; handle reuse after close rejected; clean `stop` afterwards. Extend
tests/smoke.py.
