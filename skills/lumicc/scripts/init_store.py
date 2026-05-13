#!/usr/bin/env python3
"""Initialize or migrate ~/.commerce-os/store.db.

Idempotent: safe to run multiple times. Prints current store-memory snapshot
as JSON to stdout. Exit code 0 on success, 1 on error.

Usage:
    python3 init_store.py                  # init/migrate, print snapshot
    python3 init_store.py --reset          # destructive: wipe + re-init (asks confirm)
    python3 init_store.py --root DIR       # custom root (default ~/.commerce-os)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 2

DDL_V1 = """
CREATE TABLE IF NOT EXISTS _meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS stores (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT,
  url TEXT,
  currency TEXT DEFAULT 'USD',
  target_market TEXT,
  stage TEXT,
  niche TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  store_id TEXT REFERENCES stores(id) ON DELETE CASCADE,
  sku TEXT,
  title TEXT,
  status TEXT,
  cost_usd REAL,
  price_usd REAL,
  supplier_url TEXT,
  data_json TEXT,
  created_at INTEGER,
  updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_products_store ON products(store_id);
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  store_id TEXT,
  type TEXT,
  status TEXT,
  budget_usd REAL,
  started_at INTEGER,
  ended_at INTEGER,
  results_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_campaigns_store ON campaigns(store_id);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id TEXT,
  ts INTEGER NOT NULL,
  category TEXT,
  content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_store_ts ON events(store_id, ts DESC);
CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id TEXT,
  ts INTEGER NOT NULL,
  category TEXT,
  content TEXT NOT NULL,
  confidence REAL DEFAULT 0.5,
  verified_count INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS preferences (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  skill TEXT NOT NULL,
  store_id TEXT,
  started_at INTEGER,
  finished_at INTEGER,
  status TEXT,
  result_path TEXT
);
"""

DDL_V2 = """
CREATE TABLE IF NOT EXISTS assets (
  id            TEXT PRIMARY KEY,
  store_id      TEXT,
  sku           TEXT,
  kind          TEXT NOT NULL,
  prompt        TEXT,
  revised_prompt TEXT,
  model         TEXT,
  provider      TEXT,
  path          TEXT,
  cost_usd      REAL,
  size_bytes    INTEGER,
  created_at    INTEGER NOT NULL,
  run_id        TEXT,
  metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_assets_store ON assets(store_id);
CREATE INDEX IF NOT EXISTS idx_assets_sku   ON assets(sku);
CREATE INDEX IF NOT EXISTS idx_assets_run   ON assets(run_id);
CREATE INDEX IF NOT EXISTS idx_assets_kind  ON assets(kind);
"""

MIGRATIONS: dict[int, list[str]] = {1: [DDL_V1], 2: [DDL_V2]}


def get_root(root: str | None = None) -> Path:
    if root:
        return Path(root).expanduser()
    return Path.home() / ".commerce-os"


def ensure_root(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    soul = root / "SOUL.md"
    if not soul.exists():
        soul.write_text(
            "# My Cross-Border Commerce SOUL\n\n"
            "Edit this file with rules you want every workflow to respect.\n\n"
            "Example:\n"
            "- Target gross margin >= 40%\n"
            "- I approve any spend > $500 manually\n"
            "- Primary market: US English-speaking\n",
            encoding="utf-8",
        )


def open_db(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(root / "store.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def current_version(db: sqlite3.Connection) -> int:
    db.executescript("CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT);")
    row = db.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    return int(row["value"]) if row else 0


def apply_migrations(db: sqlite3.Connection) -> int:
    have = current_version(db)
    for v in sorted(MIGRATIONS):
        if v <= have:
            continue
        for stmt in MIGRATIONS[v]:
            db.executescript(stmt)
        db.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version', ?)",
            (str(v),),
        )
        db.commit()
    return SCHEMA_VERSION


def snapshot(db: sqlite3.Connection) -> dict:
    stores = [dict(r) for r in db.execute("SELECT * FROM stores")]
    campaigns = [
        dict(r) for r in db.execute("SELECT id, store_id, type, status FROM campaigns WHERE status IN ('planned','running')")
    ]
    events_count = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    runs_count = db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    return {
        "schema_version": current_version(db),
        "stores": stores,
        "active_campaigns": campaigns,
        "events_total": events_count,
        "runs_total": runs_count,
    }


def reset(root: Path, force: bool = False) -> None:
    if not force:
        ans = input(
            f"⚠️  This will delete {root}/store.db and memory/. Type 'yes' to continue: "
        ).strip().lower()
        if ans != "yes":
            print("Aborted.", file=sys.stderr)
            sys.exit(2)
    db_path = root / "store.db"
    if db_path.exists():
        db_path.unlink()
    mem = root / "memory"
    if mem.exists():
        for p in mem.glob("*.md"):
            p.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--root", default=None)
    parser.add_argument("--force", action="store_true", help="skip reset confirmation")
    args = parser.parse_args()

    root = get_root(args.root)
    if args.reset:
        reset(root, force=args.force)

    ensure_root(root)
    db = open_db(root)
    try:
        apply_migrations(db)
        snap = snapshot(db)
    finally:
        db.close()

    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
