#!/usr/bin/env python3
"""End-to-end smoke test for Cross-Border Commerce OS.

Runs against a temporary HOME so it never touches the user's real ~/.commerce-os.
Exits 0 on pass, 1 on fail.

Run:
    python3 test_smoke.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
INIT_STORE = HERE / "init_store.py"
ROUTE = HERE / "route.py"
MEMORY = HERE / "memory.py"
HEALTH = HERE / "health_check.py"

FAILS: list[str] = []


def run(*args: str, env: dict, input_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", *args],
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
        check=False,
    )


def expect(cond: bool, msg: str) -> None:
    if not cond:
        FAILS.append(msg)
        print(f"  ✗ {msg}", file=sys.stderr)
    else:
        print(f"  ✓ {msg}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        commerce_root = Path(tmp) / ".commerce-os"

        # ---- 1) init ----
        print("\n[1] init_store.py")
        r = run(str(INIT_STORE), env=env)
        expect(r.returncode == 0, "init_store exits 0")
        snap = json.loads(r.stdout)
        expect(snap["schema_version"] >= 1, f"schema_version >= 1 (got {snap['schema_version']})")
        expect(snap["stores"] == [], "no stores initially")
        expect(commerce_root.exists(), "~/.commerce-os created")
        expect((commerce_root / "store.db").exists(), "store.db created")
        expect((commerce_root / "SOUL.md").exists(), "SOUL.md created")

        # ---- 2) idempotent re-init ----
        print("\n[2] init_store.py (re-run idempotent)")
        r = run(str(INIT_STORE), env=env)
        expect(r.returncode == 0, "re-init exits 0")
        snap2 = json.loads(r.stdout)
        expect(snap2["schema_version"] == snap["schema_version"], "schema_version unchanged after re-init")

        # ---- 3) route: no store → cold-start ----
        print("\n[3] route.py without any store")
        r = run(str(ROUTE), "--intent", "I want to start a store", env=env)
        expect(r.returncode == 0, "route exits 0")
        dec = json.loads(r.stdout)
        expect(dec["matched_subskill"] == "lumicc-launch", "cold-start matched")
        expect(dec["next_action"] == "ask_user_for_inputs", "asks for inputs")

        # ---- 4) seed a store, then route by keyword ----
        print("\n[4] seed store + route")
        import sqlite3
        db = sqlite3.connect(commerce_root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://acme.myshopify.com", "USD", "us", "1-to-10", "pets", ts, ts),
        )
        db.commit()
        db.close()

        r = run(str(ROUTE), "--intent", "我想找下一个爆款", env=env)
        dec = json.loads(r.stdout)
        expect(dec["matched_subskill"] == "lumicc-expand", "expansion matched on Chinese intent")

        r = run(str(ROUTE), "--intent", "sales dropped 50% overnight", env=env)
        dec = json.loads(r.stdout)
        expect(dec["matched_subskill"] == "lumicc-rescue", "crisis matched on English intent")

        r = run(str(ROUTE), "--intent", "差评分析", env=env)
        dec = json.loads(r.stdout)
        expect(dec["matched_subskill"] == "lumicc-voc", "voc matched on '差评'")

        # ---- 5) memory: log events ----
        print("\n[5] memory.py log/insight/soul")
        r = run(str(MEMORY), "log", "--store", sid, "--category", "decision",
                "--content", "Approved SKU magnetic-knife-rack", env=env)
        expect(r.returncode == 0, "memory log exits 0")
        evt = json.loads(r.stdout)
        expect("id" in evt, "event id returned")

        r = run(str(MEMORY), "read-day", env=env)
        expect("magnetic-knife-rack" in r.stdout, "event appears in daily md")

        # Insight twice → verified_count == 2
        r = run(str(MEMORY), "insight", "--store", sid, "--category", "listing",
                "--content", "Overhead hero converts 1.8x", "--confidence", "0.6", env=env)
        r = run(str(MEMORY), "insight", "--store", sid, "--category", "listing",
                "--content", "Overhead hero converts 1.8x", "--confidence", "0.6", env=env)
        r = run(str(MEMORY), "insights-list", "--store", sid, env=env)
        insights = json.loads(r.stdout)
        expect(any(i["verified_count"] == 2 for i in insights), "insight verified_count merged")

        # SOUL proposal is a structured stdout, NOT a write
        soul_before = (commerce_root / "SOUL.md").read_text(encoding="utf-8")
        r = run(str(MEMORY), "soul-propose", "--rule", "Target margin >= 40%", env=env)
        prop = json.loads(r.stdout)
        expect(prop["type"] == "soul_proposal", "SOUL proposal type correct")
        soul_after = (commerce_root / "SOUL.md").read_text(encoding="utf-8")
        expect(soul_before == soul_after, "Layer 3 SOUL not auto-modified")

        # ---- 6) health_check ----
        print("\n[6] health_check.py")
        r = run(str(HEALTH), env=env)
        expect(r.returncode in (0, 1), f"health exits 0 or 1 (got {r.returncode})")
        h = json.loads(r.stdout)
        expect(h["python"]["ok"], "Python OK")
        expect(h["sqlite"]["ok"], "SQLite OK")

    if FAILS:
        print(f"\n{len(FAILS)} failed assertions:", file=sys.stderr)
        for f in FAILS:
            print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
