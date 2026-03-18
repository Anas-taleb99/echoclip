from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import fcntl
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import gi

from . import __version__
from .clipboard_manager import (
    IMAGE_KIND,
    TEXT_KIND,
    ClipboardItem,
    ClipboardStore,
    DEFAULT_DEBUG_FILE,
    DEFAULT_LOCK_FILE,
    DEFAULT_REQUEST_FILE,
    format_size,
    hash_bytes,
    hash_text,
    item_fingerprint,
    make_item_id,
    preview_item,
    read_request,
    relative_time,
    write_request,
)

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

STATE_DIR = Path.home() / ".local" / "state" / "echoclip"
STORE = ClipboardStore()
POLL_MS = 150
WINDOW_TITLE = "EchoClip"


def debug_log(message: str) -> None:
    try:
        DEFAULT_DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with DEFAULT_DEBUG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def ensure_gtk() -> bool:
    return Gtk.init_check()[0]


def spawn_daemon() -> None:
    launcher = Path(sys.argv[0]).resolve()
    if launcher.exists():
        command = [str(launcher), "daemon"]
    else:
        command = [sys.executable, "-m", "echoclip.app", "daemon"]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def get_clipboard() -> Gtk.Clipboard | None:
    display = Gdk.Display.get_default()
    if display is None:
        return None
    return Gtk.Clipboard.get_for_display(display, Gdk.SELECTION_CLIPBOARD)


def clip_get_text() -> str:
    clipboard = get_clipboard()
    if clipboard is None:
        return ""
    text = clipboard.wait_for_text()
    return text or ""


def clip_clear() -> bool:
    clipboard = get_clipboard()
    if clipboard is None:
        return False
    clipboard.clear()
    clipboard.store()
    return True


def clip_set_text(text: str) -> bool:
    clipboard = get_clipboard()
    if clipboard is None:
        return False
    clipboard.set_text(text, -1)
    clipboard.store()
    return True


def clip_set_image(item: ClipboardItem) -> bool:
    if item.kind != IMAGE_KIND or not item.image_path:
        return False
    clipboard = get_clipboard()
    if clipboard is None:
        return False
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(item.image_path)
    except GLib.Error:
        return False
    clipboard.set_image(pixbuf)
    clipboard.store()
    return True


def clip_set_item(item: ClipboardItem) -> bool:
    if item.kind == IMAGE_KIND:
        return clip_set_image(item)
    return clip_set_text(item.text)


def request_clip_set(item: ClipboardItem | str) -> None:
    write_request(DEFAULT_REQUEST_FILE, item)


def set_clipboard_with_helper(text: str) -> subprocess.CompletedProcess[str]:
    helper = """
import sys
import time
import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk

ok, _ = Gtk.init_check()
if not ok:
    raise SystemExit(1)
display = Gdk.Display.get_default()
if display is None:
    raise SystemExit(2)
clipboard = Gtk.Clipboard.get_for_display(display, Gdk.SELECTION_CLIPBOARD)
clipboard.set_text(sys.argv[1], -1)
clipboard.store()
deadline = time.time() + 0.8
context = GLib.MainContext.default()
while time.time() < deadline:
    while context.pending():
        context.iteration(False)
    time.sleep(0.01)
print(clipboard.wait_for_text() or "")
"""
    return subprocess.run(
        [sys.executable, "-c", helper, text],
        check=False,
        capture_output=True,
        text=True,
    )


def read_clipboard_with_helper() -> subprocess.CompletedProcess[str]:
    helper = """
import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk

ok, _ = Gtk.init_check()
if not ok:
    raise SystemExit(1)
display = Gdk.Display.get_default()
if display is None:
    raise SystemExit(2)
clipboard = Gtk.Clipboard.get_for_display(display, Gdk.SELECTION_CLIPBOARD)
print(clipboard.wait_for_text() or "")
"""
    return subprocess.run(
        [sys.executable, "-c", helper],
        check=False,
        capture_output=True,
        text=True,
    )


