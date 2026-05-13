#!/usr/bin/env python3
"""lumicc-seo orchestrator — dispatches modes.

Modes:
  llms-txt   Generate + validate llms.txt from store + products
  schema     Generate Schema.org JSON-LD per product
  rank       Import a GSC/Ahrefs CSV → seo_keywords table; report deltas
  citation   Parse pasted AI-engine answers → seo_citations table
  audit      Run technical SEO audit on store URL
  all        Run llms-txt + schema (for all active products) + audit

Usage:
    python3 run.py --mode llms-txt --store-id ID
    python3 run.py --mode schema --product-id MKR-16
    python3 run.py --mode rank --gsc-csv export.csv
    python3 run.py --mode citation --queries-file queries.json --target-brand-keyword Acme
    python3 run.py --mode audit
    python3 run.py --mode all --store-id ID
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
import llms_txt as llms_mod
import schema_gen as schema_mod
import citation as cite_mod
import audit as audit_mod
import rank as rank_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"


def db_path() -> Path:
    return ROOT / "store.db"


# ---------- Schema migration ----------
def ensure_seo_tables() -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.executescript("""
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
        );
        CREATE INDEX IF NOT EXISTS idx_seo_kw ON seo_keywords(keyword, target_market, ts);

        CREATE TABLE IF NOT EXISTS seo_citations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id TEXT,
          engine TEXT NOT NULL,
          query TEXT NOT NULL,
          brand_mentioned INTEGER,
          position INTEGER,
          citation_url TEXT,
          raw_answer_excerpt TEXT,
          ts INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_seo_cit ON seo_citations(engine, ts);
        """)
        db.commit()
    finally:
        db.close()


def get_store(store_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def get_products(store_id: str | None, product_id: str | None = None,
                 only_active: bool = True) -> list[dict]:
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path()); db.row_factory = sqlite3.Row
    try:
        if product_id:
            return [dict(r) for r in db.execute("SELECT * FROM products WHERE id=? OR sku=?",
                                                 (product_id, product_id))]
        q = "SELECT * FROM products WHERE 1=1"
        params: list = []
        if store_id:
            q += " AND store_id=?"
            params.append(store_id)
        if only_active:
            q += " AND status='active'"
        return [dict(r) for r in db.execute(q, params)]
    finally:
        db.close()


def append_event(store_id: str | None, content: str, category: str = "task") -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, int(time.time()), category, content))
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
            (run_id, "lumicc-seo", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


# ---------- Mode implementations ----------
def mode_llms_txt(store: dict, products: list[dict], run_dir: Path) -> dict:
    data = {
        "store_name": store.get("name", "Cross-Border Store"),
        "store_url": store.get("url", "https://example.com"),
        "description": f"{store.get('niche','products')} for the {store.get('target_market','global')} market.",
        "products": [{
            "title": p.get("title", "—"),
            "handle": (p.get("title") or p.get("sku") or "product").lower().replace(" ", "-")[:50],
            "url": (store.get("url", "").rstrip("/") + f"/products/{p.get('sku','').lower()}") if p.get("sku") else "",
            "description": p.get("data_json", "")[:100] if p.get("data_json") else "",
        } for p in products[:20]],
    }
    content = llms_mod.generate(**data)
    seo_dir = ROOT / "seo"
    seo_dir.mkdir(exist_ok=True)
    final_path = seo_dir / "llms.txt"
    final_path.write_text(content, encoding="utf-8")
    # also keep a copy in the run dir
    (run_dir / "llms.txt").write_text(content, encoding="utf-8")
    validation = llms_mod.validate(content)
    return {
        "deliverable": "llms_txt",
        "path": str(final_path),
        "validation": validation,
        "char_count": validation["char_count"],
        "products_listed": len(data["products"]),
    }


def mode_schema(store: dict, products: list[dict], run_dir: Path) -> dict:
    out_files: list[str] = []
    for p in products:
        result = schema_mod.generate(product=p, store=store, faqs=[])
        sku = p.get("sku") or p.get("id")
        path = run_dir / f"schema-{sku}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        out_files.append(str(path))
        # also write the ready-to-paste HTML block
        html_path = run_dir / f"schema-{sku}.html"
        html_path.write_text(
            "\n\n".join(b["html_block"] for b in result["schemas"]),
            encoding="utf-8",
        )
    return {
        "deliverable": "schema_json_ld",
        "files": out_files,
        "products_count": len(products),
    }


def mode_rank(store_id: str | None, gsc_csv: str, market: str, source: str, run_dir: Path) -> dict:
    summary = rank_mod.import_gsc_csv(Path(gsc_csv), store_id, market, source)
    report_md = rank_mod.render_report_md(summary)
    (run_dir / "rank-report.md").write_text(report_md, encoding="utf-8")
    summary["report_path"] = str(run_dir / "rank-report.md")
    summary["deliverable"] = "rank_delta_md"
    return summary


def mode_citation(store_id: str | None, queries_file: str,
                  brand_keywords: list[str], competitor_keywords: list[str],
                  run_dir: Path) -> dict:
    queries = json.loads(Path(queries_file).read_text(encoding="utf-8"))
    if isinstance(queries, dict):
        queries = [queries]
    results = cite_mod.process_batch(queries, brand_keywords, competitor_keywords)
    # Stash on deliverable for HTML rendering
    raw_results = results
    # Persist
    if db_path().exists():
        db = sqlite3.connect(db_path())
        try:
            for r in results:
                db.execute(
                    "INSERT INTO seo_citations (store_id, engine, query, brand_mentioned, position, "
                    "citation_url, raw_answer_excerpt, ts) VALUES (?,?,?,?,?,?,?,?)",
                    (store_id, r["engine"], r["query"], 1 if r["brand_mentioned"] else 0,
                     r["position"], None, r["raw_answer_excerpt"], int(time.time())),
                )
            db.commit()
        finally:
            db.close()
    report_md = cite_mod.render_report_md(results, brand_keywords[0] if brand_keywords else "—")
    (run_dir / "citation-report.md").write_text(report_md, encoding="utf-8")
    n_mentioned = sum(1 for r in results if r["brand_mentioned"])
    return {
        "deliverable": "citation_share",
        "path": str(run_dir / "citation-report.md"),
        "results_count": len(results),
        "mentioned_count": n_mentioned,
        "share_avg": round(sum(r["share"] for r in results) / max(1, len(results)), 3),
        "results": raw_results,
    }


def mode_audit(store: dict, run_dir: Path) -> dict:
    report = audit_mod.audit(store.get("url", "https://example.com"))
    report_md = audit_mod.render_report_md(report)
    (run_dir / "audit.md").write_text(report_md, encoding="utf-8")
    report["deliverable"] = "audit_checklist"
    report["path"] = str(run_dir / "audit.md")
    return report


# ---------- Main ----------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", required=True,
                   choices=["llms-txt", "schema", "rank", "citation", "audit", "all"])
    p.add_argument("--store-id", default=None)
    p.add_argument("--product-id", default=None)
    p.add_argument("--gsc-csv", default=None)
    p.add_argument("--queries-file", default=None)
    p.add_argument("--target-brand-keyword", action="append", default=[])
    p.add_argument("--competitor-keyword", action="append", default=[])
    p.add_argument("--market", default="us")
    p.add_argument("--source", default="gsc", choices=["gsc", "ahrefs", "semrush", "manual"])
    p.add_argument("--min-position-drop", type=int, default=10)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True); (ROOT / "runs").mkdir(exist_ok=True)
    ensure_seo_tables()
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store = get_store(args.store_id) or {}
    if not store and args.mode in ("llms-txt", "schema", "audit", "all"):
        print(json.dumps({"error": "No store found; create one via lumicc init_store first."}),
              file=sys.stderr)
        return 2

    deliverables: list[dict] = []
    warnings: list[str] = []

    try:
        if args.mode in ("llms-txt", "all"):
            products = get_products(args.store_id, only_active=True)
            deliverables.append(mode_llms_txt(store, products, run_dir))

        if args.mode == "schema":
            products = get_products(args.store_id, product_id=args.product_id, only_active=False)
            if not products:
                warnings.append("No products found.")
            else:
                deliverables.append(mode_schema(store, products, run_dir))
        elif args.mode == "all":
            products = get_products(args.store_id, only_active=True)
            if products:
                deliverables.append(mode_schema(store, products, run_dir))

        if args.mode == "rank":
            if not args.gsc_csv:
                print(json.dumps({"error": "Need --gsc-csv for mode rank"}), file=sys.stderr)
                return 2
            deliverables.append(mode_rank(args.store_id, args.gsc_csv, args.market, args.source, run_dir))

        if args.mode == "citation":
            if not args.queries_file:
                print(json.dumps({"error": "Need --queries-file for mode citation"}), file=sys.stderr)
                return 2
            brand_kws = args.target_brand_keyword or ([store.get("name")] if store.get("name") else [])
            if not brand_kws:
                print(json.dumps({"error": "Need --target-brand-keyword"}), file=sys.stderr)
                return 2
            deliverables.append(mode_citation(args.store_id, args.queries_file,
                                              brand_kws, args.competitor_keyword, run_dir))

        if args.mode in ("audit", "all"):
            deliverables.append(mode_audit(store, run_dir))
    except Exception as e:
        warnings.append(f"Mode '{args.mode}' partial failure: {e}")

    # Render unified HTML report
    html_path = run_dir / "report.html"
    try:
        page_html = render_mod.render_page(
            run_id=run_id, mode=args.mode, deliverables=deliverables,
            store_name=store.get("name", ""), html_path=html_path,
        )
        html_path.write_text(page_html, encoding="utf-8")
    except Exception as e:
        warnings.append(f"HTML render failed: {e}")

    # Result
    result = {
        "run_id": run_id,
        "skill": "lumicc-seo",
        "mode": args.mode,
        "status": "success" if not warnings else "partial",
        "store_id": args.store_id,
        "deliverables": deliverables,
        "report_html": str(html_path),
        "warnings": warnings,
        "next_recommended_skill": "lumicc-content" if any(
            d.get("deliverable") == "rank_delta_md" and d.get("biggest_drops") for d in deliverables
        ) else None,
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run(run_id, args.store_id, result["status"], str(run_dir / "result.json"))
    append_event(args.store_id, f"lumicc-seo: mode '{args.mode}' produced {len(deliverables)} deliverable(s)")

    if not args.quiet_stdout:
        print(json.dumps({k: v for k, v in result.items() if k != "deliverables" or args.mode == "all"},
                         ensure_ascii=False, indent=2))

    if args.notify_channel:
        body_lines = [f"## {args.mode}", ""]
        for d in deliverables:
            body_lines.append(f"- {d.get('deliverable','—')}: {d.get('path') or d.get('files')}")
        notify_mod.notify(
            channel=args.notify_channel, target=args.notify_target,
            title=f"🔎 SEO/GEO 报告 · {args.mode}",
            body_md="\n".join(body_lines),
            severity="info" if not warnings else "warn",
            skill="lumicc-seo", run_id=run_id,
        )

    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "mode": args.mode,
                          "deliverables_count": len(deliverables)},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
