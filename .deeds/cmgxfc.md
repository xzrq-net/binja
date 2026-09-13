# Package the Personal distribution as an immutable Nix runtime

Package the paid distribution before implementing process control. Follow [Distribution and upgrades](../docs/design.md#distribution-and-upgrades).

## Work

- Use `requireFile` for `binaryninja_linux_6.0.10601_personal.zip`, flat hash `sha256-OOuY5Pw6I5iL3CrDDEPDj2UysjD2ZlADAw7L+SGVRMc=`.
- The initial file is `~/temp/binaryninja_linux_6.0.10601_personal.zip`. Document the exact store-import command and missing-file error; do not encode this home path as the derivation source.
- Start with an immutable vendor tree plus `buildFHSEnv`. Preserve modes/symlinks and bundled Python/Qt; declare libcurl and remaining libraries. Give the low-level launcher a name distinct from the future `binja` CLI and remove working-directory dependence.
- Expose bundled API docs/source. Additional public API source should match `stable/6.0.10601` (`2ddf304b3275aa184e95570404539cbc4beb64c6`).
- Establish the Python CLI development/package skeleton; replace unused Rust scaffold as appropriate. Keep licenses/credentials outside the store and paid artifacts out of public caches.

## Verification and references

Build from the supplied ZIP; check interpreter/library resolution and missing-file guidance without disturbing the user's archive. The session task performs the live GUI smoke test. No ambient user-site packages or runtime dependency on `~/src`.

Inspect the current nixpkgs `binaryninja-free` package, and [the experiment](../docs/log.md). The old FHS runner worked after adding libcurl; the separate CLI must not import Binja.