def x11_get_focused_window() -> int | None:
    if os.environ.get("WAYLAND_DISPLAY"):
        return None

    libx11_path = ctypes.util.find_library("X11")
    if not libx11_path:
        return None
    libx11 = ctypes.cdll.LoadLibrary(libx11_path)
    libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    libx11.XOpenDisplay.restype = ctypes.c_void_p
    libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    libx11.XGetInputFocus.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
    ]

    display = libx11.XOpenDisplay(None)
    if not display:
        return None
    try:
        focused = ctypes.c_ulong(0)
        revert = ctypes.c_int(0)
        libx11.XGetInputFocus(display, ctypes.byref(focused), ctypes.byref(revert))
        if focused.value in (0, 1):
            return None
        return int(focused.value)
    finally:
        libx11.XCloseDisplay(display)


def paste_active_input(target_window: int | None = None) -> bool:
    if os.environ.get("WAYLAND_DISPLAY"):
        return False

    libx11_path = ctypes.util.find_library("X11")
    libxtst_path = ctypes.util.find_library("Xtst")
    if not libx11_path or not libxtst_path:
        return False

    libx11 = ctypes.cdll.LoadLibrary(libx11_path)
    libxtst = ctypes.cdll.LoadLibrary(libxtst_path)

    libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    libx11.XOpenDisplay.restype = ctypes.c_void_p
    libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    libx11.XStringToKeysym.argtypes = [ctypes.c_char_p]
    libx11.XStringToKeysym.restype = ctypes.c_ulong
    libx11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    libx11.XKeysymToKeycode.restype = ctypes.c_uint
    libx11.XGetInputFocus.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
    ]
    libx11.XSetInputFocus.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_ulong,
    ]
    libx11.XFlush.argtypes = [ctypes.c_void_p]
    libxtst.XTestFakeKeyEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_ulong,
    ]

    display = libx11.XOpenDisplay(None)
    if not display:
        return False
    try:
        ctrl_sym = libx11.XStringToKeysym(b"Control_L")
        v_sym = libx11.XStringToKeysym(b"v")
        ctrl_code = libx11.XKeysymToKeycode(display, ctrl_sym)
        v_code = libx11.XKeysymToKeycode(display, v_sym)
        if not ctrl_code or not v_code:
            return False

        if target_window:
            libx11.XSetInputFocus(display, ctypes.c_ulong(target_window), 2, 0)
            libx11.XFlush(display)
            deadline = time.time() + 0.20
            while time.time() < deadline:
                focused = ctypes.c_ulong(0)
                revert = ctypes.c_int(0)
                libx11.XGetInputFocus(display, ctypes.byref(focused), ctypes.byref(revert))
                if int(focused.value) == int(target_window):
                    break
                time.sleep(0.01)

        time.sleep(0.03)
        libxtst.XTestFakeKeyEvent(display, ctrl_code, 1, 0)
        libxtst.XTestFakeKeyEvent(display, v_code, 1, 0)
        libxtst.XTestFakeKeyEvent(display, v_code, 0, 0)
        libxtst.XTestFakeKeyEvent(display, ctrl_code, 0, 0)
        libx11.XFlush(display)
        return True
    finally:
        libx11.XCloseDisplay(display)


@dataclass(slots=True)
class ClipboardSnapshot:
    item: ClipboardItem
    fingerprint: str
    image_bytes: bytes | None = None


def make_text_item(text: str, copied_at: float | None = None) -> ClipboardItem | None:
    if not text.strip():
        return None
    stamp = time.time() if copied_at is None else float(copied_at)
    return ClipboardItem(
        id=make_item_id(text, stamp),
        kind=TEXT_KIND,
        copied_at=stamp,
        text=text,
        content_hash=hash_text(text),
    )


def pixbuf_to_png_bytes(pixbuf: GdkPixbuf.Pixbuf) -> bytes | None:
    try:
        success, payload = pixbuf.save_to_bufferv("png", [], [])
    except GLib.Error:
        return None
    if not success or not payload:
        return None
    return bytes(payload)


def snapshot_from_text(text: str, copied_at: float | None = None) -> ClipboardSnapshot | None:
    item = make_text_item(text, copied_at=copied_at)
    if item is None:
        return None
    return ClipboardSnapshot(item=item, fingerprint=item_fingerprint(item))


