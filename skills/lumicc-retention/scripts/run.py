#!/usr/bin/env python3
"""lumicc-retention orchestrator — dispatches modes.

Usage:
    python3 run.py --mode rfm --csv orders.csv --store-id ID
    python3 run.py --mode winback --csv orders.csv --winback-days-inactive 60
    python3 run.py --mode subscription --csv orders.csv
    python3 run.py --mode vip --csv orders.csv --vip-top-percent 3
    python3 run.py --mode repeat --csv orders.csv
    python3 run.py --mode all --csv orders.csv --notify-channel feishu
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
import csv_parser as cp
import rfm as rfm_mod
import repeat_paths as rp_mod
import winback as wb_mod
import subscription as sub_mod
import vip as vip_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path:
    return ROOT / "store.db"


def ensure_segments_table() -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("""
        CREATE TABLE IF NOT EXISTS customer_segments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id TEXT,
          customer_id TEXT NOT NULL,
          email TEXT,
          segment TEXT,
          recency_days INTEGER,
          frequency INTEGER,
          monetary_usd REAL,
          rfm_code TEXT,
          ltv_usd REAL,
          ts INTEGER NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_seg_cust ON customer_segments(customer_id, ts)")
        db.commit()
    finally:
        db.close()


def get_store_name(store_id: str | None) -> str | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT name FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT name FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return row["name"] if row else None
    finally:
        db.close()


def persist_segments(store_id: str | None, classified: list[dict]) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    ts = int(time.time())
    try:
        for c in classified:
            db.execute(
                "INSERT INTO customer_segments (store_id, customer_id, email, segment, "
                "recency_days, frequency, monetary_usd, rfm_code, ltv_usd, ts) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (store_id, c["customer_id"], c.get("email"), c["segment"],
                 c["recency_days"], c["frequency"], c["monetary_usd"],
                 c["rfm_code"], c["ltv_usd"], ts),
            )
        db.commit()
    finally:
        db.close()


