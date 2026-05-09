from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import re
from urllib.parse import quote, unquote

from config import (
    OPEN_MARKERS, DONE_MARKERS, NOTES_ROOT,
    LOGSEQ_GRAPH_NAME, LOGSEQ_JOURNAL_TITLE_FORMAT,
)
import git_sync
import mutator
from store import BlockStore, categorize_dated, categorize_undated

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("logseq_dashboard")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

REF_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]*)")


def render_content(content: str) -> str:
    """Light HTML rendering: links, refs, tags. Order matters - escape first."""
    import html
    out = html.escape(content)
    out = REF_RE.sub(r'<span class="ref">\1</span>', out)
    out = TAG_RE.sub(r' <span class="tag">#\1</span>', out)
    return out


_store = BlockStore(NOTES_ROOT)
_puller: git_sync.BackgroundPuller | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _puller
    _puller = git_sync.BackgroundPuller()
    _puller.start()
    log.info("started; notes root = %s", NOTES_ROOT)
    yield
    if _puller:
        _puller.stop()


app = FastAPI(title="Logseq Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates.env.filters["render_content"] = render_content


def _block_or_404(stable_key: str):
    b = _store.find_by_key(stable_key)
    if not b:
        raise HTTPException(404, f"block not found: {stable_key}")
    return b


def _commit(paths: list[Path], message: str):
    res = git_sync.commit_and_push(paths, message)
    log.info("git: %s", res)
    return res


def _parse_date_form(s: str | None) -> date | None:
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"invalid date: {s!r} (expected YYYY-MM-DD)")


@app.get("/", response_class=HTMLResponse)
def page_todos(request: Request):
    blocks = _store.all_blocks()
    data = categorize_dated(blocks)
    return templates.TemplateResponse(request, "dated.html", {
        "today_iso": date.today().isoformat(),
        "page_title": "Todos",
        "page_path": "/",
        **data,
    })


@app.get("/no-date", response_class=HTMLResponse)
def page_no_date(request: Request):
    blocks = _store.all_blocks()
    data = categorize_undated(blocks)
    return templates.TemplateResponse(request, "undated.html", {
        "today_iso": date.today().isoformat(),
        "page_title": "No date",
        "page_path": "/no-date",
        **data,
    })


@app.get("/personal")
@app.get("/work")
@app.get("/others")
def _legacy_redirects():
    return RedirectResponse("/", status_code=302)


@app.get("/api/blocks")
def api_blocks(open_only: bool = False, include_done_days: int = 14):
    """Full structured dump. Designed for LLM context."""
    blocks = _store.all_blocks()
    today = date.today()
    out = []
    for b in blocks:
        if open_only and not b.is_open:
            continue
        if not b.is_open:
            ref = b.scheduled or b.deadline
            if not ref or (today - ref).days > include_done_days:
                continue
        out.append(b.to_dict())
    return JSONResponse({"today": today.isoformat(), "blocks": out, "count": len(out)})


@app.get("/api/dashboard")
def api_dashboard():
    blocks = _store.all_blocks()
    dated = categorize_dated(blocks)
    undated = categorize_undated(blocks)
    return JSONResponse({
        "today": date.today().isoformat(),
        "dated": {
            "counts": dated["counts"],
            "overdue": [b.to_dict() for b in dated["overdue"]],
            "due_today": [b.to_dict() for b in dated["due_today"]],
            "next_7": [b.to_dict() for b in dated["next_7"]],
            "next_31": [b.to_dict() for b in dated["next_31"]],
            "recent_done": [b.to_dict() for b in dated["recent_done"]],
        },
        "undated": {
            "counts": undated["counts"],
            "items": [b.to_dict() for b in undated["items"]],
        },
    })


