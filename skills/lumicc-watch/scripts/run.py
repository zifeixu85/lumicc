#!/usr/bin/env python3
"""Orchestrate a full watchtower run.

Reads target list from ~/.commerce-os/store.db preferences['watchtower_targets']
(or --targets-file). For each target:
  1) Snapshot current state → ~/.commerce-os/watchtower/<host>/<ts>.json
  2) Find most recent prior snapshot for same host → diff
  3) Write markdown report → ~/.commerce-os/runs/<run_id>/report.md
  4) Append to events table (Layer 1)
  5) If --notify-channel given, dispatch via notify.py

Usage (coder mode):
    python3 run.py --store-id my-pets-store
Usage (agent mode):
    python3 run.py --all-stores --notify-channel feishu --notify-target group:ops --quiet-stdout
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import snapshot as snap_mod
import diff as diff_mod
import notify as notify_mod
import render_html as render_mod

ROOT = Path.home() / ".commerce-os"
WATCH_DIR = ROOT / "watchtower"
RUNS_DIR = ROOT / "runs"


def db_path() -> Path:
    return ROOT / "store.db"


def load_targets(store_id: str | None, targets_file: str | None, cli_targets: list[str]) -> list[dict]:
    if cli_targets:
        return [{"url": u, "store_id": store_id} for u in cli_targets]
    if targets_file:
        data = json.loads(Path(targets_file).read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [{"url": u, "store_id": store_id} if isinstance(u, str) else u for u in data]
    # Read from store.db preferences
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path())
    try:
        if store_id:
            key = f"watchtower_targets:{store_id}"
        else:
            key = "watchtower_targets"
        row = db.execute("SELECT value FROM preferences WHERE key=?", (key,)).fetchone()
    finally:
        db.close()
    if not row or not row[0]:
        return []
    try:
        urls = json.loads(row[0])
        return [{"url": u, "store_id": store_id} for u in urls if isinstance(u, str)]
    except json.JSONDecodeError:
        return []


def host_of(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or "unknown"


def host_dir(url: str) -> Path:
    d = WATCH_DIR / host_of(url).replace(":", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def latest_snapshot(url: str) -> Path | None:
    d = host_dir(url)
    files = sorted(d.glob("*.json"))
    return files[-1] if files else None


def append_event(store_id: str | None, category: str, content: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT INTO events (store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, int(time.time()), category, content),
        )
        db.commit()
    finally:
        db.close()


def append_run_row(run_id: str, store_id: str | None, status: str, result_path: str) -> None:
    if not db_path().exists():
        return
    db = sqlite3.connect(db_path())
    try:
        db.execute(
            "INSERT OR REPLACE INTO runs (run_id, skill, store_id, started_at, finished_at, status, result_path) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, "lumicc-watch", store_id, int(time.time()), int(time.time()), status, result_path),
        )
        db.commit()
    finally:
        db.close()


def render_report_md(per_target: list[dict]) -> str:
    lines: list[str] = []
    lines.append(f"# Watchtower Report — {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    grand_high = sum(t["diff"]["summary"]["high"] for t in per_target if t.get("diff"))
    grand_total = sum(t["diff"]["summary"]["total_changes"] for t in per_target if t.get("diff"))
    lines.append(f"**Targets scanned**: {len(per_target)}")
    lines.append(f"**Total changes**: {grand_total} (high priority: {grand_high})")
    lines.append("")
    for t in per_target:
        lines.append(f"## {t['url']}")
        if t.get("error"):
            lines.append(f"- ⚠️ {t['error']}")
            continue
        d = t.get("diff") or {}
        sm = d.get("summary") or {}
        lines.append(f"- Total: {sm.get('total_changes', 0)} (high: {sm.get('high', 0)} / med: {sm.get('medium', 0)} / low: {sm.get('low', 0)})")
        for ch in (d.get("high_priority_changes") or [])[:6]:
            lines.append(f"  - 🔴 **{ch['category']}** — {json.dumps(ch.get('detail', {}), ensure_ascii=False)}")
        med = [c for c in (d.get("all_changes") or []) if c["severity"] == "medium"][:5]
        for ch in med:
            lines.append(f"  - 🟡 {ch['category']} — {json.dumps(ch.get('detail', {}), ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--store-id", default=None)
    p.add_argument("--all-stores", action="store_true")
    p.add_argument("--targets-file", default=None)
    p.add_argument("--target", action="append", default=[], help="One competitor URL; repeatable")
    p.add_argument("--delay-ms", type=int, default=3000)
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()

    ROOT.mkdir(exist_ok=True)
    WATCH_DIR.mkdir(exist_ok=True)
    RUNS_DIR.mkdir(exist_ok=True)
    run_id = args.run_id or str(uuid.uuid4())
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    targets = load_targets(args.store_id, args.targets_file, args.target)
    if not targets:
        msg = "No watchtower targets configured. Use --target URL or set preferences['watchtower_targets']."
        if not args.quiet_stdout:
            print(msg, file=sys.stderr)
        run_status = "failed"
        result = {"run_id": run_id, "skill": "lumicc-watch", "status": run_status, "error": msg}
        (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        append_run_row(run_id, args.store_id, run_status, str(run_dir / "result.json"))
        return 2

    per_target: list[dict] = []
    for t in targets:
        url = t["url"]
        out: dict = {"url": url}
        try:
            ts_dir = host_dir(url)
            ts = int(time.time())
            curr_path = ts_dir / f"{ts}.json"
            snap = snap_mod.snapshot_url(url, delay_s=args.delay_ms / 1000.0)
            curr_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            out["snapshot_path"] = str(curr_path)
            # find prior
            files = sorted(ts_dir.glob("*.json"))
            prior = [f for f in files if f != curr_path]
            if prior:
                prev_snap = json.loads(prior[-1].read_text(encoding="utf-8"))
                out["diff"] = diff_mod.diff_snapshots(prev_snap, snap)
            else:
                out["diff"] = {"summary": {"total_changes": 0, "high": 0, "medium": 0, "low": 0},
                               "note": "First snapshot — no baseline to diff."}
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        per_target.append(out)

    # Write markdown + JSON results
    md = render_report_md(per_target)
    md_path = run_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")

    # Build DTO for HTML renderer
    warnings: list[str] = []
    targets_results: list[dict] = []
    for t in per_target:
        url = t.get("url", "")
        d = t.get("diff") or {}
        snap_path = t.get("snapshot_path")
        snap_ts: int | None = None
        if snap_path:
            try:
                snap_ts = json.loads(Path(snap_path).read_text(encoding="utf-8")).get("ts")
            except Exception:
                snap_ts = None
        is_first_run = bool(d.get("note")) and not d.get("all_changes")
        targets_results.append({
            "url": url,
            "host": host_of(url),
            "snapshot_ts": snap_ts or d.get("curr_ts"),
            "prior_ts": d.get("prev_ts"),
            "is_first_run": is_first_run,
            "changes": d.get("all_changes") or [],
            "error": t.get("error"),
        })

    html_path = run_dir / "report.html"
    try:
        html = render_mod.render_page(
            run_id=run_id,
            store_name=args.store_id or "",
            targets_results=targets_results,
            html_path=html_path,
        )
        html_path.write_text(html, encoding="utf-8")
    except Exception as e:
        warnings.append(f"html render failed: {type(e).__name__}: {e}")
        html_path = None  # type: ignore[assignment]

    result = {
        "run_id": run_id,
        "skill": "lumicc-watch",
        "store_id": args.store_id,
        "started_at": int(time.time()),
        "finished_at": int(time.time()),
        "status": "success",
        "targets": per_target,
        "report_path": str(md_path),
        "report_html": str(html_path) if html_path else None,
        "warnings": warnings,
    }
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # Append event row
    total_changes = sum(t.get("diff", {}).get("summary", {}).get("total_changes", 0) for t in per_target)
    append_event(args.store_id, "task",
                 f"lumicc-watch: scanned {len(per_target)} targets, {total_changes} changes detected; run={run_id}")
    append_run_row(run_id, args.store_id, "success", str(run_dir / "result.json"))

    # Output
    if not args.quiet_stdout:
        print(md)

    # Notify
    if args.notify_channel:
        title = f"Watchtower: {total_changes} changes across {len(per_target)} stores"
        severity = "warn" if any(t.get("diff", {}).get("summary", {}).get("high", 0) for t in per_target) else "info"
        notify_mod.notify(
            channel=args.notify_channel,
            target=args.notify_target,
            title=title,
            body_md=md,
            severity=severity,
            skill="lumicc-watch",
            run_id=run_id,
        )

    # Simple JSON line for cron logs
    if args.quiet_stdout:
        print(json.dumps({"run_id": run_id, "total_changes": total_changes, "report": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
