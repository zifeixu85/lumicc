#!/usr/bin/env python3
"""Find the next winning SKU. Read existing winners from store.db,
score candidates, and emit ranked recommendations.

Two modes:
  - With explicit candidates JSON (--candidates file.json) — score and rank them.
  - Without — emit a research worksheet template (built-in fallback when no
    Amazon revenue adapter is configured).

Usage:
    python3 run.py --store-id ID --candidates new-candidates.json
    python3 run.py --store-id ID  # produces a worksheet
    python3 run.py --store-id ID --notify-channel feishu --quiet-stdout
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
import score as score_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"


def get_store_name(store_id: str | None) -> str:
    if not db_path().exists():
        return ""
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT name FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT name FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return (row["name"] if row else "") or ""
    finally:
        db.close()


def db_path() -> Path:
    return ROOT / "store.db"


def existing_winners(store_id: str | None) -> list[dict]:
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        q = "SELECT * FROM products WHERE status='active'"
        params: list = []
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        q += " ORDER BY (COALESCE(price_usd,0) - COALESCE(cost_usd,0)) DESC LIMIT 10"
        return [dict(r) for r in db.execute(q, params)]
    finally:
        db.close()


def soul_min_margin() -> float:
    soul = ROOT / "SOUL.md"
    if not soul.exists():
        return 0.0
    text = soul.read_text(encoding="utf-8").lower()
    import re
    m = re.search(r"margin[^0-9]*([0-9]{1,3})\s*%", text)
    return float(m.group(1)) / 100 if m else 0.0


def write_worksheet(out_dir: Path, store_id: str | None, winners: list[dict]) -> Path:
    title_list = ", ".join(w.get("title", "—") for w in winners[:3]) or "(no winners yet)"
    md = f"""# Expansion Research Worksheet

> No Amazon revenue adapter detected — fill in this worksheet by hand (or wire up an adapter and re-run).
> The same fields will be auto-populated when you have Jungle Scout / Helium 10 / similar configured.

**Store**: `{store_id or '—'}`
**Current top performers**: {title_list}

## Step 1 — List 5-10 candidate adjacent SKUs

For each candidate, fill in the JSON skeleton below. Save as `candidates.json`, then re-run:

```bash
python3 run.py --store-id {store_id or 'STORE_ID'} --candidates candidates.json
```

## Candidate template (copy per SKU)

```json
{{
  "title": "Magnetic Spice Rack 8-jar",
  "landed_cost_usd": 4.20,
  "suggested_retail_usd": 24.99,
  "demand_signals": {{
    "amazon_revenue_yoy_pct": 30,
    "tiktok_hashtag_growth_pct": 80,
    "google_trends_slope": 8
  }},
  "content_angle": "before_after",
  "has_visual_hook": true,
  "supplier": {{
    "name": "Acme Magnetics Co.",
    "alibaba_verified": true,
    "moq": 50,
    "response_rate": 0.95,
    "existing_relationship": false,
    "sample_ordered": false
  }},
  "fulfillment": {{
    "weight_g": 320,
    "fragile": false,
    "battery": false,
    "liquid": false,
    "hazardous": false,
    "oversized": false,
    "trademarked": false
  }}
}}
```

## Step 2 — Adjacency paths (suggest at least one per path)

- **Co-purchase**: products bought with your hero (check order history if you have it)
- **Same niche, different use-case**: e.g., kitchen magnetic rack → spice rack
- **Cross-niche, same audience**: e.g., pet owners also buy home cleaning
- **Same supplier upsell**: ask current suppliers what else they make

## Step 3 — Score each candidate

Lumicc applies the 5-factor matrix (see `references/scoring-matrix.md`):
margin × 0.25 + demand × 0.25 + content × 0.20 + supplier × 0.15 + fulfillment × 0.15

