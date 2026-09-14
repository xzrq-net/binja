"""Undo the latest native entry, which can include edits from the GUI."""
from binja.editing import edit_result

entries = bv.file.undo_entries
summary = "\n".join(action.summary_text for action in entries[-1].actions) if entries else None
if entries:
    bv.undo()
bv.update_analysis_and_wait()
remaining = len(bv.file.undo_entries)
result = edit_result(request, remaining < len(entries), summary=summary, remaining=remaining)
print(summary if summary is not None else "No native undo entry.")
