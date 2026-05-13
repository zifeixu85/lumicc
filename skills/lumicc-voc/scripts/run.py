#!/usr/bin/env python3
"""Voice-of-Customer closed loop.

Reads reviews from either: --input JSON file (list of {text, sku?, ts?, source?})
or stdin paste mode (one review per line, agent-mode friendly).
Clusters by keyword groups, proposes fixes, writes a campaign of type='voc-fix'
to enable next-cycle verification.

Usage:
    python3 run.py --store-id ID --input reviews.json
    python3 run.py --store-id ID --input reviews.json --notify-channel feishu --quiet-stdout
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import notify as notify_mod
import cluster as cluster_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path: return ROOT / "store.db"


def load_input(path: str | None) -> list[dict]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    # Stdin paste mode: one review per line
    return [{"text": line.strip()} for line in sys.stdin if line.strip()]


def append_event(store_id, content):
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), "observation", content))
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
            (run_id, "lumicc-voc", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def insert_campaign(camp_id, store_id, results):
    if not db_path().exists(): return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO campaigns (id, store_id, type, status, budget_usd, started_at, ended_at, results_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (camp_id, store_id, "voc-fix", "running", 0, int(time.time()), None, json.dumps(results, ensure_ascii=False)),
        )
        db.commit()
    finally:
        db.close()


def prior_cluster_sizes(store_id: str | None) -> dict[str, int]:
    """For verification: how big was each cluster in our most recent prior voc-fix campaign?"""
    if not db_path().exists(): return {}
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        q = "SELECT results_json FROM campaigns WHERE type='voc-fix'"
        params: list = []
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        q += " ORDER BY started_at DESC LIMIT 1"
        row = db.execute(q, params).fetchone()
        if not row or not row["results_json"]:
            return {}
        prior = json.loads(row["results_json"])
        return {c["topic"]: c["size"] for c in prior.get("clusters", [])}
    finally:
        db.close()


def render_report_md(clusters: list[dict], prior: dict[str, int]) -> str:
    if not clusters:
        return "_未检测到匹配的 VoC 主题。_"
    lines = [f"# VoC 反馈分析 ({len(clusters)} 个主题)", ""]
    for c in clusters:
        prev = prior.get(c["topic"])
        verify = ""
        if prev is not None:
            shrink = (prev - c["size"]) / prev if prev else 0
            symbol = "📉" if shrink > 0.2 else "📈" if shrink < -0.2 else "→"
            verify = f" · {symbol} 上轮 {prev} → 本轮 {c['size']} ({shrink:+.0%})"
        lines.append(f"\n## {c['topic']}{verify}")
        lines.append(f"**频次**: {c['size']} · **影响 SKU**: {', '.join(c['products_affected']) or '(全店)'}")
        lines.append("\n_示例反馈_:")
        for ex in c["exemplars"]:
            lines.append(f"> {ex}")
        if c.get("proposed_fixes"):
            lines.append("\n**建议修复**:")
            for fx in c["proposed_fixes"]:
                lines.append(f"- [{fx['type']}] {fx['detail']}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--input", default=None)
    p.add_argument("--min-cluster-size", type=int, default=1)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True); (ROOT / "runs").mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    items = load_input(args.input)
    raw_clusters = cluster_mod.cluster(items)
    clusters = [c for c in raw_clusters if c["size"] >= args.min_cluster_size]
    clusters = cluster_mod.propose_fixes(clusters)

    prior = prior_cluster_sizes(args.store_id)
    report_md = render_report_md(clusters, prior)
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")

    # Resolve a friendly store name for the HTML header (best-effort).
    store_name = ""
    if args.store_id and db_path().exists():
        try:
            db = sqlite3.connect(db_path())
            row = db.execute("SELECT name FROM stores WHERE id=?", (args.store_id,)).fetchone()
            if row: store_name = row[0] or ""
            db.close()
        except Exception:
            pass

    html_path = run_dir / "report.html"
    warnings: list[str] = []
    total_reviews = len(items)
    unmatched_count = max(0, total_reviews - sum(c["size"] for c in clusters))
    try:
        html = render_mod.render_page(
            run_id=run_id, store_name=store_name, clusters=clusters,
            prior=prior, total_reviews=total_reviews,
            unmatched_count=unmatched_count, html_path=html_path,
        )
        html_path.write_text(html, encoding="utf-8")
    except Exception as e:
        warnings.append(f"render_html failed: {e}")

    camp_id = str(uuid.uuid4())
    results = {
        "run_id": run_id, "skill": "lumicc-voc", "campaign_id": camp_id,
        "input_count": len(items), "matched_count": sum(c["size"] for c in clusters),
        "clusters": clusters, "prior_cluster_sizes": prior,
        "report_html": str(html_path), "warnings": warnings,
    }
    if clusters:
        insert_campaign(camp_id, args.store_id, results)
    (run_dir / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    append_event(args.store_id, f"lumicc-voc: clustered {len(clusters)} topics from {len(items)} items")
    append_run(run_id, args.store_id, "success", str(run_dir / "result.json"))

    if not args.quiet_stdout:
        print(report_md)
    if args.notify_channel:
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"💬 VoC 闭环 · {len(clusters)} 个主题",
            body_md=report_md, severity="info",
            skill="lumicc-voc", run_id=run_id,
        )
    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "clusters": len(clusters)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
