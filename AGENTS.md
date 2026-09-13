# Headless Binary Ninja

<!-- deeds:begin -->
If present, use the `deeds` tool and skill for task tracking.
<!-- deeds:end -->

## User rules (do not change, advice welcome)

- This is a vibe-coded project. Agents make local commits at task or phase
  boundaries. With colocated jj, finish a completed change with `jj new`.

## Key inter-session context (maintained by agents)

- [Design](docs/design.md) defines the intended CLI/plugin interface. Milestone
  `r2neck` gates a usable MVP and initial subagent trials; convenience commands
  and display extras follow those trials. Start with `deeds ready`, use
  `deeds show r2neck --tree` for the MVP graph, and `deeds list` for follow-ups.
- [Investigation log](docs/log.md) records the 6.0 runtime probes and source
  observations. Scripts under `temp/` are disposable evidence, not the product.
