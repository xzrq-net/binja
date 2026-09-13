"""Deliberately save a database; never write the original executable."""
from pathlib import Path
import time

destination = Path(args["path"])
if destination.suffix.lower() != ".bndb":
    raise ValueError("Database destination must end in .bndb.")
if destination.is_relative_to(bridge.state):
    raise ValueError("Save databases outside the managed state directory.")
for target in on_ui(bridge.targets.refresh):
    if target["path"] == str(destination) and target["file_id"] != bv.file.session_id:
        raise ValueError("Destination is open as another target; choose a different path.")
current_database = bv.file.has_database and Path(bv.file.filename).resolve() == destination
if destination.exists() and not current_database:
    raise FileExistsError("Destination already exists; choose a new path, or open that database to update it.")
if not destination.parent.is_dir():
    raise FileNotFoundError("Destination parent directory does not exist.")
request["phase"] = "saving_database"
success = bv.save_auto_snapshot() if current_database else bv.create_database(str(destination))
if not success:
    raise RuntimeError("Binary Ninja reported database save failure; no successful save recorded.")
saved = {"path": str(destination), "time": time.time()}

def record_save():
    bridge.targets.saves[bv.file.session_id] = saved
    # Keep the GUI's own filename/save destination in sync with its FileMetadata.
    import binaryninjaui as ui
    for context in ui.FileContext.getOpenFileContexts():
        if context.getMetadata().session_id == bv.file.session_id:
            context.markAsSaved(str(destination))
    return bridge.targets.describe(bv)

result = {"saved": saved, "target": on_ui(record_save)}
