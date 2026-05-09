from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid
from datetime import date
from pathlib import Path

from parser import (
    Block, BULLET_RE, MARKER_RE, PROP_RE, LEADING_WS_RE,
    parse_file, _expanded_len,
)

WEEKDAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SCHED_LINE_RE = re.compile(r"^[\t ]*SCHEDULED:")
DEAD_LINE_RE = re.compile(r"^[\t ]*DEADLINE:")
ID_LINE_RE = re.compile(r"^[\t ]*id::\s*(\S+)")

_file_lock = threading.RLock()


def format_date(d: date) -> str:
    return f"<{d.isoformat()} {WEEKDAY_ABBR[d.weekday()]}>"


def _atomic_write(path: Path, content: str) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".swp_", text=False)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _split_text(text: str) -> tuple[list[str], str, bool]:
    eol = "\r\n" if "\r\n" in text else "\n"
    has_trailing = text.endswith(eol)
    return text.splitlines(), eol, has_trailing


def _join_text(lines: list[str], eol: str, has_trailing: bool) -> str:
    return eol.join(lines) + (eol if has_trailing else "")


def _find_block(lines: list[str], block: Block) -> tuple[int, int, str]:
    """Locate the block in the current file content. Returns (start, end, indent)."""
    if block.id:
        for i, line in enumerate(lines):
            m = ID_LINE_RE.match(line)
            if m and m.group(1) == block.id:
                start = i
                while start > 0 and not BULLET_RE.match(lines[start]):
                    start -= 1
                if not BULLET_RE.match(lines[start]):
                    raise ValueError(f"Could not find bullet for id {block.id}")
                return _extend_block(lines, start)
    if 0 <= block.line_start < len(lines) and BULLET_RE.match(lines[block.line_start]):
        return _extend_block(lines, block.line_start)
    raise ValueError(f"Block not found in {block.file_path} (key={block.stable_key})")


def _extend_block(lines: list[str], start: int) -> tuple[int, int, str]:
    bm = BULLET_RE.match(lines[start])
    indent = bm.group("indent")
    indent_w = _expanded_len(indent)
    end = start
    j = start + 1
    while j < len(lines):
        l = lines[j]
        if not l.strip():
            break
        if BULLET_RE.match(l):
            break
        li = LEADING_WS_RE.match(l).group(1)
        if _expanded_len(li) <= indent_w:
            break
        end = j
        j += 1
    return start, end, indent


def _ensure_id(lines: list[str], start: int, end: int, indent: str) -> tuple[int, str]:
    for i in range(start + 1, end + 1):
        m = ID_LINE_RE.match(lines[i])
        if m:
            return end, m.group(1)
    new_id = str(uuid.uuid4())
    lines.insert(end + 1, f"{indent}  id:: {new_id}")
    return end + 1, new_id


def _set_property_line(
    lines: list[str], start: int, end: int, indent: str,
    pattern: re.Pattern, new_line: str | None,
) -> int:
    for i in range(start + 1, end + 1):
        if pattern.match(lines[i]):
            if new_line is None:
                del lines[i]
                return end - 1
            lines[i] = new_line
            return end
    if new_line is None:
        return end
    lines.insert(start + 1, new_line)
    return end + 1


def _refresh_block(path: Path, stable_key: str) -> Block | None:
    for b in parse_file(path):
        if b.stable_key == stable_key:
            return b
    return None


def _apply(path: Path, block: Block, op):
    """Acquire lock, read, locate, ensure id, apply op, write atomically.
    Returns the freshly re-parsed Block.
    """
    with _file_lock:
        text = path.read_text(encoding="utf-8")
        lines, eol, has_trailing = _split_text(text)
        start, end, indent = _find_block(lines, block)
        end, new_id = _ensure_id(lines, start, end, indent)
        op(lines, start, end, indent)
        _atomic_write(path, _join_text(lines, eol, has_trailing))
    return _refresh_block(path, f"id:{new_id}")


def set_marker(path: Path, block: Block, new_marker: str) -> Block | None:
    def op(lines, start, end, indent):
        bm = BULLET_RE.match(lines[start])
        rest = bm.group("rest")
        mm = MARKER_RE.match(rest)
        if not mm:
            raise ValueError(f"No marker on bullet at {path}:{start}")
        new_rest = re.sub(
            r"^" + re.escape(mm.group("marker")),
            new_marker,
            rest,
            count=1,
        )
        lines[start] = f"{indent}- {new_rest}"
    return _apply(path, block, op)


def set_scheduled(path: Path, block: Block, d: date | None) -> Block | None:
    def op(lines, start, end, indent):
        new_line = f"{indent}  SCHEDULED: {format_date(d)}" if d else None
        _set_property_line(lines, start, end, indent, SCHED_LINE_RE, new_line)
    return _apply(path, block, op)


def set_deadline(path: Path, block: Block, d: date | None) -> Block | None:
    def op(lines, start, end, indent):
        new_line = f"{indent}  DEADLINE: {format_date(d)}" if d else None
        _set_property_line(lines, start, end, indent, DEAD_LINE_RE, new_line)
    return _apply(path, block, op)
