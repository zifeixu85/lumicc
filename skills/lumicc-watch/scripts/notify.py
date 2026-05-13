#!/usr/bin/env python3
"""Notification dispatch — runtime-agnostic.

In coder mode (no notification channel), we just print the message.
In agent mode, we write a notification request to ~/.commerce-os/outbox/<uuid>.json
and the agent runtime (OpenClaw / Hermes / etc.) picks it up and delivers.

Lumicc never holds IM credentials directly. The agent runtime owns the gateway.

Usage as a library:
    from notify import notify
    notify(channel="feishu", target="group:跨境运营组",
           title="Watchtower diff", body_md="...", severity="info")

Usage from CLI:
    python3 notify.py --channel feishu --target group:ops --title 'x' --body 'y'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path.home() / ".commerce-os"
OUTBOX = ROOT / "outbox"


def notify(
    channel: str,
    target: str,
    title: str,
    body_md: str,
    severity: str = "info",
    skill: str = "lumicc-watch",
    run_id: str | None = None,
) -> dict:
    """Dispatch a notification request.

    Returns a dict with `mode` (`stdout` or `outbox`) and `path` (where it was written).
    """
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
        # Coder mode fallback — print to stdout
        print(f"### [{severity.upper()}] {title}")
        print(body_md)
        return {"mode": "stdout", "payload": payload}

    # Agent mode — write to outbox for runtime gateway pickup
    OUTBOX.mkdir(parents=True, exist_ok=True)
    out_path = OUTBOX / f"{payload['id']}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"mode": "outbox", "path": str(out_path), "payload": payload}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--channel", default="stdout")
    p.add_argument("--target", default="")
    p.add_argument("--title", required=True)
    p.add_argument("--body", required=True)
    p.add_argument("--severity", default="info", choices=["info", "warn", "error"])
    p.add_argument("--skill", default="lumicc-watch")
    p.add_argument("--run-id", default=None)
    args = p.parse_args()
    result = notify(
        channel=args.channel, target=args.target, title=args.title,
        body_md=args.body, severity=args.severity, skill=args.skill,
        run_id=args.run_id,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "payload"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
