from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "echoclip"
DEFAULT_HISTORY_FILE = STATE_DIR / "history.json"
DEFAULT_REQUEST_FILE = STATE_DIR / "set_request.json"
DEFAULT_LOCK_FILE = STATE_DIR / "daemon.lock"
DEFAULT_DEBUG_FILE = STATE_DIR / "debug.log"
LEGACY_HISTORY_FILE = Path.home() / ".local" / "state" / "winv_clipboard_history.json"


@dataclass(slots=True)
class ClipboardItem:
    id: str
    text: str
    copied_at: float
    pinned: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> "ClipboardItem | None":
        if not isinstance(payload, dict):
            return None
        item_id = payload.get("id")
        text = payload.get("text")
        copied_at = payload.get("copied_at")
        pinned = payload.get("pinned", False)
        if not isinstance(item_id, str) or not item_id:
            return None
        if not isinstance(text, str):
            return None
        if not isinstance(copied_at, (int, float)):
            return None
        if not isinstance(pinned, bool):
            pinned = False
        return cls(id=item_id, text=text, copied_at=float(copied_at), pinned=pinned)

    def to_dict(self) -> dict:
        return asdict(self)


def make_item_id(text: str, copied_at: float | None = None) -> str:
    stamp = copied_at if copied_at is not None else time.time()
    digest = hashlib.sha1(f"{stamp}:{len(text)}:{text}".encode("utf-8")).hexdigest()
    return digest[:16]


def preview_text(text: str, limit: int = 90) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "(blank text)"
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def relative_time(timestamp: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    delta = max(0, int(now - timestamp))
    if delta < 5:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 604800:
        return f"{delta // 86400}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def search_items(items: list[ClipboardItem], query: str) -> list[ClipboardItem]:
    query = query.strip().lower()
    if not query:
        return list(items)
    return [item for item in items if query in item.text.lower()]


class ClipboardStore:
    def __init__(
        self,
        history_file: Path = DEFAULT_HISTORY_FILE,
        legacy_history_file: Path = LEGACY_HISTORY_FILE,
        max_items: int = 250,
    ) -> None:
        self.history_file = history_file
        self.legacy_history_file = legacy_history_file
        self.max_items = max_items

    def load(self) -> list[ClipboardItem]:
        items = self._read_structured_history()
        if items is None:
            items = self._load_legacy_history()
            if items:
                self.save(items)
        return self._sorted(items)

    def save(self, items: list[ClipboardItem]) -> None:
        items = self._trim(self._sorted(items))
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.to_dict() for item in items]
        self.history_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def record(self, text: str, copied_at: float | None = None, pinned: bool = False) -> ClipboardItem | None:
        if not isinstance(text, str):
            return None
        if not text.strip():
            return None

        items = self.load()
        existing = next((item for item in items if item.text == text), None)
        item = ClipboardItem(
            id=existing.id if existing else make_item_id(text, copied_at),
            text=text,
            copied_at=time.time() if copied_at is None else float(copied_at),
            pinned=pinned or (existing.pinned if existing else False),
        )
        items = [entry for entry in items if entry.text != text]
        items.insert(0, item)
        self.save(items)
        return item

    def delete(self, item_id: str) -> bool:
        items = self.load()
        filtered = [item for item in items if item.id != item_id]
        if len(filtered) == len(items):
            return False
        self.save(filtered)
        return True

    def clear(self, keep_pinned: bool = False) -> None:
        items = self.load()
        if keep_pinned:
            items = [item for item in items if item.pinned]
        else:
            items = []
        self.save(items)

    def set_pinned(self, item_id: str, pinned: bool) -> ClipboardItem | None:
        items = self.load()
        updated = None
        for item in items:
            if item.id == item_id:
                item.pinned = pinned
                updated = item
                break
        if updated is None:
            return None
        self.save(items)
        return updated

    def toggle_pin(self, item_id: str) -> ClipboardItem | None:
        items = self.load()
        updated = None
        for item in items:
            if item.id == item_id:
                item.pinned = not item.pinned
                updated = item
                break
        if updated is None:
            return None
        self.save(items)
        return updated

    def find(self, item_id: str) -> ClipboardItem | None:
        return next((item for item in self.load() if item.id == item_id), None)

    def search(self, query: str) -> list[ClipboardItem]:
        return search_items(self.load(), query)

    def _read_structured_history(self) -> list[ClipboardItem] | None:
        if not self.history_file.exists():
            return None
        try:
            payload = json.loads(self.history_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        items: list[ClipboardItem] = []
        for entry in payload:
            item = ClipboardItem.from_dict(entry)
            if item is not None and item.text.strip():
                items.append(item)
        return items

    def _load_legacy_history(self) -> list[ClipboardItem]:
        if not self.legacy_history_file.exists():
            return []
        try:
            payload = json.loads(self.legacy_history_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        now = time.time()
        items: list[ClipboardItem] = []
        for index, text in enumerate(payload):
            if not isinstance(text, str) or not text.strip():
                continue
            copied_at = now - index
            items.append(
                ClipboardItem(
                    id=make_item_id(text, copied_at),
                    text=text,
                    copied_at=copied_at,
                    pinned=False,
                )
            )
        return items

    def _sorted(self, items: list[ClipboardItem]) -> list[ClipboardItem]:
        return sorted(items, key=lambda item: (0 if item.pinned else 1, -item.copied_at))

    def _trim(self, items: list[ClipboardItem]) -> list[ClipboardItem]:
        pinned = [item for item in items if item.pinned]
        unpinned = [item for item in items if not item.pinned]
        room = max(0, self.max_items - len(pinned))
        return pinned + unpinned[:room]


def write_request(request_file: Path, text: str) -> None:
    request_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": time.time(), "text": text}
    request_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_request(request_file: Path) -> dict | None:
    if not request_file.exists():
        return None
    try:
        payload = json.loads(request_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    ts = payload.get("ts")
    text = payload.get("text")
    if not isinstance(ts, (int, float)) or not isinstance(text, str):
        return None
    return {"ts": float(ts), "text": text}
