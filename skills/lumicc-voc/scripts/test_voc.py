#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-voc."""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import cluster as C

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def main() -> int:
    print("[1] cluster.py — keyword grouping")
    items = [
        {"text": "Arrived dented, terrible packaging", "sku": "MKR-16", "ts": int(time.time())},
        {"text": "包装压坏了", "sku": "MKR-16", "ts": int(time.time())},
        {"text": "Box was crushed", "sku": "FH-3PK"},
        {"text": "Doesn't fit my drawer, too big", "sku": "FH-3PK"},
        {"text": "Slow shipping, took 5 weeks"},
        {"text": "I love this product 5 stars!"},  # no cluster match
    ]
    clusters = C.cluster(items)
    topics = [c["topic"] for c in clusters]
    expect("packaging_damage" in topics, "packaging cluster detected")
    expect("size_mismatch" in topics, "size cluster detected")
    expect("delivery_late" in topics, "delivery cluster detected")
    pkg = next(c for c in clusters if c["topic"] == "packaging_damage")
    expect(pkg["size"] == 3, f"packaging size=3 (got {pkg['size']})")
    expect(set(pkg["products_affected"]) == {"MKR-16", "FH-3PK"}, "products_affected correct")

    print("\n[2] propose_fixes")
    fixed = C.propose_fixes(clusters)
    pkg = next(c for c in fixed if c["topic"] == "packaging_damage")
    expect(len(pkg["proposed_fixes"]) >= 1, "packaging has proposed fixes")
    expect(any(f["type"] == "operation" for f in pkg["proposed_fixes"]), "operation fix present")

    print("\n[3] run.py end-to-end")
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        root = Path(tmp) / ".commerce-os"
        subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
        # Seed a store
        db = sqlite3.connect(root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://x.com", "USD", "us", "1-to-10", "pets", ts, ts),
        )
        db.commit(); db.close()

        # Input
        in_path = Path(tmp) / "reviews.json"
        in_path.write_text(json.dumps(items))
        r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--input", str(in_path), "--quiet-stdout"],
                           env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "run.py exits 0")
        result = json.loads(r.stdout)
        expect(result["clusters"] >= 3, f"clusters >= 3 (got {result['clusters']})")

        # Verify campaign + run rows
        db = sqlite3.connect(root / "store.db")
        n_camp = db.execute("SELECT COUNT(*) FROM campaigns WHERE type='voc-fix'").fetchone()[0]
        n_run = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-voc'").fetchone()[0]
        db.close()
        expect(n_camp >= 1, "voc-fix campaign inserted")
        expect(n_run >= 1, "run row inserted")

        # 4) Verification cycle: re-run with smaller dataset to test shrinkage detection
        print("\n[4] verification on re-run")
        items_smaller = items[:1]  # one packaging complaint left
        in2 = Path(tmp) / "r2.json"
        in2.write_text(json.dumps(items_smaller))
        r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--input", str(in2), "--quiet-stdout"],
                           env=env, capture_output=True, text=True)
        expect(r.returncode == 0, "verification re-run exits 0")
        # Read latest run result
        runs_dir = root / "runs"
        latest = max(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        r2 = json.loads((latest / "result.json").read_text())
        expect(r2["prior_cluster_sizes"].get("packaging_damage") == 3, "prior size detected")

        # 5) Agent mode
        print("\n[5] agent mode notification")
        r = subprocess.run(
            ["python3", str(RUN), "--store-id", sid, "--input", str(in_path), "--quiet-stdout",
             "--notify-channel", "feishu", "--notify-target", "group:ops"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "agent mode exits 0")
        outbox = root / "outbox"
        files = list(outbox.glob("*.json"))
        expect(len(files) >= 1, "outbox dropped")

    print("\n[6] render_html smoke")
    import render_html as RH
    synth_clusters = [
        {"topic": "packaging_damage", "size": 3, "products_affected": ["MKR-16"],
         "exemplars": ["Box was crushed", "包装压坏了"], "recency_weighted_size": 3.5,
         "proposed_fixes": [{"type": "operation", "detail": "Bubble wrap"}]},
        {"topic": "size_mismatch", "size": 1, "products_affected": [],
         "exemplars": ["Too big"], "recency_weighted_size": 1.0,
         "proposed_fixes": []},
    ]
    synth_prior = {"packaging_damage": 5, "delivery_late": 2}
    html = RH.render_page(
        run_id="abcdef1234567890", store_name="Acme Pets",
        clusters=synth_clusters, prior=synth_prior,
        total_reviews=8, unmatched_count=4,
        html_path=Path("/tmp/voc_smoke.html"),
    )
    expect("<!doctype html>" in html, "render_page returns full HTML doc")
    expect("包装破损" in html, "topic label rendered")
    expect("NEW" in html or "新出现" in html, "delta vs prior rendered")
    # Empty prior path
    html2 = RH.render_page(
        run_id="x" * 16, store_name="", clusters=[], prior={},
        total_reviews=0, unmatched_count=0, html_path=Path("/tmp/voc_empty.html"),
    )
    expect("<!doctype html>" in html2, "render_page handles empty clusters")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-voc smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
