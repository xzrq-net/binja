---
tier: objective
---
# Rewrite the client in Rust over SOCK_SEQPACKET with a blocking wait

User decisions, 2026-09-13: rewrite the CLI in Rust; use `SOCK_SEQPACKET`
Unix sockets; if tokio, use the single-thread (`current_thread`) executor.

Goal: remove the client-side completion latency floor (`vf2ttr`, 245 ms wall
for 1 ms of work, caused by the CLI's fixed 200 ms first poll) by letting the
client block on a read. The plugin's RPC server is already thread per
connection (`binja/bridge.py`), so the server side can hold the connection:
give `submit` and `request` a `wait` seconds parameter, have the handler wait
on a condition variable that the worker notifies on every terminal transition,
and reply when the record is terminal or the deadline passes. The client puts a
tokio timeout around the read; the existing exit-2 expiry semantics stay.
Raise the per-connection server timeout for waiting handlers only.

Wire size: SEQPACKET messages fail with EMSGSIZE above the socket send buffer,
about 208 KiB at the default `net.core.wmem_default`. `SO_SNDBUF` can be
raised only up to `net.core.wmem_max`, which is host dependent. Do not rely on
it: cap protocol messages at something like 128 KiB, pass large script sources
by path (client and plugin share the filesystem), and keep large results as
artifact files, which is already the design over 16 KiB. Bump the protocol
version; the Python client goes away rather than being kept in step.

Keep the CLI surface and output identical unless a deed says otherwise, so the
trial scripts in `temp/trials/runD/scripts/` remain a valid before/after
benchmark. Package the binary through Nix in place of the Python entry point.
Closes `vf2ttr` when done.

## Implementation handoff

Phase A protocol transition: protocol 3 uses 32 KiB data chunks tagged 0x01 and
a 0x00 end packet; request/response bounds are 4/64 MiB. submit(wait>0) emits
admission before its blocking result; request(wait) blocks on the worker
condition. Exact envelopes are in docs/design.md. No Python client
compatibility work was done. Rust CLI and hidden supervisor,
packaging/devshell, live CLI smoke, and benchmark comparison remain in B.
Baseline harness and raw results are under temp/phase-a/; reuse tight_loop.py
with the same sample for comparison.