def append_event(store_id: str | None, content: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), "task", content))
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
            (run_id, "lumicc-retention", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


# ---------- Main ----------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", required=True,
                   choices=["rfm", "repeat", "winback", "subscription", "vip", "all"])
    p.add_argument("--csv", required=True, help="Customer-orders CSV path")
    p.add_argument("--store-id", default=None)
    p.add_argument("--winback-days-inactive", type=int, default=90)
    p.add_argument("--vip-top-percent", type=float, default=5.0)
    p.add_argument("--subscription-min-repeat-rate", type=float, default=0.20)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True); (ROOT / "runs").mkdir(exist_ok=True)
    ensure_segments_table()
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(json.dumps({"error": f"CSV file not found: {csv_path}"}), file=sys.stderr)
        return 2

    try:
        orders = list(cp.iter_orders(csv_path))
    except Exception as e:
        print(json.dumps({"error": f"CSV parse failed: {e}"}), file=sys.stderr)
        return 2

    if not orders:
        print(json.dumps({"error": "No valid orders parsed from CSV."}), file=sys.stderr)
        return 2

    store_name = get_store_name(args.store_id)
    deliverables: list[dict] = []
    metrics: dict = {"total_orders": len(orders)}

    # Aggregate by customer (cheap; do once if any mode needs it)
    needs_rfm = args.mode in ("rfm", "winback", "vip", "all")
    needs_repeat = args.mode in ("repeat", "all")
    needs_subscription = args.mode in ("subscription", "all")
    classified: list[dict] = []
    repeat_analysis: dict | None = None
    sub_candidates: list[dict] = []
    eligible_winback: list[dict] = []
    winback_drafts: list[dict] = []
    vips: list[dict] = []
    vip_drafts: list[dict] = []

    if needs_rfm:
        by_cust = cp.aggregate_by_customer(orders)
        classified = rfm_mod.classify(by_cust)
        metrics["total_customers"] = len(classified)

    if args.mode in ("rfm", "all"):
        report_md = rfm_mod.render_report_md(classified)
        path = run_dir / "rfm-report.md"
        path.write_text(report_md, encoding="utf-8")
        persist_segments(args.store_id, classified)
        summary = rfm_mod.segment_summary(classified)
        metrics["champions_count"] = summary["Champions"]["count"]
        metrics["at_risk_count"] = summary["At Risk"]["count"]
        metrics["median_ltv_usd"] = round(
            sorted([c["ltv_usd"] for c in classified])[len(classified)//2] if classified else 0, 2,
        )
        deliverables.append({"type": "rfm_report_md", "path": str(path),
                              "segment_summary": summary})

    if needs_repeat:
        repeat_analysis = rp_mod.analyze(orders)
        path = run_dir / "repeat-paths.md"
        path.write_text(rp_mod.render_report_md(repeat_analysis), encoding="utf-8")
        metrics["repeat_rate"] = repeat_analysis["overall_repeat_rate"]
        deliverables.append({"type": "repeat_paths_md", "path": str(path),
                              "overall_repeat_rate": repeat_analysis["overall_repeat_rate"]})

    if args.mode in ("winback", "all"):
        eligible_winback = wb_mod.find_eligible(classified, days_inactive=args.winback_days_inactive)
        winback_drafts = [wb_mod.draft_email(c, store_name=store_name) for c in eligible_winback]
        csv_path_out = run_dir / "winback-segment.csv"
        csv_path_out.write_text(wb_mod.render_segment_csv(eligible_winback), encoding="utf-8")
        md_path = run_dir / "winback-drafts.md"
        md_path.write_text(wb_mod.render_drafts_md(winback_drafts), encoding="utf-8")
        metrics["winback_eligible_count"] = len(eligible_winback)
        deliverables.append({"type": "winback_segment_csv", "path": str(csv_path_out)})
        deliverables.append({"type": "winback_drafts_md", "path": str(md_path),
                              "count": len(winback_drafts)})

    if needs_subscription:
        sub_candidates = sub_mod.analyze(orders, min_repeat_rate=args.subscription_min_repeat_rate)
        path = run_dir / "subscription-candidates.md"
        path.write_text(sub_mod.render_report_md(sub_candidates), encoding="utf-8")
        metrics["subscription_candidate_count"] = len(sub_candidates)
        deliverables.append({"type": "subscription_candidates_md", "path": str(path),
                              "count": len(sub_candidates)})

    if args.mode in ("vip", "all"):
        vips = vip_mod.find_vips(classified, top_percent=args.vip_top_percent)
        vip_drafts = [vip_mod.draft_outreach(c, store_name=store_name) for c in vips]
        path = run_dir / "vip-outreach.md"
        path.write_text(vip_mod.render_report_md(vips, vip_drafts), encoding="utf-8")
        metrics["vip_count"] = len(vips)
        deliverables.append({"type": "vip_outreach_drafts_md", "path": str(path),
                              "count": len(vips)})

    # Render unified HTML
    html_path = run_dir / "report.html"
    warnings: list[str] = []
    try:
        page_html = render_mod.render_page(
            run_id=run_id, mode=args.mode, store_name=store_name or "",
            metrics=metrics, deliverables=deliverables,
            rfm_classified=classified if classified else None,
            winback_drafts=winback_drafts if args.mode in ("winback", "all") else None,
            vips=vips if args.mode in ("vip", "all") else None,
            vip_drafts=vip_drafts if args.mode in ("vip", "all") else None,
            subscription_candidates=sub_candidates if needs_subscription else None,
            repeat_analysis=repeat_analysis if needs_repeat else None,
            html_path=html_path,
        )
        html_path.write_text(page_html, encoding="utf-8")
    except Exception as e:
        warnings.append(f"HTML render failed: {e}")

    result = {
        "run_id": run_id,
        "skill": "lumicc-retention",
        "mode": args.mode,
        "status": "success" if not warnings else "partial",
        "store_id": args.store_id,
        "metrics": metrics,
        "deliverables": deliverables,
        "report_html": str(html_path),
        "warnings": warnings,
        "next_recommended_skill": (
            "lumicc-content" if metrics.get("winback_eligible_count", 0) > 5 else None
        ),
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run(run_id, args.store_id, "success", str(run_dir / "result.json"))
    append_event(args.store_id,
                 f"lumicc-retention: mode '{args.mode}' processed {len(orders)} orders, "
                 f"produced {len(deliverables)} deliverable(s)")

    if not args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "mode": args.mode,
                          "metrics": metrics,
                          "deliverables_count": len(deliverables)},
                         ensure_ascii=False, indent=2))

    if args.notify_channel:
        body_parts = [f"- {k}: {v}" for k, v in metrics.items()]
        body_parts.append("\n产出文件：")
        for d in deliverables:
            body_parts.append(f"- {d.get('type')}: {d.get('path')}")
        severity = "warn" if metrics.get("at_risk_count", 0) > 5 else "info"
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"📊 客户留存报告 · {args.mode}",
            body_md="\n".join(body_parts), severity=severity,
            skill="lumicc-retention", run_id=run_id,
        )

    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "mode": args.mode,
                          "metrics": metrics,
                          "deliverables_count": len(deliverables)},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
