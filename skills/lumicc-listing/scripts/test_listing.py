#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-listing."""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import checks as C

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        root = Path(tmp) / ".commerce-os"

        # 1) Pure check library
        print("\n[1] checks.py — image_count")
        r = C.check_images({"images": [{"url": "x", "width": 1500}, {"url": "y"}, {"url": "z"}, {"url": "a"}, {"url": "b"}, {"url": "c"}]})
        expect(r["score"] == 10, f"6 images + 1500px hero = 10/10 (got {r['score']})")
        r = C.check_images({"images": [{"url": "x", "width": 600}]})
        expect(r["score"] <= 4, "1 small image is low score")

        print("\n[2] checks.py — title_seo")
        r = C.check_title_seo({"title": "Magnetic Knife Rack 16 inch — Heavy-Duty Stainless Steel Magnetic Strip", "primary_keywords": ["magnetic", "knife"]})
        expect(r["score"] == 10, f"60-80 char title with keyword = 10 (got {r['score']})")
        r = C.check_title_seo({"title": "BUY NOW MAGNETIC KNIFE RACK CHEAP!!!", "primary_keywords": ["magnetic"]})
        expect(r["score"] <= 4, "ALL CAPS title → low")

        print("\n[3] checks.py — bullets")
        long_b = "B" * 250
        r = C.check_bullets({"bullets": ["Benefit one", "Benefit two", "Benefit three", "Benefit four", "Benefit five"]})
        expect(r["score"] >= 7, "5 normal bullets ≥ 7")
        r = C.check_bullets({"bullets": [long_b]})
        expect(r["score"] <= 5, "long bullet penalized")

        print("\n[4] checks.py — full audit")
        prod = {
            "title": "Magnetic Knife Rack 16 inch — Heavy-Duty Stainless Steel",
            "description": "<h2>Why magnetic?</h2>" + " ".join(["organize"] * 250) + " Shop now!",
            "bullets": ["Strong magnets", "Easy install", "16in length", "Stainless steel", "Easy clean"],
            "images": [{"url": "x", "width": 1500}] + [{"url": str(i)} for i in range(5)],
            "price": 29.99,
            "compare_at_price": 39.99,
            "reviews": {"count": 12, "avg": 4.4, "last_review_ts": int(time.time()) - 86400},
            "scarcity_signal": True,
            "mobile_lcp_ms": 2200,
            "primary_keywords": ["magnetic", "knife"],
        }
        a = C.audit(prod)
        expect(a["total"] >= 85, f"healthy product = ≥85 (got {a['total']})")
        expect(a["severity"] == "healthy", "severity = healthy")
        expect(len(a["top_fixes"]) <= 3, "top_fixes capped at 3")

        # 5) sick listing
        sick = {"title": "x", "bullets": [], "images": [], "price": 10, "reviews": {"count": 0, "avg": 0}}
        a = C.audit(sick)
        expect(a["total"] < 50, f"sick listing < 50 (got {a['total']})")
        expect(a["severity"] == "sick", "severity = sick")

        # 6) End-to-end run.py
        print("\n[5] run.py end-to-end")
        subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
        db = sqlite3.connect(root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://x.myshopify.com", "USD", "us", "1-to-10", "pets", ts, ts),
        )
        db.execute(
            "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, data_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sid, "MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99,
             json.dumps({"bullets": ["A", "B", "C", "D", "E"], "images": [{"url": "x", "width": 1500}, {"url": "y"}, {"url": "z"}]}), ts),
        )
        db.execute(
            "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, data_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sid, "BAD-1", "x", "active", 5, 10, "{}", ts),
        )
        db.commit(); db.close()

        r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--quiet-stdout"], env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "run.py exits 0")
        result = json.loads(r.stdout)
        expect(result["products_audited"] == 2, "audited 2 products")

        # Find the run dir
        run_dirs = sorted((root / "runs").iterdir())
        rd = run_dirs[-1]
        rep = (rd / "report.md").read_text(encoding="utf-8")
        expect("Magnetic Knife Rack 16in" in rep, "report mentions good product")
        expect("Top 3 修复" in rep, "report has fixes section")

        # 7) DB rows
        db = sqlite3.connect(root / "store.db")
        n_runs = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-listing'").fetchone()[0]
        n_evt = db.execute("SELECT COUNT(*) FROM events WHERE category='task' AND content LIKE '%lumicc-listing%'").fetchone()[0]
        db.close()
        expect(n_runs >= 1, "runs row inserted")
        expect(n_evt >= 1, "event inserted")

        # 8) Agent mode
        r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--quiet-stdout",
                            "--notify-channel", "feishu", "--notify-target", "group:ops"],
                           env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "agent mode exits 0")
        outbox = root / "outbox"
        files = list(outbox.glob("*.json"))
        expect(len(files) >= 1, "outbox notification")
        payload = json.loads(files[0].read_text())
        expect(payload["skill"] == "lumicc-listing", "outbox skill correct")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-listing smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
