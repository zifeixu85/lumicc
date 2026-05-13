#!/usr/bin/env python3
"""Crisis response orchestrator.

3-question triage → branch hypothesis → action playbook → 24h watchdog setup.
Collects evidence (recent events from last 7d, recent changes) before diagnosing.

Usage (coder mode):
    python3 run.py --store-id ID \\
        --platform-notification ad_disapproval \\
        --recent-change ad \\
        --scope store_wide

Agent mode:
    python3 run.py --store-id ID --platform-notification account_warning --scope store_wide \\
        --notify-channel feishu --notify-target user:cheche --quiet-stdout
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify as notify_mod
import render_html as render_mod
import triage as triage_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path: return ROOT / "store.db"


def recent_changes(store_id: str | None, hours: int = 48) -> list[dict]:
    if not db_path().exists(): return []
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        since = int(time.time()) - hours * 3600
        q = "SELECT * FROM events WHERE category='decision' AND ts >= ?"
        params: list = [since]
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        q += " ORDER BY ts DESC LIMIT 20"
        return [dict(r) for r in db.execute(q, params)]
    finally:
        db.close()


def append_event(store_id, content, category="warning"):
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), category, content))
        db.commit()
    finally:
        db.close()


def append_run(run_id, store_id, status, result_path):
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-rescue", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def insert_crisis_campaign(camp_id, store_id, diagnosis):
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO campaigns (id, store_id, type, status, budget_usd, started_at, ended_at, results_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (camp_id, store_id, "crisis", "running", 0, int(time.time()), None,
             json.dumps(diagnosis, ensure_ascii=False)),
        )
        db.commit()
    finally:
        db.close()


def render_report_md(diag: dict, evidence: list[dict]) -> str:
    severity_icon = {"A": "🚨", "B": "⚠️", "C": "⚠️", "D": "🟡", "E": "🟡",
                     "F": "🔵", "G": "🟡", "H": "🟡"}.get(diag["branch_id"], "⚠️")
    lines = [f"# {severity_icon} 危机诊断 · {diag['hypothesis']}", ""]
    lines.append(f"**分支**: {diag['branch_id']} — {diag['branch_key']}")
    lines.append(f"**置信度**: {diag['confidence']:.0%}")
    lines.append(f"**预估解决时间**: {diag['resolution_time']}")
    if diag.get("alternatives"):
        lines.append("\n**备选诊断**:")
        for a in diag["alternatives"]:
            lines.append(f"- {a['branch_id']}: {a['hypothesis']} — {a['reason']}")

    lines.append("\n## 行动方案")
    for i, step in enumerate(diag["playbook_steps"], 1):
        lines.append(f"{i}. {step}")

    if evidence:
        lines.append(f"\n## 最近 48h 决策事件 ({len(evidence)})")
        for e in evidence[:8]:
            lines.append(f"- {time.strftime('%m-%d %H:%M', time.localtime(e['ts']))}: {e['content']}")

    lines.append("\n## 24h Watchdog")
    lines.append("Lumicc 将在 24 小时后自动检查指标是否回升。若仍未恢复，会升级到下一个最可能分支。")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--platform-notification", default="none",
                   choices=["none", "account_warning", "ad_disapproval", "listing_suppression", "other"])
    p.add_argument("--recent-change", default="none",
                   choices=["none", "price", "listing", "ad", "inventory"])
    p.add_argument("--scope", default="store_wide", choices=["single_sku", "store_wide"])
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True); (ROOT / "runs").mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    evidence = recent_changes(args.store_id)
    inp = triage_mod.TriageInput(
        platform_notification=args.platform_notification,
        recent_change_kind=args.recent_change,
        scope=args.scope,
    )
    diag = triage_mod.diagnose(inp)

    report_md = render_report_md(diag, evidence)
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")

    warnings: list[str] = []
    html_path = run_dir / "report.html"
    try:
        html_text = render_mod.render_page(
            run_id=run_id, store_name=args.store_id or "",
            diag=diag, evidence=evidence, html_path=html_path,
        )
        html_path.write_text(html_text, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"render_html failed: {e}")

    camp_id = str(uuid.uuid4())
    full = {
        "run_id": run_id, "skill": "lumicc-rescue", "campaign_id": camp_id,
        "input": {"platform_notification": args.platform_notification,
                  "recent_change": args.recent_change, "scope": args.scope},
        "diagnosis": diag, "evidence_events": evidence,
        "watchdog_check_at": int(time.time()) + 24 * 3600,
        "report_html": str(html_path),
        "warnings": warnings,
    }
    (run_dir / "result.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    insert_crisis_campaign(camp_id, args.store_id, full)
    append_event(args.store_id,
                 f"lumicc-rescue: crisis diagnosed as {diag['hypothesis']} (confidence {diag['confidence']:.0%})",
                 category="warning")
    append_run(run_id, args.store_id, "success", str(run_dir / "result.json"))

    if not args.quiet_stdout:
        print(report_md)
    if args.notify_channel:
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"🚨 危机诊断 · {diag['hypothesis']}",
            body_md=report_md,
            severity="error" if diag["branch_id"] == "A" else "warn",
            skill="lumicc-rescue", run_id=run_id,
        )
    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "branch": diag["branch_id"],
                          "hypothesis": diag["hypothesis"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
