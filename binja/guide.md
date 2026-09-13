# binja

Controls a managed Binary Ninja Personal GUI through a private Wayland session.
The Python API and documentation match the packaged 6.0.10601 distribution.

Select a workspace session explicitly:

```sh
export BINJA_STATE_DIR="$PWD/.binja"
binja start                         # ~/.binaryninja/license.dat by default
binja status
binja targets
binja api search 'call site'
binja api show BinaryView.get_functions_containing
binja api paths
```

`api search` and `api show` read matching Python declarations and docstrings;
`api paths` points to the bundled Sphinx documentation and source. They work
without a state directory, license, or GUI. Static lookup cannot enumerate
inherited members or introspect native UI extension classes.

Python execution and file operations are under implementation. For this initial
empty-session launcher, `binja stop --force` explicitly discards session state.
