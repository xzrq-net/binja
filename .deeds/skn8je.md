---
blocked-by: [tbfe3h]
---
# Add the resident RPC transport and explicit BinaryView targets

Add a small resident plugin using versioned JSON over `<state>/runtime/rpc.sock`. Follow [Targets](../docs/design.md#targets). This task establishes discovery/identity; execution is mpsj67.

## Work

- Publish generation ID, Binja/protocol versions, and documentation locations; add a live readiness handshake to CLI status.
- Enumerate tabs/view frames on the main thread. Expose handles, full paths, view types, and GUI focus.
- Resolve handles or unambiguous paths/names. Infer one eligible analysis view, suppressing redundant Raw views only for inference; require an explicit target otherwise.
- Treat `active` as a deliberate snapshot of focus. Retain accepted views and invalidate handles after close/reopen/restart. Never maintain a shared selected view.
- Reject incompatible clients and duplicate ownership. Do not unconditionally unlink an existing live socket.

## Verification

Use two clients and two copied files. Prove independent targeting, GUI tab-switch independence, duplicate-basename rejection, explicit Raw-view access, stale-handle rejection, and empty-session behavior. Exercise actual GUI integration as well as useful isolated helper tests.

Reference: banteg/bn's `targets.py` in the existing checkout. Inspect its assumptions rather than treating them as guarantees; preserve notices when copying code.
