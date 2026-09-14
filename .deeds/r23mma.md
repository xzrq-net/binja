# Report a stopped session from status instead of an endpoint error

After `binja stop` succeeds, `binja status` prints
`Session endpoint unavailable: [Errno 2] No such file or directory. Inspect <state>/logs.`
and exits nonzero. Two of three usability subjects called `status` right after a
clean stop to confirm cleanup and read this as a fault; one named it the first
thing to fix. Report "no running session" with the state path (exit 0 or a
distinct code), and reserve the logs pointer for a session that should be
running. The same subjects wanted the `status` headline to count files, not
views: one opened binary shows `2 views` because of the redundant Raw view.
