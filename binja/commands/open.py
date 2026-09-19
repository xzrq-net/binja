"""Load on the worker, then attach the view to the GUI on its main thread."""
import binaryninjaui as ui

existing = on_ui(bridge.targets.refresh)
matches = [target for target in existing if target["path"] == args["path"]]
if matches:
    loaded, target = on_ui(lambda: bridge.targets.resolve(args["path"]))
else:
    loaded = bn.load(args["path"], update_analysis=False)
    if loaded is None:
        raise RuntimeError("Binary Ninja could not load this file with its default loader.")

    def attach():
        context = ui.UIContext.activeContext()
        if context is None:
            raise RuntimeError("No GUI context is available.")
        file_context = ui.FileContext(loaded.file, loaded.file.raw, args["path"])
        frame = context.openFileContext(file_context)
        if frame is None:
            raise RuntimeError("GUI could not attach the loaded file.")
        bridge.targets.refresh()
        return bridge.targets.describe(loaded)

    try:
        target = on_ui(attach)
    except BaseException:
        loaded.file.close()
        raise
    loaded.update_analysis()
bridge.execution.opened(request, loaded, target)
