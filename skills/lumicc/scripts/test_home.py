#!/usr/bin/env python3
"""Smoke test for home.py — the Lumicc control center.

Seeds a multi-store ~/.commerce-os/ in a tempdir, renders the control center,
and asserts the portfolio strip + cross-store focus feed behave correctly.

Run:
    python3 test_home.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
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


def seed(root: Path) -> dict:
    """Insert 3 stores with distinct urgency profiles."""
    db = sqlite3.connect(root / "store.db")
    ts = int(time.time())
    crisis_sid = str(uuid.uuid4())
    coldstart_sid = str(uuid.uuid4())
    idle_sid = str(uuid.uuid4())

    for sid, name, stage in [
        (crisis_sid, "Acme Pets", "1-to-10"),
        (coldstart_sid, "New Kitchen", "0-to-1"),
        (idle_sid, "Old Beauty", "10-to-100"),
    ]:
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, name, "shopify", f"https://{name}.myshopify.com", "USD", "us",
             stage, "test niche", ts - 40 * 86400, ts),
        )

    # crisis store: a warning event in last 48h
    db.execute("INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
               (crisis_sid, ts - 3600, "warning", "广告被拒绝 — 创意涉及违规声明"))
    # crisis store also has a recent run — with a report.html on disk
    crisis_run_id = str(uuid.uuid4())
    crisis_run_dir = root / "runs" / crisis_run_id
    crisis_run_dir.mkdir(parents=True, exist_ok=True)
    (crisis_run_dir / "result.json").write_text(
        json.dumps({"metrics": {"high_severity_count": 2}}), encoding="utf-8")
    (crisis_run_dir / "report.html").write_text("<html>report</html>", encoding="utf-8")
    db.execute("INSERT INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
               "VALUES (?,?,?,?,?,?,?)",
               (crisis_run_id, "lumicc-watch", crisis_sid, ts - 7200, ts - 7100,
                "success", str(crisis_run_dir / "result.json")))

    # cold-start store: a running cold-start campaign started 5 days ago
    plan = {"schedule": [{"day": i} for i in range(1, 31)]}
    db.execute(
        "INSERT INTO campaigns (id, store_id, type, status, budget_usd, started_at, ended_at, results_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), coldstart_sid, "cold-start", "running", 2000,
         ts - 5 * 86400, None, json.dumps(plan)),
    )

    # idle store: a run 10 days ago, nothing since
    db.execute("INSERT INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
               "VALUES (?,?,?,?,?,?,?)",
               (str(uuid.uuid4()), "lumicc-retention", idle_sid, ts - 10 * 86400,
                ts - 10 * 86400 + 60, "success", ""))

    db.commit()
    db.close()
    return {"crisis": crisis_sid, "coldstart": coldstart_sid, "idle": idle_sid,
            "crisis_run_id": crisis_run_id}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / ".commerce-os"
        env_root = str(root)
        os.environ["LUMICC_DATA_ROOT"] = env_root

        # init
        import subprocess
        r = subprocess.run(["python3", str(INIT_STORE)],
                           env={**os.environ, "LUMICC_DATA_ROOT": env_root},
                           capture_output=True, text=True)
        expect(r.returncode == 0, "init_store.py succeeds")

        ids = seed(root)

        # import home fresh (after LUMICC_DATA_ROOT set)
        sys.path.insert(0, str(HERE))
        import importlib
        import home as home_mod
        importlib.reload(home_mod)

        # --- 1) load_state picks up all 3 stores ---
        state = home_mod.load_state()
        expect(len(state["stores"]) == 3, f"load_state finds 3 stores (got {len(state['stores'])})")

        # --- 2) action items: crisis store gets a 🚨 high-urgency item ---
        crisis_items = home_mod.action_items_for_store(
            next(s for s in state["stores"] if s["id"] == ids["crisis"]),
            state["events_by_store"][ids["crisis"]],
            state["campaigns_by_store"][ids["crisis"]],
            state["runs_by_store"][ids["crisis"]],
        )
        crisis_top = max(crisis_items, key=lambda x: x["urgency"])
        expect(crisis_top["urgency"] >= 90, f"crisis store top urgency >= 90 (got {crisis_top['urgency']})")
        expect("🚨" in crisis_top["emoji"], "crisis item uses 🚨 emoji")

        # --- 3) cold-start store gets a Day X/30 item ---
        cs_items = home_mod.action_items_for_store(
            next(s for s in state["stores"] if s["id"] == ids["coldstart"]),
            state["events_by_store"][ids["coldstart"]],
            state["campaigns_by_store"][ids["coldstart"]],
            state["runs_by_store"][ids["coldstart"]],
        )
        cs_titles = " ".join(it["title"] for it in cs_items)
        expect("Day" in cs_titles and "/30" in cs_titles, "cold-start store shows Day X/30")

        # --- 4) idle store flagged as stale (10 days idle >= 7) ---
        idle_items = home_mod.action_items_for_store(
            next(s for s in state["stores"] if s["id"] == ids["idle"]),
            state["events_by_store"][ids["idle"]],
            state["campaigns_by_store"][ids["idle"]],
            state["runs_by_store"][ids["idle"]],
        )
        idle_titles = " ".join(it["title"] for it in idle_items)
        expect("天没动作" in idle_titles, "idle store flagged as stale")

        # --- 5) render_home produces valid HTML ---
        html = home_mod.render_home(state)
        expect("<!doctype html>" in html, "render_home emits doctype")
        expect("</body>" in html and "</html>" in html, "render_home well-formed")
        expect("portfolio-strip" in html, "render_home has portfolio strip")
        expect("focus-feed" in html, "render_home has focus feed")
        expect("data-theme=" in html, "render_home inherits theme system")
        expect(".ts-btn" in html or "theme-switch" in html, "render_home has theme switcher")
        for name in ("Acme Pets", "New Kitchen", "Old Beauty"):
            expect(name in html, f"render_home shows store '{name}'")
        expect("6 个专家团队" in html, "render_home shows team cards")

        # --- 5b) run WITH report.html → href in output; runs without → no href ---
        report_href = f"runs/{ids['crisis_run_id']}/report.html"
        expect(report_href in html, "render_home links to existing report.html")
        # idle store's run has result_path="" → must not produce a broken link
        expect("runs//report.html" not in html,
               "no broken link for run without result_path")

        # --- 6) store filter works ---
        state_filtered = home_mod.load_state(ids["crisis"])
        expect(len(state_filtered["stores"]) == 1, "load_state(store_id) filters to 1 store")
        html_filtered = home_mod.render_home(state_filtered, active=ids["crisis"])
        expect("Acme Pets" in html_filtered, "filtered view shows the store")
        expect("New Kitchen" not in html_filtered, "filtered view hides other stores' items")

        # --- 7) empty state: no stores ---
        empty_root = Path(tmp) / "empty" / ".commerce-os"
        empty_root.mkdir(parents=True)
        os.environ["LUMICC_DATA_ROOT"] = str(empty_root)
        subprocess.run(["python3", str(INIT_STORE)],
                       env={**os.environ, "LUMICC_DATA_ROOT": str(empty_root)},
                       capture_output=True, text=True)
        importlib.reload(home_mod)
        empty_state = home_mod.load_state()
        expect(len(empty_state["stores"]) == 0, "empty install → 0 stores")
        empty_html = home_mod.render_home(empty_state)
        expect("还没有接入任何店铺" in empty_html, "empty state shows onboarding prompt")
        expect("接入我的店" in empty_html, "empty state has 接入 action")

        # --- 8) CLI runs + writes home.html + JSON ---
        os.environ["LUMICC_DATA_ROOT"] = env_root
        out_html = root / "home.html"
        r = subprocess.run(
            ["python3", str(HERE / "home.py"), "--no-open", "--quiet-stdout"],
            env={**os.environ, "LUMICC_DATA_ROOT": env_root},
            capture_output=True, text=True)
        expect(r.returncode == 0, "home.py CLI exits 0")
        expect(out_html.exists(), "home.py writes home.html")
        try:
            payload = json.loads(r.stdout)
            expect(payload["stores"] == 3, "CLI JSON reports 3 stores")
            expect(payload["action_items"] >= 3, "CLI JSON reports >= 3 action items")
        except json.JSONDecodeError:
            FAILS.append(f"CLI stdout not JSON: {r.stdout[:200]}")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("\nAll home.py control-center tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
