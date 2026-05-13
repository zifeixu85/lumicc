#!/usr/bin/env python3
"""Smoke tests for assets module + migration idempotency.

Run:
    python3 test_assets.py
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT_STORE = HERE / "init_store.py"

FAILS: list[str] = []


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def init_store(root: Path) -> None:
    env = {**os.environ, "HOME": str(root.parent)}
    r = subprocess.run(
        ["python3", str(INIT_STORE), "--root", str(root)],
        env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"init_store failed: {r.stderr}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        commerce_root = Path(tmp) / ".commerce-os"
        os.environ["LUMICC_DATA_ROOT"] = str(commerce_root)

        # Force fresh import after env var set
        sys.path.insert(0, str(HERE))
        if "assets" in sys.modules:
            del sys.modules["assets"]
        import assets  # noqa: E402

        # 1) Init creates table
        init_store(commerce_root)
        db = sqlite3.connect(commerce_root / "store.db")
        cols = [r[1] for r in db.execute("PRAGMA table_info(assets)").fetchall()]
        db.close()
        expect("id" in cols and "kind" in cols and "cost_usd" in cols,
               "assets table created with expected columns")

        # 2) record_asset returns UUID
        fake_file = commerce_root / "fake.png"
        fake_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
        aid = assets.record_asset(
            kind="image", path=fake_file, sku="MKR-16",
            prompt="test prompt", model="gemini-3-pro-image-preview",
            cost_usd=0.04,
        )
        expect(isinstance(aid, str) and len(aid) >= 32, "record_asset returns UUID-like string")

        # 3) list_assets kind=image
        rows = assets.list_assets(kind="image")
        expect(len(rows) == 1, "list_assets(kind=image) returns 1 row")
        expect(rows[0]["sku"] == "MKR-16", "row has correct SKU")
        expect(rows[0]["exists_on_disk"] is True, "exists_on_disk=True")
        expect(rows[0]["size_bytes"] > 0, "size_bytes computed")

        # 4) list_assets kind=video → empty
        vids = assets.list_assets(kind="video")
        expect(vids == [], "list_assets(kind=video) returns []")

        # 5) asset_stats total=1
        s = assets.asset_stats()
        expect(s["total"] == 1, "asset_stats total=1")
        expect(s["by_kind"].get("image") == 1, "stats by_kind image=1")
        expect(abs(s["total_cost_usd"] - 0.04) < 1e-6, "stats total_cost_usd=0.04")

        # 6) delete_asset removes file + row
        ok = assets.delete_asset(aid)
        expect(ok is True, "delete_asset returns True")
        expect(not fake_file.exists(), "asset file removed from disk")
        expect(assets.list_assets() == [], "list_assets empty after delete")
        s2 = assets.asset_stats()
        expect(s2["total"] == 0, "asset_stats total=0 after delete")

        # 7) Re-run init_store → idempotent, no data loss
        aid2 = assets.record_asset(kind="prompt", path="",
                                   prompt="just a prompt", cost_usd=0.0)
        before = assets.list_assets()
        init_store(commerce_root)  # second run
        after = assets.list_assets()
        expect(len(before) == 1 and len(after) == 1, "data survives re-init")
        expect(before[0]["id"] == after[0]["id"] == aid2, "asset row preserved")

        # Verify schema version
        db = sqlite3.connect(commerce_root / "store.db")
        v = db.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
        db.close()
        expect(v is not None and int(v[0]) >= 2, f"schema_version >= 2 (got {v})")

    if FAILS:
        print(f"\n{len(FAILS)} failures", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll assets tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
