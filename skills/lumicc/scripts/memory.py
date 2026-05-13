#!/usr/bin/env python3
"""Three-layer memory CRUD for Cross-Border Commerce OS.

Layer 1: events (SQLite) + memory/YYYY-MM-DD.md (append-only Markdown)
Layer 2: insights (SQLite) + memory/insights.md (curated)
Layer 3: SOUL.md (user-edited only — this script never auto-writes Layer 3;
         it only proposes changes via stdout for the agent to relay)

Usage:
    # Layer 1
    python3 memory.py log --store STORE_ID --category decision --content "Approved SKU foo"
    python3 memory.py read-day [--date 2026-05-08]

    # Layer 2
    python3 memory.py insight --store STORE_ID --category listing --content "..." --confidence 0.7
    python3 memory.py insights-list [--store STORE_ID] [--min-confidence 0.5]

    # Layer 3
    python3 memory.py soul-read
    python3 memory.py soul-propose --rule "Target gross margin >= 40%"
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path.home() / ".commerce-os"


def open_db() -> sqlite3.Connection:
    db = sqlite3.connect(ROOT / "store.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def today() -> str:
    return time.strftime("%Y-%m-%d")


def now_ts() -> int:
    return int(time.time())


# ---------- Layer 1: events ----------
def log_event(store_id: str | None, category: str, content: str) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "memory").mkdir(exist_ok=True)
    db = open_db()
    try:
        ts = now_ts()
        cur = db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, ts, category, content),
        )
        db.commit()
        eid = cur.lastrowid
    finally:
        db.close()

    md = ROOT / "memory" / f"{today()}.md"
    tag = f"[{category}]" if category else ""
    md.write_text(
        (md.read_text(encoding="utf-8") if md.exists() else "")
        + f"\n---\n{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))} {tag} store={store_id or '-'}\n---\n\n{content}\n",
        encoding="utf-8",
    )
    return {"id": eid, "ts": ts}


def read_day(date: str | None) -> str:
    target = ROOT / "memory" / f"{date or today()}.md"
    return target.read_text(encoding="utf-8") if target.exists() else ""


# ---------- Layer 2: insights ----------
def add_insight(store_id: str | None, category: str, content: str, confidence: float) -> dict:
    db = open_db()
    try:
        # Verified-count merge: same store + category + content → bump count
        row = db.execute(
            "SELECT id, verified_count FROM insights WHERE store_id IS ? AND category=? AND content=?",
            (store_id, category, content),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE insights SET verified_count = verified_count + 1, confidence = MIN(0.99, confidence + 0.05), ts = ? WHERE id = ?",
                (now_ts(), row["id"]),
            )
            iid = row["id"]
        else:
            cur = db.execute(
                "INSERT INTO insights (store_id, ts, category, content, confidence, verified_count) VALUES (?,?,?,?,?,1)",
                (store_id, now_ts(), category, content, confidence),
            )
            iid = cur.lastrowid
        db.commit()
        return {"id": iid}
    finally:
        db.close()


def list_insights(store_id: str | None, min_confidence: float) -> list[dict]:
    db = open_db()
    try:
        q = "SELECT * FROM insights WHERE confidence >= ?"
        params: list = [min_confidence]
        if store_id:
            q += " AND store_id = ?"
            params.append(store_id)
        q += " ORDER BY verified_count DESC, confidence DESC LIMIT 200"
        return [dict(r) for r in db.execute(q, params)]
    finally:
        db.close()


# ---------- Layer 3: SOUL ----------
def soul_read() -> str:
    p = ROOT / "SOUL.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def soul_propose(rule: str) -> dict:
    """Never auto-write Layer 3. Return a structured proposal for the agent to surface."""
    return {
        "type": "soul_proposal",
        "proposed_rule": rule,
        "current_soul_path": str(ROOT / "SOUL.md"),
        "instruction_to_user": (
            "If you accept, add the rule manually to SOUL.md. "
            "The skill will not write to SOUL.md without your edit."
        ),
    }


# ---------- env loader ----------
def load_env() -> dict:
    """Load credentials from ~/.commerce-os/.env if present, else from process env."""
    env: dict[str, str] = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log")
    p_log.add_argument("--store", default=None)
    p_log.add_argument("--category", default="observation")
    p_log.add_argument("--content", required=True)

    p_day = sub.add_parser("read-day")
    p_day.add_argument("--date", default=None)

    p_ins = sub.add_parser("insight")
    p_ins.add_argument("--store", default=None)
    p_ins.add_argument("--category", required=True)
    p_ins.add_argument("--content", required=True)
    p_ins.add_argument("--confidence", type=float, default=0.5)

    p_il = sub.add_parser("insights-list")
    p_il.add_argument("--store", default=None)
    p_il.add_argument("--min-confidence", type=float, default=0.5)

    sub.add_parser("soul-read")
    p_sp = sub.add_parser("soul-propose")
    p_sp.add_argument("--rule", required=True)

    sub.add_parser("env-dump")  # for debugging

    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "memory").mkdir(exist_ok=True)

    if args.cmd == "log":
        print(json.dumps(log_event(args.store, args.category, args.content)))
    elif args.cmd == "read-day":
        print(read_day(args.date))
    elif args.cmd == "insight":
        print(json.dumps(add_insight(args.store, args.category, args.content, args.confidence)))
    elif args.cmd == "insights-list":
        print(json.dumps(list_insights(args.store, args.min_confidence), ensure_ascii=False, indent=2))
    elif args.cmd == "soul-read":
        print(soul_read())
    elif args.cmd == "soul-propose":
        print(json.dumps(soul_propose(args.rule), ensure_ascii=False, indent=2))
    elif args.cmd == "env-dump":
        env = load_env()
        # Mask values
        masked = {k: (v[:4] + "***" if v and len(v) > 6 else "***") for k, v in env.items() if k.startswith(("SHOPIFY_", "AMAZON_", "TIKTOK_", "ETSY_", "JUNGLE_", "KLAVIYO_", "OPENAI_", "ANTHROPIC_"))}
        print(json.dumps(masked, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
