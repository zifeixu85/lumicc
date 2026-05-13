#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-content.

Mocks the evolink.ai API via a local HTTP server so the test is hermetic
(no real API calls, no real credits). Tests:
  1. Prompt templates produce correct shape per type
  2. Model auto-switch: Chinese → gpt-image-2; English → gemini-3-pro-image-preview
  3. dry-run path (no API)
  4. Real generation path (mock API returns image)
  5. Video opt-in path (default off, --enable-video-gen on)
  6. HTML rendering with all card types
  7. DB rows written (generated_assets, runs, events)
  8. Cost cap rejects overruns
  9. Agent mode outbox notification
"""
from __future__ import annotations
import http.server
import io
import json
import os
import socketserver
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import prompts as prompts_mod

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def seed_secret(home_tmp: str, key: str, value: str) -> None:
    """Write a fake secret file mirroring what secret_form would save.

    Tests need to pretend a credential is configured without going through
    the HTML form. We write the JSON directly into the temp HOME's
    ~/.commerce-os/secrets/ so image_client.read_secret() picks it up.
    """
    import json as _j
    from pathlib import Path as _P
    sec_dir = _P(home_tmp) / ".commerce-os" / "secrets"
    sec_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(sec_dir, 0o700)
    except Exception:
        pass
    f = sec_dir / f"{key}.json"
    f.write_text(_j.dumps({
        "key": key, "provider": "test", "value": value,
        "stored_at": int(time.time()),
        "fingerprint": (value[:2] + "***" + value[-4:]) if len(value) > 6 else "***",
    }), encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except Exception:
        pass


# Minimal valid PNG (1×1 red pixel)
def make_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        ln = struct.pack(">I", len(d))
        crc = struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        return ln + t + d + crc
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"  # filter byte + R G B
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


PNG_BYTES = make_png()
MOCK_TASKS: dict = {}


class MockHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _png(self):
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG_BYTES)))
        self.end_headers()
        self.wfile.write(PNG_BYTES)

    def do_POST(self):
        if self.path.endswith("/images/generations") or self.path.endswith("/videos/generations"):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode())
            tid = f"task-{uuid.uuid4().hex[:8]}"
            MOCK_TASKS[tid] = {
                "kind": "video" if "videos" in self.path else "image",
                "model": body.get("model"),
                "n": body.get("n", 1),
            }
            self._json(200, {
                "id": tid, "model": body.get("model"),
                "object": "image.generation.task", "status": "pending",
                "usage": {"credits_reserved": 1.6 if "image" in self.path else 6.0},
            })
            return
        self.send_response(404); self.end_headers()

    def do_GET(self):
        if self.path.startswith("/v1/tasks/"):
            tid = self.path.rsplit("/", 1)[-1]
            task = MOCK_TASKS.get(tid)
            if not task:
                self._json(404, {"error": "not found"}); return
            host = self.headers.get("Host", "127.0.0.1")
            ext = "mp4" if task["kind"] == "video" else "png"
            urls = [f"http://{host}/asset-{i}.{ext}" for i in range(1, task["n"] + 1)]
            self._json(200, {
                "id": tid, "status": "completed",
                "output": {"images" if task["kind"] == "image" else "videos": urls},
            })
            return
        if self.path.startswith("/asset-"):
            if self.path.endswith(".png"):
                self._png()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                fake = b"FAKEMP4" * 100
                self.send_header("Content-Length", str(len(fake)))
                self.end_headers()
                self.wfile.write(fake)
            return
        self.send_response(404); self.end_headers()


def start_mock_server():
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.TCPServer(("127.0.0.1", 0), MockHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    return srv


def main() -> int:
    srv = start_mock_server()
    port = srv.server_address[1]
    mock_base = f"http://127.0.0.1:{port}/v1"

    try:
        # === Tests 1-3: pure template / language switching ===
        print("\n[1] Prompt templates — shape")
        for tname in prompts_mod.TEMPLATES:
            items = prompts_mod.generate(
                tname, sku="MKR-16", title="Magnetic Knife Rack",
                niche="kitchen", language="en", count=1,
            )
            expect(isinstance(items, list) and len(items) >= 1, f"{tname} returns list")
            expect("prompt_text" in items[0] and items[0]["prompt_text"], f"{tname} has prompt_text")
            expect("category" in items[0], f"{tname} has category")
            expect("subject" in items[0], f"{tname} has subject")

        print("\n[2] Model auto-switch by language")
        en_items = prompts_mod.generate("poster", sku="X", count=1, language="en")
        zh_items = prompts_mod.generate("poster", sku="X", count=1, language="zh")
        expect(en_items[0]["image_gen_params"]["model"] == "gemini-3-pro-image-preview", "English → Nano Banana")
        expect(zh_items[0]["image_gen_params"]["model"] == "gpt-image-2", "Chinese → GPT Image 2")

        print("\n[3] Product image with custom angles")
        items = prompts_mod.generate("product_image", sku="X", angles=["hero", "lifestyle"])
        expect(len(items) == 2, "2 angles → 2 items")
        cats = [it["category"] for it in items]
        expect(all(c == "product_image" for c in cats), "all items category=product_image")

        print("\n[4] Video item — default opt-out")
        items = prompts_mod.generate("video", sku="X", style="before_after", enable_video_gen=False)
        expect(items[0]["video_gen_enabled"] is False, "video_gen_enabled false by default")
        expect(items[0]["video_gen_params"]["model"].startswith("seedance"), "default video model = seedance")

        # === Test 5: e2e dry-run (no API) ===
        print("\n[5] run.py dry-run (prompt-only)")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": ""}  # no key
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "Test Pets", "shopify", "https://x.com", "USD", "us", "1-to-10", "kitchen", ts, ts),
            )
            db.execute(
                "INSERT INTO products (id, store_id, sku, title, status, cost_usd, price_usd, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), sid, "MKR-16", "Magnetic Knife Rack 16in", "active", 4.20, 29.99, ts),
            )
            db.commit(); db.close()

            r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--type", "poster",
                                "--occasion", "Mother's Day", "--count", "2", "--dry-run",
                                "--quiet-stdout"], env=env, capture_output=True, text=True)
            expect(r.returncode == 0, f"dry-run exits 0 (stderr={r.stderr[:200]})")
            result = json.loads(r.stdout)
            expect(result["items"] == 2, "2 posters generated as prompt-only")
            expect(result["credits"] == 0, "0 credits in dry-run")
            html = (root / "runs" / result["run_id"] / "content.html").read_text(encoding="utf-8")
            expect("仅生成 prompt" in html or "复制 prompt" in html, "HTML shows prompt-only state")

        # === Test 6: real-gen with mock API ===
        print("\n[6] run.py real generation (mock API)")
        with tempfile.TemporaryDirectory() as tmp:
            seed_secret(tmp, "EVOLINK_API_KEY", "test-key-mock")
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": "test-key-mock"}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "Test Pets", "shopify", "https://x.com", "USD", "us", "1-to-10", "kitchen", ts, ts),
            )
            db.commit(); db.close()

            # Set EVOLINK_API_BASE to the mock server
            env_with_mock = {**env, "PYTHONPATH": str(HERE)}
            # Use a small wrapper to monkey-patch image_client.EVOLINK_API_BASE
            wrap = Path(tmp) / "wrap.py"
            wrap.write_text(
                f"import sys; sys.path.insert(0, {str(HERE)!r})\n"
                f"import image_client as ic\n"
                f"ic.EVOLINK_BASE = {mock_base!r}\n"
                f"ic.EVOLINK_API_BASE = {mock_base!r}\n"
                f"try:\n"
                f"    import video_client as vc\n"
                f"    vc.EVOLINK_API_BASE = {mock_base!r}\n"
                f"except ImportError:\n"
                f"    pass\n"
                f"import runpy; runpy.run_path({str(RUN)!r}, run_name='__main__')\n"
            )
            r = subprocess.run(
                ["python3", str(wrap), "--store-id", sid, "--type", "poster",
                 "--occasion", "Mother's Day", "--count", "2", "--auto-confirm",
                 "--quiet-stdout"],
                env=env_with_mock, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"real-gen exits 0 (stderr={r.stderr[:300]})")
            result = json.loads(r.stdout)
            expect(result["items"] == 2, "2 items generated")
            expect(result["credits"] > 0, f"credits used (got {result['credits']})")

            # Verify generated PNGs exist
            gen = root / "runs" / result["run_id"] / "generated"
            pngs = list(gen.glob("*.png"))
            expect(len(pngs) == 2, f"2 PNG files generated (got {len(pngs)})")
            # Verify generated_assets table
            db = sqlite3.connect(root / "store.db")
            n_assets = db.execute(
                "SELECT COUNT(*) FROM generated_assets WHERE run_id=?", (result["run_id"],)
            ).fetchone()[0]
            expect(n_assets == 2, f"2 generated_assets rows (got {n_assets})")
            # Verify HTML embeds images
            html = (root / "runs" / result["run_id"] / "content.html").read_text(encoding="utf-8")
            expect(html.count("<img") >= 2, "HTML embeds <img> for each generated image")
            expect("下载图片" in html, "HTML has download buttons")
            db.close()

        # === Test 7: video opt-in default OFF ===
        print("\n[7] video — default OFF + HTML shows enable banner")
        with tempfile.TemporaryDirectory() as tmp:
            seed_secret(tmp, "EVOLINK_API_KEY", "test-key")
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": "test-key"}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "X", "shopify", "x", "USD", "us", "1-to-10", "k", ts, ts),
            )
            db.commit(); db.close()
            r = subprocess.run(["python3", str(RUN), "--store-id", sid, "--type", "video",
                                "--sku", "MKR-16", "--dry-run", "--quiet-stdout"],
                               env=env, capture_output=True, text=True)
            expect(r.returncode == 0, "video dry-run exits 0")
            result = json.loads(r.stdout)
            html = (root / "runs" / result["run_id"] / "content.html").read_text(encoding="utf-8")
            expect("启用视频生成" in html, "HTML shows '启用视频生成' button")
            expect("视频默认仅生成 prompt" in html, "HTML shows default-off explanation")
            expect("Seedance" in html, "HTML mentions Seedance")

        # === Test 8: cost cap ===
        print("\n[8] --max-credits cap")
        with tempfile.TemporaryDirectory() as tmp:
            seed_secret(tmp, "EVOLINK_API_KEY", "test")
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": "test"}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute("INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (sid,"X","shopify","x","USD","us","1-to-10","k",ts,ts))
            db.commit(); db.close()
            r = subprocess.run(
                ["python3", str(RUN), "--store-id", sid, "--type", "poster",
                 "--occasion", "X", "--count", "5", "--max-credits", "0.1",
                 "--auto-confirm", "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 2, f"cap exceeded → exit 2 (got {r.returncode})")
            expect("max-credits" in (r.stderr + r.stdout), "error message mentions max-credits")

        # === Test 9: agent-mode outbox ===
        print("\n[9] agent-mode outbox notification")
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": ""}
            root = Path(tmp) / ".commerce-os"
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute("INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (sid,"X","shopify","x","USD","us","1-to-10","k",ts,ts))
            db.commit(); db.close()
            r = subprocess.run(
                ["python3", str(RUN), "--store-id", sid, "--type", "pdp",
                 "--sku", "MKR-16", "--dry-run",
                 "--notify-channel", "feishu", "--notify-target", "group:ops",
                 "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "agent-mode exits 0")
            outbox = root / "outbox"
            files = list(outbox.glob("*.json"))
            expect(len(files) >= 1, "outbox JSON written")
            payload = json.loads(files[0].read_text())
            expect(payload["skill"] == "lumicc-content", "payload skill correct")

        # === Test 10: picker workflow (--pick-style → --build) ===
        print("\n[10] picker workflow")
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / ".commerce-os"
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": "",
                   "LUMICC_DATA_ROOT": str(data_root)}
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(data_root / "store.db")
            sid_store = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid_store, "Studio", "shopify", "x", "USD", "us", "1-to-10", "kitchen", ts, ts),
            )
            db.commit(); db.close()

            test_sid = "test-sid-picker"
            # Step 1: pick-style returns picker URL
            r = subprocess.run(
                ["python3", str(RUN), "--pick-style", "--session", test_sid,
                 "--store-id", sid_store],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--pick-style exits 0 (stderr={r.stderr[:200]})")
            try:
                pj = json.loads(r.stdout)
            except json.JSONDecodeError:
                pj = {}
            expect(pj.get("session_id") == test_sid, "session_id echoed")
            expect("picker_url" in pj and pj["picker_url"].startswith("file://"),
                   "picker_url is a file:// URL")
            picker_html = data_root / "sessions" / test_sid / "picker-landing_style.html"
            expect(picker_html.exists(), "picker HTML written to session dir")

            # Step 2: write a fake choice file like the picker would
            choice_path = data_root / "sessions" / test_sid / "choice-landing_style.json"
            choice_payload = {
                "kind": "landing_style", "selected_id": "aesop_apothecary",
                "id": "aesop_apothecary", "label": "Aesop · 药剂铺",
                "tagline": "克制、留白、衬线、深色木质感",
                "fit_for": "护肤 / 香氛 / 茶 / 高端食品",
                "palette": ["#1a1814", "#a89478", "#d4cab8", "#5b4f3e"],
                "fonts": "Iowan Old Style / Times",
                "rhythm": "大留白 · 单列阅读 · 不闪",
                "picked_at": int(time.time()), "session_id": test_sid,
            }
            choice_path.write_text(json.dumps(choice_payload), encoding="utf-8")

            # Step 3: --build renders content with style applied
            r = subprocess.run(
                ["python3", str(RUN), "--build", "--session", test_sid,
                 "--store-id", sid_store, "--type", "poster",
                 "--occasion", "Mother's Day", "--count", "1", "--dry-run",
                 "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--build exits 0 (stderr={r.stderr[:300]})")
            try:
                result = json.loads(r.stdout)
            except json.JSONDecodeError:
                result = {}
            if result.get("run_id"):
                html = (data_root / "runs" / result["run_id"] / "content.html").read_text(encoding="utf-8")
                expect("Aesop" in html, "rendered HTML embeds chosen style label")
                expect("你选的设计方向" in html, "rendered HTML shows style prelude")

        # === Test 11: v0.4 --generate-images / --video / --enable-video / embed ===
        print("\n[11] v0.4 flags: --generate-images / --video opt-in / inline embed")
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / ".commerce-os"
            seed_secret(tmp, "EVOLINK_API_KEY", "test-mock")
            env = {**os.environ, "HOME": tmp, "EVOLINK_API_KEY": "test-mock",
                   "LUMICC_DATA_ROOT": str(data_root)}
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(data_root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "X", "shopify", "x", "USD", "us", "1-to-10", "k", ts, ts),
            )
            db.commit(); db.close()

            # 11a: --video without preference → opt-in message, exit 0
            r = subprocess.run(
                ["python3", str(RUN), "--store-id", sid, "--video",
                 "--type", "poster", "--occasion", "X"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--video without pref → exit 0 (got {r.returncode})")
            expect("视频生成默认关闭" in r.stdout, "opt-in message shown")
            expect("--enable-video" in r.stdout, "opt-in mentions --enable-video")

            # 11b: --enable-video persists preference
            r = subprocess.run(
                ["python3", str(RUN), "--enable-video"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "--enable-video exits 0")
            expect("视频生成已启用" in r.stdout, "enable confirmation shown")
            db = sqlite3.connect(data_root / "store.db")
            row = db.execute(
                "SELECT value FROM preferences WHERE key='video_gen_enabled'"
            ).fetchone()
            db.close()
            expect(row is not None and row[0] == "true", "preference persisted")

            # 11c: --generate-images with mock → inline base64 in HTML
            wrap = Path(tmp) / "wrap11.py"
            wrap.write_text(
                f"import sys; sys.path.insert(0, {str(HERE)!r})\n"
                f"import image_client as ic\n"
                f"ic.EVOLINK_BASE = {mock_base!r}\n"
                f"import runpy; runpy.run_path({str(RUN)!r}, run_name='__main__')\n"
            )
            r = subprocess.run(
                ["python3", str(wrap), "--store-id", sid, "--type", "poster",
                 "--occasion", "Mother's Day", "--count", "2",
                 "--generate-images", "--auto-confirm", "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, f"--generate-images exits 0 (stderr={r.stderr[:300]})")
            try:
                result = json.loads(r.stdout)
            except json.JSONDecodeError:
                result = {}
            expect(result.get("items") == 2, "2 items generated")
            run_id_11 = result.get("run_id")
            if run_id_11:
                html = (data_root / "runs" / run_id_11 / "content.html").read_text(encoding="utf-8")
                expect("data:image/" in html, "HTML embeds base64 data URI")
                expect("已生成的素材" in html, "HTML has '已生成的素材' section")
                expect("本次生成花费" in html, "HTML shows cost banner")
                result_json = json.loads(
                    (data_root / "runs" / run_id_11 / "result.json").read_text()
                )
                expect("generated_images" in result_json, "result.json has generated_images")
                expect(result_json.get("total_cost_usd", 0) > 0, "result.json has total_cost_usd > 0")

            # 11d: --estimate-only prints estimate without calling API
            r = subprocess.run(
                ["python3", str(RUN), "--store-id", sid, "--type", "poster",
                 "--occasion", "X", "--count", "3", "--estimate-only"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 0, "--estimate-only exits 0")
            try:
                est = json.loads(r.stdout)
                expect("estimate_usd" in est, "--estimate-only emits estimate_usd")
            except json.JSONDecodeError:
                expect(False, "--estimate-only output is not JSON")

        # === Test 12: MissingSecretError surfaces friendly help + exit 1 ===
        print("\n[12] MissingSecretError → helpful message")
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp) / ".commerce-os"
            env = {**os.environ, "HOME": tmp, "LUMICC_DATA_ROOT": str(data_root)}
            env.pop("EVOLINK_API_KEY", None)
            subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
            db = sqlite3.connect(data_root / "store.db")
            sid = str(uuid.uuid4()); ts = int(time.time())
            db.execute(
                "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "X", "shopify", "x", "USD", "us", "1-to-10", "k", ts, ts),
            )
            db.commit(); db.close()
            r = subprocess.run(
                ["python3", str(RUN), "--store-id", sid, "--type", "poster",
                 "--occasion", "X", "--count", "1",
                 "--generate-images", "--auto-confirm", "--quiet-stdout"],
                env=env, capture_output=True, text=True,
            )
            expect(r.returncode == 1, f"missing secret → exit 1 (got {r.returncode})")
            expect("EVOLINK_API_KEY" in r.stderr, "stderr mentions EVOLINK_API_KEY")
            expect("secret_form.py" in r.stderr, "stderr mentions secret_form.py")

    finally:
        srv.shutdown()

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-content smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
