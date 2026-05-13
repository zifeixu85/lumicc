#!/usr/bin/env python3
"""Keyword rank tracker — import from Google Search Console CSV / Ahrefs / etc.

GSC export format (Search Console → Performance → Export → CSV):
  Query,Clicks,Impressions,CTR,Position
  "magnetic knife rack","42","521","8.06%","12.3"
  ...

Other tools (Ahrefs, Semrush, ranxplorer) follow the same shape with slight
column renames. We accept a flexible mapping.

Persists to seo_keywords table for trend analysis. Computes rank delta vs
previous import for the same (keyword, target_market).
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path:
    return ROOT / "store.db"


def ensure_table() -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("""
        CREATE TABLE IF NOT EXISTS seo_keywords (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id TEXT,
          keyword TEXT NOT NULL,
          target_market TEXT,
          search_volume INTEGER,
          cpc REAL,
          current_rank INTEGER,
          prev_rank INTEGER,
          url TEXT,
          ts INTEGER NOT NULL,
          source TEXT
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_seo_kw_keyword ON seo_keywords(keyword, target_market, ts)")
        db.commit()
    finally:
        db.close()


def previous_rank(store_id: str | None, keyword: str, market: str | None) -> int | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        q = "SELECT current_rank FROM seo_keywords WHERE keyword=? "
        params: list = [keyword]
        if store_id:
            q += "AND store_id=? "
            params.append(store_id)
        if market:
            q += "AND target_market=? "
            params.append(market)
        q += "ORDER BY ts DESC LIMIT 1"
        row = db.execute(q, params).fetchone()
        return row["current_rank"] if row else None
    finally:
        db.close()


def insert_keyword(store_id: str | None, keyword: str, market: str | None,
                   current_rank: int | None, prev_rank: int | None,
                   search_volume: int | None, cpc: float | None,
                   url: str | None, source: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT INTO seo_keywords (store_id, keyword, target_market, search_volume, cpc, "
            "current_rank, prev_rank, url, ts, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (store_id, keyword, market, search_volume, cpc, current_rank, prev_rank,
             url, int(time.time()), source),
        )
        db.commit()
    finally:
        db.close()


def import_gsc_csv(csv_path: Path, store_id: str | None, market: str = "us",
                   source: str = "gsc") -> dict:
    """Import a GSC-style CSV. Returns a summary with deltas."""
    ensure_table()
    rows_processed = 0
    deltas: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Find the right columns (GSC: Query / Position; Ahrefs: Keyword / Position; ...)
        keyword_col = next((c for c in reader.fieldnames or [] if c.lower() in ("query", "keyword", "搜索词")), None)
        pos_col = next((c for c in reader.fieldnames or [] if c.lower() in ("position", "rank", "排名", "avg position", "average position")), None)
        impressions_col = next((c for c in reader.fieldnames or [] if c.lower() in ("impressions", "搜索量")), None)
        cpc_col = next((c for c in reader.fieldnames or [] if c.lower() in ("cpc", "$cpc")), None)
        url_col = next((c for c in reader.fieldnames or [] if c.lower() in ("page", "url", "landing page", "落地页")), None)
        if not keyword_col or not pos_col:
            return {"error": f"CSV missing keyword/position columns; got {reader.fieldnames}"}

        for row in reader:
            kw = (row[keyword_col] or "").strip()
            if not kw:
                continue
            try:
                pos = int(round(float(row[pos_col] or 0)))
            except (ValueError, TypeError):
                continue
            try:
                vol = int(row[impressions_col]) if impressions_col and row.get(impressions_col) else None
            except (ValueError, TypeError):
                vol = None
            try:
                cpc = float(row[cpc_col].lstrip("$")) if cpc_col and row.get(cpc_col) else None
            except (ValueError, TypeError):
                cpc = None
            url = (row.get(url_col) if url_col else None) or None

            prev = previous_rank(store_id, kw, market)
            insert_keyword(store_id, kw, market, pos, prev, vol, cpc, url, source)
            rows_processed += 1
            if prev is not None:
                delta = pos - prev  # positive = worse rank
                if abs(delta) >= 1:
                    deltas.append({"keyword": kw, "prev": prev, "current": pos, "delta": delta})

    deltas.sort(key=lambda x: x["delta"], reverse=True)  # worst movers first
    return {
        "rows_processed": rows_processed,
        "deltas": deltas,
        "biggest_drops": [d for d in deltas if d["delta"] > 0][:10],
        "biggest_climbs": sorted([d for d in deltas if d["delta"] < 0], key=lambda x: x["delta"])[:10],
    }


def render_report_md(summary: dict) -> str:
    lines = ["# 关键词排名追踪", ""]
    lines.append(f"**本次导入**: {summary['rows_processed']} 个关键词")
    drops = summary.get("biggest_drops") or []
    climbs = summary.get("biggest_climbs") or []
    if drops:
        lines.append(f"\n## 🔴 排名下降 Top {len(drops)}（小心）")
        for d in drops:
            lines.append(f"- `{d['keyword']}`: #{d['prev']} → #{d['current']} (+{d['delta']} 位)")
    if climbs:
        lines.append(f"\n## 🟢 排名上升 Top {len(climbs)}")
        for d in climbs:
            lines.append(f"- `{d['keyword']}`: #{d['prev']} → #{d['current']} ({d['delta']} 位)")
    if not drops and not climbs:
        lines.append("\n_首次导入，下次再跑就能看到 delta 趋势。_")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True)
    p.add_argument("--store-id", default=None)
    p.add_argument("--market", default="us")
    p.add_argument("--source", default="gsc", choices=["gsc", "ahrefs", "semrush", "manual"])
    p.add_argument("--out", default=None)
    args = p.parse_args()
    summary = import_gsc_csv(Path(args.csv), args.store_id, args.market, args.source)
    report_md = render_report_md(summary)
    if args.out:
        Path(args.out).write_text(report_md, encoding="utf-8")
        print(json.dumps({"saved": args.out, "rows": summary.get("rows_processed", 0),
                          "drops": len(summary.get("biggest_drops") or []),
                          "climbs": len(summary.get("biggest_climbs") or [])},
                         ensure_ascii=False))
    else:
        print(report_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