Threshold: `total ≥ 8.0` → order sample. `6.5–7.9` → watchlist. `< 6.5` → reject.
"""
    p = out_dir / "worksheet.md"
    p.write_text(md, encoding="utf-8")
    return p


def render_report_md(scored: list[dict]) -> str:
    if not scored:
        return "_No candidates scored._"
    lines = [f"# 扩品候选评分 ({len(scored)} 个)", ""]
    by_action: dict[str, list[dict]] = {"order_sample": [], "watchlist": [], "reject": []}
    for s in scored:
        by_action.setdefault(s["action"], []).append(s)

    if by_action["order_sample"]:
        lines.append(f"## 🟢 立即下单样品 ({len(by_action['order_sample'])})")
        for s in by_action["order_sample"]:
            lines.append(f"- **{s['title']}** — {s['total']}/10 — {s['reason']}")
        lines.append("")
    if by_action["watchlist"]:
        lines.append(f"## 🟡 观察名单 ({len(by_action['watchlist'])})")
        for s in by_action["watchlist"]:
            lines.append(f"- **{s['title']}** — {s['total']}/10 — {s['reason']}")
        lines.append("")
    if by_action["reject"]:
        lines.append(f"## 🔴 拒绝 ({len(by_action['reject'])})")
        for s in by_action["reject"]:
            lines.append(f"- {s['title']} — {s['total']}/10 — {s['reason']}")
        lines.append("")

    lines.append("## 详细评分")
    for s in scored:
        lines.append(f"\n### #{s['rank']} {s['title']} — **{s['total']}/10**")
        for fname, fdata in s["factors"].items():
            lines.append(f"- {fname}: {fdata['score']}/10 (w={fdata['weight']}) — {fdata['evidence']}")
    return "\n".join(lines)


def append_event(store_id: str | None, content: str) -> None:
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


def append_run(run_id: str, store_id: str | None, status: str, result_path: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-expand", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--candidates", default=None, help="JSON file of candidate dicts")
    p.add_argument("--min-score", type=float, default=6.5)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True)
    (ROOT / "runs").mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    winners = existing_winners(args.store_id)
    soul = soul_min_margin()

    if args.candidates:
        # Score path
        data = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = [data]
        scored = score_mod.rank(data, soul_min_margin=soul)
        report_md = render_report_md(scored)
        (run_dir / "report.md").write_text(report_md, encoding="utf-8")
        # Render interactive HTML decision board
        html_path = run_dir / "decision-board.html"
        try:
            page_html = render_mod.render_page(
                run_id=run_id, store_name=get_store_name(args.store_id),
                candidates=scored, soul_min_margin=soul,
                existing_winners=[w.get("title", "") for w in winners],
                html_path=html_path,
            )
            html_path.write_text(page_html, encoding="utf-8")
        except Exception as e:
            print(f"HTML render failed: {e}", file=sys.stderr)
        result = {
            "run_id": run_id, "skill": "lumicc-expand", "status": "success",
            "store_id": args.store_id,
            "soul_min_margin": soul,
            "existing_winners": [w.get("title") for w in winners],
            "candidates": scored,
            "report_path": str(run_dir / "report.md"),
            "decision_board_html": str(html_path),
            "next_recommended_skill": "lumicc-launch" if any(s["action"] == "order_sample" for s in scored) else None,
        }
        (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        n_sample = sum(1 for s in scored if s["action"] == "order_sample")
        append_event(args.store_id, f"lumicc-expand: scored {len(scored)} candidates; {n_sample} → order_sample")
        if not args.quiet_stdout:
            print(report_md)
        if args.notify_channel:
            notify_mod.notify(
                channel=args.notify_channel, target=args.notify_target,
                title=f"📦 {n_sample} 个新品候选可下样品（共 {len(scored)} 评分）",
                body_md=report_md, severity="info",
                skill="lumicc-expand", run_id=run_id,
            )
    else:
        # Worksheet path
        ws_path = write_worksheet(run_dir, args.store_id, winners)
        result = {
            "run_id": run_id, "skill": "lumicc-expand", "status": "partial",
            "mode": "worksheet", "store_id": args.store_id,
            "soul_min_margin": soul,
            "existing_winners": [w.get("title") for w in winners],
            "worksheet_path": str(ws_path),
            "next_action": "user fills candidates.json then re-runs with --candidates",
        }
        (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        append_event(args.store_id, f"lumicc-expand: worksheet generated at {ws_path}")
        if not args.quiet_stdout:
            print(ws_path.read_text(encoding="utf-8"))

    append_run(run_id, args.store_id, result["status"], str(run_dir / "result.json"))
    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "status": result["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
