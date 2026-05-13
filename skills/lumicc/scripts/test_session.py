#!/usr/bin/env python3
"""Tests for session.py — stdlib only, no pytest needed.

Runs against a TemporaryDirectory via LUMICC_DATA_ROOT env override so it
never touches the user's real ~/.commerce-os.

Run:
    python3 test_session.py
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def fresh_module():
    """Re-import session under a fresh LUMICC_DATA_ROOT."""
    if "session" in sys.modules:
        del sys.modules["session"]
    import session  # type: ignore
    return session


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LUMICC_DATA_ROOT"] = tmp
        session = fresh_module()
        root = Path(tmp)

        # ---- 1) new_session creates dir + state.json with 0600 ----
        print("\n[1] new_session")
        sid = session.new_session("lumicc-launch", store_id="store-abc")
        expect(isinstance(sid, str) and len(sid) == 16, "session id is 16 hex chars")
        sdir = root / "sessions" / sid
        expect(sdir.is_dir(), "session dir created")
        state_path = sdir / "state.json"
        expect(state_path.exists(), "state.json created")
        mode = stat.S_IMODE(state_path.stat().st_mode)
        expect(mode == 0o600, f"state.json mode is 0600 (got {oct(mode)})")
        state = json.loads(state_path.read_text())
        expect(state["session_id"] == sid, "state.session_id matches")
        expect(state["skill"] == "lumicc-launch", "state.skill stored")
        expect(state["store_id"] == "store-abc", "state.store_id stored")
        expect(state["status"] == "in_progress", "initial status in_progress")
        expect(state["answers"] == {}, "answers init empty")

        # ---- 2) update_state shallow-merges, bumps updated_at ----
        print("\n[2] update_state")
        old_ts = state["updated_at"]
        time.sleep(1.05)  # ensure ts changes
        new_state = session.update_state(sid, answers={"niche": "pets"}, status="confirmed")
        expect(new_state["answers"] == {"niche": "pets"}, "answers patched")
        expect(new_state["status"] == "confirmed", "status patched")
        expect(new_state["updated_at"] > old_ts, "updated_at bumped")
        expect(new_state["created_at"] == state["created_at"], "created_at preserved")
        # re-read from disk
        on_disk = json.loads(state_path.read_text())
        expect(on_disk["status"] == "confirmed", "state persisted to disk")

        # ---- 3) append_event ----
        print("\n[3] append_event")
        session.append_event(sid, "question", "asked niche")
        session.append_event(sid, "answer", "user said pets", source="cli")
        events_path = sdir / "events.jsonl"
        expect(events_path.exists(), "events.jsonl exists")
        lines = events_path.read_text().strip().split("\n")
        expect(len(lines) == 2, "two events appended")
        e0 = json.loads(lines[0])
        e1 = json.loads(lines[1])
        expect(e0["kind"] == "question", "event[0] kind")
        expect(e1["meta"] == {"source": "cli"}, "event[1] meta carried")

        # ---- 4) current_session ----
        print("\n[4] current_session")
        # Re-open as in_progress so it qualifies as "active"
        session.update_state(sid, status="in_progress")
        cur = session.current_session()
        expect(cur == sid, "current_session finds active (any skill)")
        cur2 = session.current_session(skill="lumicc-launch")
        expect(cur2 == sid, "current_session filters by skill")
        cur3 = session.current_session(skill="lumicc-rescue")
        expect(cur3 is None, "current_session returns None on no match")

        # Most-recent-wins: create newer session, expect it returned
        time.sleep(1.05)
        sid2 = session.new_session("lumicc-rescue")
        cur4 = session.current_session()
        expect(cur4 == sid2, "current_session returns newest")

        # ---- 5) read_choice / has_choice ----
        print("\n[5] choice files")
        expect(session.read_choice(sid, "foo") is None, "read_choice missing → None")
        expect(session.has_choice(sid, "foo") is False, "has_choice missing → False")
        choice_path = sdir / "choice-foo.json"
        choice_path.write_text(json.dumps({"picked": "option-a", "qty": 3}))
        expect(session.has_choice(sid, "foo") is True, "has_choice present → True")
        body = session.read_choice(sid, "foo")
        expect(body == {"picked": "option-a", "qty": 3}, "read_choice returns dict")

        # ---- 6) list_sessions ----
        print("\n[6] list_sessions")
        rows = session.list_sessions()
        expect(len(rows) == 2, "list has 2 sessions")
        expect(rows[0]["id"] == sid2, "list sorted newest first")
        only_launch = session.list_sessions(skill="lumicc-launch")
        expect(len(only_launch) == 1 and only_launch[0]["id"] == sid, "list filter by skill")

        # ---- 7) gc_old_sessions ----
        print("\n[7] gc_old_sessions")
        # Backdate sid: rewrite state.json with old updated_at
        stale = json.loads(state_path.read_text())
        stale["updated_at"] = int(time.time()) - 40 * 86400
        state_path.write_text(json.dumps(stale))
        deleted = session.gc_old_sessions(older_than_days=30)
        expect(deleted == 1, f"gc deleted 1 (got {deleted})")
        expect(not sdir.exists(), "stale session dir removed")
        expect((root / "sessions" / sid2).exists(), "fresh session preserved")

    if FAILS:
        print(f"\n{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll session tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
