#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-retention."""
from __future__ import annotations
import csv, datetime, json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import csv_parser as cp
import rfm as rfm_mod
import repeat_paths as rp
import winback as wb
import subscription as sub
import vip

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def make_synthetic_csv(path: Path) -> None:
    """Create a 50-customer × ~120-order synthetic dataset.
    Mix of: 1 champion, 5 loyal, 10 at-risk, 20 new, 14 lost/promising.
    """
    today = datetime.date.today()

    def days_ago(d: int) -> datetime.date:
        return today - datetime.timedelta(days=d)

    rows = []

    # 1 Champion: 8 recent orders, high spend
    for i in range(8):
        rows.append({
            "customer_id": "champ-001", "email": "champ001@x.com",
            "order_id": f"o-champ-{i}", "order_date": days_ago(7 + i * 10).isoformat(),
            "total": 49.99, "skus": "MKR-16;FH-3PK",
        })

    # 5 Loyal: 4 orders each, moderate spend
    for n in range(5):
        for i in range(4):
            rows.append({
                "customer_id": f"loyal-{n}", "email": f"loyal{n}@x.com",
                "order_id": f"o-loy-{n}-{i}", "order_date": days_ago(20 + i * 25).isoformat(),
                "total": 29.99, "skus": "MKR-16",
            })

    # 10 At Risk: 3 orders, last was 120-180 days ago
    for n in range(10):
        for i in range(3):
            rows.append({
                "customer_id": f"risk-{n}", "email": f"risk{n}@x.com",
                "order_id": f"o-risk-{n}-{i}", "order_date": days_ago(150 + i * 60).isoformat(),
                "total": 39.99, "skus": "FH-3PK",
            })

    # 20 New: 1-2 orders, recent
    for n in range(20):
        rows.append({
            "customer_id": f"new-{n}", "email": f"new{n}@x.com",
            "order_id": f"o-new-{n}", "order_date": days_ago(3 + n).isoformat(),
            "total": 19.99, "skus": "CS-MAGIC",
        })

    # 14 Lost: 1 order, > 365 days ago
    for n in range(14):
        rows.append({
            "customer_id": f"lost-{n}", "email": f"lost{n}@x.com",
            "order_id": f"o-lost-{n}", "order_date": days_ago(400 + n * 10).isoformat(),
            "total": 14.99, "skus": "CS-MAGIC",
        })

    # Add a subscription-candidate SKU: 8 customers buy "consumable-x" every ~30 days
    for n in range(8):
        for i in range(4):  # 4 purchases each, ~30 days apart
            rows.append({
                "customer_id": f"sub-{n}", "email": f"sub{n}@x.com",
                "order_id": f"o-sub-{n}-{i}", "order_date": days_ago(10 + i * 30).isoformat(),
                "total": 24.99, "skus": "CONSUMABLE-X",
            })

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["customer_id", "email", "order_id",
                                                "order_date", "total", "skus"])
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "customer_id": r["customer_id"], "email": r["email"],
                "order_id": r["order_id"], "order_date": r["order_date"],
                "total": r["total"], "skus": r["skus"],
            })


