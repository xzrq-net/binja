"""GUI enumeration and dispatch adapted from banteg/bn; see licenses/banteg-bn.txt."""
import ctypes
from pathlib import Path

import binaryninja as bn
import binaryninjaui as ui
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .common import Error


def on_ui(function):
    if bn.mainthread.is_main_thread():
        return function()
    holder = {}

    def invoke():
        try:
            holder["value"] = function()
        except BaseException as exc:
            holder["error"] = exc

    bn.execute_on_main_thread_and_wait(invoke)
    if "error" in holder:
        raise holder["error"]
    return holder.get("value")


def key(bv):
    return (bv.file.session_id, bv.view_type, ctypes.cast(bv.handle, ctypes.c_void_p).value)


class Targets:
    """All registry access occurs on the UI thread. Handles never get reused."""
    def __init__(self, generation):
        self.generation = generation
        self.views = {}
        self.handles = {}
        self.next_id = 0
        self.saves = {}

    def refresh(self):
        views = {}
        contexts = list(ui.UIContext.allContexts())
        context = ui.UIContext.activeContext()
        frame = context.getCurrentViewFrame() if context else None
        focused = frame.getCurrentBinaryView() if frame else None
        for context in contexts:
            for tab in context.getTabs():
                for frame in context.getAllViewFramesForTab(tab):
                    bv = frame.getCurrentBinaryView()
                    if bv is not None:
                        views[key(bv)] = bv
        # FileContexts can outlive their tabs until Qt processes deferred deletes
        # (or a queued request releases its view). They are no longer live targets.
        attached = {k[0] for k in views}
        for file_context in ui.FileContext.getOpenFileContexts():
            if file_context.getMetadata().session_id in attached:
                for bv in file_context.getAllDataViews():
                    views[key(bv)] = bv
        self.handles = {k: h for k, h in self.handles.items() if k in views}
        for k in views:
            if k not in self.handles:
                self.next_id += 1
                self.handles[k] = f"{self.generation}:v{self.next_id}"
        self.views = views
        focused_key = key(focused) if focused is not None else None
        return [self.describe(bv, active=k == focused_key) for k, bv in views.items()]

    def describe(self, bv, active=False):
        return {
            "handle": self.handles[key(bv)], "path": str(Path(bv.file.filename).resolve()),
            "view_type": bv.view_type, "active": active, "file_id": bv.file.session_id,
            "analysis": bv.analysis_state.name, "modified": bv.file.modified,
            "analysis_changed": bv.file.analysis_changed,
            "last_save": self.saves.get(bv.file.session_id),
        }

    def resolve(self, selector):
        targets = self.refresh()
        if selector and ":v" in selector:
            matches = [t for t in targets if t["handle"] == selector]
        elif selector == "active":
            matches = [t for t in targets if t["active"]]
        else:
            matches = targets if not selector else [t for t in targets if selector in (t["path"], Path(t["path"]).name)]
            analyzed = {t["file_id"] for t in matches if t["view_type"] != "Raw"}
            matches = [t for t in matches if t["view_type"] != "Raw" or t["file_id"] not in analyzed]
        if len(matches) != 1:
            if not matches:
                if selector and ":v" in selector:
                    raise Error(f"Target handle expired or unknown: {selector}. "
                        "Run binja targets and use a live handle, or reopen the file.")
                raise Error(f"No live target matches {selector!r}; run binja targets (handles expire on close/restart).")
            choices = ", ".join(f"{t['handle']} {t['path']} ({t['view_type']})" for t in matches)
            raise Error(f"Target is ambiguous; use a live handle from binja targets. Choices: {choices}")
        target = matches[0]
        bv = next(bv for k, bv in self.views.items() if self.handles[k] == target["handle"])
        return bv, target

    def close(self, target, force):
        if QApplication.activeModalWidget() is not None:
            raise Error("GUI modal is open; use binja screenshot and binja input to dismiss it before closing.")
        related = [t for t in self.refresh() if t["file_id"] == target["file_id"]]
        dirty = any(t["modified"] or t["analysis_changed"] for t in related)
        if dirty and not force:
            raise Error(f"Unsaved analysis: {target['path']}. Save to a BNDB, "
                "or use close HANDLE|PATH --force to discard it.")
        tabs = []
        for context in ui.UIContext.allContexts():
            for tab in context.getTabs():
                frames = context.getAllViewFramesForTab(tab)
                views = [f.getCurrentBinaryView() for f in frames]
                if any(bv is not None and bv.file.session_id == target["file_id"] for bv in views):
                    tabs.append((context, tab))
        if not tabs:
            raise Error("Target handle expired; run binja targets or reopen the file.")

        # closeTab has no force argument. Answer only its native modified-file
        # prompts, during this call, after the managed unsaved/pending guards.
        timer = QTimer()
        def discard_prompt():
            dialog = QApplication.activeModalWidget()
            if (isinstance(dialog, QMessageBox)
                    and dialog.windowTitle().casefold() in ("analysis modified", "file modified")):
                button = dialog.button(QMessageBox.StandardButton.Discard)
                if button is not None:
                    button.click()
        timer.timeout.connect(discard_prompt)
        if force:
            timer.start(10)
        try:
            for context, tab in tabs:
                context.closeTab(tab)
        finally:
            timer.stop()
        remaining = self.refresh()
        if any(t["file_id"] == target["file_id"] for t in remaining):
            raise Error("GUI did not close every view; inspect binja targets and binja status before retrying.")
        self.saves.pop(target["file_id"], None)
        return dict(path=target["path"], handles=[t["handle"] for t in related], discarded=dirty)
