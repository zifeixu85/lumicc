#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-launch.

Tests:
  1) resource_estimator returns correct tier
  2) plan.py builds a 30-day plan with all 30 days and writes campaign row
  3) day_advance.py reads campaign and outputs today's tasks
  4) day_advance.py at day_offset >= 31 marks campaign complete
  5) Agent mode (--notify-channel) writes outbox file
  6) listing_csv.py generates valid CSV
  7) niche_worksheet.py + outreach_pack.py produce expected markdown
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_ROOT = HERE.parent.parent / "lumicc"

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def run(*args: str, env: dict, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", *args], capture_output=True, text=True, env=env, **kw)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        commerce_root = Path(tmp) / ".commerce-os"

        # Init store
        r = run(str(LUMICC_ROOT / "scripts" / "init_store.py"), env=env)
        expect(r.returncode == 0, "init_store.py exits 0")

        # Seed a store
        db = sqlite3.connect(commerce_root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://acme.myshopify.com",
             "USD", "us", "0-to-1", "pet accessories", ts, ts),
        )
        db.commit()
        db.close()

        # 1) Resource estimator
        print("\n[1] resource_estimator.py")
        r = run(str(HERE / "resource_estimator.py"),
                "--budget", "2500", "--hours-per-week", "15", "--tiktok-accounts", "1", env=env)
        expect(r.returncode == 0, "estimator exits 0")
        out = json.loads(r.stdout)
        expect(out["tier"] in ("Lean", "Standard", "Comfortable"), "tier classified")
        expect("first_sale_in_30d_probability" in out, "probability returned")

        # 2) plan.py
        print("\n[2] plan.py")
        r = run(str(HERE / "plan.py"), "--store-id", sid,
                "--budget", "2500", "--hours", "15", env=env)
        expect(r.returncode == 0, "plan.py exits 0")
        expect("30-Day Cold-Start Plan" in r.stdout, "markdown title present")
        expect("Day 1" in r.stdout and "Day 30" in r.stdout, "all 30 days included")
        # Verify campaign row
        db = sqlite3.connect(commerce_root / "store.db")
        camps = db.execute("SELECT * FROM campaigns WHERE store_id=? AND type='cold-start' AND status='running'", (sid,)).fetchall()
        db.close()
        expect(len(camps) == 1, "campaign row inserted")
        plan_json = json.loads(camps[0][7])  # results_json
        expect(len(plan_json["schedule"]) == 30, "schedule has 30 days")

        # 3) day_advance.py — fresh campaign, should be day 1
        print("\n[3] day_advance.py — day 1")
        r = run(str(HERE / "day_advance.py"), "--store-id", sid, env=env)
        expect(r.returncode == 0, "day_advance exits 0")
        expect("Day 1 of 30" in r.stdout, "first run = day 1")
        expect("Validate niche" in r.stdout or "Pull 12" in r.stdout, "day 1 task content")

        # 4) day_advance.py — simulate day 31 (past end)
        print("\n[4] day_advance.py — beyond day 30")
        future_ts = int(time.time()) + 31 * 86400
        r = run(str(HERE / "day_advance.py"), "--store-id", sid, "--now-ts", str(future_ts), env=env)
        expect(r.returncode == 0, "day_advance future exits 0")
        expect("DONE" in r.stdout, "campaign marked complete at day > 30")

        # 5) Agent mode notify
        print("\n[5] day_advance.py agent mode")
        r = run(str(HERE / "day_advance.py"), "--store-id", sid,
                "--notify-channel", "feishu", "--notify-target", "group:ops",
                "--quiet-stdout", env=env)
        expect(r.returncode == 0, "agent mode exits 0")
        expect("Today's Cold-Start" not in r.stdout, "markdown NOT printed in quiet mode")
        outbox = commerce_root / "outbox"
        files = list(outbox.glob("*.json"))
        expect(len(files) >= 1, "notification written to outbox")
        payload = json.loads(files[0].read_text())
        expect(payload["channel"] == "feishu" and payload["skill"] == "lumicc-launch", "outbox payload correct")

        # 6) listing_csv.py
        print("\n[6] listing_csv.py")
        product_json = {
            "handle": "magnetic-knife-rack",
            "title": "Magnetic Knife Rack — 16 inch",
            "body_html": "Strong magnets. Keeps knives organized.",
            "vendor": "Acme Pets",
            "product_type": "Kitchen",
            "tags": ["kitchen", "magnetic"],
            "variants": [{"sku": "MKR-16", "price": 29.99, "compare_at": 39.99, "weight_g": 320}],
            "images": [{"src": "https://cdn.example.com/mkr.jpg", "alt": "Front view", "position": 1}],
            "seo_title": "Best Magnetic Knife Rack 16in", "seo_description": "Heavy-duty.",
        }
        in_path = Path(tmp) / "p.json"
        in_path.write_text(json.dumps([product_json]))
        out_path = Path(tmp) / "p.csv"
        r = run(str(HERE / "listing_csv.py"), "--input", str(in_path), "--out", str(out_path), env=env)
        expect(r.returncode == 0, "listing_csv exits 0")
        csv_text = out_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)
        expect(len(rows) >= 1, "csv has rows")
        expect(rows[0]["Handle"] == "magnetic-knife-rack", "csv Handle correct")
        expect(rows[0]["Variant SKU"] == "MKR-16", "csv SKU correct")
        expect(rows[0]["Variant Price"] == "29.99", "csv price correct")
        expect(rows[0]["Image Src"] == "https://cdn.example.com/mkr.jpg", "csv image correct")

        # 7a) niche worksheet
        print("\n[7] niche_worksheet.py + outreach_pack.py")
        wsh = Path(tmp) / "w.md"
        r = run(str(HERE / "niche_worksheet.py"),
                "--niche", "pet accessories", "--target-market", "us", "--out", str(wsh), env=env)
        expect(r.returncode == 0, "niche_worksheet exits 0")
        text = wsh.read_text()
        expect("Niche Validation Worksheet" in text, "worksheet title present")
        expect("pet accessories" in text, "niche embedded")

        # 7b) outreach pack
        oth = Path(tmp) / "out.md"
        r = run(str(HERE / "outreach_pack.py"),
                "--niche", "pet accessories", "--product", "Magnetic Knife Rack",
                "--price", "29.99", "--product-url", "https://acme.com/p/m",
                "--count", "5", "--out", str(oth), env=env)
        expect(r.returncode == 0, "outreach_pack exits 0")
        outxt = oth.read_text()
        expect("Draft 1" in outxt and "Draft 5" in outxt, "5 drafts produced")
        expect("[Creator]" in outxt, "placeholder remains for user to fill")

    if FAILS:
        print(f"\n{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-launch smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