def snapshot_from_pixbuf(
    pixbuf: GdkPixbuf.Pixbuf,
    copied_at: float | None = None,
) -> ClipboardSnapshot | None:
    payload = pixbuf_to_png_bytes(pixbuf)
    if not payload:
        return None
    stamp = time.time() if copied_at is None else float(copied_at)
    content_hash = hash_bytes(payload)
    item = ClipboardItem(
        id=make_item_id(content_hash, stamp),
        kind=IMAGE_KIND,
        copied_at=stamp,
        mime_type="image/png",
        width=pixbuf.get_width(),
        height=pixbuf.get_height(),
        size_bytes=len(payload),
        content_hash=content_hash,
    )
    return ClipboardSnapshot(
        item=item,
        fingerprint=item_fingerprint(item),
        image_bytes=payload,
    )


def read_clipboard_snapshot() -> ClipboardSnapshot | None:
    clipboard = get_clipboard()
    if clipboard is None:
        return None

    if clipboard.wait_is_image_available():
        pixbuf = clipboard.wait_for_image()
        if pixbuf is not None:
            snapshot = snapshot_from_pixbuf(pixbuf)
            if snapshot is not None:
                return snapshot

    text = clipboard.wait_for_text() or ""
    return snapshot_from_text(text)


class ClipboardDaemonController:
    def __init__(
        self,
        store: ClipboardStore,
        read_snapshot=read_clipboard_snapshot,
        apply_item=clip_set_item,
    ) -> None:
        self.store = store
        self.read_snapshot = read_snapshot
        self.apply_item = apply_item
        self.last_fingerprint: str | None = None
        self.last_request_ts = 0.0

    def initialize_session(self) -> None:
        self.store.clear(keep_pinned=False)
        snapshot = self.read_snapshot()
        self.last_fingerprint = snapshot.fingerprint if snapshot is not None else None
        debug_log(f"daemon initialized fingerprint={self.last_fingerprint or 'empty'}")

    def handle_request(self, request: dict | None) -> None:
        if not request:
            return
        ts = request.get("ts")
        item = request.get("item")
        if not isinstance(ts, (int, float)) or not isinstance(item, ClipboardItem):
            return
        if float(ts) <= self.last_request_ts:
            return

        self.last_request_ts = float(ts)
        self.apply_item(item)
        recorded = self.store.record_item(item)
        if recorded is not None:
            self.last_fingerprint = item_fingerprint(recorded)
        else:
            self.last_fingerprint = item_fingerprint(item)
        debug_log(f"daemon applied clipboard request kind={item.kind}")

    def poll_clipboard(self) -> None:
        snapshot = self.read_snapshot()
        if snapshot is None:
            self.last_fingerprint = None
            return
        if snapshot.fingerprint == self.last_fingerprint:
            return

        recorded = self.store.record_item(snapshot.item, image_bytes=snapshot.image_bytes)
        self.last_fingerprint = snapshot.fingerprint if recorded is None else item_fingerprint(recorded)
        if recorded is not None:
            debug_log(f"daemon captured clipboard kind={recorded.kind} id={recorded.id}")

    def tick(self) -> bool:
        self.handle_request(read_request(DEFAULT_REQUEST_FILE))
        self.poll_clipboard()
        return True


