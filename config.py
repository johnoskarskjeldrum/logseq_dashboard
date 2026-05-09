from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

NOTES_ROOT = Path(os.environ.get(
    "LOGSEQ_NOTES_ROOT",
    str(Path(__file__).resolve().parent.parent / "logseq_notes"),
)).expanduser().resolve()

LOGSEQ_GRAPH_NAME = os.environ.get("LOGSEQ_GRAPH_NAME", NOTES_ROOT.name)

# Logseq's journal page title format. Tokens supported by the formatter:
#   yyyy  yy  MMMM  MMM  MM  dd  do  EEEE  EEE
# Defaults match the format produced by the user's Logseq install.
LOGSEQ_JOURNAL_TITLE_FORMAT = os.environ.get("LOGSEQ_JOURNAL_TITLE_FORMAT", "EEE, dd-MM-yyyy")

SCAN_DIRS = ("journals", "pages")

OPEN_MARKERS = ("LATER", "NOW", "TODO", "DOING", "WAITING")
DONE_MARKERS = ("DONE", "CANCELLED", "CANCELED")
ALL_MARKERS = OPEN_MARKERS + DONE_MARKERS

GIT_AUTO_COMMIT = os.environ.get("LOGSEQ_GIT_AUTO_COMMIT", "1") == "1"
GIT_AUTO_PUSH = os.environ.get("LOGSEQ_GIT_AUTO_PUSH", "1") == "1"
GIT_BACKGROUND_PULL_SECONDS = int(os.environ.get("LOGSEQ_GIT_PULL_INTERVAL", "120"))
