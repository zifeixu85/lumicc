#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-expand."""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
SCORE = HERE / "score.py"
FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        root = Path(tmp) / ".commerce-os"

        r = subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "init_store succeeds")

        # Seed store with an existing winner
        db = sqlite3.connect(root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://x.myshopify.com", "USD", "us", "1-to-10", "pet accessories", ts, ts),
        )
        db.execute(
            "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sid, "MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99, ts, ts),
        )
        db.commit(); db.close()
        (root / "SOUL.md").write_text("Target gross margin >= 40%\n", encoding="utf-8")

        # Test 1: score.py library — strong candidate
        print("\n[1] score.py — strong candidate")
        cand = {
            "title": "Magnetic Spice Rack 8-jar",
            "landed_cost_usd": 4.20,
            "suggested_retail_usd": 24.99,
            "demand_signals": {"amazon_revenue_yoy_pct": 30, "tiktok_hashtag_growth_pct": 80, "google_trends_slope": 8},
            "content_angle": "before_after",
            "has_visual_hook": True,
            "supplier": {"alibaba_verified": True, "moq": 50, "response_rate": 0.95},
            "fulfillment": {"weight_g": 320},
        }
        r = subprocess.run(["python3", str(SCORE)], env=env, capture_output=True, text=True, input=json.dumps(cand))
        expect(r.returncode == 0, "score CLI exits 0")
        scored = json.loads(r.stdout)
        expect(isinstance(scored, list) and len(scored) == 1, "returns list of 1")
        expect(scored[0]["action"] == "order_sample", "strong candidate → order_sample")
        expect(scored[0]["total"] >= 8.0, f"total >= 8.0 (got {scored[0]['total']})")

        # Test 2: score.py — below SOUL margin
        print("\n[2] score.py — below SOUL margin")
        bad = {**cand, "landed_cost_usd": 20, "suggested_retail_usd": 25}
        r = subprocess.run(["python3", str(SCORE), "--soul-min-margin", "0.4"], env=env, capture_output=True, text=True, input=json.dumps(bad))
        scored = json.loads(r.stdout)
        expect(scored[0]["action"] == "reject", "below-margin → reject")
        expect("SOUL" in scored[0]["factors"]["margin"]["evidence"], "evidence references SOUL")

        # Test 3: score.py — hazardous auto-reject
        print("\n[3] score.py — hazardous")
        haz = {**cand, "fulfillment": {**cand["fulfillment"], "hazardous": True}}
        r = subprocess.run(["python3", str(SCORE)], env=env, capture_output=True, text=True, input=json.dumps(haz))
        scored = json.loads(r.stdout)
        expect(scored[0]["action"] == "reject", "hazardous → reject")
        expect(scored[0]["factors"]["fulfillment"]["score"] == 0, "fulfillment 0/10 for hazardous")

        # Test 4: run.py — no candidates → worksheet mode
        print("\n[4] run.py — worksheet fallback")
        r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--quiet-stdout"], env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "worksheet mode exits 0")
        result = json.loads(r.stdout)
        expect(result["status"] in ("success", "partial"), "status set")
        # Locate the run dir
        runs_dir = root / "runs"
        run_dirs = list(runs_dir.iterdir())
        expect(len(run_dirs) >= 1, "run dir created")
        rd = run_dirs[-1]
        ws = rd / "worksheet.md"
        expect(ws.exists(), "worksheet.md written")
        expect("Expansion Research Worksheet" in ws.read_text(encoding="utf-8"), "worksheet content present")

        # Test 5: run.py — with candidates JSON
        print("\n[5] run.py — full scoring path")
        cand_file = Path(tmp) / "cands.json"
        cand_file.write_text(json.dumps([cand, bad, haz]))
        r = subprocess.run(
            ["python3", str(RUN), "--store-id", sid, "--candidates", str(cand_file), "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "full scoring exits 0")

        # Verify event + run rows
        db = sqlite3.connect(root / "store.db")
        n_events = db.execute("SELECT COUNT(*) FROM events WHERE category='task'").fetchone()[0]
        n_runs = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-expand'").fetchone()[0]
        db.close()
        expect(n_events >= 2, "events appended")
        expect(n_runs >= 2, "runs logged")

        # Test 6: agent mode notification
        print("\n[6] agent mode notification")
        r = subprocess.run(
            ["python3", str(RUN), "--store-id", sid, "--candidates", str(cand_file),
             "--notify-channel", "feishu", "--notify-target", "group:ops", "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "agent-mode exits 0")
        outbox = root / "outbox"
        files = list(outbox.glob("*.json"))
        expect(len(files) >= 1, "outbox notification dropped")
        payload = json.loads(files[0].read_text())
        expect(payload["skill"] == "lumicc-expand", "payload skill correct")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-expand smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
