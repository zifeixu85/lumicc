#!/usr/bin/env python3
"""Advance one day in the active cold-start campaign and emit today's tasks.

Run on demand (coder mode) or by cron (agent mode, daily 09:00).
Reads the running campaign for the given store_id, computes day_offset
from started_at, and outputs the schedule entry for that day.

Usage:
    python3 day_advance.py --store-id ID                          # coder mode
    python3 day_advance.py --store-id ID --notify-channel feishu  # agent mode
    python3 day_advance.py --all-stores --quiet-stdout            # cron-friendly
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify as notify_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path:
    return ROOT / "store.db"


def active_campaigns(store_id: str | None) -> list[dict]:
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        if store_id:
            rows = db.execute(
                "SELECT * FROM campaigns WHERE store_id=? AND type='cold-start' AND status='running'",
                (store_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM campaigns WHERE type='cold-start' AND status='running'"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def get_day(plan: dict, day_offset: int) -> dict | None:
    for d in plan.get("schedule", []):
        if d["day"] == day_offset:
            return d
    return None


def advance(camp: dict, now_ts: int | None = None) -> dict:
    now_ts = now_ts if now_ts is not None else int(time.time())
    started_at = camp.get("started_at") or now_ts
    day_offset = max(1, (now_ts - started_at) // 86400 + 1)
    plan = json.loads(camp.get("results_json") or "{}")
    today = get_day(plan, day_offset)
    return {
        "campaign_id": camp["id"],
        "store_id": camp.get("store_id"),
        "day_offset": day_offset,
        "phase": today.get("phase") if today else None,
        "tasks": today.get("tasks", []) if today else [],
        "capability_slots": today.get("capability_slots", []) if today else [],
        "is_complete": day_offset > 30,
    }


def render_md(advance_results: list[dict]) -> str:
    if not advance_results:
        return "_No active cold-start campaign found. Run plan.py first._"
    lines = [f"# Today's Cold-Start Tasks — {time.strftime('%Y-%m-%d')}", ""]
    for r in advance_results:
        if r["is_complete"]:
            lines.append(f"## Campaign {r['campaign_id'][:8]} — DONE (Day {r['day_offset']} of 30)")
            lines.append("- 🎉 30-day cold-start window closed. Run a retro and consider `lumicc-expand`.")
            continue
        lines.append(f"## Campaign {r['campaign_id'][:8]} — Day {r['day_offset']} of 30")
        lines.append(f"**Phase**: {r['phase']}")
        lines.append("")
        if not r["tasks"]:
            lines.append("- _(no tasks scheduled for today)_")
        for t in r["tasks"]:
            lines.append(f"- [ ] {t}")
        if r["capability_slots"]:
            lines.append("")
            lines.append(f"_Capability slots needed today: {', '.join(r['capability_slots'])}_")
        lines.append("")
    return "\n".join(lines)


def insert_event(store_id: str | None, content: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, int(time.time()), "task", content),
        )
        db.commit()
    finally:
        db.close()


def insert_run(run_id: str, store_id: str | None, status: str, result_path: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-launch:day-advance", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--all-stores", action="store_true")
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    p.add_argument("--now-ts", type=int, default=None, help="Override 'now' for testing")
    args = p.parse_args()

    sid = None if args.all_stores else args.store_id
    camps = active_campaigns(sid)
    results = [advance(c, now_ts=args.now_ts) for c in camps]
    md = render_md(results)

    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "today.md").write_text(md, encoding="utf-8")
    (run_dir / "result.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    insert_run(run_id, sid, "success", str(run_dir / "result.json"))

    if results:
        first = results[0]
        if first["is_complete"]:
            content = f"lumicc-launch day-advance: campaign {first['campaign_id']} cold-start complete"
        else:
            content = f"lumicc-launch day-advance: campaign {first['campaign_id']} day {first['day_offset']}/30 — {len(first['tasks'])} tasks"
        insert_event(sid, content)

    if not args.quiet_stdout:
        print(md)

    if args.notify_channel:
        any_active = any(not r["is_complete"] for r in results)
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"📋 Today's cold-start tasks ({time.strftime('%Y-%m-%d')})",
            body_md=md, severity="info" if any_active else "warn",
            skill="lumicc-launch", run_id=run_id,
        )

    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "campaigns": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