@app.post("/blocks/{stable_key}/marker")
def post_marker(stable_key: str, marker: str = Form(...)):
    if marker not in OPEN_MARKERS + DONE_MARKERS:
        raise HTTPException(400, f"invalid marker: {marker}")
    b = _block_or_404(stable_key)
    new_block = mutator.set_marker(b.file_path, b, marker)
    _store.invalidate_file(b.file_path)
    snippet = (b.content[:60] + "…") if len(b.content) > 60 else b.content
    _commit([b.file_path], f"[dashboard] {b.marker}→{marker}: {snippet}")
    return _todo_row_response(new_block) if new_block else RedirectResponse("/", status_code=303)


@app.post("/blocks/{stable_key}/scheduled")
def post_scheduled(stable_key: str, scheduled: str = Form("")):
    b = _block_or_404(stable_key)
    d = _parse_date_form(scheduled)
    new_block = mutator.set_scheduled(b.file_path, b, d)
    _store.invalidate_file(b.file_path)
    snippet = (b.content[:60] + "…") if len(b.content) > 60 else b.content
    msg = f"[dashboard] scheduled={d.isoformat() if d else 'cleared'}: {snippet}"
    _commit([b.file_path], msg)
    return _todo_row_response(new_block) if new_block else RedirectResponse("/", status_code=303)


@app.post("/blocks/{stable_key}/deadline")
def post_deadline(stable_key: str, deadline: str = Form("")):
    b = _block_or_404(stable_key)
    d = _parse_date_form(deadline)
    new_block = mutator.set_deadline(b.file_path, b, d)
    _store.invalidate_file(b.file_path)
    snippet = (b.content[:60] + "…") if len(b.content) > 60 else b.content
    msg = f"[dashboard] deadline={d.isoformat() if d else 'cleared'}: {snippet}"
    _commit([b.file_path], msg)
    return _todo_row_response(new_block) if new_block else RedirectResponse("/", status_code=303)


def _todo_row_response(block):
    """HTMX out-of-band swap: returns updated dashboard via redirect.
    Simpler than partial swaps for MVP — full reload after each action.
    """
    return RedirectResponse("/", status_code=303)


_LOGSEQ_TOKEN_RE = re.compile(r"yyyy|yy|MMMM|MMM|MM|dd|do|EEEE|EEE")
_ORDINAL_SUFFIX = ["th", "st", "nd", "rd", "th", "th", "th", "th", "th", "th"]


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{_ORDINAL_SUFFIX[n % 10]}"


def _format_journal_title(d: date, fmt: str) -> str:
    """Translate Logseq's date format tokens into the rendered string."""
    def replace(m: re.Match) -> str:
        tok = m.group()
        if tok == "yyyy": return f"{d.year:04d}"
        if tok == "yy":   return f"{d.year % 100:02d}"
        if tok == "MMMM": return d.strftime("%B")
        if tok == "MMM":  return d.strftime("%b")
        if tok == "MM":   return f"{d.month:02d}"
        if tok == "dd":   return f"{d.day:02d}"
        if tok == "do":   return _ordinal(d.day)
        if tok == "EEEE": return d.strftime("%A")
        if tok == "EEE":  return d.strftime("%a")
        return tok
    return _LOGSEQ_TOKEN_RE.sub(replace, fmt)


def _logseq_page_name(block) -> str:
    if "journals" in block.file_path.parts:
        try:
            d = date.fromisoformat(block.page.replace("_", "-"))
            return _format_journal_title(d, LOGSEQ_JOURNAL_TITLE_FORMAT)
        except ValueError:
            pass
    return unquote(block.page)


@app.get("/open/{stable_key:path}")
def open_in_logseq(stable_key: str):
    """Redirect to a logseq:// URL pointing at this block (or its page)."""
    b = _block_or_404(stable_key)
    graph = quote(LOGSEQ_GRAPH_NAME, safe="")
    if b.id:
        target = f"logseq://graph/{graph}?block-id={b.id}"
    else:
        target = f"logseq://graph/{graph}?page={quote(_logseq_page_name(b), safe='')}"
    return RedirectResponse(target, status_code=302)


@app.get("/healthz")
def healthz():
    return {"ok": True}
