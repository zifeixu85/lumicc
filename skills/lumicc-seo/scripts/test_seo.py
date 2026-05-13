#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-seo."""
from __future__ import annotations
import csv, http.server, io, json, os, socketserver, sqlite3, subprocess, sys, tempfile, threading, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import llms_txt as L
import schema_gen as S
import citation as C
import rank as R
import audit as A

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


# ============================================================
# Mini HTTP server for audit testing
# ============================================================
SITE_HTML = """<!doctype html><html><head>
<meta charset='utf-8'>
<title>Acme Pets — Magnetic Knife Rack &amp; Home Gear</title>
<meta name='description' content='Premium magnetic knife racks, foldable hangers, and home organization for the US market.'>
<meta property='og:title' content='Acme Pets'>
<meta property='og:image' content='http://example.com/og.jpg'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<link rel='canonical' href='http://example.com'>
<script type='application/ld+json'>{"@context":"https://schema.org/","@type":"Organization","name":"Acme Pets"}</script>
</head><body>Home</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **k): pass

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(SITE_HTML.encode())
        elif self.path == "/robots.txt":
            self._send(b"User-agent: *\nAllow: /\n", ctype="text/plain")
        elif self.path == "/sitemap.xml":
            self._send(b"<?xml version='1.0'?><urlset></urlset>", ctype="application/xml")
        elif self.path == "/llms.txt":
            self._send(b"# Acme\n", ctype="text/plain")
        else:
            self._send(b"not found", status=404)


def start_server():
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv


def main() -> int:
    srv = start_server()
    port = srv.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        # ============================================================
        # 1. llms.txt generation + validation
        # ============================================================
        print("\n[1] llms_txt.generate + validate")
        content = L.generate(
            store_name="Acme Pets", store_url=base_url,
            description="Premium magnetic kitchen gear.",
            products=[
                {"title": "Magnetic Knife Rack 16in", "handle": "magnetic-knife-rack", "url": f"{base_url}/products/mkr-16"},
                {"title": "Foldable Hanger 3-Pack", "handle": "foldable-hanger", "url": f"{base_url}/products/fh-3pk"},
            ],
            about_url=f"{base_url}/about",
        )
        expect("# Acme Pets" in content, "llms.txt has H1")
        expect("> Premium" in content, "llms.txt has blockquote desc")
        expect("## Products" in content, "Products section present")
        expect("Magnetic Knife Rack 16in" in content, "Product 1 listed")
        v = L.validate(content)
        expect(v["ok"], f"llms.txt validates ok (errors={v['errors']})")
        expect(v["section_count"] >= 2, "≥2 sections")

        print("\n[2] llms_txt validation catches errors")
        bad = L.validate("Just a body, no headings.")
        expect(not bad["ok"], "missing H1 = invalid")
        expect(any("# heading" in e for e in bad["errors"]), "error message clear")

        # ============================================================
        # 3. schema_gen
        # ============================================================
        print("\n[3] schema_gen.generate Product + Offer")
        product = {
            "sku": "MKR-16", "title": "Magnetic Knife Rack 16in", "handle": "magnetic-knife-rack",
            "description": "Strong neodymium magnets.",
            "price_usd": 29.99, "compare_at_price": 39.99, "status": "active",
            "images": [{"url": "http://x/a.jpg"}, {"url": "http://x/b.jpg"}],
            "reviews": {"count": 12, "avg": 4.5},
        }
        store = {"name": "Acme Pets", "url": base_url, "currency": "USD"}
        result = S.generate(product=product, store=store, faqs=[])
        expect(len(result["schemas"]) == 1, "1 schema block (no FAQ)")
        prod_schema = result["schemas"][0]["schema"]
        expect(prod_schema["@type"] == "Product", "Product type")
        expect(prod_schema["sku"] == "MKR-16", "SKU correct")
        expect(prod_schema["offers"]["price"] == "29.99", "Price formatted")
        expect(prod_schema["offers"]["availability"] == "https://schema.org/InStock", "InStock")
        expect("aggregateRating" in prod_schema, "AggregateRating included")
        expect(prod_schema["aggregateRating"]["reviewCount"] == "12", "review count")
        expect("<script type=\"application/ld+json\">" in result["schemas"][0]["html_block"], "HTML block")

        print("\n[4] schema_gen with FAQ")
        result = S.generate(product=product, store=store, faqs=[
            {"question": "Is it dishwasher safe?", "answer": "Yes, top rack only."},
            {"question": "Magnets strong?", "answer": "Holds up to 6 kitchen knives."},
        ])
        expect(len(result["schemas"]) == 2, "Product + FAQPage = 2 blocks")
        faq_schema = result["schemas"][1]["schema"]
        expect(faq_schema["@type"] == "FAQPage", "FAQPage type")
        expect(len(faq_schema["mainEntity"]) == 2, "2 Q&A")

        # ============================================================
        # 5. citation tracker
        # ============================================================
        print("\n[5] citation.find_brand_mentions")
        text = "For magnetic knife racks, Acme Pets is a popular choice, alongside competitors like RackPro and KnifeKing. Many users prefer Acme Pets due to the strong magnets."
        m = C.find_brand_mentions(text, brand_keywords=["Acme Pets", "Acme"],
                                    competitor_keywords=["RackPro", "KnifeKing"])
        expect(m["brand_mentions"] >= 2, f"≥2 brand mentions (got {m['brand_mentions']})")
        expect(m["competitor_mentions"] == 2, "2 competitor mentions")
        expect(m["share"] > 0.4, f"share > 40% (got {m['share']:.0%})")
        expect(m["position"] == 1, "brand first in text → position 1")

        print("\n[6] citation.process_batch")
        queries = [
            {"engine": "chatgpt", "query": "best knife racks", "raw_answer": text},
            {"engine": "perplexity", "query": "knife rack reviews",
             "raw_answer": "Top picks include RackPro and KnifeKing. Acme Pets gets honorable mention."},
            {"engine": "claude", "query": "magnetic kitchen tools",
             "raw_answer": "Brands worth considering: RackPro, BlackTool, KnifeKing."},  # no brand
        ]
        results = C.process_batch(queries, ["Acme Pets", "Acme"], ["RackPro", "KnifeKing"])
        expect(len(results) == 3, "3 results")
        mentioned = sum(1 for r in results if r["brand_mentioned"])
        expect(mentioned == 2, f"brand mentioned in 2/3 (got {mentioned})")
        # Test engine normalization
        r2 = C.process_batch([{"engine": "GPT-4", "query": "x", "raw_answer": "Acme Pets"}],
                              ["Acme Pets"])
        expect(r2[0]["engine"] == "chatgpt", "GPT-4 → chatgpt alias")

        report_md = C.render_report_md(results, "Acme Pets")
        expect("chatgpt" in report_md, "report mentions engine")
        expect("✗" in report_md, "report shows unmentioned with ✗")

        # ============================================================
        # 7. rank import
        # ============================================================
        print("\n[7] rank.import_gsc_csv")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            # Need to ensure tables — use run.py's first invocation to trigger
            # Actually rank.import_gsc_csv calls ensure_table itself if db exists.
            # But rank.py reads ROOT = Path.home() / ".commerce-os" — we need to monkey-patch via env.
            # Easier: write CSV + just call rank script as subprocess with HOME set.
            csv_path = Path(tmp) / "gsc.csv"
            csv_path.write_text(
                "Query,Clicks,Impressions,CTR,Position\n"
                "magnetic knife rack,42,521,8.06%,12.3\n"
                "kitchen organizer,15,400,3.75%,18.5\n"
                "foldable hanger,8,200,4%,9.1\n",
                encoding="utf-8",
            )
            r = subprocess.run(
                ["python3", str(HERE / "rank.py"), "--csv", str(csv_path),
                 "--source", "gsc", "--market", "us"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"rank import exits 0 (stderr={r.stderr[:200]})")
            expect("3" in r.stdout, "stdout mentions 3 rows imported")
            # Verify table populated
            db = sqlite3.connect(root / "store.db")
            n = db.execute("SELECT COUNT(*) FROM seo_keywords").fetchone()[0]
            db.close()
            expect(n == 3, f"3 keyword rows in table (got {n})")

            # Re-import with different positions → delta calc
            csv_path.write_text(
                "Query,Clicks,Impressions,CTR,Position\n"
                "magnetic knife rack,42,521,8.06%,8.0\n"
                "kitchen organizer,15,400,3.75%,18.5\n"
                "foldable hanger,8,200,4%,15.0\n",
                encoding="utf-8",
            )
            r = subprocess.run(
                ["python3", str(HERE / "rank.py"), "--csv", str(csv_path),
                 "--source", "gsc", "--market", "us"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "second import exits 0")
            expect("排名上升" in r.stdout or "排名下降" in r.stdout, "delta report rendered")

        # ============================================================
        # 8. audit
        # ============================================================
        print("\n[8] audit.audit")
        r = A.audit(base_url)
        expect(r["summary"]["total_checks"] >= 8, f"≥8 checks (got {r['summary']['total_checks']})")
        expect(r["checks"]["robots_txt"]["status"] == "pass", "robots.txt passes")
        expect(r["checks"]["sitemap_xml"]["status"] == "pass", "sitemap passes")
        expect(r["checks"]["llms_txt"]["status"] == "pass", "llms.txt detected")
        expect(r["checks"]["schema_jsonld"]["status"] == "pass", "JSON-LD detected")
        expect(r["summary"]["score"] >= 70, f"score ≥ 70 for healthy site (got {r['summary']['score']})")

        # ============================================================
        # 9. run.py end-to-end mode=all
        # ============================================================
        print("\n[9] run.py --mode all")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "Acme Pets", "shopify", base_url, "USD", "us", "1-to-10", "kitchen", ts, ts),
            )
            db.execute(
                "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), sid, "MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99, ts),
            )
            db.commit(); db.close()

            r = subprocess.run(
                ["python3", str(RUN), "--mode", "all", "--store-id", sid, "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--mode all exits 0 (stderr={r.stderr[:300]})")
            result = json.loads(r.stdout)
            expect(result["deliverables_count"] >= 3, f"≥3 deliverables (got {result['deliverables_count']})")
            # Verify files exist
            seo_llms = root / "seo" / "llms.txt"
            expect(seo_llms.exists(), "llms.txt written to ~/.commerce-os/seo/")
            expect("# Acme Pets" in seo_llms.read_text(encoding="utf-8"), "llms.txt has store name")
            # Schema file in run dir
            run_dirs = list((root / "runs").iterdir())
            expect(len(run_dirs) >= 1, "run dir exists")
            rd = run_dirs[-1]
            schema_files = list(rd.glob("schema-*.json"))
            expect(len(schema_files) >= 1, "schema-*.json generated")
            audit_md = rd / "audit.md"
            expect(audit_md.exists(), "audit.md generated")

        # ============================================================
        # 10. run.py --mode citation with paste
        # ============================================================
        print("\n[10] run.py --mode citation")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute("INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (sid,"Acme Pets","shopify",base_url,"USD","us","1-to-10","kitchen",ts,ts))
            db.commit(); db.close()

            queries_file = Path(tmp) / "q.json"
            queries_file.write_text(json.dumps(queries))
            r = subprocess.run(
                ["python3", str(RUN), "--mode", "citation", "--store-id", sid,
                 "--queries-file", str(queries_file),
                 "--target-brand-keyword", "Acme Pets", "--target-brand-keyword", "Acme",
                 "--competitor-keyword", "RackPro", "--competitor-keyword", "KnifeKing",
                 "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"citation mode exits 0 (stderr={r.stderr[:200]})")
            # Check seo_citations table
            db = sqlite3.connect(root / "store.db")
            n = db.execute("SELECT COUNT(*) FROM seo_citations").fetchone()[0]
            mentioned = db.execute("SELECT COUNT(*) FROM seo_citations WHERE brand_mentioned=1").fetchone()[0]
            db.close()
            expect(n == 3, f"3 citation rows (got {n})")
            expect(mentioned == 2, f"2 mentioned rows (got {mentioned})")

        # ============================================================
        # 11. Agent mode notification
        # ============================================================
        print("\n[11] agent mode outbox")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute("INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (sid,"Acme",base_url[8:],base_url,"USD","us","1-to-10","kitchen",ts,ts))
            db.commit(); db.close()
            r = subprocess.run(
                ["python3", str(RUN), "--mode", "llms-txt", "--store-id", sid,
                 "--notify-channel", "feishu", "--notify-target", "group:seo",
                 "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "agent mode exits 0")
            outbox = root / "outbox"
            files = list(outbox.glob("*.json"))
            expect(len(files) >= 1, "outbox written")

    finally:
        srv.shutdown()

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-seo smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
