from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from echoclip.clipboard_manager import (
    ClipboardItem,
    ClipboardStore,
    preview_text,
    read_request,
    relative_time,
    search_items,
    write_request,
)


class ClipboardStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.history_file = root / "history.json"
        self.legacy_file = root / "legacy.json"
        self.request_file = root / "request.json"
        self.store = ClipboardStore(
            history_file=self.history_file,
            legacy_history_file=self.legacy_file,
            max_items=3,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_record_deduplicates_and_keeps_pin(self) -> None:
        first = self.store.record("alpha")
        self.assertIsNotNone(first)
        self.store.toggle_pin(first.id)
        updated = self.store.record("alpha", copied_at=200.0)
        items = self.store.load()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].text, "alpha")
        self.assertTrue(items[0].pinned)
        self.assertEqual(updated.id, first.id)

    def test_trim_keeps_pinned_items(self) -> None:
        first = self.store.record("one", copied_at=1.0)
        second = self.store.record("two", copied_at=2.0)
        third = self.store.record("three", copied_at=3.0)
        self.store.toggle_pin(first.id)
        self.store.record("four", copied_at=4.0)
        items = self.store.load()
        self.assertEqual([item.text for item in items], ["one", "four", "three"])
        self.assertTrue(items[0].pinned)
        self.assertEqual(second.text, "two")
        self.assertEqual(third.text, "three")

    def test_loads_and_migrates_legacy_history(self) -> None:
        self.legacy_file.write_text(json.dumps(["recent", "older"]), encoding="utf-8")
        items = self.store.load()
        self.assertEqual([item.text for item in items], ["recent", "older"])
        migrated = json.loads(self.history_file.read_text(encoding="utf-8"))
        self.assertEqual(len(migrated), 2)
        self.assertEqual(migrated[0]["text"], "recent")

    def test_search_preview_and_relative_time_helpers(self) -> None:
        items = [
            ClipboardItem(id="1", text="Alpha beta", copied_at=50.0),
            ClipboardItem(id="2", text="Gamma", copied_at=40.0, pinned=True),
        ]
        self.assertEqual([item.id for item in search_items(items, "beta")], ["1"])
        self.assertEqual(preview_text("line one\nline two", limit=12), "line one...")
        self.assertEqual(relative_time(95.0, now=100.0), "5s ago")

    def test_clear_keep_pinned(self) -> None:
        first = self.store.record("keep")
        second = self.store.record("drop")
        self.store.toggle_pin(first.id)
        self.store.clear(keep_pinned=True)
        items = self.store.load()
        self.assertEqual([item.text for item in items], ["keep"])
        self.assertTrue(items[0].pinned)
        self.assertEqual(second.text, "drop")

    def test_request_round_trip(self) -> None:
        write_request(self.request_file, "clipboard text")
        payload = read_request(self.request_file)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["text"], "clipboard text")


if __name__ == "__main__":
    unittest.main()
