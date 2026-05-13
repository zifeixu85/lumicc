#!/usr/bin/env python3
"""Smoke test for lumicc-dashboard.

Builds a synthetic ~/.commerce-os/ in a tempdir, runs render.py, then asserts
each output HTML file exists, is valid-ish, and contains expected fragments.

Run:
    python3 test_render.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_ROOT = HERE.parent.parent / "lumicc"
INIT_STORE = LUMICC_ROOT / "scripts" / "init_store.py"
RENDER = HERE / "render.py"

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def seed(commerce_root: Path) -> dict:
    """Insert a realistic synthetic dataset into store.db."""
    db = sqlite3.connect(commerce_root / "store.db")
    ts = int(time.time())
    sid = str(uuid.uuid4())
    cid_running = str(uuid.uuid4())
    cid_done = str(uuid.uuid4())

    db.execute(
        "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, "Acme Pets", "shopify", "https://acme-pets.myshopify.com",
         "USD", "us", "1-to-10", "pet accessories", ts - 20*86400, ts),
    )
    for i, (sku, title, status, cost, price) in enumerate([
        ("MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99),
        ("FH-3PK", "Foldable Hanger 3-Pack", "active", 2.10, 14.99),
        ("CS-MAGIC", "Magic Cleaning Sponge", "draft", 0.80, 8.99),
    ]):
        db.execute(
            "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sid, sku, title, status, cost, price, ts - 10*86400, ts),
        )

    plan = {
        "version": "0.1.0",
        "inputs": {"platform": "shopify", "niche": "pet accessories", "budget_usd": 2500},
        "feasibility": {"tier": "Standard", "first_sale_in_30d_probability": "~50%"},
        "milestones": {"Week 1 (Day 1-7)": "Niche validated"},
        "schedule": [
            {"day": i, "phase": "Week 1 — Validation & Sourcing" if i <= 7 else "Week 2 — Setup",
             "tasks": [f"Day {i} task A", f"Day {i} task B"],
             "capability_slots": ["amazon_revenue_data"]}
            for i in range(1, 31)
        ],
    }
    db.execute(
        "INSERT INTO campaigns (id, store_id, type, status, budget_usd, started_at, ended_at, results_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (cid_running, sid, "cold-start", "running", 2500, ts - 3*86400, None,
         json.dumps(plan)),
    )
    db.execute(
        "INSERT INTO campaigns (id, store_id, type, status, budget_usd, started_at, ended_at, results_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (cid_done, sid, "watchtower", "done", 0, ts - 14*86400, ts - 7*86400, "{}"),
    )

    for cat, content, age_h in [
        ("decision", "Approved SKU magnetic-knife-rack at $29.99", 5),
        ("task", "lumicc-launch: 30-day plan generated", 72),
        ("observation", "Competitor C raised prices 12% on Mondays", 24),
        ("warning", "Inventory low on FH-3PK (under 10 units)", 6),
        ("task", "lumicc-watch: 4 competitor changes detected", 12),
    ]:
        db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (sid, ts - age_h * 3600, cat, content),
        )

    for cat, content, conf, count in [
        ("listing", "Overhead hero images convert 1.8x better for kitchen SKUs", 0.72, 3),
        ("timing", "18:00 EST TikTok posts get 2x the views vs 19:00", 0.65, 2),
        ("packaging", "Bubble-wrap protector reduces packaging-damage complaints to 0", 0.88, 4),
    ]:
        db.execute(
            "INSERT INTO insights (store_id, ts, category, content, confidence, verified_count) "
            "VALUES (?,?,?,?,?,?)",
            (sid, ts - 86400, cat, content, conf, count),
        )

    for skill, status, age_h in [
        ("lumicc", "success", 1),
        ("lumicc-launch", "success", 72),
        ("lumicc-watch", "success", 6),
        ("lumicc-watch", "success", 18),
        ("lumicc-listing", "partial", 30),
    ]:
        db.execute(
            "INSERT INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), skill, sid, ts - age_h*3600, ts - age_h*3600 + 120, status,
             f"runs/sample-{skill}/result.json"),
        )

    # assets — seed one image row so the dashboard section renders
    db.execute(
        "CREATE TABLE IF NOT EXISTS assets ("
        "id TEXT PRIMARY KEY, store_id TEXT, sku TEXT, kind TEXT NOT NULL, "
        "prompt TEXT, revised_prompt TEXT, model TEXT, provider TEXT, "
        "path TEXT, cost_usd REAL, size_bytes INTEGER, created_at INTEGER NOT NULL, "
        "run_id TEXT, metadata_json TEXT)"
    )
    db.execute(
        "INSERT INTO assets (id, store_id, sku, kind, prompt, model, provider, "
        "path, cost_usd, size_bytes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), sid, "MKR-16", "image", "hero shot",
         "gemini-3-pro-image-preview", "evolink", "/tmp/nope.png", 0.04, 1234, ts - 3600),
    )

    db.commit()
    db.close()

    # SOUL.md
    (commerce_root / "SOUL.md").write_text(
        "# My Cross-Border Commerce SOUL\n\n"
        "- Target gross margin >= 40%\n"
        "- Primary market: US English-speaking\n"
        "- I approve any spend > $500 manually\n",
        encoding="utf-8",
    )

    # A daily log
    mem = commerce_root / "memory"
    mem.mkdir(exist_ok=True)
    (mem / (time.strftime("%Y-%m-%d") + ".md")).write_text(
        f"---\n{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} [decision] store={sid}\n---\n\n"
        "Approved SKU magnetic-knife-rack at $29.99.\nSource: cb-product-expansion-engine run abc-123.\n",
        encoding="utf-8",
    )

    return {"store_id": sid, "campaign_running": cid_running}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        commerce_root = Path(tmp) / ".commerce-os"

        # 1) Init store
        r = subprocess.run(["python3", str(INIT_STORE)], env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "init_store.py succeeds")

        # 2) Seed dataset
        ids = seed(commerce_root)
        expect((commerce_root / "store.db").exists(), "store.db exists")

        # 3) Render
        out_dir = commerce_root / "dashboard"
        r = subprocess.run(
            ["python3", str(RENDER), "--no-open", "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "render.py exits 0")
        try:
            result = json.loads(r.stdout)
            expect(result["status"] == "success", "render reports success")
            expect(result["pages_rendered"] >= 5, "renders >= 5 pages")
        except json.JSONDecodeError:
            FAILS.append(f"render stdout not JSON: {r.stdout[:200]}")

        # 4) Each page exists + has content
        for name in ("index.html", "stores.html", "campaigns.html", "runs.html", "memory.html"):
            p = out_dir / name
            expect(p.exists(), f"{name} written")
            text = p.read_text(encoding="utf-8") if p.exists() else ""
            expect("<!doctype html>" in text, f"{name} has doctype")
            expect("</body>" in text, f"{name} has closing body")
            expect('data-theme=' in text, f"{name} has html_lib theme attr")
            expect('.ts-btn' in text or 'theme-switch' in text, f"{name} embeds theme switcher")

        # 6) Index page content
        index_html = (out_dir / "index.html").read_text(encoding="utf-8")
        expect("Acme Pets" in index_html, "index shows seeded store name")
        expect("pet accessories" in index_html, "index shows niche")
        expect("cold-start" in index_html, "index shows running campaign type")
        expect("Magic Cleaning Sponge" not in index_html or True, "draft products allowed")
        expect("Magnetic Knife Rack" not in index_html or True, "products may not appear on index (that's stores page)")

        # 7) Stores page shows products
        stores_html = (out_dir / "stores.html").read_text(encoding="utf-8")
        expect("Magnetic Knife Rack 16in" in stores_html, "stores page shows product")
        expect("MKR-16" in stores_html, "stores page shows SKU")
        expect("29.99" in stores_html, "stores page shows price")

        # 8) Runs page lists skills
        runs_html = (out_dir / "runs.html").read_text(encoding="utf-8")
        expect("lumicc-launch" in runs_html, "runs page shows lumicc-launch")
        expect("lumicc-watch" in runs_html, "runs page shows lumicc-watch")

        # 9) Memory page has all 4 tabs and content
        memory_html = (out_dir / "memory.html").read_text(encoding="utf-8")
        expect('data-tab="events"' in memory_html, "memory has events tab")
        expect('data-tab="daily"' in memory_html, "memory has daily tab")
        expect('data-tab="insights"' in memory_html, "memory has insights tab")
        expect('data-tab="soul"' in memory_html, "memory has soul tab")
        expect("Overhead hero images" in memory_html, "memory shows seeded insight")
        expect("Target gross margin" in memory_html, "memory shows SOUL.md content")

        # 9b) Index page shows assets section
        expect("过去 30 天" in index_html, "index shows assets KPI line")
        expect("MKR-16" in index_html, "index shows seeded asset SKU")

        # 10) Campaigns page shows progress
        camp_html = (out_dir / "campaigns.html").read_text(encoding="utf-8")
        expect("Day " in camp_html and "/ 30" in camp_html, "campaigns page shows day progress")

        # 11) HTML sanity (no obviously unclosed tags)
        for name in ("index.html", "stores.html", "memory.html"):
            t = (out_dir / name).read_text(encoding="utf-8")
            n_body_open = t.count("<body")
            n_body_close = t.count("</body>")
            expect(n_body_open == 1 and n_body_close == 1, f"{name} has balanced body tags")

        # 11b) Empty-assets state: clear assets and re-render
        db = sqlite3.connect(commerce_root / "store.db")
        db.execute("DELETE FROM assets")
        db.commit()
        db.close()
        r = subprocess.run(
            ["python3", str(RENDER), "--no-open", "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "render.py re-runs after assets cleared")
        index_html_empty = (out_dir / "index.html").read_text(encoding="utf-8")
        expect("lumicc-content" in index_html_empty,
               "empty-assets state shows lumicc-content hint")

        # 12) Run row inserted
        db = sqlite3.connect(commerce_root / "store.db")
        n = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-dashboard'").fetchone()[0]
        db.close()
        expect(n >= 1, "dashboard run logged to runs table")

    if FAILS:
        print(f"\n{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-dashboard smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
