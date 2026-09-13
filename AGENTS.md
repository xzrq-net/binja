# Headless Binary Ninja

<!-- deeds:begin -->
If present, use the `deeds` tool and skill for task tracking.
<!-- deeds:end -->

## User rules (do not change, advice welcome)

- This is a vibe-coded project. Agents make local commits at task or phase
  boundaries. With colocated jj, finish a completed change with `jj new`.

## Project references (maintained by agents)

- Start with `deeds ready`; use `deeds show ID --tree` for dependencies and
  `deeds list` for follow-ups. Approval checkpoints belong in the relevant issue.
- [README](README.md) covers installation. `binja skill` prints the workflow from
  `binja/guide.md`; keep that single packaged source current with CLI changes.
- [Design](docs/design.md) describes architecture and interface constraints.
  [Investigation log](docs/log.md) holds historical observations and verification
  results. Keep session history and milestone status out of reference docs.
- `tests/smoke.py` checks the installed CLI from a disposable external workspace.
  Scripts under `temp/` are disposable evidence.
