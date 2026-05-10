# Logseq Dashboard

A self-hosted dashboard over a Logseq notes graph, focused on todos and designed
to keep all data in a single normalised Block model that's reusable from an LLM.

## What it does

- Walks `journals/` and `pages/` under your Logseq notes root, parsing every
  bullet that has a marker (`LATER`, `NOW`, `TODO`, `DOING`, `DONE`, …).
- Renders a dashboard split into:
  - **Today** — open todos due/scheduled today
  - **Overdue** — open todos with `DEADLINE` in the past
  - **Work — today** — same-day filter for `#work` / `[[work]]` tagged todos
  - **Next 7 days** — open todos scheduled in the upcoming week
  - **No date** — open todos with no scheduled / deadline
  - **Recently done** — last 7 days of completions
- Lets you (per todo): mark DONE, re-open, change scheduled date, change
  deadline, clear either date.
- Every mutation edits the original markdown file in place, atomically. The
  first time the dashboard touches a block it adds an `id::` UUID so the
  block can be located robustly afterwards even if you reorder the file.
- Optionally `git add && git commit && git push` after each mutation, with a
  descriptive commit message like `[dashboard] LATER→DONE: <todo content>`.
- A background thread runs `git pull --rebase` periodically to keep the read
  view in sync with edits made elsewhere (mobile, desktop Logseq, Pi).
- Exposes `/api/blocks` returning the full normalised Block list as JSON —
  the same data the dashboard uses, ready to feed into an LLM.

## Setup

Dependencies are managed with [`uv`](https://docs.astral.sh/uv/). Install it
once (`curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux/macOS), then:

```sh
cd logseq_dashboard
uv sync                # creates .venv and installs from uv.lock
cp .env.example .env   # optional — only if you want to override defaults
```

## Run

```sh
./run.sh
```

Open <http://localhost:8765/>.

## Configuration

All optional. Set via environment variables, or copy `.env.example` to `.env`
and edit there (loaded automatically on startup).

| Variable | Default | Effect |
| --- | --- | --- |
| `LOGSEQ_NOTES_ROOT` | `../logseq_notes` (sibling of this folder) | Path to the Logseq graph |
| `LOGSEQ_GRAPH_NAME` | basename of `LOGSEQ_NOTES_ROOT` | Graph name used in `logseq://` links |
| `LOGSEQ_JOURNAL_TITLE_FORMAT` | `EEE, dd-MM-yyyy` | Logseq journal page title format |
| `LOGSEQ_GIT_AUTO_COMMIT` | `1` | Commit after every mutation |
| `LOGSEQ_GIT_AUTO_PUSH` | `1` | Push after the auto-commit |
| `LOGSEQ_GIT_PULL_INTERVAL` | `120` | Background pull interval (seconds) |
| `HOST` | `0.0.0.0` | Network interface uvicorn binds to |
| `PORT` | `8765` | Port uvicorn binds to |

## Security

This dashboard has **no authentication and no CSRF protection**. It is designed
for a single user on a trusted network — anyone who can reach the port can edit
or wipe your todos.

Sane deployments:

- `HOST=127.0.0.1` for localhost-only.
- `HOST=0.0.0.0` on a home LAN you trust, or on a Tailscale-only host.
- Tailscale (or another private overlay) for remote access — your tailnet stays
  private, so only your enrolled devices can reach the dashboard.

Do **not** expose the dashboard to the public internet.

## Markdown export (CLI)

A small CLI renders the same buckets the dashboard shows as a Markdown file:

```sh
uv run cli.py > todos.md
```

Sections: Overdue, Today, Next 7 days, Next 31 days, No date. Useful for
piping into a file, an LLM, or `pandoc`.

## API

- `GET /api/dashboard` — JSON version of the dashboard buckets.
- `GET /api/blocks?open_only=true&include_done_days=14` — full block list
  for LLM consumption. One canonical schema for every todo:
  ```json
  {
    "stable_key": "id:02b49817-…",
    "marker": "LATER",
    "priority": null,
    "content": "Read [[Some Book]]",
    "scheduled": "2026-05-17",
    "deadline": "2026-05-27",
    "refs": ["Some Book"],
    "tags": [],
    "page": "2026_05_07",
    "is_open": true,
    "...": "..."
  }
  ```
- `POST /blocks/{stable_key}/marker` form: `marker=DONE`
- `POST /blocks/{stable_key}/scheduled` form: `scheduled=2026-05-20` (empty = clear)
- `POST /blocks/{stable_key}/deadline` form: `deadline=2026-05-20` (empty = clear)

`stable_key` is `id:<uuid>` once the block has an `id::` property, otherwise
`loc:<filename>:<line>` as a fallback.

## Hosting on a Raspberry Pi

1. Clone the notes repo on the Pi.
2. Clone this dashboard on the Pi.
3. Install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
4. `uv sync` to install dependencies into `.venv` from `uv.lock`.
5. Make sure `git pull` / `git push` work non-interactively (SSH key on the Pi,
   SSH remote URL — not HTTPS — on the notes repo).
6. Install as a systemd service (see below) so it survives SSH disconnects and
   restarts on boot.

### Installing as a systemd service

A unit template lives at [`deploy/logseq-dashboard.service`](deploy/logseq-dashboard.service).
It assumes the Pi user is `pi` and the dashboard is at `/home/pi/logseq_dashboard` —
edit the `User=`, `WorkingDirectory=`, and `ExecStart=` lines if that's not the case.

```sh
sudo cp deploy/logseq-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now logseq-dashboard
```

Useful commands:

```sh
systemctl status logseq-dashboard       # is it running?
journalctl -u logseq-dashboard -f       # tail the logs
sudo systemctl restart logseq-dashboard # after editing .env or pulling new code
```

## Interaction with `logseq-plugin-git`

If Logseq is open on a desktop, `logseq-plugin-git` will auto-commit edits
made by the dashboard with its own timestamp message before the dashboard
gets a chance to commit. That's harmless — the change is still committed.
The dashboard's commit only "wins" when the plugin isn't running (e.g., Pi).

## Layout

```
logseq_dashboard/
├── app.py            # FastAPI routes (dashboard, mutations, JSON API)
├── parser.py         # Markdown → Block dataclass
├── store.py          # Mtime-aware in-memory cache; categorisation
├── mutator.py        # Atomic in-place edits; auto-adds id:: on first touch
├── git_sync.py       # Commit/push wrapper; background puller
├── config.py         # Env-var driven configuration
├── templates/        # Jinja2 templates (base + dashboard)
└── static/style.css
```

## Future hooks for the LLM layer

- `/api/blocks` is the single source of truth — point an LLM at it and
  prompts can read the full state without touching the filesystem.
- Pages, refs and tags are already extracted, so the LLM can be asked to
  reason about projects (`[[project]]`), tags (`#work`) or page context.
- Adding a `/api/suggest` route later (LLM-backed) is a straightforward
  next step; it would use the same Block model.