class ClipboardPalette(Gtk.Window):
    def __init__(self, store: ClipboardStore, target_window: int | None) -> None:
        super().__init__(title=WINDOW_TITLE)
        self.store = store
        self.target_window = target_window
        self.current_items: list[ClipboardItem] = []

        self.set_default_size(1020, 640)
        self.set_border_width(14)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("key-press-event", self.on_key_press)
        self.connect("focus-out-event", self.on_focus_out)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(root)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        root.pack_start(title_box, False, False, 0)

        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>Clipboard</span>")
        subtitle = Gtk.Label(xalign=0)
        subtitle.set_text("Search, pin, preview, and re-paste clipboard history.")
        subtitle.get_style_context().add_class("dim-label")
        title_box.pack_start(title, False, False, 0)
        title_box.pack_start(subtitle, False, False, 0)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Search clipboard history")
        self.search_entry.connect("search-changed", self.on_search_changed)
        self.search_entry.connect("activate", self.on_search_activate)
        self.search_entry.connect("key-press-event", self.on_search_key_press)
        root.pack_start(self.search_entry, False, False, 0)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        root.pack_start(paned, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self.on_row_selected)
        self.listbox.connect("row-activated", self.on_row_activated)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        list_scroll.add(self.listbox)
        paned.pack1(list_scroll, resize=True, shrink=False)

        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        paned.pack2(preview_box, resize=True, shrink=False)

        self.meta_label = Gtk.Label(xalign=0)
        self.meta_label.set_selectable(True)
        preview_box.pack_start(self.meta_label, False, False, 0)

        self.preview_stack = Gtk.Stack()
        preview_box.pack_start(self.preview_stack, True, True, 0)

        self.preview = Gtk.TextView()
        self.preview.set_editable(False)
        self.preview.set_cursor_visible(False)
        self.preview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.preview.set_monospace(True)
        self.preview_buffer = self.preview.get_buffer()
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        preview_scroll.add(self.preview)
        self.preview_stack.add_named(preview_scroll, "text")

        self.image_preview = Gtk.Image()
        self.image_preview.set_halign(Gtk.Align.START)
        self.image_preview.set_valign(Gtk.Align.START)
        image_scroll = Gtk.ScrolledWindow()
        image_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        image_scroll.add_with_viewport(self.image_preview)
        self.preview_stack.add_named(image_scroll, "image")

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.pack_start(actions, False, False, 0)

        self.paste_button = Gtk.Button(label="Paste")
        self.paste_button.connect("clicked", lambda *_: self.activate_selected(paste=True))
        actions.pack_start(self.paste_button, False, False, 0)

        self.copy_button = Gtk.Button(label="Copy")
        self.copy_button.connect("clicked", lambda *_: self.activate_selected(paste=False))
        actions.pack_start(self.copy_button, False, False, 0)

        self.pin_button = Gtk.Button(label="Pin")
        self.pin_button.connect("clicked", lambda *_: self.toggle_pin_selected())
        actions.pack_start(self.pin_button, False, False, 0)

        self.delete_button = Gtk.Button(label="Delete")
        self.delete_button.connect("clicked", lambda *_: self.delete_selected())
        actions.pack_start(self.delete_button, False, False, 0)

        self.clear_button = Gtk.Button(label="Clear All")
        self.clear_button.connect("clicked", lambda *_: self.clear_history())
        actions.pack_end(self.clear_button, False, False, 0)

        self.refresh()
        self.show_all()
        self.search_entry.grab_focus()

    def on_focus_out(self, *_args) -> bool:
        GLib.idle_add(self.destroy)
        return False

    def refresh(self, selected_item_id: str | None = None) -> None:
        query = self.search_entry.get_text() if hasattr(self, "search_entry") else ""
        self.current_items = self.store.search(query)

        for child in self.listbox.get_children():
            self.listbox.remove(child)

        if not self.current_items:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(xalign=0)
            label.set_margin_top(20)
            label.set_margin_bottom(20)
            label.set_text("No clipboard items match this search.")
            row.add(label)
            row.item_id = None
            self.listbox.add(row)
            self.listbox.show_all()
            self.set_preview(None)
            self.update_action_state()
            return

        for item in self.current_items:
            row = Gtk.ListBoxRow()
            row.item_id = item.id
            container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            container.set_margin_top(8)
            container.set_margin_bottom(8)
            container.set_margin_start(10)
            container.set_margin_end(10)

            title = Gtk.Label(xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_text(preview_item(item, limit=80))

            details = Gtk.Label(xalign=0)
            details.set_ellipsize(Pango.EllipsizeMode.END)
            parts = [relative_time(item.copied_at)]
            if item.kind == IMAGE_KIND and item.width and item.height:
                parts.append(f"{item.width}x{item.height}")
            if item.pinned:
                parts.insert(0, "Pinned")
            details.set_text("  |  ".join(parts))
            details.get_style_context().add_class("dim-label")

            container.pack_start(title, False, False, 0)
            container.pack_start(details, False, False, 0)
            row.add(container)
            self.listbox.add(row)

        self.listbox.show_all()

        selected_row = None
        if selected_item_id:
            for row in self.listbox.get_children():
                if getattr(row, "item_id", None) == selected_item_id:
                    selected_row = row
                    break
        if selected_row is None:
            selected_row = self.listbox.get_row_at_index(0)
        if selected_row is not None:
            self.listbox.select_row(selected_row)
            self.set_preview(self.get_selected_item())
        self.update_action_state()

    def get_selected_item(self) -> ClipboardItem | None:
        row = self.listbox.get_selected_row()
        if row is None:
            return None
        item_id = getattr(row, "item_id", None)
        if item_id is None:
            return None
        return next((item for item in self.current_items if item.id == item_id), None)

    def set_preview(self, item: ClipboardItem | None) -> None:
        if item is None:
            self.meta_label.set_text("")
            self.preview_buffer.set_text("")
            self.image_preview.clear()
            self.preview_stack.set_visible_child_name("text")
            return

        metadata = [relative_time(item.copied_at)]
        if item.kind == IMAGE_KIND:
            if item.width and item.height:
                metadata.append(f"{item.width}x{item.height}")
            if item.mime_type:
                metadata.append(item.mime_type)
            metadata.append(format_size(item.size_bytes))
            self.preview_buffer.set_text("")
            self.image_preview.clear()
            if item.image_path:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(item.image_path)
                except GLib.Error:
                    pixbuf = None
                if pixbuf is not None:
                    self.image_preview.set_from_pixbuf(pixbuf)
            self.preview_stack.set_visible_child_name("image")
        else:
            metadata.append(f"{len(item.text)} chars")
            self.preview_buffer.set_text(item.text)
            self.image_preview.clear()
            self.preview_stack.set_visible_child_name("text")
        if item.pinned:
            metadata.insert(0, "Pinned")
        self.meta_label.set_text("  |  ".join(metadata))
        self.pin_button.set_label("Unpin" if item.pinned else "Pin")

    def update_action_state(self) -> None:
        has_item = self.get_selected_item() is not None
        self.paste_button.set_sensitive(has_item)
        self.copy_button.set_sensitive(has_item)
        self.pin_button.set_sensitive(has_item)
        self.delete_button.set_sensitive(has_item)
        self.clear_button.set_sensitive(bool(self.store.load()))
        if not has_item:
            self.pin_button.set_label("Pin")

    def activate_selected(self, paste: bool) -> None:
        item = self.get_selected_item()
        if item is None:
            return
        request_clip_set(item)
        clip_set_item(item)
        refreshed = self.store.record_item(item)
        debug_log(f"activated {item.id} kind={item.kind} paste={paste}")
        if paste:
            paste_active_input(self.target_window)
        self.destroy()
        if refreshed:
            debug_log(f"promoted {refreshed.id}")

    def toggle_pin_selected(self) -> None:
        item = self.get_selected_item()
        if item is None:
            return
        updated = self.store.toggle_pin(item.id)
        if updated is not None:
            debug_log(f"toggled pin {item.id} -> {updated.pinned}")
            self.refresh(selected_item_id=updated.id)

    def delete_selected(self) -> None:
        item = self.get_selected_item()
        if item is None:
            return
        if self.store.delete(item.id):
            debug_log(f"deleted {item.id}")
            self.refresh()

    def clear_history(self) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Clear clipboard history?",
        )
        dialog.format_secondary_text("Pinned items will stay unless you choose to remove everything.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Clear Unpinned", 1)
        dialog.add_button("Clear Everything", 2)
        response = dialog.run()
        dialog.destroy()
        if response == 1:
            self.store.clear(keep_pinned=True)
        elif response == 2:
            self.store.clear(keep_pinned=False)
        else:
            return
        self.refresh()

    def on_search_changed(self, *_args) -> None:
        self.refresh()

    def on_search_activate(self, *_args) -> None:
        self.activate_selected(paste=True)

    def on_search_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Down:
            row = self.listbox.get_selected_row()
            if row is None:
                row = self.listbox.get_row_at_index(0)
            elif row.get_index() + 1 < len(self.current_items):
                row = self.listbox.get_row_at_index(row.get_index() + 1)
            if row is not None:
                self.listbox.select_row(row)
            return True
        if event.keyval == Gdk.KEY_Up:
            row = self.listbox.get_selected_row()
            if row is None:
                row = self.listbox.get_row_at_index(0)
            elif row.get_index() > 0:
                row = self.listbox.get_row_at_index(row.get_index() - 1)
            if row is not None:
                self.listbox.select_row(row)
            return True
        return False

    def on_row_selected(self, _widget, _row) -> None:
        self.set_preview(self.get_selected_item())
        self.update_action_state()

    def on_row_activated(self, _widget, _row) -> None:
        self.activate_selected(paste=True)

    def on_key_press(self, _widget, event) -> bool:
        state = event.state
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and ctrl:
            self.activate_selected(paste=False)
            return True
        if event.keyval == Gdk.KEY_Delete:
            self.delete_selected()
            return True
        if ctrl and event.keyval == Gdk.KEY_p:
            self.toggle_pin_selected()
            return True
        if ctrl and event.keyval == Gdk.KEY_l:
            self.search_entry.set_text("")
            return True
        return False


