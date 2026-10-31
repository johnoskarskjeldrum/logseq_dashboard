"""Push a short "what am I doing" todo list to a TRMNL private plugin webhook.

    uv run trmnl.py            # git pull the notes, then POST to TRMNL_WEBHOOK_URL
    uv run trmnl.py --dry-run  # print the payload instead of sending it
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import date

from config import NOTES_ROOT
from git_sync import pull
from store import BlockStore, categorize_dated

MAX_ITEMS = 8
MAX_TEXT = 70
# TRMNL rejects webhook payloads over 5 KB.
MAX_PAYLOAD_BYTES = 5000

LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
URL_RE = re.compile(r"https?://\S+")


def _clean(content: str) -> str:
    text = URL_RE.sub("", LINK_RE.sub(r"\1", content)).strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def _item(b, today: date) -> dict:
    due = b.deadline or b.scheduled
    when = "" if due is None or due == today else due.strftime("%d.%m")
    return {"text": _clean(b.content), "when": when}


def build_payload(today: date | None = None) -> dict:
    today = today or date.today()
    blocks = BlockStore(NOTES_ROOT).all_blocks()
    dated = categorize_dated(blocks, today=today)
    doing = [b for b in blocks if b.is_open and b.marker in ("NOW", "DOING")]

    sections = [
        ("Doing", doing),
        ("Overdue", dated["overdue"]),
        ("Today", dated["due_today"]),
        ("Coming up", dated["next_7"]),
    ]
    budget = MAX_ITEMS
    out = []
    for title, items in sections:
        shown = items[:budget]
        budget -= len(shown)
        if shown:
            out.append({"title": title, "items": [_item(b, today) for b in shown]})

    return {"merge_variables": {"updated": today.strftime("%d.%m.%Y"), "sections": out}}


def send(payload: dict, url: str) -> int:
    body = json.dumps(payload, ensure_ascii=False).encode()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload is {len(body)} bytes, TRMNL allows {MAX_PAYLOAD_BYTES}")
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print, don't send")
    parser.add_argument("--no-pull", action="store_true", help="skip git pull")
    args = parser.parse_args()

    if not args.no_pull:
        res = pull()
        if not res["ok"]:
            print(f"git pull failed, using local notes: {res['message']}", file=sys.stderr)

    payload = build_payload()
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    url = os.environ.get("TRMNL_WEBHOOK_URL")
    if not url:
        sys.exit("Set TRMNL_WEBHOOK_URL in .env (from the private plugin's settings).")
    print(f"TRMNL responded {send(payload, url)}")


if __name__ == "__main__":
    main()
