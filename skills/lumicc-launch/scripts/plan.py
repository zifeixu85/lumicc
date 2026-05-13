#!/usr/bin/env python3
"""Generate a 30-day cold-start plan for a new cross-border store.

Reads store info from ~/.commerce-os/store.db (or via CLI flags), runs the
resource estimator, then writes:
  - A `campaign` row (type='cold-start') with the full plan in results_json
  - A markdown plan file at ~/.commerce-os/runs/<run_id>/plan.md
  - An events row "Started cold-start 30-day plan"
  - Optionally notify (agent mode)

The plan is data-driven: schedule is generated from `templates/schedule.json`
so non-engineers can tune the SOP without code changes.

Usage:
  python3 plan.py --store-id STORE_ID
  python3 plan.py --store-id STORE_ID --notify-channel feishu --notify-target group:ops
  python3 plan.py --budget 1800 --hours 12 --platform shopify --niche "pet accessories"
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify as notify_mod
import resource_estimator as re_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"
RUNS_DIR = ROOT / "runs"
TEMPLATES_DIR = HERE.parent / "templates"


def db_path() -> Path:
    return ROOT / "store.db"


def get_store(store_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def load_schedule_template() -> list[dict]:
    """Load the 30-day schedule template (data-driven)."""
    p = TEMPLATES_DIR / "schedule.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return DEFAULT_SCHEDULE


def insert_campaign(camp_id: str, store_id: str | None, budget: float, plan_json: dict) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        ts = int(time.time())
        db.execute(
            "INSERT OR REPLACE INTO campaigns (id, store_id, type, status, budget_usd, "
            "started_at, ended_at, results_json) VALUES (?,?,?,?,?,?,?,?)",
            (camp_id, store_id, "cold-start", "running", budget, ts, None,
             json.dumps(plan_json, ensure_ascii=False)),
        )
        db.commit()
    finally:
        db.close()


def insert_event(store_id: str | None, category: str, content: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, int(time.time()), category, content),
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
            (run_id, "lumicc-launch", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def render_plan_md(plan: dict) -> str:
    lines: list[str] = []
    lines.append("# 30-Day Cold-Start Plan")
    lines.append("")
    info = plan.get("inputs", {})
    fz = plan.get("feasibility", {})
    lines.append(f"- **Store**: {info.get('niche', '-')} on {info.get('platform', '-')} → {info.get('target_market', '-')}")
    lines.append(f"- **Budget**: ${info.get('budget_usd', '-')}")
    lines.append(f"- **Time**: {info.get('hours_per_week', '-')} h/week")
    lines.append(f"- **Tier**: {fz.get('tier', '-')}  ·  First-sale-in-30d probability: {fz.get('first_sale_in_30d_probability', '-')}")
    if fz.get("issues"):
        lines.append("- **Risks**:")
        for i in fz["issues"]:
            lines.append(f"  - ⚠️ {i}")
    if fz.get("recommended_actions"):
        lines.append("- **Recommended adjustments**:")
        for a in fz["recommended_actions"]:
            lines.append(f"  - ✅ {a}")
    lines.append("")
    lines.append("## Milestones")
    for k, v in plan.get("milestones", {}).items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Daily schedule")
    cur_phase = None
    for day in plan.get("schedule", []):
        if day.get("phase") != cur_phase:
            cur_phase = day["phase"]
            lines.append(f"\n### {cur_phase}")
        tasks = "; ".join(day.get("tasks", []))
        slot = ", ".join(day.get("capability_slots", [])) or "—"
        lines.append(f"- **Day {day['day']}** — {tasks}  _(slots: {slot})_")
    lines.append("")
    lines.append("## Capability slots used in this plan")
    used = sorted({slot for d in plan.get("schedule", []) for slot in d.get("capability_slots", [])})
    for u in used:
        lines.append(f"- {u}")
    lines.append("")
    lines.append("> Slots are filled by whatever adapter you have configured (Shopify Admin token, Jungle Scout API, etc.).")
    lines.append("> Missing adapters fall back to built-in workflows. See `references/required-skills.md`.")
    return "\n".join(lines)


def build_plan(inputs: dict) -> dict:
    schedule = load_schedule_template()
    feasibility = re_mod.recommend(
        budget=inputs.get("budget_usd", 0) or 0,
        hours_week=inputs.get("hours_per_week", 0) or 0,
        tiktok_accounts=inputs.get("tiktok_accounts", 0) or 0,
    )
    milestones = {
        "Week 1 (Day 1-7)": "Niche validated; top 3 SKUs chosen; suppliers contacted",
        "Week 2 (Day 8-14)": "Store live; 3 products listed with full creative; theme polished",
        "Week 3 (Day 15-21)": "Content live across TikTok/IG; first 100 sessions logged",
        "Week 4 (Day 22-30)": "First sales reviewed; listings optimized; expansion candidates queued",
    }
    return {
        "version": "0.1.0",
        "inputs": inputs,
        "feasibility": feasibility,
        "milestones": milestones,
        "schedule": schedule,
    }


# ---------- Default schedule (fallback if templates/schedule.json missing) ----------
DEFAULT_SCHEDULE: list[dict] = [
    # Week 1 — Validation & Sourcing
    {"day": 1, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Validate niche with 3 signals (TikTok hashtag volume, Amazon revenue, Google Trends)"], "capability_slots": ["amazon_revenue_data"]},
    {"day": 2, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Pull 12 candidate ASINs; filter to top 5"], "capability_slots": ["amazon_revenue_data"]},
    {"day": 3, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Find 3-5 suppliers per top-5 ASIN"], "capability_slots": ["b2b_supplier_matching"]},
    {"day": 4, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Calculate landed cost + tariff for top candidates"], "capability_slots": ["landed_cost_duty"]},
    {"day": 5, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Margin math + final-pick top 3 SKUs"], "capability_slots": []},
    {"day": 6, "phase": "Week 1 — Validation & Sourcing", "tasks": ["User confirmation gate: budget, target margin, market"], "capability_slots": []},
    {"day": 7, "phase": "Week 1 — Validation & Sourcing", "tasks": ["Order samples (if budget allows) or commit on supplier rating"], "capability_slots": []},
    # Week 2 — Store Setup & Listing
    {"day": 8, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Register Shopify trial (or chosen platform)"], "capability_slots": []},
    {"day": 9, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Generate API credentials per api-credentials.md"], "capability_slots": []},
    {"day": 10, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Logo + brand basics (color + 2-font pair)"], "capability_slots": ["image_video_gen"]},
    {"day": 11, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Bulk product upload (3 products, ≥5 images each)"], "capability_slots": ["platform_write"]},
    {"day": 12, "phase": "Week 2 — Store Setup & Listing", "tasks": ["SEO titles + descriptions for all 3 listings"], "capability_slots": []},
    {"day": 13, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Collections, policies, shipping zones"], "capability_slots": ["platform_write"]},
    {"day": 14, "phase": "Week 2 — Store Setup & Listing", "tasks": ["Homepage hero banner + announcement bar"], "capability_slots": ["platform_write", "image_video_gen"]},
    # Week 3 — Content & Initial Traffic
    {"day": 15, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Plan TikTok content calendar (5 videos × hero SKU)"], "capability_slots": []},
    {"day": 16, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Shoot or generate first 5 TikTok videos"], "capability_slots": ["image_video_gen"]},
    {"day": 17, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Schedule TikTok posts (1-2/day)"], "capability_slots": ["social_publishing"]},
    {"day": 18, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Instagram carousel for hero SKU"], "capability_slots": ["social_publishing"]},
    {"day": 19, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Instagram Reels seeding"], "capability_slots": ["social_publishing"]},
    {"day": 20, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Pinterest pins (optional, free)"], "capability_slots": ["social_publishing"]},
    {"day": 21, "phase": "Week 3 — Content & Initial Traffic", "tasks": ["Reach out to 5-10 micro-influencers"], "capability_slots": []},
    # Week 4 — Monitor & Iterate
    {"day": 22, "phase": "Week 4 — Monitor & Iterate", "tasks": ["First metrics review: sessions, CR, top traffic source"], "capability_slots": ["platform_write"]},
    {"day": 23, "phase": "Week 4 — Monitor & Iterate", "tasks": ["Run lumicc-listing audit"], "capability_slots": []},
    {"day": 24, "phase": "Week 4 — Monitor & Iterate", "tasks": ["Apply top-3 listing fixes"], "capability_slots": ["platform_write"]},
    {"day": 25, "phase": "Week 4 — Monitor & Iterate", "tasks": ["First competitor watchtower run (lumicc-watch)"], "capability_slots": ["browser_snapshot"]},
    {"day": 26, "phase": "Week 4 — Monitor & Iterate", "tasks": ["Iterate on content cadence based on data"], "capability_slots": []},
    {"day": 27, "phase": "Week 4 — Monitor & Iterate", "tasks": ["Test TikTok ads (optional, if margin > 40%)"], "capability_slots": []},
    {"day": 28, "phase": "Week 4 — Monitor & Iterate", "tasks": ["First VoC pass if reviews exist (lumicc-voc)"], "capability_slots": ["review_ticket_signal"]},
    {"day": 29, "phase": "Week 4 — Monitor & Iterate", "tasks": ["Compute Week-4 KPIs (sales, AOV, CR)"], "capability_slots": []},
    {"day": 30, "phase": "Week 4 — Monitor & Iterate", "tasks": ["30-day retrospective + plan next cycle"], "capability_slots": []},
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--hours", type=float, default=None)
    p.add_argument("--platform", default=None)
    p.add_argument("--niche", default=None)
    p.add_argument("--target-market", default=None)
    p.add_argument("--tiktok-accounts", type=int, default=1)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    store = get_store(args.store_id)
    inputs = {
        "store_id": args.store_id or (store["id"] if store else None),
        "platform": args.platform or (store.get("platform") if store else None),
        "niche": args.niche or (store.get("niche") if store else None),
        "target_market": args.target_market or (store.get("target_market") if store else None),
        "budget_usd": args.budget if args.budget is not None else 1500,
        "hours_per_week": args.hours if args.hours is not None else 12,
        "tiktok_accounts": args.tiktok_accounts,
    }

    ROOT.mkdir(exist_ok=True)
    RUNS_DIR.mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    plan = build_plan(inputs)
    plan["campaign_id"] = str(uuid.uuid4())
    md = render_plan_md(plan)
    md_path = run_dir / "plan.md"
    md_path.write_text(md, encoding="utf-8")
    plan["plan_md_path"] = str(md_path)

    # Render HTML Gantt
    html_path = run_dir / "plan.html"
    started_at = int(time.time())
    try:
        page_html = render_mod.render_page(
            run_id=run_id,
            store_name=(store.get("name") if store else inputs.get("niche", "")),
            plan=plan, started_at=started_at, today_day_offset=1,
            html_path=html_path,
        )
        html_path.write_text(page_html, encoding="utf-8")
        plan["plan_html_path"] = str(html_path)
    except Exception as e:
        plan["html_render_error"] = str(e)

    insert_campaign(plan["campaign_id"], inputs["store_id"], inputs["budget_usd"], plan)
    insert_event(inputs["store_id"], "task",
                 f"lumicc-launch: 30-day cold-start campaign created (tier={plan['feasibility']['tier']}); campaign={plan['campaign_id']}")
    (run_dir / "result.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    insert_run(run_id, inputs["store_id"], "success", str(run_dir / "result.json"))

    if not args.quiet_stdout:
        print(md)

    if args.notify_channel:
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"Cold-start plan ready ({plan['feasibility']['tier']} tier)",
            body_md=md, severity="info", skill="lumicc-launch", run_id=run_id,
        )

    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "campaign_id": plan["campaign_id"], "tier": plan["feasibility"]["tier"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
