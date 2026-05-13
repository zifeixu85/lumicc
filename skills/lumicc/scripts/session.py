#!/usr/bin/env python3
"""Session state machine for Lumicc.

Each session lives at ``~/.commerce-os/sessions/<id>/`` and contains:
  - ``state.json``         — shallow state for the current dialogue turn
  - ``events.jsonl``       — append-only audit log (one JSON per line)
  - ``choice-<name>.json`` — files dropped by HTML pickers / secret forms

All public functions are pure stdlib. State files are written atomically
(tempfile + os.replace) and chmod'd to 0600. Session dirs are 0700.

Set ``LUMICC_DATA_ROOT`` to override ``~/.commerce-os`` (used by tests).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path


def _root() -> Path:
    env = os.environ.get("LUMICC_DATA_ROOT")
    return Path(env).expanduser() if env else Path.home() / ".commerce-os"


# Module-level aliases. Evaluated at import time; functions below re-read
# LUMICC_DATA_ROOT each call so tests that flip the env still see the right path.
ROOT = _root()
SESSIONS_DIR = ROOT / "sessions"


def _mk0700(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _sessions_dir() -> Path:
    return _mk0700(_root() / "sessions")


def session_dir(session_id: str) -> Path:
    """Return ``~/.commerce-os/sessions/<id>/``, creating with 0700 if missing."""
    return _mk0700(_sessions_dir() / session_id)


def _now() -> int:
    return int(time.time())


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def new_session(skill: str, store_id: str | None = None) -> str:
    """Create a new session and return its id."""
    sid = uuid.uuid4().hex[:16]
    now = _now()
    state = {
        "session_id": sid,
        "skill": skill,
        "store_id": store_id,
        "persona": None,
        "created_at": now,
        "updated_at": now,
        "status": "in_progress",
        "answers": {},
        "pending_questions": [],
        "handoff_history": [],
    }
    _atomic_write_json(session_dir(sid) / "state.json", state)
    return sid


def read_state(session_id: str) -> dict:
    """Read ``state.json``. Return ``{}`` if missing or unreadable."""
    p = _sessions_dir() / session_id / "state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_state(session_id: str, **patch) -> dict:
    """Shallow-merge ``patch`` into state.json, bump ``updated_at``, return new state."""
    state = read_state(session_id)
    state.update(patch)
    state["updated_at"] = _now()
    state.setdefault("session_id", session_id)
    _atomic_write_json(session_dir(session_id) / "state.json", state)
    return state


def append_event(session_id: str, kind: str, content: str, **meta) -> None:
    """Append one JSON line to ``events.jsonl``."""
    line: dict = {"ts": _now(), "kind": kind, "content": content}
    if meta:
        line["meta"] = meta
    p = session_dir(session_id) / "events.jsonl"
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def list_sessions(skill: str | None = None, limit: int = 20) -> list[dict]:
    """List recent sessions (most-recent first) with summary fields."""
    out: list[dict] = []
    for child in _sessions_dir().iterdir():
        if not child.is_dir():
            continue
        state = read_state(child.name)
        if not state:
            continue
        if skill and state.get("skill") != skill:
            continue
        out.append(
            {
                "id": state.get("session_id", child.name),
                "skill": state.get("skill"),
                "store_id": state.get("store_id"),
                "created_at": state.get("created_at", 0),
                "updated_at": state.get("updated_at", 0),
                "status": state.get("status"),
            }
        )
    out.sort(key=lambda r: r.get("updated_at", 0), reverse=True)
    return out[:limit]


def current_session(skill: str | None = None, max_age_hours: int = 24) -> str | None:
    """Return most recent in_progress session id within age window, else None."""
    cutoff = _now() - max_age_hours * 3600
    for row in list_sessions(skill=skill, limit=50):
        if row.get("status") not in (None, "in_progress"):
            continue
        if row.get("updated_at", 0) < cutoff:
            continue
        return row["id"]
    return None


def read_choice(session_id: str, name: str) -> dict | None:
    """Read ``sessions/<id>/choice-<name>.json``. Return None if not present."""
    p = _sessions_dir() / session_id / f"choice-{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def has_choice(session_id: str, name: str) -> bool:
    """Quick existence check for a choice file."""
    return (_sessions_dir() / session_id / f"choice-{name}.json").exists()


def _picker_history_key(store_id: str | None, kind: str) -> str:
    return f"picker_history:{store_id or '_global'}:{kind}"


def _open_store_db() -> sqlite3.Connection | None:
    """Open ~/.commerce-os/store.db; return None if it doesn't exist."""
    db_path = _root() / "store.db"
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(str(db_path))
    except sqlite3.Error:
        return None


def record_picker_choice(store_id: str | None, kind: str, choice: dict) -> None:
    """Persist a picker choice to store.db preferences so we don't ask again.

    Writes preferences row with key=f'picker_history:{store_id or "_global"}:{kind}'
    and value=json.dumps(choice). Silently no-ops if store.db doesn't exist.
    """
    db = _open_store_db()
    if db is None:
        return
    try:
        # Best-effort: the preferences table is created by init_store.py. If it
        # doesn't exist (raw / partial DB), don't crash.
        db.execute(
            "CREATE TABLE IF NOT EXISTS preferences ("
            "  key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER)"
        )
        db.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
            (_picker_history_key(store_id, kind),
             json.dumps(choice, ensure_ascii=False),
             _now()),
        )
        db.commit()
    except sqlite3.Error:
        pass
    finally:
        db.close()


def get_picker_history(store_id: str | None, kind: str) -> dict | None:
    """Return the most recent picker choice for this store + kind, or None."""
    db = _open_store_db()
    if db is None:
        return None
    try:
        row = db.execute(
            "SELECT value FROM preferences WHERE key=?",
            (_picker_history_key(store_id, kind),),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        db.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return None


def gc_old_sessions(older_than_days: int = 30) -> int:
    """Delete sessions whose ``updated_at`` is older than N days. Return count."""
    cutoff = _now() - older_than_days * 86400
    deleted = 0
    for child in _sessions_dir().iterdir():
        if not child.is_dir():
            continue
        state = read_state(child.name)
        if (state.get("updated_at", 0) if state else 0) < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            deleted += 1
    return deleted


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new"); p.add_argument("--skill", required=True); p.add_argument("--store", default=None)
    p = sub.add_parser("read"); p.add_argument("session_id")
    p = sub.add_parser("list"); p.add_argument("--skill", default=None)
    p = sub.add_parser("current"); p.add_argument("--skill", default=None)
    p = sub.add_parser("gc"); p.add_argument("--days", type=int, default=30)

    a = parser.parse_args()
    if a.cmd == "new":
        print(new_session(a.skill, a.store))
    elif a.cmd == "read":
        print(json.dumps(read_state(a.session_id), indent=2, ensure_ascii=False))
    elif a.cmd == "list":
        print(json.dumps(list_sessions(a.skill), indent=2, ensure_ascii=False))
    elif a.cmd == "current":
        print(current_session(a.skill) or "")
    elif a.cmd == "gc":
        print(gc_old_sessions(a.days))
