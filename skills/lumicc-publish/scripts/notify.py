#!/usr/bin/env python3
"""Notification dispatch for lumicc-publish — mirrors lumicc-listing/notify.py.

Coder mode: print to stdout.
Agent mode: write to ~/.commerce-os/outbox/<uuid>.json (or LUMICC_DATA_ROOT/outbox).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get("LUMICC_DATA_ROOT") or (Path.home() / ".commerce-os"))


def notify(
    channel: str,
    target: str,
    title: str,
    body_md: str,
    severity: str = "info",
    skill: str = "lumicc-publish",
    run_id: str | None = None,
) -> dict:
    payload = {
        "id": str(uuid.uuid4()),
        "ts": int(time.time()),
        "skill": skill,
        "run_id": run_id,
        "channel": channel,
        "target": target,
        "title": title,
        "body_md": body_md,
        "severity": severity,
    }
    if channel in ("stdout", "", None):
        print(f"### [{severity.upper()}] {title}")
        print(body_md)
        return {"mode": "stdout", "payload": payload}
    outbox = _root() / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    out_path = outbox / f"{payload['id']}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"mode": "outbox", "path": str(out_path), "payload": payload}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--channel", default="stdout")
    p.add_argument("--target", default="")
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--severity", default="info", choices=["info", "warn", "error"])
    p.add_argument("--skill", default="lumicc-publish")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()
    r = notify(channel=args.channel, target=args.target, title=args.title,
               body_md=args.body, severity=args.severity, skill=args.skill,
               run_id=args.run_id)
    print(json.dumps({k: v for k, v in r.items() if k != "payload"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
