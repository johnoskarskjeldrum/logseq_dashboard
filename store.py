from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path

from config import NOTES_ROOT, OPEN_MARKERS
from parser import Block, iter_note_files, parse_file


class BlockStore:
    """In-memory cache of parsed Logseq blocks. Reparses files whose mtime changed."""

    def __init__(self, root: Path = NOTES_ROOT):
        self.root = root
        self._lock = threading.RLock()
        self._mtime: dict[Path, float] = {}
        self._by_file: dict[Path, list[Block]] = {}

    def refresh(self) -> None:
        with self._lock:
            current_files = set(iter_note_files(self.root))
            stale = set(self._by_file) - current_files
            for f in stale:
                self._by_file.pop(f, None)
                self._mtime.pop(f, None)
            for f in current_files:
                try:
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                if self._mtime.get(f) != mtime:
                    self._by_file[f] = parse_file(f)
                    self._mtime[f] = mtime

    def all_blocks(self) -> list[Block]:
        self.refresh()
        with self._lock:
            return [b for blocks in self._by_file.values() for b in blocks]

    def find_by_key(self, stable_key: str) -> Block | None:
        for b in self.all_blocks():
            if b.stable_key == stable_key:
                return b
        return None

    def invalidate_file(self, path: Path) -> None:
        with self._lock:
            self._mtime.pop(path, None)


def categorize_dated(
    blocks: list[Block],
    today: date | None = None,
    near_days: int = 7,
    far_days: int = 31,
) -> dict:
    """Bucket open todos that have a scheduled or deadline date."""
    today = today or date.today()
    near = today + timedelta(days=near_days)
    far = today + timedelta(days=far_days)

    overdue: list[Block] = []
    due_today: list[Block] = []
    next_7: list[Block] = []
    next_31: list[Block] = []
    recent_done: list[Block] = []

    for b in blocks:
        if not (b.scheduled or b.deadline):
            continue

        if b.is_open:
            anchor = b.scheduled or b.deadline
            if b.deadline and b.deadline < today:
                overdue.append(b)
            elif b.scheduled and b.scheduled <= today and (b.deadline is None or b.deadline >= today):
                due_today.append(b)
            elif b.deadline == today:
                due_today.append(b)
            elif anchor and today < anchor <= near:
                next_7.append(b)
            elif anchor and near < anchor <= far:
                next_31.append(b)
        else:
            ref = b.scheduled or b.deadline
            if ref and 0 <= (today - ref).days <= 7:
                recent_done.append(b)

    overdue.sort(key=lambda b: b.deadline or date.max)
    due_today.sort(key=lambda b: (b.deadline or date.max, b.scheduled or date.max))
    next_7.sort(key=lambda b: b.scheduled or b.deadline or date.max)
    next_31.sort(key=lambda b: b.scheduled or b.deadline or date.max)
    recent_done.sort(key=lambda b: b.scheduled or b.deadline or date.min, reverse=True)

    return {
        "overdue": overdue,
        "due_today": due_today,
        "next_7": next_7,
        "next_31": next_31,
        "recent_done": recent_done[:20],
        "counts": {
            "overdue": len(overdue),
            "due_today": len(due_today),
            "next_7": len(next_7),
            "next_31": len(next_31),
            "open_total": len(overdue) + len(due_today) + len(next_7) + len(next_31),
        },
    }


def categorize_undated(blocks: list[Block]) -> dict:
    """Open todos with no scheduled and no deadline."""
    items = [b for b in blocks if b.is_open and not b.scheduled and not b.deadline]
    items.sort(key=lambda b: b.page)
    return {
        "items": items,
        "counts": {"total": len(items)},
    }
