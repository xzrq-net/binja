# Recognize cap-rejected IDs in request retrieval instead of the generic unknown-ID warning

Observed 2026-09-13 by a cold trial subject (GPT) during the guide compression
review, Binary Ninja 6.0.10601: after the worker cap rejected a `py --no-wait`
submission with an explicit "not accepted and will not execute" message,
`binja request <that ID>` answered with the generic warning: "Unknown request
ID; this is not proof that a submitted mutation ran or did not run. Do not
blindly resubmit." The subject found this contradictory. `requests` does count
the rejection and `--all` lists it, and resubmitting the same ID later ran it.

Suggested fix: when `request ID` misses the record store but the ID matches a
recorded rejection, say so ("rejected at capacity, never executed; safe to
resubmit") instead of the unknown-ID warning. The guide now states that
rejections are listed by `requests` but have no record for `request`; update
that sentence if the tool changes.