def run_show() -> int:
    if not ensure_gtk():
        print("No GUI display available for clipboard manager.", file=sys.stderr)
        return 1
    spawn_daemon()
    target_window = x11_get_focused_window()
    debug_log(f"show target_window={target_window}")
    palette = ClipboardPalette(STORE, target_window)
    palette.present()
    Gtk.main()
    return 0


def run_daemon() -> int:
    if not ensure_gtk():
        return 0

    DEFAULT_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = DEFAULT_LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0

    controller = ClipboardDaemonController(STORE)
    controller.initialize_session()
    GLib.timeout_add(POLL_MS, controller.tick)
    Gtk.main()
    return 0


def read_text_argument(text: str | None) -> str:
    if text is not None:
        return text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def command_copy(args: argparse.Namespace) -> int:
    if not ensure_gtk():
        print("No GUI display available for clipboard access.", file=sys.stderr)
        return 1
    text = read_text_argument(args.text)
    item = make_text_item(text)
    if item is None:
        print("No clipboard text provided.", file=sys.stderr)
        return 1
    request_clip_set(item)
    clip_set_item(item)
    STORE.record_item(item)
    return 0


def command_current(_args: argparse.Namespace) -> int:
    if not ensure_gtk():
        print("No GUI display available for clipboard access.", file=sys.stderr)
        return 1
    snapshot = read_clipboard_snapshot()
    if snapshot is not None and snapshot.item.kind == TEXT_KIND:
        sys.stdout.write(snapshot.item.text)
    return 0


