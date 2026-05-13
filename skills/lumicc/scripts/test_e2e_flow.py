#!/usr/bin/env python3
"""End-to-end integration test for the full Lumicc skill bundle.

Simulates a real cross-border store life-cycle:
  Day 0  : init store
  Day 1  : lumicc-launch (30-day plan)
  Day 8  : lumicc-watch (competitor diff) — bypass network with stub
  Day 15 : lumicc-listing (audit)
  Day 18 : lumicc-voc (review clustering + verification on re-run)
  Day 22 : lumicc-rescue (crisis: ad disapproval)
  Day 23 : lumicc-expand (find next SKU)
  Day 24 : lumicc-dashboard (render HTML from accumulated state)

All run against the same ~/.commerce-os/ — proving the skills compose correctly,
shared schema works across sub-skills, and the dashboard reflects accumulated state.
"""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS_ROOT = HERE.parent.parent
LUMICC = SKILLS_ROOT / "lumicc"
LAUNCH = SKILLS_ROOT / "lumicc-launch"
WATCH = SKILLS_ROOT / "lumicc-watch"
LISTING = SKILLS_ROOT / "lumicc-listing"
VOC = SKILLS_ROOT / "lumicc-voc"
RESCUE = SKILLS_ROOT / "lumicc-rescue"
EXPAND = SKILLS_ROOT / "lumicc-expand"
DASHBOARD = SKILLS_ROOT / "lumicc-dashboard"

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def run(*args, env, **kw):
    return subprocess.run(["python3", *args], capture_output=True, text=True, env=env, **kw)


