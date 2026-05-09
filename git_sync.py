from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path

from config import GIT_AUTO_COMMIT, GIT_AUTO_PUSH, GIT_BACKGROUND_PULL_SECONDS, NOTES_ROOT

log = logging.getLogger("logseq_dashboard.git")
_git_lock = threading.Lock()


def _run(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        log.warning("git %s timed out", " ".join(args))
        return -1, "", "timeout"
    except FileNotFoundError:
        log.warning("git binary not found")
        return -2, "", "git not found"


def commit_and_push(paths: list[Path], message: str, root: Path = NOTES_ROOT) -> dict:
    """Stage given paths, commit, push. Best-effort; logs but doesn't raise."""
    result = {"committed": False, "pushed": False, "messages": []}
    if not GIT_AUTO_COMMIT:
        return result
    with _git_lock:
        rel_paths = [str(p.relative_to(root)) for p in paths if p.is_relative_to(root)]
        if not rel_paths:
            return result

        rc, _, err = _run(["add", "--", *rel_paths], root)
        if rc != 0:
            result["messages"].append(f"add failed: {err}")
            return result

        rc, out, err = _run(["diff", "--cached", "--quiet"], root)
        if rc == 0:
            result["messages"].append("nothing to commit")
            return result

        rc, _, err = _run(["commit", "-m", message], root)
        if rc != 0:
            result["messages"].append(f"commit failed: {err}")
            return result
        result["committed"] = True

        if GIT_AUTO_PUSH:
            rc, out, err = _run(["push"], root, timeout=60)
            if rc == 0:
                result["pushed"] = True
            else:
                result["messages"].append(f"push failed: {err}")
    return result


def pull(root: Path = NOTES_ROOT) -> dict:
    result = {"ok": False, "message": ""}
    with _git_lock:
        rc, out, err = _run(["pull", "--rebase", "--autostash"], root, timeout=60)
        result["ok"] = rc == 0
        result["message"] = out or err
    return result


class BackgroundPuller(threading.Thread):
    def __init__(self, root: Path = NOTES_ROOT, interval: int = GIT_BACKGROUND_PULL_SECONDS):
        super().__init__(daemon=True, name="git-puller")
        self.root = root
        self.interval = max(30, interval)
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                res = pull(self.root)
                if not res["ok"]:
                    log.debug("background pull: %s", res["message"])
            except Exception as e:
                log.warning("background pull error: %s", e)
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
