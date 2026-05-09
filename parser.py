from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

from config import ALL_MARKERS, OPEN_MARKERS, NOTES_ROOT, SCAN_DIRS

BULLET_RE = re.compile(r"^(?P<indent>[\t ]*)-\s+(?P<rest>.*)$")
MARKER_RE = re.compile(
    r"^(?P<marker>" + "|".join(ALL_MARKERS) + r")\b\s*"
    r"(?:\[#(?P<priority>[A-C])\]\s*)?"
    r"(?P<content>.*)$"
)
SCHED_RE = re.compile(
    r"^(?P<indent>[\t ]*)SCHEDULED:\s*<(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:\s+[A-Za-z]{3})?(?:\s+(?P<repeat>\.\+\d+[dwmy]))?>\s*$"
)
DEAD_RE = re.compile(
    r"^(?P<indent>[\t ]*)DEADLINE:\s*<(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:\s+[A-Za-z]{3})?(?:\s+(?P<repeat>\.\+\d+[dwmy]))?>\s*$"
)
PROP_RE = re.compile(
    r"^(?P<indent>[\t ]*)(?P<key>[a-zA-Z][a-zA-Z0-9_-]*)::\s*(?P<value>.*)$"
)
LEADING_WS_RE = re.compile(r"^([\t ]*)")
REF_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]*)")


@dataclass
class Block:
    id: str | None
    marker: str
    priority: str | None
    content: str
    scheduled: date | None
    deadline: date | None
    refs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    page: str = ""
    file_path: Path = field(default_factory=Path)
    line_start: int = 0
    line_end: int = 0
    indent: str = ""

    @property
    def is_open(self) -> bool:
        return self.marker in OPEN_MARKERS

    @property
    def stable_key(self) -> str:
        """Identifier used by the API. Prefers logseq id::; falls back to file+line."""
        if self.id:
            return f"id:{self.id}"
        return f"loc:{self.file_path.name}:{self.line_start}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["file_path"] = str(self.file_path)
        d["scheduled"] = self.scheduled.isoformat() if self.scheduled else None
        d["deadline"] = self.deadline.isoformat() if self.deadline else None
        d["is_open"] = self.is_open
        d["stable_key"] = self.stable_key
        return d


def _expanded_len(s: str) -> int:
    return len(s.expandtabs(4))


def parse_file(path: Path) -> list[Block]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    lines = text.splitlines()
    blocks: list[Block] = []
    page = path.stem
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        bm = BULLET_RE.match(line)
        if not bm:
            i += 1
            continue
        indent = bm.group("indent")
        rest = bm.group("rest")
        mm = MARKER_RE.match(rest)
        if not mm:
            i += 1
            continue

        marker = mm.group("marker")
        priority = mm.group("priority")
        content = mm.group("content").strip()
        line_start = i
        line_end = i
        scheduled: date | None = None
        deadline: date | None = None
        block_id: str | None = None
        bullet_indent_w = _expanded_len(indent)

        j = i + 1
        while j < n:
            l = lines[j]
            if not l.strip():
                break
            if BULLET_RE.match(l):
                break
            li = LEADING_WS_RE.match(l).group(1)
            if _expanded_len(li) <= bullet_indent_w:
                break
            sm = SCHED_RE.match(l)
            dm = DEAD_RE.match(l)
            pm = PROP_RE.match(l)
            if sm:
                try:
                    scheduled = date.fromisoformat(sm.group("date"))
                except ValueError:
                    pass
            elif dm:
                try:
                    deadline = date.fromisoformat(dm.group("date"))
                except ValueError:
                    pass
            elif pm and pm.group("key").lower() == "id":
                block_id = pm.group("value").strip()
            line_end = j
            j += 1

        refs = REF_RE.findall(content)
        tags = [t.lower() for t in TAG_RE.findall(content)]

        blocks.append(Block(
            id=block_id,
            marker=marker,
            priority=priority,
            content=content,
            scheduled=scheduled,
            deadline=deadline,
            refs=refs,
            tags=tags,
            page=page,
            file_path=path,
            line_start=line_start,
            line_end=line_end,
            indent=indent,
        ))
        i = j
    return blocks


def iter_note_files(root: Path = NOTES_ROOT) -> list[Path]:
    files: list[Path] = []
    for sub in SCAN_DIRS:
        d = root / sub
        if not d.is_dir():
            continue
        files.extend(p for p in d.glob("*.md") if p.is_file())
    return files


def parse_all(root: Path = NOTES_ROOT) -> list[Block]:
    out: list[Block] = []
    for f in iter_note_files(root):
        out.extend(parse_file(f))
    return out