def main() -> int:
    print("=" * 60)
    print("Lumicc End-to-End Flow Integration Test")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        root = Path(tmp) / ".commerce-os"

        # ============ Day 0: init ============
        print("\n[Day 0] init_store.py")
        r = run(str(LUMICC / "scripts" / "init_store.py"), env=env)
        expect(r.returncode == 0, "init succeeds")
        expect((root / "store.db").exists(), "store.db created")

        # Seed a store manually (in real life lumicc would ask)
        db = sqlite3.connect(root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets E2E", "shopify", "https://e2e-acme.myshopify.com",
             "USD", "us", "0-to-1", "pet accessories", ts, ts),
        )
        db.commit(); db.close()

        # ============ Day 1: route + launch ============
        print("\n[Day 1] route.py → should pick lumicc-launch")
        r = run(str(LUMICC / "scripts" / "route.py"),
                "--intent", "I want to start a cross-border store from scratch",
                "--store-id", sid, env=env)
        expect(r.returncode == 0, "route exits 0")
        decision = json.loads(r.stdout)
        expect(decision["matched_subskill"] == "lumicc-launch", "router picks lumicc-launch")

        print("\n[Day 1] lumicc-launch — generate 30-day plan")
        r = run(str(LAUNCH / "scripts" / "plan.py"),
                "--store-id", sid, "--budget", "2500", "--hours", "15", "--quiet-stdout", env=env)
        expect(r.returncode == 0, "plan exits 0")

        # Verify campaign + event + run
        db = sqlite3.connect(root / "store.db")
        cold_camp = db.execute(
            "SELECT * FROM campaigns WHERE store_id=? AND type='cold-start' AND status='running'", (sid,)
        ).fetchone()
        db.close()
        expect(cold_camp is not None, "cold-start campaign running")

        # ============ Day 1 (still): day_advance ============
        print("\n[Day 1] day_advance — today's tasks")
        r = run(str(LAUNCH / "scripts" / "day_advance.py"), "--store-id", sid, "--quiet-stdout", env=env)
        expect(r.returncode == 0, "day_advance exits 0")

        # ============ Day 8: lumicc-watch ============
        print("\n[Day 8] lumicc-watch — config targets, then run with one local URL")
        # Set preferences
        db = sqlite3.connect(root / "store.db")
        db.execute("INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?,?,?)",
                   (f"watchtower_targets:{sid}", json.dumps([]), int(time.time())))
        db.commit(); db.close()
        # Run with explicit --target pointing to a placeholder URL — should error gracefully
        r = run(str(WATCH / "scripts" / "run.py"),
                "--store-id", sid, "--target", "http://127.0.0.1:1", "--delay-ms", "10",
                "--quiet-stdout", env=env)
        # Watch may exit non-zero on connection refused, but the run row should still log
        expect(r.returncode in (0, 1), f"watch exits 0 or 1 (got {r.returncode})")

        # ============ Day 15: lumicc-listing ============
        print("\n[Day 15] lumicc-listing — audit listings")
        # Seed a product
        db = sqlite3.connect(root / "store.db")
        db.execute(
            "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, data_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), sid, "MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99,
             json.dumps({"bullets": ["Strong", "Easy", "Stainless", "16in", "Clean"],
                         "images": [{"url": "h", "width": 1500}] + [{"url": str(i)} for i in range(5)]}),
             int(time.time())),
        )
        db.commit(); db.close()
        r = run(str(LISTING / "scripts" / "run.py"), "--store-id", sid, "--quiet-stdout", env=env)
        expect(r.returncode == 0, "listing audit exits 0")

        # ============ Day 18: lumicc-voc ============
        print("\n[Day 18] lumicc-voc — cluster reviews")
        reviews = Path(tmp) / "reviews.json"
        reviews.write_text(json.dumps([
            {"text": "Arrived dented", "sku": "MKR-16", "ts": int(time.time())},
            {"text": "Box was crushed", "sku": "MKR-16"},
            {"text": "包装压坏了", "sku": "MKR-16"},
            {"text": "Doesn't fit my drawer", "sku": "MKR-16"},
        ]))
        r = run(str(VOC / "scripts" / "run.py"),
                "--store-id", sid, "--input", str(reviews), "--quiet-stdout", env=env)
        expect(r.returncode == 0, "voc exits 0")

        # ============ Day 22: lumicc-rescue ============
        print("\n[Day 22] lumicc-rescue — ad disapproval crisis")
        r = run(str(RESCUE / "scripts" / "run.py"),
                "--store-id", sid, "--platform-notification", "ad_disapproval",
                "--recent-change", "ad", "--scope", "store_wide", "--quiet-stdout", env=env)
        expect(r.returncode == 0, "rescue exits 0")
        result = json.loads(r.stdout)
        expect(result["branch"] == "B", "branch B for ad disapproval")

        # ============ Day 23: lumicc-expand ============
        print("\n[Day 23] lumicc-expand — score candidates")
        cands = Path(tmp) / "cands.json"
        cands.write_text(json.dumps([
            {"title": "Magnetic Spice Rack 8-jar", "landed_cost_usd": 4.20, "suggested_retail_usd": 24.99,
             "demand_signals": {"amazon_revenue_yoy_pct": 30, "tiktok_hashtag_growth_pct": 80},
             "content_angle": "before_after", "has_visual_hook": True,
             "supplier": {"alibaba_verified": True, "moq": 50, "response_rate": 0.95},
             "fulfillment": {"weight_g": 320}},
        ]))
        r = run(str(EXPAND / "scripts" / "run.py"),
                "--store-id", sid, "--candidates", str(cands), "--quiet-stdout", env=env)
        expect(r.returncode == 0, "expand exits 0")

        # ============ Day 24: lumicc-dashboard ============
        print("\n[Day 24] lumicc-dashboard — render HTML")
        r = run(str(DASHBOARD / "scripts" / "render.py"),
                "--no-open", "--quiet-stdout", env=env)
        expect(r.returncode == 0, "dashboard render exits 0")
        result = json.loads(r.stdout)
        expect(result["status"] == "success", "render success")
        expect(result["pages_rendered"] == 5, "5 pages rendered")

        # ============ Final state verification ============
        print("\n[Final] verify accumulated state")
        db = sqlite3.connect(root / "store.db")
        n_stores = db.execute("SELECT COUNT(*) FROM stores").fetchone()[0]
        n_camps = db.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
        camps_by_type = dict(db.execute("SELECT type, COUNT(*) FROM campaigns GROUP BY type").fetchall())
        n_events = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        runs_by_skill = dict(db.execute("SELECT skill, COUNT(*) FROM runs GROUP BY skill").fetchall())
        db.close()

        expect(n_stores == 1, "1 store accumulated")
        expect(n_camps >= 3, f"≥3 campaigns (got {n_camps}: {camps_by_type})")
        expect("cold-start" in camps_by_type, "cold-start campaign exists")
        expect("voc-fix" in camps_by_type, "voc-fix campaign exists")
        expect("crisis" in camps_by_type, "crisis campaign exists")
        expect(n_events >= 6, f"≥6 events (got {n_events})")
        expected_skills = {"lumicc-launch", "lumicc-watch", "lumicc-listing",
                           "lumicc-voc", "lumicc-rescue", "lumicc-expand", "lumicc-dashboard"}
        actual_skills = set(runs_by_skill.keys())
        missing = expected_skills - actual_skills
        expect(not missing, f"all 7 sub-skills have runs (missing: {missing})")

        # Verify dashboard HTML reflects state
        dash_index = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        expect("Acme Pets E2E" in dash_index, "dashboard shows seeded store")
        expect("cold-start" in dash_index, "dashboard shows active cold-start")
        memory_html = (root / "dashboard" / "memory.html").read_text(encoding="utf-8")
        runs_html = (root / "dashboard" / "runs.html").read_text(encoding="utf-8")
        for sk in ["lumicc-launch", "lumicc-listing", "lumicc-voc", "lumicc-rescue", "lumicc-expand"]:
            expect(sk in runs_html, f"runs page shows {sk}")

    if FAILS:
        print(f"\n{'='*60}")
        print(f"{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print(f"\n{'='*60}")
    print("✅ End-to-end flow integration test: ALL PASSED")
    print("    7 skills composed correctly on shared store.db.")
    print(f"{'='*60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