def main() -> int:
    # ============================================================
    # 1. csv_parser
    # ============================================================
    print("\n[1] csv_parser column detection")
    with tempfile.TemporaryDirectory() as tmp:
        # Standard format
        csv_p = Path(tmp) / "standard.csv"
        Path(csv_p).write_text(
            "customer_id,email,order_id,order_date,total,product_skus\n"
            "c1,a@b.com,o1,2026-01-15,29.99,MKR-16\n",
            encoding="utf-8",
        )
        orders = list(cp.iter_orders(csv_p))
        expect(len(orders) == 1, "1 order parsed from standard CSV")
        expect(orders[0]["customer_id"] == "c1", "customer_id parsed")
        expect(orders[0]["total"] == 29.99, "total parsed")
        expect(orders[0]["skus"] == ["MKR-16"], "skus parsed")

        # Shopify-style format
        csv_p2 = Path(tmp) / "shopify.csv"
        Path(csv_p2).write_text(
            "Name,Email,Created at,Total,Lineitem sku\n"
            "#1001,b@c.com,2026-01-20 14:30:00 +0000,$44.99,FH-3PK;CS-MAGIC\n",
            encoding="utf-8",
        )
        orders = list(cp.iter_orders(csv_p2))
        expect(len(orders) == 1, "1 order parsed from Shopify CSV")
        expect(orders[0]["customer_id"] == "b@c.com", "email used as ID when customer_id missing")
        expect(orders[0]["total"] == 44.99, "$ symbol stripped from total")
        expect(len(orders[0]["skus"]) == 2, "multiple SKUs parsed")

    # ============================================================
    # 2. RFM
    # ============================================================
    print("\n[2] RFM classification on synthetic data")
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "orders.csv"
        make_synthetic_csv(csv_path)
        orders = list(cp.iter_orders(csv_path))
        expect(len(orders) >= 100, f"≥100 orders generated (got {len(orders)})")

        by_cust = cp.aggregate_by_customer(orders)
        expect(len(by_cust) >= 50, f"≥50 customers (got {len(by_cust)})")

        classified = rfm_mod.classify(by_cust)
        expect(len(classified) == len(by_cust), "all customers classified")

        segments = {c["segment"] for c in classified}
        expect("Champions" in segments, "Champions segment present")
        expect("At Risk" in segments or "Lost" in segments, "At Risk or Lost present")
        expect("New" in segments, "New segment present")

        summary = rfm_mod.segment_summary(classified)
        expect(summary["Champions"]["count"] >= 1, "≥1 Champion")

        # Champion should be near top by LTV
        top_lt = classified[0]
        expect(top_lt["ltv_usd"] > 100, f"top customer LTV > 100 (got {top_lt['ltv_usd']})")

        # ============================================================
        # 3. repeat_paths
        # ============================================================
        print("\n[3] repeat_paths.analyze")
        analysis = rp.analyze(orders)
        expect(analysis["total_first_purchase_skus"] >= 3, "≥3 first-purchase SKUs")
        expect(analysis["funnel"], "funnel non-empty")
        # Customers who first bought CONSUMABLE-X should have high repeat rate
        cx = next((f for f in analysis["funnel"] if f["first_sku"] == "CONSUMABLE-X"), None)
        if cx:
            expect(cx["repeat_rate"] >= 0.5, f"CONSUMABLE-X gateway repeat rate ≥ 50% (got {cx['repeat_rate']*100:.0f}%)")

        # ============================================================
        # 4. winback
        # ============================================================
        print("\n[4] winback.find_eligible")
        eligible = wb.find_eligible(classified, days_inactive=90)
        expect(len(eligible) >= 5, f"≥5 winback candidates (got {len(eligible)})")
        # Eligible should include at-risk + lost
        eligible_segs = {c["segment"] for c in eligible}
        expect("At Risk" in eligible_segs or "Lost" in eligible_segs, "winback includes At Risk or Lost")

        # Draft an email
        if eligible:
            d = wb.draft_email(eligible[0], store_name="Acme Pets")
            expect("subject" in d and d["subject"], "draft has subject")
            expect("body_md" in d and d["body_md"], "draft has body")
            expect("WB20" in d["body_md"] or "LAST30" in d["body_md"], "draft includes promo code")

        # CSV export
        csv_text = wb.render_segment_csv(eligible)
        expect(csv_text.startswith("email,"), "csv has header")
        expect(len(csv_text.splitlines()) == len(eligible) + 1, "csv row count matches")

        # ============================================================
        # 5. subscription
        # ============================================================
        print("\n[5] subscription.analyze")
        sub_candidates = sub.analyze(orders, min_repeat_rate=0.20, min_buyers=5)
        expect(len(sub_candidates) >= 1, f"≥1 subscription candidate (got {len(sub_candidates)})")
        consumable = next((c for c in sub_candidates if c["sku"] == "CONSUMABLE-X"), None)
        expect(consumable is not None, "CONSUMABLE-X detected as subscription candidate")
        if consumable:
            expect(consumable["repeat_rate"] >= 0.5, "CONSUMABLE-X repeat rate ≥ 50%")
            expect(25 <= consumable["median_interval_days"] <= 35,
                   f"median interval ~30 days (got {consumable['median_interval_days']})")

        # ============================================================
        # 6. VIP
        # ============================================================
        print("\n[6] vip.find_vips")
        vips = vip.find_vips(classified, top_percent=10)
        expect(len(vips) >= 1, f"≥1 VIP (got {len(vips)})")
        # VIPs are sorted by LTV — first VIP should be highest LTV
        expect(vips[0]["ltv_usd"] == classified[0]["ltv_usd"], "first VIP = top LTV")
        draft = vip.draft_outreach(vips[0], store_name="Acme Pets")
        expect("personal note" in draft["subject"].lower() or "thank" in draft["body_md"].lower(),
               "VIP draft is personal-toned")

        # ============================================================
        # 7. End-to-end via run.py
        # ============================================================
        print("\n[7] run.py --mode all (end-to-end)")
        with tempfile.TemporaryDirectory() as tmp2:
            env = {**os.environ, "HOME": tmp2}
            root = Path(tmp2) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            # Seed a store
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "Acme Pets", "shopify", "https://x.com", "USD", "us", "10-to-100", "kitchen", ts, ts),
            )
            db.commit(); db.close()

            r = subprocess.run(
                ["python3", str(RUN), "--mode", "all", "--csv", str(csv_path),
                 "--store-id", sid, "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--mode all exits 0 (stderr={r.stderr[:400]})")
            result = json.loads(r.stdout)
            expect(result["metrics"]["total_customers"] >= 50, "metrics: 50+ customers")
            expect(result["metrics"]["champions_count"] >= 1, "metrics: champions exist")
            expect(result["metrics"]["winback_eligible_count"] >= 5, "metrics: winback eligible exist")
            expect(result["metrics"]["subscription_candidate_count"] >= 1,
                   "metrics: subscription candidates")
            expect(result["metrics"]["vip_count"] >= 1, "metrics: VIPs exist")
            expect(result["deliverables_count"] >= 5, "5+ deliverables generated")

            # Verify customer_segments table populated
            db = sqlite3.connect(root / "store.db")
            n = db.execute("SELECT COUNT(*) FROM customer_segments").fetchone()[0]
            db.close()
            expect(n >= 50, f"customer_segments has 50+ rows (got {n})")

            # Verify files
            run_dirs = list((root / "runs").iterdir())
            rd = run_dirs[-1]
            for filename in ["rfm-report.md", "repeat-paths.md", "winback-drafts.md",
                              "winback-segment.csv", "subscription-candidates.md",
                              "vip-outreach.md", "result.json"]:
                expect((rd / filename).exists(), f"{filename} written")

        # ============================================================
        # 8. Agent mode
        # ============================================================
        print("\n[8] run.py agent mode + outbox notification")
        with tempfile.TemporaryDirectory() as tmp3:
            env = {**os.environ, "HOME": tmp3}
            root = Path(tmp3) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute("INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (sid, "X", "shopify", "x", "USD", "us", "1-to-10", "k", ts, ts))
            db.commit(); db.close()
            r = subprocess.run(
                ["python3", str(RUN), "--mode", "rfm", "--csv", str(csv_path),
                 "--store-id", sid, "--quiet-stdout",
                 "--notify-channel", "feishu", "--notify-target", "group:retention"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "agent mode exits 0")
            outbox = root / "outbox"
            files = list(outbox.glob("*.json"))
            expect(len(files) >= 1, "outbox notification written")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-retention smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
