#!/usr/bin/env python3
"""Assets CRUD module for Lumicc.

Records generated images/videos/prompts to ~/.commerce-os/store.db (assets table)
and helps surface them in the dashboard. Honors LUMICC_DATA_ROOT env var.

Usage as a module:
    from assets import record_asset, list_assets, delete_asset, asset_stats

CLI:
    python3 assets.py list [--kind image] [--store STORE_ID] [--limit 20]
    python3 assets.py stats [--days 30]
    python3 assets.py delete --id ASSET_ID
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path


def _data_root() -> Path:
    env = os.environ.get("LUMICC_DATA_ROOT")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".commerce-os"


def _open_db() -> sqlite3.Connection:
    root = _data_root()
    db = sqlite3.connect(root / "store.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _now_ts() -> int:
    return int(time.time())


def _ensure_table(db: sqlite3.Connection) -> None:
    """Backwards-compat safety: create assets table if missing.

    Old store.db (v1) doesn't have it. We create-on-demand so this module
    works against any schema version >= 1.
    """
    db.executescript(
        """
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
    )


def record_asset(
    *,
    kind: str,
    path: str | Path,
    store_id: str | None = None,
    sku: str | None = None,
    prompt: str | None = None,
    revised_prompt: str | None = None,
    model: str | None = None,
    provider: str = "evolink",
    cost_usd: float = 0.0,
    run_id: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Insert one asset row, return its UUID."""
    if kind not in ("image", "video", "prompt"):
        raise ValueError(f"invalid kind: {kind!r}")
    asset_id = str(uuid.uuid4())
    p = Path(path).expanduser() if path else None
    size_bytes: int | None = None
    abs_path = ""
    if p is not None:
        try:
            abs_path = str(p.resolve())
            if p.exists() and p.is_file():
                size_bytes = p.stat().st_size
        except OSError:
            abs_path = str(p)
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    db = _open_db()
    try:
        _ensure_table(db)
        db.execute(
            "INSERT INTO assets (id, store_id, sku, kind, prompt, revised_prompt, "
            "model, provider, path, cost_usd, size_bytes, created_at, run_id, metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, store_id, sku, kind, prompt, revised_prompt, model,
             provider, abs_path, float(cost_usd or 0.0), size_bytes,
             _now_ts(), run_id, meta_json),
        )
        db.commit()
    finally:
        db.close()
    return asset_id


def list_assets(
    *,
    store_id: str | None = None,
    sku: str | None = None,
    kind: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
    since_ts: int | None = None,
) -> list[dict]:
    """Return matching asset rows, sorted DESC by created_at.

    Each dict gets a computed 'exists_on_disk' bool.
    """
    db = _open_db()
    try:
        _ensure_table(db)
        clauses: list[str] = []
        params: list = []
        if store_id is not None:
            clauses.append("store_id = ?")
            params.append(store_id)
        if sku is not None:
            clauses.append("sku = ?")
            params.append(sku)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if since_ts is not None:
            clauses.append("created_at >= ?")
            params.append(int(since_ts))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM assets{where} ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    finally:
        db.close()

    for r in rows:
        p = r.get("path") or ""
        try:
            r["exists_on_disk"] = bool(p) and Path(p).exists()
        except OSError:
            r["exists_on_disk"] = False
    return rows


def delete_asset(asset_id: str) -> bool:
    """Delete row + best-effort file removal. Returns True if row existed."""
    db = _open_db()
    try:
        _ensure_table(db)
        row = db.execute("SELECT path FROM assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            return False
        path = row["path"]
        db.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        db.commit()
    finally:
        db.close()
    if path:
        try:
            p = Path(path)
            if p.exists() and p.is_file():
                p.unlink()
        except OSError:
            pass
    return True


def asset_stats(store_id: str | None = None, days: int = 30) -> dict:
    """Aggregate stats over the last `days` days."""
    cutoff = _now_ts() - int(days) * 86400
    db = _open_db()
    try:
        _ensure_table(db)
        clauses = ["created_at >= ?"]
        params: list = [cutoff]
        if store_id is not None:
            clauses.append("store_id = ?")
            params.append(store_id)
        where = " WHERE " + " AND ".join(clauses)
        rows = [dict(r) for r in db.execute(
            f"SELECT id, kind, model, cost_usd, path FROM assets{where}",
            params,
        ).fetchall()]
    finally:
        db.close()

    by_kind: dict[str, int] = {}
    by_model: dict[str, int] = {}
    total_cost = 0.0
    missing = 0
    for r in rows:
        k = r.get("kind") or "?"
        by_kind[k] = by_kind.get(k, 0) + 1
        m = r.get("model") or "—"
        by_model[m] = by_model.get(m, 0) + 1
        total_cost += float(r.get("cost_usd") or 0.0)
        p = r.get("path") or ""
        try:
            if not p or not Path(p).exists():
                missing += 1
        except OSError:
            missing += 1
    return {
        "total": len(rows),
        "by_kind": by_kind,
        "by_model": by_model,
        "total_cost_usd": round(total_cost, 4),
        "count_missing_on_disk": missing,
        "days": int(days),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--store", default=None)
    p_list.add_argument("--sku", default=None)
    p_list.add_argument("--kind", default=None)
    p_list.add_argument("--run-id", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--store", default=None)
    p_stats.add_argument("--days", type=int, default=30)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)

    args = parser.parse_args()
    if args.cmd == "list":
        out = list_assets(
            store_id=args.store, sku=args.sku, kind=args.kind,
            run_id=args.run_id, limit=args.limit,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "stats":
        print(json.dumps(asset_stats(args.store, args.days), ensure_ascii=False, indent=2))
    elif args.cmd == "delete":
        ok = delete_asset(args.id)
        print(json.dumps({"deleted": ok}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
