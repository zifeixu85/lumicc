#!/usr/bin/env python3
"""Smoke test for config.py — the Lumicc local HTTP wizard server.

Tests handler-logic functions + step renderers + the CLI directly. The live
server gets one minimal, timeout-guarded round-trip.

Run:
    python3 test_config.py
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT_STORE = HERE / "init_store.py"
CONFIG_PY = HERE / "config.py"

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def _init(root: Path) -> None:
    subprocess.run(
        ["python3", str(INIT_STORE)],
        env={**os.environ, "LUMICC_DATA_ROOT": str(root)},
        capture_output=True, text=True, check=True,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / ".commerce-os"
        env_root = str(root)
        os.environ["LUMICC_DATA_ROOT"] = env_root
        _init(root)

        sys.path.insert(0, str(HERE))
        import config as cfg
        importlib.reload(cfg)
        importlib.reload(cfg.secret_form)
        importlib.reload(cfg)

        # init_store.py writes a SOUL.md by default — remove it to test the
        # fresh-install path cleanly.
        soul = root / "SOUL.md"
        if soul.exists():
            soul.unlink()

        # --- 1) --create-store CLI: "有店" path ---
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--create-store", "--platform", "shopify",
             "--market", "us", "--niche", "宠物用品", "--stage", "1-to-10",
             "--name", "Have Store", "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--create-store (有店) exits 0")
        p1 = json.loads(r.stdout)
        expect(p1.get("created") is True, "--create-store reports created")
        expect(bool(p1.get("store_id")), "--create-store returns store_id")
        expect(soul.exists(), "--create-store writes SOUL.md when missing")

        # "从零" path (stage 0-to-1)
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--create-store", "--platform", "独立站",
             "--market", "Global", "--niche", "手工饰品", "--stage", "0-to-1",
             "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--create-store (从零) exits 0")
        p2 = json.loads(r.stdout)
        expect(p2["store_id"] != p1["store_id"], "second store has distinct id")

        # --- 2) --quiet-stdout status JSON ---
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--quiet-stdout exits 0")
        out = json.loads(r.stdout)
        expect(out.get("stores") == 2, f"status JSON: 2 stores (got {out.get('stores')})")
        expect("keys_configured" in out, "status JSON has keys_configured")
        expect("soul_exists" in out, "status JSON has soul_exists")

        # --- 3) --status human-readable ---
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--status"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--status exits 0")
        expect("配置状态" in r.stdout, "--status prints human-readable text")
        expect("店铺数" in r.stdout, "--status shows store count")

        # --- 4) step renderers return valid themed HTML ---
        importlib.reload(cfg)
        s1 = cfg.render_step1()
        expect(s1.startswith(cfg._WIZARD_CSS[:20]) or "<!doctype" in s1,
               "render_step1 returns HTML")
        for team in ("CMO 总指挥", "建站团队", "数据分析师",
                     "市场情报员", "品牌内容师", "危机响应官"):
            expect(team in s1, f"step1 shows team '{team}'")
        expect("选品" in s1 and "救火" in s1, "step1 shows workflow")
        expect("开始设置" in s1, "step1 has start button")
        expect("data-theme=" in s1, "step1 inherits theme system")
        expect(".ts-btn" in s1 or "theme-switch" in s1, "step1 has theme switcher")

        s2 = cfg.render_step2()
        expect("我已经有店" in s2, "step2 has '有店' radio")
        expect("从零开始" in s2, "step2 has '从零' radio")
        expect("/api/store" in s2, "step2 posts to /api/store")
        expect("跳过" in s2, "step2 has skip option")
        expect("data-theme=" in s2, "step2 inherits theme system")

        s3 = cfg.render_step3()
        for key in cfg.secret_form.PROVIDERS:
            expect(key in s3, f"step3 lists provider key {key}")
        for key in cfg.CLOUDFLARE_KEYS:
            expect(key in s3, f"step3 lists cloudflare key {key}")
        for key, hint in cfg.KEY_HINTS.items():
            expect(hint in s3, f"step3 shows hint for {key}")
        expect("/api/save-key" in s3, "step3 posts to /api/save-key")
        expect("电商平台数据" in s3, "step3 has 电商平台数据 fieldset")
        expect("data-theme=" in s3, "step3 inherits theme system")

        s4 = cfg.render_step4()
        expect("设置完成" in s4, "step4 shows completion")
        expect("/api/shutdown" in s4, "step4 posts to /api/shutdown")
        expect("lumicc config" in s4, "step4 footnote mentions 'lumicc config'")
        expect("打开控制台" in s4, "step4 has console link")
        expect("data-theme=" in s4, "step4 inherits theme system")

        # --- 5) _save_key writes a 0600 secret file in correct format ---
        res = cfg._save_key("ETSY_API_KEY", "etsytestkey1234567", "etsy")
        expect(res.get("ok") is True, "_save_key returns ok")
        expect(bool(res.get("fingerprint")), "_save_key returns fingerprint")
        secret_file = cfg.secret_form.SECRETS_DIR / "ETSY_API_KEY.json"
        expect(secret_file.exists(), "_save_key created the secret file")
        mode = oct(secret_file.stat().st_mode & 0o777)
        expect(mode == "0o600", f"_save_key file mode 0600 (got {mode})")
        data = json.loads(secret_file.read_text(encoding="utf-8"))
        for field in ("key", "provider", "value", "stored_at", "fingerprint"):
            expect(field in data, f"_save_key file has '{field}' field")
        expect(data["value"] == "etsytestkey1234567", "_save_key stores raw value")
        expect(cfg.secret_form.read_secret("ETSY_API_KEY") == "etsytestkey1234567",
               "secret_form can read back what _save_key wrote")

        # --- 6) _verify_* functions ---
        # format-check ones
        v = cfg.verify_token("SHOPIFY_ADMIN_TOKEN", "shpat_abcdefghij")
        expect(v["ok"] and v["verified"], "verify shopify good prefix → verified")
        v = cfg.verify_token("SHOPIFY_ADMIN_TOKEN", "wrong_prefix_value")
        expect(v["ok"] and not v["verified"] and v.get("code") == "E_FORMAT",
               "verify shopify bad prefix → saved but not verified")
        v = cfg.verify_token("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxx")
        expect(v["ok"] and v["verified"], "verify anthropic good prefix")
        v = cfg.verify_token("OPENAI_API_KEY", "x")
        expect(not v["ok"] and v.get("code") == "E_FORMAT",
               "verify openai too short → hard fail")
        v = cfg.verify_token("ETSY_API_KEY", "a-reasonable-key")
        expect(v["ok"] and v["verified"], "verify generic key → verified by length")

        # mock urllib for cloudflare real-API path
        orig = cfg._http_json
        cfg._http_json = lambda url, headers: (200, {"success": True})
        v = cfg.verify_token("CLOUDFLARE_API_TOKEN", "x" * 40)
        expect(v["ok"] and v["verified"], "verify cloudflare 200 → verified")
        cfg._http_json = lambda url, headers: (401, None)
        v = cfg.verify_token("CLOUDFLARE_API_TOKEN", "x" * 40)
        expect(v["ok"] and not v["verified"] and v["code"] == "E_401",
               "verify cloudflare 401 → saved, not verified")
        cfg._http_json = orig
        v = cfg.verify_token("CLOUDFLARE_API_TOKEN", "short")
        expect(not v["ok"] and v["code"] == "E_FORMAT",
               "verify cloudflare too-short → hard fail")

        # --- 7) create_store logic: store row + SOUL.md draft ---
        soul.unlink()
        importlib.reload(cfg)
        before = len(cfg.load_stores())
        result = cfg.create_store(platform="amazon", market="UK",
                                  niche="厨房", stage="0-to-1", name="Logic Store")
        expect(result["created"] is True, "create_store returns created")
        after = cfg.load_stores()
        expect(len(after) == before + 1, "create_store adds a store row")
        expect(any(s["name"] == "Logic Store" for s in after),
               "create_store row has the right name")
        expect(soul.exists(), "create_store writes SOUL.md draft when missing")

        # --- 8) _find_port returns an available port + server ---
        port, server = cfg._find_port()
        expect(port in cfg.PORTS, f"_find_port returns a port in range (got {port})")
        try:
            # --- 10) live server: GET / returns 200/302 ---
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            time.sleep(0.2)
            try:
                req = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/step/1", timeout=3)
                body = req.read().decode("utf-8")
                expect(req.status == 200, "live server GET /step/1 → 200")
                expect("欢迎使用 Lumicc" in body, "live server serves step 1 HTML")
            except Exception as e:  # noqa: BLE001
                expect(False, f"live server GET failed: {e}")
        finally:
            server.shutdown()
            server.server_close()

        # --- 9) HTML inherits the 4-theme system ---
        expect(len(cfg.KEY_GROUPS) == 5, "5 key groups defined")
        expect("data-theme=" in cfg.render_step1(),
               "wizard pages carry data-theme")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nAll config.py tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
