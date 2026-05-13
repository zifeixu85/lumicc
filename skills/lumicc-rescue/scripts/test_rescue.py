#!/usr/bin/env python3
"""End-to-end smoke test for lumicc-rescue."""
from __future__ import annotations
import json, os, sqlite3, subprocess, sys, tempfile, time, uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
INIT = HERE.parent.parent / "lumicc" / "scripts" / "init_store.py"
RUN = HERE / "run.py"
sys.path.insert(0, str(HERE))
import triage as T

FAILS: list[str] = []


def expect(c: bool, m: str) -> None:
    (FAILS.append(m) or print(f"  ✗ {m}", file=sys.stderr)) if not c else print(f"  ✓ {m}")


def main() -> int:
    print("[1] triage — account warning dominates")
    d = T.diagnose(T.TriageInput(platform_notification="account_warning"))
    expect(d["branch_id"] == "A", "account warning → branch A")
    expect(d["confidence"] >= 0.9, "high confidence on account warning")
    expect("Account Health" in d["playbook_steps"][0], "playbook step 1 mentions Account Health")

    print("\n[2] triage — ad disapproval")
    d = T.diagnose(T.TriageInput(platform_notification="ad_disapproval"))
    expect(d["branch_id"] == "B", "ad disapproval → branch B")
    expect(d["playbook_id"] == "ad-disapproval", "playbook id correct")

    print("\n[3] triage — self inflicted (price change)")
    d = T.diagnose(T.TriageInput(recent_change_kind="price"))
    expect(d["branch_id"] == "D", "recent change → self-inflicted")
    expect("REVERT" in d["playbook_steps"][1], "playbook step says revert")

    print("\n[4] triage — alternatives surface for ambiguous cases")
    d = T.diagnose(T.TriageInput(scope="store_wide"))
    expect(d["branch_id"] == "E", "store-wide no signals → price war default")
    expect(len(d["alternatives"]) >= 1, "alternatives suggested when ambiguous")
    alt_ids = [a["branch_id"] for a in d["alternatives"]]
    expect("G" in alt_ids, "algorithm shift in alternatives")

    print("\n[5] triage — single SKU goes to listing suppression")
    d = T.diagnose(T.TriageInput(scope="single_sku"))
    expect(d["branch_id"] == "C", "single sku → listing suppression branch")

    print("\n[6] run.py end-to-end")
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "HOME": tmp}
        root = Path(tmp) / ".commerce-os"
        subprocess.run(["python3", str(INIT)], env=env, capture_output=True, text=True)
        db = sqlite3.connect(root / "store.db")
        sid = str(uuid.uuid4())
        ts = int(time.time())
        db.execute(
            "INSERT INTO stores (id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, "Acme Pets", "shopify", "https://x.com", "USD", "us", "1-to-10", "pets", ts, ts),
        )
        # Seed a recent decision (will appear as evidence)
        db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (sid, ts - 12 * 3600, "decision", "Bumped MKR-16 price from $29.99 to $34.99"),
        )
        db.commit(); db.close()

        r = subprocess.run(
            ["python3", str(RUN), "--store-id", sid,
             "--platform-notification", "ad_disapproval",
             "--recent-change", "ad", "--scope", "store_wide", "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "run.py exits 0")
        result = json.loads(r.stdout)
        expect(result["branch"] == "B", "branch B selected")
        expect(result["hypothesis"] == "Ad creative or policy rejection", "hypothesis returned")

        # 7) Verify crisis campaign + event + run inserted
        db = sqlite3.connect(root / "store.db")
        n_camp = db.execute("SELECT COUNT(*) FROM campaigns WHERE type='crisis'").fetchone()[0]
        n_warn = db.execute("SELECT COUNT(*) FROM events WHERE category='warning'").fetchone()[0]
        n_run = db.execute("SELECT COUNT(*) FROM runs WHERE skill='lumicc-rescue'").fetchone()[0]
        db.close()
        expect(n_camp >= 1, "crisis campaign inserted")
        expect(n_warn >= 1, "warning event added")
        expect(n_run >= 1, "run row inserted")

        # 8) Inspect the report.md for evidence row
        runs_dir = root / "runs"
        rd = max(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime)
        rep = (rd / "report.md").read_text(encoding="utf-8")
        expect("Bumped MKR-16 price" in rep, "evidence event surfaced in report")
        expect("行动方案" in rep, "report has Chinese 行动方案 heading")

        # 9) Agent mode
        print("\n[7] agent mode")
        r = subprocess.run(
            ["python3", str(RUN), "--store-id", sid,
             "--platform-notification", "account_warning", "--scope", "store_wide",
             "--notify-channel", "feishu", "--notify-target", "user:cheche",
             "--quiet-stdout"],
            env=env, capture_output=True, text=True,
        )
        expect(r.returncode == 0, "agent mode exits 0")
        outbox = root / "outbox"
        files = list(outbox.glob("*.json"))
        expect(len(files) >= 1, "outbox dropped")
        payload = json.loads(files[0].read_text())
        expect(payload["severity"] == "error", "account warning → severity error")
        expect(payload["skill"] == "lumicc-rescue", "skill correct")

    if FAILS:
        print(f"\n{len(FAILS)} failed:", file=sys.stderr)
        for f in FAILS: print(f" - {f}", file=sys.stderr)
        return 1
    print("\nAll lumicc-rescue smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
