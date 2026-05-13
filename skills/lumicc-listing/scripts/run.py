#!/usr/bin/env python3
"""Audit listings and produce an ordered fix plan.

Reads products from store.db, normalizes each into the audit schema (with
sensible fallbacks if optional fields are missing), runs 8 checks, and writes
a report with per-product score + top-3 fixes.

Usage:
    python3 run.py --store-id ID
    python3 run.py --store-id ID --product-id PROD
    python3 run.py --store-id ID --notify-channel feishu --quiet-stdout
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify as notify_mod
import checks as checks_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path:
    return ROOT / "store.db"


def load_products(store_id: str | None, product_id: str | None) -> list[dict]:
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if product_id:
            return [dict(r) for r in db.execute("SELECT * FROM products WHERE id=?", (product_id,))]
        q = "SELECT * FROM products WHERE status IN ('active','draft')"
        params: list = []
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        return [dict(r) for r in db.execute(q, params)]
    finally:
        db.close()


def normalize(p: dict) -> dict:
    """Convert store.db product row to audit schema, parsing data_json if present."""
    extra = {}
    try:
        extra = json.loads(p.get("data_json") or "{}")
    except json.JSONDecodeError:
        pass
    return {
        "title": p.get("title") or "",
        "description": extra.get("description") or extra.get("body_html") or "",
        "bullets": extra.get("bullets") or [],
        "images": extra.get("images") or [],
        "price": p.get("price_usd") or 0,
        "compare_at_price": extra.get("compare_at_price") or 0,
        "reviews": extra.get("reviews") or {"count": 0, "avg": 0},
        "scarcity_signal": bool(extra.get("scarcity_signal")),
        "mobile_lcp_ms": extra.get("mobile_lcp_ms"),
        "competitor_avg_price": extra.get("competitor_avg_price"),
        "primary_keywords": extra.get("primary_keywords") or [],
    }


def render_report_md(audits: list[dict]) -> str:
    if not audits:
        return "_未找到可审计的商品。_"
    lines = [f"# Listing 体检报告 ({len(audits)} 个商品)", ""]
    avg = sum(a["audit"]["total"] for a in audits) / len(audits)
    lines.append(f"**平均健康度**: {avg:.1f}/100")
    lines.append("")
    by_sev: dict[str, list[dict]] = {"sick": [], "improvable": [], "healthy": []}
    for a in audits:
        by_sev[a["audit"]["severity"]].append(a)
    if by_sev["sick"]:
        lines.append(f"\n## 🔴 重病 ({len(by_sev['sick'])}) — 优先处理")
        for a in by_sev["sick"]:
            lines.append(f"- **{a['title']}** — {a['audit']['total']}/100")
    if by_sev["improvable"]:
        lines.append(f"\n## 🟡 可改进 ({len(by_sev['improvable'])})")
        for a in by_sev["improvable"]:
            lines.append(f"- {a['title']} — {a['audit']['total']}/100")
    if by_sev["healthy"]:
        lines.append(f"\n## 🟢 健康 ({len(by_sev['healthy'])})")
        for a in by_sev["healthy"]:
            lines.append(f"- {a['title']} — {a['audit']['total']}/100")

    lines.append("\n## Top 3 修复（按 影响 × 容易度 排序）\n")
    for a in audits:
        if not a["audit"]["top_fixes"]:
            continue
        lines.append(f"### {a['title']}")
        for fx in a["audit"]["top_fixes"]:
            lines.append(f"- **{fx['check']}** (impact {fx['impact']:.2f}) — {fx['evidence']}")
            lines.append(f"  → {fx['fix']}")
        lines.append("")
    return "\n".join(lines)


def append_event(store_id: str | None, content: str) -> None:
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), "task", content))
        db.commit()
    finally:
        db.close()


def append_run(run_id: str, store_id: str | None, status: str, result_path: str) -> None:
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-listing", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--product-id", default=None)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True); (ROOT / "runs").mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    products = load_products(args.store_id, args.product_id)
    audits = []
    for prod in products:
        normalized = normalize(prod)
        audits.append({
            "product_id": prod.get("id"),
            "sku": prod.get("sku"),
            "title": prod.get("title"),
            "audit": checks_mod.audit(normalized),
        })
    # Sort sickest first
    audits.sort(key=lambda a: a["audit"]["total"])

    report_md = render_report_md(audits)
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")

    # If any product has a weak hero (image_count score < 6), recommend re-running
    # the landing_style picker on it.
    recommended_pickers = [
        {
            "product_sku": a.get("sku"),
            "product_title": a.get("title"),
            "kind": "landing_style",
            "reason": "hero image quality below threshold",
            "command": (
                f"python3 ../lumicc/scripts/picker.py --kind landing_style "
                f"--session {run_id} --open"
            ),
        }
        for a in audits
        if (a["audit"]["checks"].get("image_count") or {}).get("score", 10) < 6
    ]

    warnings: list[str] = []
    html_path = run_dir / "report.html"
    try:
        html = render_mod.render_page(
            run_id=run_id,
            store_name=args.store_id or "",
            audits=audits,
            html_path=html_path,
            recommended_pickers=recommended_pickers,
        )
        html_path.write_text(html, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"html render failed: {e}")
        html_path = None  # type: ignore[assignment]

    result = {
        "run_id": run_id, "skill": "lumicc-listing", "status": "success",
        "store_id": args.store_id, "products_audited": len(audits),
        "audits": audits, "report_path": str(run_dir / "report.md"),
        "report_html": str(html_path) if html_path else None,
        "warnings": warnings,
        "recommended_pickers": recommended_pickers,
        "next_recommended_skill": "lumicc-voc" if any(a["audit"]["checks"]["reviews"]["score"] <= 3 for a in audits) else None,
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(args.store_id, f"lumicc-listing: audited {len(audits)} products")
    append_run(run_id, args.store_id, "success", str(run_dir / "result.json"))

    if not args.quiet_stdout:
        print(report_md)
    if args.notify_channel:
        n_sick = sum(1 for a in audits if a["audit"]["severity"] == "sick")
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"🏥 Listing 体检完成 · {n_sick} 个需重点处理",
            body_md=report_md, severity="warn" if n_sick else "info",
            skill="lumicc-listing", run_id=run_id,
        )
    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "products_audited": len(audits)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
