# Headless Binary Ninja

<!-- deeds:begin -->
If present, use the `deeds` tool and skill for task tracking.
<!-- deeds:end -->

## User rules (do not change, advice welcome)

- This is a vibe-coded project. Agents make local commits at task or phase
  boundaries. With colocated jj, finish a completed change with `jj new`.

## Key inter-session context (maintained by agents)

- [Design](docs/design.md) defines the first CLI/plugin interface. Implementation
  is tracked by milestone `r2neck`; start with `deeds ready` and use
  `deeds show r2neck --tree` for the dependency graph.
- [Investigation log](docs/log.md) records the 6.0 runtime probes and source
  observations. Scripts under `temp/` are disposable evidence, not the product.
