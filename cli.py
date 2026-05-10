"""Render the dashboard as Markdown to stdout. Run from the project root:

    uv run cli.py > todos.md
"""
from __future__ import annotations

from datetime import date

from config import NOTES_ROOT
from store import BlockStore, categorize_dated, categorize_undated


def _fmt_block(b) -> str:
    prio = f" [#{b.priority}]" if b.priority else ""
    extras = []
    if b.scheduled:
        extras.append(f"S:{b.scheduled.isoformat()}")
    if b.deadline:
        extras.append(f"D:{b.deadline.isoformat()}")
    suffix = f"  ({', '.join(extras)})" if extras else ""
    return f"- [{b.marker}]{prio} {b.content}  _({b.page})_{suffix}"


def render() -> str:
    store = BlockStore(NOTES_ROOT)
    blocks = store.all_blocks()
    dated = categorize_dated(blocks)
    undated = categorize_undated(blocks)

    sections = [
        ("Overdue", dated["overdue"]),
        ("Today", dated["due_today"]),
        ("Next 7 days", dated["next_7"]),
        ("Next 31 days", dated["next_31"]),
        ("No date", undated["items"]),
    ]

    parts = [f"# Todos — {date.today().isoformat()}", ""]
    for title, items in sections:
        parts.append(f"## {title} ({len(items)})")
        parts.append("")
        if items:
            parts.extend(_fmt_block(b) for b in items)
        else:
            parts.append("_(none)_")
        parts.append("")
    return "\n".join(parts)


if __name__ == "__main__":
    print(render())
