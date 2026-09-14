# Remove the 200 ms completion-latency floor on small requests

In the stress trial, 100 sequential trivial `py` calls took 25.2 s: median
CLI wall time 245 ms against median worker execution 1 ms. The cause is
`wait_for` in `binja/cli.py`: after the submit acknowledgement it sleeps
200 ms before its first `request` poll, so no request can complete from the
client's view in under about 240 ms including interpreter startup. Per-function
querying, the natural unit for an agent, runs at 4 calls/s serial; the subject
had to batch or spread across shells to get 24 to 33 calls/s.

Fix direction: let the plugin's `request` operation block until completion or a
server-side deadline (condition variable under the existing lock), and have the
client long-poll instead of sleeping. A cheaper stopgap is a short first poll
with backoff (5, 10, 20, 50, 200 ms). Measure the tight loop from
`temp/trials/runD/scripts/` before and after.
