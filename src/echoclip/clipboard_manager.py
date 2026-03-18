from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

STATE_DIR = Path.home() / ".local" / "state" / "echoclip"
DEFAULT_HISTORY_FILE = STATE_DIR / "history.json"
DEFAULT_REQUEST_FILE = STATE_DIR / "set_request.json"
DEFAULT_LOCK_FILE = STATE_DIR / "daemon.lock"
DEFAULT_DEBUG_FILE = STATE_DIR / "debug.log"
DEFAULT_IMAGES_DIR = STATE_DIR / "images"

TEXT_KIND = "text"
IMAGE_KIND = "image"
VALID_KINDS = {TEXT_KIND, IMAGE_KIND}


def hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha1(payload).hexdigest()


@dataclass(slots=True)
class ClipboardItem:
    id: str
    kind: str
    copied_at: float
    pinned: bool = False
    text: str = ""
    image_path: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    content_hash: str | None = None

    @classmethod
    def from_dict(cls, payload: dict) -> "ClipboardItem | None":
        if not isinstance(payload, dict):
            return None

        item_id = payload.get("id")
        copied_at = payload.get("copied_at")
        if not isinstance(item_id, str) or not item_id:
            return None
        if not isinstance(copied_at, (int, float)):
            return None

        kind = payload.get("kind", TEXT_KIND)
        if not isinstance(kind, str):
            return None
        kind = kind.lower()
        if kind not in VALID_KINDS:
            return None

        pinned = payload.get("pinned", False)
        if not isinstance(pinned, bool):
            pinned = False

        content_hash = payload.get("content_hash")
        if not isinstance(content_hash, str) or not content_hash:
            content_hash = None

        if kind == TEXT_KIND:
            text = payload.get("text", "")
            if not isinstance(text, str):
                return None
            if content_hash is None and text:
                content_hash = hash_text(text)
            return cls(
                id=item_id,
                kind=TEXT_KIND,
                copied_at=float(copied_at),
                pinned=pinned,
                text=text,
                content_hash=content_hash,
            )

        image_path = payload.get("image_path")
        if not isinstance(image_path, str) or not image_path:
            return None

        mime_type = payload.get("mime_type")
        if not isinstance(mime_type, str) or not mime_type:
            mime_type = "image/png"

        width = payload.get("width")
        if not isinstance(width, int) or width <= 0:
            width = None

        height = payload.get("height")
        if not isinstance(height, int) or height <= 0:
            height = None

        size_bytes = payload.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            size_bytes = None

        return cls(
            id=item_id,
            kind=IMAGE_KIND,
            copied_at=float(copied_at),
            pinned=pinned,
            image_path=image_path,
            mime_type=mime_type,
            width=width,
            height=height,
            size_bytes=size_bytes,
            content_hash=content_hash,
        )

    def to_dict(self, include_internal: bool = False) -> dict:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "copied_at": self.copied_at,
            "pinned": self.pinned,
        }
        if self.kind == TEXT_KIND:
            payload["text"] = self.text
        else:
            payload["image_path"] = self.image_path
            payload["mime_type"] = self.mime_type
            payload["width"] = self.width
            payload["height"] = self.height
            payload["size_bytes"] = self.size_bytes
        if include_internal and self.content_hash:
            payload["content_hash"] = self.content_hash
        return payload

    def has_content(self) -> bool:
        if self.kind == TEXT_KIND:
            return bool(self.text.strip())
        return bool(self.image_path)

    def search_blob(self) -> str:
        if self.kind == TEXT_KIND:
            return self.text
        parts = ["image"]
        if self.mime_type and "/" in self.mime_type:
            parts.append(self.mime_type.split("/", 1)[1])
        elif self.mime_type:
            parts.append(self.mime_type)
        if self.width and self.height:
            parts.append(f"{self.width}x{self.height}")
        return " ".join(parts)


def make_item_id(seed: str, copied_at: float | None = None) -> str:
    stamp = copied_at if copied_at is not None else time.time()
    digest = hashlib.sha1(f"{stamp}:{len(seed)}:{seed}".encode("utf-8")).hexdigest()
    return digest[:16]


def format_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown size"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def preview_text(text: str, limit: int = 90) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "(blank text)"
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def preview_item(item: ClipboardItem, limit: int = 90) -> str:
    if item.kind == TEXT_KIND:
        return preview_text(item.text, limit=limit)
    label = "Image"
    if item.mime_type and "/" in item.mime_type:
        label += f" {item.mime_type.split('/', 1)[1].upper()}"
    elif item.mime_type:
        label += f" {item.mime_type.upper()}"
    if item.width and item.height:
        label += f" {item.width}x{item.height}"
    return label


def item_fingerprint(item: ClipboardItem) -> str:
    if item.content_hash:
        return f"{item.kind}:{item.content_hash}"
    if item.kind == TEXT_KIND:
        return f"{TEXT_KIND}:{hash_text(item.text)}"
    return f"{IMAGE_KIND}:{item.image_path or item.id}"


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
    return [item for item in items if query in item.search_blob().lower()]