def command_history(args: argparse.Namespace) -> int:
    items = STORE.search(args.query)
    if args.limit:
        items = items[: args.limit]
    if args.json:
        payload = []
        for item in items:
            entry = item.to_dict()
            entry["preview"] = preview_item(item)
            payload.append(entry)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return 0

    for item in items:
        marker = "*" if item.pinned else " "
        print(f"{marker} {item.id}  {relative_time(item.copied_at):>10}  {preview_item(item)}")
    return 0


def command_toggle_pin(args: argparse.Namespace) -> int:
    item = STORE.toggle_pin(args.item_id)
    if item is None:
        print(f"Clipboard item not found: {args.item_id}", file=sys.stderr)
        return 1
    print(f"{item.id} pinned={str(item.pinned).lower()}")
    return 0


def command_delete(args: argparse.Namespace) -> int:
    if not STORE.delete(args.item_id):
        print(f"Clipboard item not found: {args.item_id}", file=sys.stderr)
        return 1
    print(f"deleted {args.item_id}")
    return 0


def command_clear(args: argparse.Namespace) -> int:
    STORE.clear(keep_pinned=args.keep_pinned)
    print("history cleared")
    return 0


def command_smoke_test(_args: argparse.Namespace) -> int:
    if not ensure_gtk():
        print("No GUI display available for clipboard access.", file=sys.stderr)
        return 1

    original_history = STORE.load()
    original_clipboard = read_clipboard_snapshot()
    spawn_daemon()
    prefix = f"echoclip-smoke-{int(time.time())}"
    text_a = f"{prefix}-A"
    text_b = f"{prefix}-B"

    try:
        helper = set_clipboard_with_helper(text_a)
        if helper.returncode != 0:
            print("Smoke test failed: helper process could not write to the clipboard.", file=sys.stderr)
            return 1
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if any(item.kind == TEXT_KIND and item.text == text_a for item in STORE.load()):
                break
            time.sleep(0.05)
        else:
            print("Smoke test failed: daemon did not capture first clipboard item.", file=sys.stderr)
            return 1

        helper = set_clipboard_with_helper(text_b)
        if helper.returncode != 0:
            print("Smoke test failed: helper process could not write the second clipboard item.", file=sys.stderr)
            return 1
        deadline = time.time() + 2.0
        while time.time() < deadline:
            items = STORE.load()
            if items and items[0].kind == TEXT_KIND and items[0].text == text_b:
                break
            time.sleep(0.05)
        else:
            print("Smoke test failed: daemon did not capture the latest clipboard item.", file=sys.stderr)
            return 1

        items = STORE.search(prefix)
        if len(items) < 2:
            print("Smoke test failed: search did not return the expected history.", file=sys.stderr)
            return 1

        pinned = STORE.toggle_pin(items[-1].id)
        if pinned is None or not pinned.pinned:
            print("Smoke test failed: pin toggle did not persist.", file=sys.stderr)
            return 1

        item_a = make_text_item(text_a)
        if item_a is None:
            print("Smoke test failed: could not build clipboard request item.", file=sys.stderr)
            return 1
        request_clip_set(item_a)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            current_result = read_clipboard_with_helper()
            current = current_result.stdout.rstrip("\n") if current_result.returncode == 0 else ""
            latest = STORE.load()
            if current == text_a and latest and latest[0].kind == TEXT_KIND and latest[0].text == text_a:
                break
            time.sleep(0.05)
        else:
            print("Smoke test failed: daemon did not restore the selected clipboard item.", file=sys.stderr)
            return 1

        latest = next((item for item in STORE.search(prefix) if item.kind == TEXT_KIND and item.text == text_b), None)
        if latest is None or not STORE.delete(latest.id):
            print("Smoke test failed: delete did not remove the selected item.", file=sys.stderr)
            return 1

        remaining = STORE.search(prefix)
        if not remaining or remaining[0].kind != TEXT_KIND or remaining[0].text != text_a or not remaining[0].pinned:
            print("Smoke test failed: history order after delete/pin is incorrect.", file=sys.stderr)
            return 1

        current_result = read_clipboard_with_helper()
        current = current_result.stdout.rstrip("\n") if current_result.returncode == 0 else ""
        if current != text_a:
            print("Smoke test failed: clipboard contents were not restored.", file=sys.stderr)
            return 1

        print("Smoke test passed.")
        return 0
    finally:
        STORE.save(original_history)
        if original_clipboard is None:
            clip_clear()
        else:
            clip_set_item(original_clipboard.item)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"EchoClip clipboard manager for Linux ({__version__})"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("show", help="Open the clipboard palette")
    subparsers.add_parser("daemon", help="Run the clipboard watcher daemon")

    copy_parser = subparsers.add_parser("copy", help="Copy text into the clipboard and history")
    copy_parser.add_argument("text", nargs="?", help="Clipboard text. Reads stdin when omitted.")

    subparsers.add_parser("current", help="Print the current clipboard text")

    history_parser = subparsers.add_parser("history", help="Print clipboard history")
    history_parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text")
    history_parser.add_argument("--limit", type=int, default=20, help="Maximum number of items to print")
    history_parser.add_argument("--query", default="", help="Filter items by text")

    pin_parser = subparsers.add_parser("toggle-pin", help="Toggle the pinned state for an item")
    pin_parser.add_argument("item_id", help="Clipboard item id")

    delete_parser = subparsers.add_parser("delete", help="Delete an item from history")
    delete_parser.add_argument("item_id", help="Clipboard item id")

    clear_parser = subparsers.add_parser("clear", help="Clear clipboard history")
    clear_parser.add_argument("--keep-pinned", action="store_true", help="Keep pinned items")

    subparsers.add_parser("smoke-test", help="Run a live clipboard smoke test")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "show"

    if command == "show":
        return run_show()
    if command == "daemon":
        return run_daemon()
    if command == "copy":
        return command_copy(args)
    if command == "current":
        return command_current(args)
    if command == "history":
        return command_history(args)
    if command == "toggle-pin":
        return command_toggle_pin(args)
    if command == "delete":
        return command_delete(args)
    if command == "clear":
        return command_clear(args)
    if command == "smoke-test":
        return command_smoke_test(args)
    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
