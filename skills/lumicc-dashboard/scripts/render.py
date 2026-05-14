#!/usr/bin/env python3
"""Render Lumicc dashboard from ~/.commerce-os/ data into static HTML.

Reads:
  ~/.commerce-os/store.db       (stores, products, campaigns, events, insights, runs)
  ~/.commerce-os/memory/*.md    (daily Layer 1 logs)
  ~/.commerce-os/SOUL.md        (Layer 3 user rules)
  ~/.commerce-os/runs/*.json    (per-run detail, optional)

Writes:
  ~/.commerce-os/dashboard/index.html
  ~/.commerce-os/dashboard/stores.html
  ~/.commerce-os/dashboard/campaigns.html
  ~/.commerce-os/dashboard/runs.html
  ~/.commerce-os/dashboard/memory.html
  ~/.commerce-os/dashboard/assets/style.css
  ~/.commerce-os/dashboard/assets/app.js

Usage:
    python3 render.py                              # coder mode, opens browser
    python3 render.py --no-open                    # coder mode, no browser
    python3 render.py --quiet-stdout               # agent mode, JSON one-liner
    python3 render.py --data-root /custom/path     # custom data root
    python3 render.py --notify-channel feishu --notify-target group:ops
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import templates as T  # noqa: E402

DEFAULT_DATA_ROOT = Path.home() / ".commerce-os"


# ---------- Data loaders ----------
def open_db(data_root: Path) -> sqlite3.Connection | None:
    db_path = data_root / "store.db"
    if not db_path.exists():
        return None
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    return db


def table_exists(db: sqlite3.Connection, name: str) -> bool:
    row = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def safe_query(db: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    try:
        rows = db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def load_state(data_root: Path) -> dict:
    state: dict = {
        "stores": [], "products": [], "campaigns": [], "events": [],
        "insights": [], "runs": [],
        "soul": "", "daily_logs": [],
    }
    db = open_db(data_root)
    if db is not None:
        try:
            state["stores"] = safe_query(db, "SELECT * FROM stores ORDER BY updated_at DESC")
            state["products"] = safe_query(db, "SELECT * FROM products ORDER BY created_at DESC")
            state["campaigns"] = safe_query(db, "SELECT * FROM campaigns ORDER BY started_at DESC")
            state["events"] = safe_query(db, "SELECT * FROM events ORDER BY ts DESC LIMIT 500")
            state["insights"] = safe_query(db, "SELECT * FROM insights ORDER BY verified_count DESC, confidence DESC LIMIT 100")
            state["runs"] = safe_query(db, "SELECT * FROM runs ORDER BY started_at DESC LIMIT 200")
        finally:
            db.close()

    soul_path = data_root / "SOUL.md"
    if soul_path.exists():
        state["soul"] = soul_path.read_text(encoding="utf-8")

    mem_dir = data_root / "memory"
    if mem_dir.exists():
        logs = []
        for f in sorted(mem_dir.glob("*.md"), reverse=True):
            if f.name == "insights.md":
                continue
            logs.append({"date": f.stem, "content": f.read_text(encoding="utf-8")})
        state["daily_logs"] = logs
    return state


# ---------- Context builders per page ----------
def kpis(state: dict) -> dict:
    now = int(time.time())
    week = now - 7 * 86400
    return {
        "stores": len(state["stores"]),
        "active_campaigns": sum(1 for c in state["campaigns"] if c.get("status") in ("planned", "running")),
        "runs_7d": sum(1 for r in state["runs"] if (r.get("started_at") or 0) >= week),
        "events_7d": sum(1 for e in state["events"] if (e.get("ts") or 0) >= week),
    }


def index_ctx(state: dict) -> dict:
    return {
        "stores": state["stores"],
        "active_campaigns": [c for c in state["campaigns"] if c.get("status") in ("planned", "running")][:6],
        "recent_events": state["events"][:12],
        "recent_runs": state["runs"][:8],
        "kpis": kpis(state),
        "store_count": len(state["stores"]),
    }


def stores_ctx(state: dict) -> dict:
    by_store_p: dict[str, list[dict]] = {}
    for p in state["products"]:
        by_store_p.setdefault(p.get("store_id") or "—", []).append(p)
    by_store_e: dict[str, list[dict]] = {}
    for e in state["events"]:
        by_store_e.setdefault(e.get("store_id") or "—", []).append(e)
    return {
        "stores": state["stores"],
        "products_by_store": by_store_p,
        "events_by_store": by_store_e,
        "store_count": len(state["stores"]),
    }


def campaigns_ctx(state: dict) -> dict:
    return {
        "campaigns": state["campaigns"],
        "runs": state["runs"],
        "store_count": len(state["stores"]),
    }


def runs_ctx(state: dict) -> dict:
    return {"runs": state["runs"], "store_count": len(state["stores"])}


def memory_ctx(state: dict) -> dict:
    return {
        "events": state["events"],
        "insights": state["insights"],
        "soul": state["soul"],
        "daily_logs": state["daily_logs"],
        "store_count": len(state["stores"]),
    }


# ---------- Main ----------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    p.add_argument("--output-root", default=None)
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    data_root = Path(args.data_root).expanduser().resolve()
    out_root = Path(args.output_root).expanduser().resolve() if args.output_root else (data_root / "dashboard")

    if not data_root.exists():
        msg = f"Data root not found: {data_root}. Run init_store.py first."
        print(json.dumps({"error": msg}), file=sys.stderr)
        return 2

    out_root.mkdir(parents=True, exist_ok=True)
    state = load_state(data_root)

    pages = {
        "index.html": T.render_index(index_ctx(state)),
        "stores.html": T.render_stores(stores_ctx(state)),
        "campaigns.html": T.render_campaigns(campaigns_ctx(state)),
        "runs.html": T.render_runs(runs_ctx(state)),
        "memory.html": T.render_memory(memory_ctx(state)),
    }
    total_bytes = 0
    for filename, html_text in pages.items():
        path = out_root / filename
        path.write_text(html_text, encoding="utf-8")
        total_bytes += len(html_text.encode("utf-8"))

    run_id = args.run_id or str(uuid.uuid4())
    result = {
        "run_id": run_id,
        "skill": "lumicc-dashboard",
        "status": "success",
        "pages_rendered": len(pages),
        "total_size_kb": round(total_bytes / 1024, 1),
        "dashboard_index_path": str(out_root / "index.html"),
        "warnings": [],
    }

    # Record to ~/.commerce-os/runs and events if DB exists
    db_path = data_root / "store.db"
    if db_path.exists():
        try:
            db = sqlite3.connect(db_path)
            run_dir = data_root / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            db.execute(
                "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, "lumicc-dashboard", None, int(time.time()), int(time.time()), "success",
                 str(run_dir / "result.json")),
            )
            db.execute(
                "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                (None, int(time.time()), "task",
                 f"lumicc-dashboard: rendered {len(pages)} pages to {out_root}"),
            )
            db.commit()
            db.close()
        except sqlite3.Error:
            result["warnings"].append("Could not log run to store.db")

    # Open browser in coder mode
    if not args.no_open and not args.quiet_stdout and not args.notify_channel:
        try:
            webbrowser.open(f"file://{out_root / 'index.html'}")
        except Exception as e:
            result["warnings"].append(f"Could not open browser: {e}")

    # Agent-mode notification
    if args.notify_channel:
        try:
            # Import the watch's notify (shared protocol)
            outbox = data_root / "outbox"
            outbox.mkdir(parents=True, exist_ok=True)
            (outbox / f"{uuid.uuid4()}.json").write_text(json.dumps({
                "id": str(uuid.uuid4()),
                "ts": int(time.time()),
                "skill": "lumicc-dashboard",
                "run_id": run_id,
                "channel": args.notify_channel,
                "target": args.notify_target,
                "title": "📊 仪表盘已刷新",
                "body_md": f"{len(pages)} 页 · {result['total_size_kb']} KB · 打开 file://{out_root/'index.html'}",
                "severity": "info",
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            result["warnings"].append(f"Could not write notification: {e}")

    if args.quiet_stdout:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"✓ {len(pages)} pages rendered ({result['total_size_kb']} KB)")
        print(f"  Open: file://{out_root / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