class ClipboardStore:
    def __init__(
        self,
        history_file: Path = DEFAULT_HISTORY_FILE,
        images_dir: Path = DEFAULT_IMAGES_DIR,
        max_items: int = 250,
    ) -> None:
        self.history_file = history_file
        self.images_dir = images_dir
        self.max_items = max_items

    def load(self) -> list[ClipboardItem]:
        return self._sorted(self._read_structured_history())

    def save(self, items: list[ClipboardItem]) -> None:
        items = self._trim(self._sorted(items))
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.to_dict(include_internal=True) for item in items]
        self.history_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self._cleanup_images(items)

    def record(self, text: str, copied_at: float | None = None, pinned: bool = False) -> ClipboardItem | None:
        return self.record_text(text, copied_at=copied_at, pinned=pinned)

    def record_text(self, text: str, copied_at: float | None = None, pinned: bool = False) -> ClipboardItem | None:
        if not isinstance(text, str):
            return None
        if not text.strip():
            return None

        items = self.load()
        existing = next((item for item in items if item.kind == TEXT_KIND and item.text == text), None)
        content_hash = hash_text(text)
        item = ClipboardItem(
            id=existing.id if existing else make_item_id(text, copied_at),
            kind=TEXT_KIND,
            copied_at=time.time() if copied_at is None else float(copied_at),
            pinned=pinned or (existing.pinned if existing else False),
            text=text,
            content_hash=content_hash,
        )
        items = [
            entry
            for entry in items
            if not (entry.kind == TEXT_KIND and entry.text == text)
        ]
        items.insert(0, item)
        self.save(items)
        return item

    def record_item(
        self,
        item: ClipboardItem,
        copied_at: float | None = None,
        pinned: bool = False,
        image_bytes: bytes | None = None,
    ) -> ClipboardItem | None:
        if item.kind == TEXT_KIND:
            return self.record_text(item.text, copied_at=copied_at, pinned=pinned or item.pinned)
        if item.kind != IMAGE_KIND:
            return None

        payload = image_bytes
        if payload is None and item.image_path:
            payload = self._read_image_bytes(Path(item.image_path))
        if not payload:
            return None

        content_hash = item.content_hash or hash_bytes(payload)
        items = self.load()
        existing = next(
            (
                entry
                for entry in items
                if entry.kind == IMAGE_KIND and item_fingerprint(entry) == f"{IMAGE_KIND}:{content_hash}"
            ),
            None,
        )
        item_id = existing.id if existing else (item.id or make_item_id(content_hash, copied_at))
        self.images_dir.mkdir(parents=True, exist_ok=True)
        stored_path = self.images_dir / f"{item_id}.png"
        stored_path.write_bytes(payload)
        stored = ClipboardItem(
            id=item_id,
            kind=IMAGE_KIND,
            copied_at=time.time() if copied_at is None else float(copied_at),
            pinned=pinned or (existing.pinned if existing else item.pinned),
            image_path=str(stored_path),
            mime_type=item.mime_type or (existing.mime_type if existing else "image/png") or "image/png",
            width=item.width or (existing.width if existing else None),
            height=item.height or (existing.height if existing else None),
            size_bytes=len(payload),
            content_hash=content_hash,
        )
        items = [
            entry
            for entry in items
            if not (
                entry.kind == IMAGE_KIND
                and item_fingerprint(entry) == f"{IMAGE_KIND}:{content_hash}"
            )
        ]
        items.insert(0, stored)
        self.save(items)
        return stored

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

    def _read_structured_history(self) -> list[ClipboardItem]:
        if not self.history_file.exists():
            return []
        try:
            payload = json.loads(self.history_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []

        items: list[ClipboardItem] = []
        for entry in payload:
            item = ClipboardItem.from_dict(entry)
            if item is None or not item.has_content():
                continue
            items.append(self._normalize_item(item))
        return items

    def _normalize_item(self, item: ClipboardItem) -> ClipboardItem:
        if item.kind == TEXT_KIND:
            if not item.content_hash:
                item.content_hash = hash_text(item.text)
            return item

        image_path = Path(item.image_path) if item.image_path else None
        if image_path and item.size_bytes is None and image_path.exists():
            try:
                item.size_bytes = image_path.stat().st_size
            except OSError:
                item.size_bytes = None
        if image_path and not item.content_hash:
            image_bytes = self._read_image_bytes(image_path)
            if image_bytes:
                item.content_hash = hash_bytes(image_bytes)
        return item

    def _sorted(self, items: list[ClipboardItem]) -> list[ClipboardItem]:
        return sorted(items, key=lambda item: (0 if item.pinned else 1, -item.copied_at))

    def _trim(self, items: list[ClipboardItem]) -> list[ClipboardItem]:
        pinned = [item for item in items if item.pinned]
        unpinned = [item for item in items if not item.pinned]
        room = max(0, self.max_items - len(pinned))
        return pinned + unpinned[:room]

    def _cleanup_images(self, items: list[ClipboardItem]) -> None:
        if not self.images_dir.exists():
            return

        keep = {
            str(Path(item.image_path))
            for item in items
            if item.kind == IMAGE_KIND and item.image_path
        }
        for path in self.images_dir.glob("*.png"):
            if str(path) in keep:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    def _read_image_bytes(self, image_path: Path) -> bytes | None:
        try:
            return image_path.read_bytes()
        except OSError:
            return None


def write_request(request_file: Path, item: ClipboardItem | str) -> None:
    request_file.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"ts": time.time()}
    if isinstance(item, ClipboardItem):
        payload["item"] = item.to_dict(include_internal=True)
    else:
        payload["text"] = str(item)
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
    if not isinstance(ts, (int, float)):
        return None

    item_payload = payload.get("item")
    item = ClipboardItem.from_dict(item_payload) if isinstance(item_payload, dict) else None
    if item is None:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        item = ClipboardItem(
            id=make_item_id(text, ts),
            kind=TEXT_KIND,
            copied_at=float(ts),
            text=text,
            content_hash=hash_text(text),
        )
    return {"ts": float(ts), "item": item}
