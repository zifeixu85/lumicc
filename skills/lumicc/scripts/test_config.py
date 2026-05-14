#!/usr/bin/env python3
"""Smoke test for config.py — the Lumicc config center + onboarding entry.

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

        # init_store.py writes a SOUL.md by default — remove it so we can test
        # the fresh-install path cleanly.
        soul = root / "SOUL.md"
        if soul.exists():
            soul.unlink()

        # --- 1) Fresh install (no stores) → Landing mode ---
        stores = cfg.load_stores()
        expect(len(stores) == 0, "fresh install → 0 stores")
        landing = cfg.render_config([])
        expect("欢迎使用" in landing, "landing shows 欢迎使用 hero")
        for team in ("CMO 总指挥", "建站团队", "数据分析师",
                     "市场情报员", "品牌内容师", "危机响应官"):
            expect(team in landing, f"landing shows team '{team}'")
        expect("我有店 · 接入数据" in landing, "landing has '我有店' action card")
        expect("从零开始 · 开新店" in landing, "landing has '从零开始' action card")
        expect("data-theme=" in landing, "landing inherits theme system")
        expect(".ts-btn" in landing or "theme-switch" in landing,
               "landing has theme switcher")

        # --- 2) --create-store CLI creates a store + SOUL.md ---
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--create-store", "--platform", "shopify",
             "--market", "us", "--niche", "宠物用品", "--stage", "0-to-1",
             "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--create-store CLI exits 0")
        payload = json.loads(r.stdout)
        expect(payload.get("created") is True, "--create-store reports created")
        expect(bool(payload.get("store_id")), "--create-store returns store_id")
        expect(soul.exists(), "--create-store writes SOUL.md when missing")
        # second store also works
        r2 = subprocess.run(
            ["python3", str(CONFIG_PY), "--create-store", "--platform", "amazon",
             "--market", "uk", "--niche", "厨房", "--stage", "1-to-10",
             "--name", "Second Store", "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r2.returncode == 0, "second --create-store exits 0")
        p2 = json.loads(r2.stdout)
        expect(p2["store_id"] != payload["store_id"], "second store has distinct id")

        # --- 3) After stores exist → config-center mode ---
        importlib.reload(cfg)
        stores = cfg.load_stores()
        expect(len(stores) == 2, f"now 2 stores (got {len(stores)})")
        center = cfg.render_config(stores)
        expect("你的店铺" in center, "config center shows 你的店铺")
        expect("Second Store" in center, "config center shows store name")
        expect("API 凭据" in center, "config center shows API 凭据 section")

        # --- 4) API 凭据 lists all known providers, all missing ---
        for key in cfg.secret_form.PROVIDERS:
            expect(key in center, f"API 凭据 lists provider {key}")
        expect("✗ 未配置" in center, "missing providers shown as 未配置")
        expect("secret_form.py --generate" in center,
               "API 凭据 includes secret_form --generate command")

        # --- 5) SOUL.md section: present shows preview ---
        expect("运营铁律" in center, "SOUL.md section shows content preview")
        # missing case
        soul.unlink()
        importlib.reload(cfg)
        center_no_soul = cfg.render_config(cfg.load_stores())
        expect("还没有 SOUL.md" in center_no_soul,
               "SOUL.md missing → shows 还没有 prompt")
        soul.write_text(cfg.SOUL_TEMPLATE, encoding="utf-8")

        # --- 6) theme system inherited ---
        importlib.reload(cfg)
        center = cfg.render_config(cfg.load_stores())
        expect("data-theme=" in center, "config center inherits theme system")
        expect(".ts-btn" in center or "theme-switch" in center,
               "config center has theme switcher")

        # --- 7) CLI --quiet-stdout emits valid JSON ---
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--no-open", "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "config.py --quiet-stdout exits 0")
        out = json.loads(r.stdout)
        expect(out.get("stores") == 2, "CLI JSON reports 2 stores")
        expect("keys_configured" in out, "CLI JSON has keys_configured")
        expect(Path(out["config_html"]).exists(), "CLI JSON config_html exists")

        # --- 8) --create-store --from-json ---
        jpath = Path(tmp) / "store.json"
        jpath.write_text(json.dumps({
            "platform": "etsy", "market": "de", "niche": "手工", "stage": "0-to-1",
            "name": "JSON Store",
        }), encoding="utf-8")
        r = subprocess.run(
            ["python3", str(CONFIG_PY), "--create-store",
             "--from-json", str(jpath), "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True,
        )
        expect(r.returncode == 0, "--from-json exits 0")
        jp = json.loads(r.stdout)
        expect(jp.get("created") is True, "--from-json creates store")
        importlib.reload(cfg)
        names = [s.get("name") for s in cfg.load_stores()]
        expect("JSON Store" in names, "--from-json store appears in store list")

        # --- 9) theme section lists all 4 theme names ---
        center = cfg.render_config(cfg.load_stores())
        for t in cfg.THEME_NAMES:
            expect(t in center, f"theme section lists '{t}'")
        expect(len(cfg.THEME_NAMES) == 4, "exactly 4 themes defined")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nAll config.py tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
