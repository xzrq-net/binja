# Headless Binary Ninja

## Development

Enter the Rust development shell with `nix develop` or `direnv allow`.

```sh
cargo run
cargo test
cargo fmt --check
cargo clippy -- -D warnings
```

Build the package with `nix build`; run its checks with `nix flake check`.
