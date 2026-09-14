---
tier: nit
---
# Decide backpressure for bursts above the pending cap

With one 12 s script running, a 32-shell burst had 7 accepted and 25 rejected
in 88 ms; the subject then bounded its own client count and retried. The
rejection is explicit and safe, so this is a policy question, not a bug: a
wait-for-capacity submission mode, a larger cap, or leaving retry to the
client. Also observed: a `--no-target` read waits behind unrelated CPU-bound
work, so short reads cannot overtake long scripts. Revisit when a real
workload, not a synthetic burst, hits the cap.
