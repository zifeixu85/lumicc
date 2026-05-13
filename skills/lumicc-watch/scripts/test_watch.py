#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-watch.

Uses a synthetic local HTTP server so the test is hermetic (no real internet).
Tests:
  1) Snapshot parses homepage correctly
  2) Snapshot + sitemap.xml extracts product URLs
  3) diff.py detects new_product, removed_product, banner change
  4) run.py outputs valid JSON + markdown
  5) notify.py writes to outbox or stdout based on channel

Exits 0 on pass, 1 on fail.
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


# ---- Synthetic site state ----
class FakeSite:
    def __init__(self) -> None:
        self.products: list[str] = ["/products/widget-a", "/products/widget-b", "/products/widget-c"]
        self.banner: str = "Free shipping over $35 — limited time!"
        self.title: str = "Acme Shop — Premium Widgets"
        self.hero_heading: str = "Best-selling widgets of 2026"


SITE = FakeSite()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/robots.txt":
            self._send(b"User-agent: *\nAllow: /\n", ctype="text/plain")
            return
        if self.path == "/sitemap.xml":
            urls = "".join(f"<url><loc>http://{self.headers.get('Host')}{p}</loc></url>"
                           for p in SITE.products)
            body = f"<?xml version='1.0'?><urlset>{urls}</urlset>".encode()
            self._send(body, ctype="application/xml")
            return
        if self.path == "/":
            anchors = "".join(
                f'<a href="{p}">Widget Link</a>' for p in SITE.products
            )
            html = f"""<!doctype html>
<html><head>
<title>{SITE.title}</title>
<meta name="description" content="Premium widgets at low prices.">
<meta property="og:image" content="http://example.com/og.jpg">
</head><body>
<div class="announcement">{SITE.banner}</div>
<h1>{SITE.hero_heading}</h1>
{anchors}
<a href="https://instagram.com/acmeshop">IG</a>
</body></html>""".encode()
            self._send(html)
            return
        self._send(b"not found", status=404)


def start_server() -> tuple[socketserver.TCPServer, int]:
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, port


