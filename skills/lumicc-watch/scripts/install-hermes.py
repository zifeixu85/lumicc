#!/usr/bin/env python3
"""Install lumicc-watch into a Hermes Agent installation.

Adds:
  1) Symlink/copy of this skill into ~/.hermes/skills/lumicc-watch
  2) Registers a cron job (09:00 + 21:00 daily) via ~/.hermes/cron.yaml

Hermes natively supports `cronjob()` tool calls; we write to the canonical
cron config file so Hermes picks it up on next reload (or via `hermes cron reload`).

Usage:
  python3 install-hermes.py
  python3 install-hermes.py --hermes-home ~/.hermes
  python3 install-hermes.py --no-cron
  python3 install-hermes.py --notify-channel feishu --notify-target group:跨境运营组
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
SKILL_ROOT = THIS.parent.parent  # the lumicc-watch directory

CRON_MARKER = "lumicc-watch:default"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hermes-home", default=str(Path.home() / ".hermes"))
    p.add_argument("--no-cron", action="store_true")
    p.add_argument("--notify-channel", default="")
    p.add_argument("--notify-target", default="")
    args = p.parse_args()

    hermes_home = Path(args.hermes_home).expanduser()
    if not hermes_home.exists():
        print(f"Hermes home not found: {hermes_home}", file=sys.stderr)
        print("Install Hermes first: https://github.com/NousResearch/hermes-agent", file=sys.stderr)
        return 2

    skills_dir = hermes_home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    target = skills_dir / "lumicc-watch"
    if target.exists():
        print(f"Refreshing existing install at {target}")
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    shutil.copytree(SKILL_ROOT, target)
    print(f"✓ Skill copied to {target}")

    # Cron registration
    if not args.no_cron:
        cron_path = hermes_home / "cron.yaml"
        notify_args = ""
        if args.notify_channel:
            notify_args = f' --notify-channel {args.notify_channel} --notify-target "{args.notify_target}"'

        new_entry = (
            f"# {CRON_MARKER}\n"
            f"- id: {CRON_MARKER}\n"
            f"  schedule: \"0 9,21 * * *\"\n"
            f"  command: python3 {target}/scripts/run.py --all-stores{notify_args} --quiet-stdout\n"
            f"  description: \"lumicc-watch daily competitor snapshots (managed by install-hermes.py)\"\n"
            f"# /{CRON_MARKER}\n"
        )

        existing = cron_path.read_text(encoding="utf-8") if cron_path.exists() else ""
        # Replace existing block if present, else append
        import re
        pattern = re.compile(r"# " + re.escape(CRON_MARKER) + r"\n.*?# /" + re.escape(CRON_MARKER) + r"\n", re.DOTALL)
        if pattern.search(existing):
            content = pattern.sub(new_entry, existing)
        else:
            content = existing + ("\n" if existing and not existing.endswith("\n") else "") + new_entry
        cron_path.write_text(content, encoding="utf-8")
        print(f"✓ Cron entry added to {cron_path}")
        print("  Run `hermes cron reload` (if needed) or restart the Hermes daemon to pick up changes.")

    print("\n----------------------------------------------------------------------")
    print("lumicc-watch installed for Hermes.")
    print(f"Skill: {target}")
    print(f"Cron:  {'09:00 + 21:00 daily' if not args.no_cron else 'skipped'}")
    print()
    print("Next steps:")
    print("  1) Configure competitor targets (~/.commerce-os/store.db preferences):")
    print(f"       python3 {target.parent}/../lumicc/scripts/memory.py log \\")
    print('         --category preference \\')
    print('         --content \'{"watchtower_targets": ["https://shop1.com", "https://shop2.com"]}\'')
    print()
    print("  2) Test:")
    print(f"       python3 {target}/scripts/run.py --target https://shop1.com")
    print()
    print("  3) Talk to Hermes naturally (since cronjob is its first-class tool):")
    print('       "Show me the latest lumicc-watch report"')
    print("----------------------------------------------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