def main() -> int:
    srv, port = start_server()
    base_url = f"http://127.0.0.1:{port}"

    try:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp}
            commerce_root = Path(tmp) / ".commerce-os"

            # Init store.db (required for events + runs tables)
            init_path = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
            r = subprocess.run(["python3", str(init_path)], env=env, capture_output=True, text=True)
            expect(r.returncode == 0, "init_store.py succeeded")

            # ---- Test 1: snapshot ----
            print("\n[1] snapshot.py")
            out1 = Path(tmp) / "snap1.json"
            r = subprocess.run(
                ["python3", str(HERE / "snapshot.py"), "--url", base_url, "--out", str(out1), "--delay-ms", "10"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "snapshot exits 0")
            snap1 = json.loads(out1.read_text())
            expect(snap1["homepage"]["title"] == SITE.title, "title extracted")
            expect(SITE.hero_heading in snap1["homepage"]["headings"], "h1 extracted")
            expect(snap1["sitemap_product_count"] == 3, "sitemap returns 3 products")
            expect(snap1["homepage"]["social_handles"].get("instagram") == "acmeshop", "instagram handle extracted")
            expect(SITE.banner in snap1["homepage"]["announcement_candidates"], "banner extracted")

            # ---- Test 2: diff after change ----
            print("\n[2] diff.py")
            # Mutate the site: add new product, remove one, change banner
            SITE.products = ["/products/widget-a", "/products/widget-d", "/products/widget-e"]
            SITE.banner = "Mega sale: 30% off everything!"
            time.sleep(0.1)
            out2 = Path(tmp) / "snap2.json"
            r = subprocess.run(
                ["python3", str(HERE / "snapshot.py"), "--url", base_url, "--out", str(out2), "--delay-ms", "10"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "second snapshot exits 0")
            diff_out = Path(tmp) / "diff.json"
            r = subprocess.run(
                ["python3", str(HERE / "diff.py"), "--prev", str(out1), "--curr", str(out2), "--out", str(diff_out)],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "diff exits 0")
            d = json.loads(diff_out.read_text())
            cats = {c["category"] for c in d["all_changes"]}
            expect("new_product" in cats, "diff detected new_product")
            expect("removed_product" in cats, "diff detected removed_product")
            expect("promo_banner_change" in cats, "diff detected promo_banner_change")

            # ---- Test 3: full run.py ----
            print("\n[3] run.py (coder mode, single target)")
            r = subprocess.run(
                ["python3", str(HERE / "run.py"), "--target", base_url, "--delay-ms", "10"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "run.py coder-mode exits 0")
            expect("Watchtower Report" in r.stdout, "markdown report printed to stdout")
            # Verify run row + event row
            import sqlite3
            db = sqlite3.connect(commerce_root / "store.db")
            n_runs = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-watch'").fetchone()[0]
            n_events = db.execute("SELECT COUNT(*) FROM events WHERE category='task'").fetchone()[0]
            db.close()
            expect(n_runs >= 1, "run row inserted")
            expect(n_events >= 1, "event row inserted")

            # ---- Test 4: agent mode with notification ----
            print("\n[4] run.py (agent mode, --quiet-stdout + notify-channel feishu)")
            r = subprocess.run(
                ["python3", str(HERE / "run.py"), "--target", base_url, "--delay-ms", "10",
                 "--quiet-stdout", "--notify-channel", "feishu", "--notify-target", "group:ops"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "run.py agent-mode exits 0")
            expect("Watchtower Report" not in r.stdout, "markdown NOT printed (quiet-stdout)")
            outbox = commerce_root / "outbox"
            outbox_files = list(outbox.glob("*.json"))
            expect(len(outbox_files) >= 1, "notification dropped to outbox")
            req = json.loads(outbox_files[0].read_text())
            expect(req["channel"] == "feishu", "outbox payload channel=feishu")
            expect(req["target"] == "group:ops", "outbox payload target preserved")

            # ---- Test 4b: HTML render smoke ----
            print("\n[4b] render_html.py (synthetic targets_results)")
            sys.path.insert(0, str(HERE))
            import render_html as rh
            html = rh.render_page(
                run_id="smoke-1234",
                store_name="demo-store",
                targets_results=[{
                    "url": base_url,
                    "host": "127.0.0.1",
                    "snapshot_ts": int(time.time()),
                    "prior_ts": int(time.time()) - 3600,
                    "is_first_run": False,
                    "changes": [
                        {"category": "new_product", "weight": 3.0, "severity": "high",
                         "detail": {"url": f"{base_url}/products/widget-x"}},
                        {"category": "promo_banner_change", "weight": 1.8, "severity": "medium",
                         "detail": {"new_lines": ["Mega sale 30%"]}},
                    ],
                }],
                html_path=Path(tmp) / "smoke.html",
            )
            expect("<!doctype html>" in html, "render_page returns HTML doc")
            expect("竞品监控" in html, "Chinese title rendered")
            expect("新品上架" in html, "category label rendered")
            # Also verify run.py produced a real report.html
            runs_dir = commerce_root / "runs"
            html_reports = list(runs_dir.glob("*/report.html"))
            expect(len(html_reports) >= 1, "run.py wrote report.html")

            # ---- Test 5: notify.py direct ----
            print("\n[5] notify.py")
            r = subprocess.run(
                ["python3", str(HERE / "notify.py"), "--channel", "stdout",
                 "--title", "T", "--body", "B"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "notify stdout exits 0")
            expect("T" in r.stdout, "stdout notify prints title")

    finally:
        srv.shutdown()

    if FAILS:
        print(f"\n{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print(f"\nAll {sum(1 for _ in ['init','snapshot','diff','run-coder','run-agent','notify'])*4} lumicc-watch smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
