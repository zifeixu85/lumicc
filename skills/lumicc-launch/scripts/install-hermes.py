#!/usr/bin/env python3
"""Install lumicc-launch into a Hermes Agent installation.

Adds:
  1) Skill files copied to ~/.hermes/skills/lumicc-launch
  2) Cron job in ~/.hermes/cron.yaml: daily 09:00 push today's cold-start tasks

Usage:
    python3 install-hermes.py [--no-cron] [--notify-channel feishu --notify-target group:ops]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
SKILL_ROOT = THIS.parent.parent
CRON_MARKER = "lumicc-launch:default"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hermes-home", default=str(Path.home() / ".hermes"))
    p.add_argument("--no-cron", action="store_true")
    p.add_argument("--notify-channel", default="")
    p.add_argument("--notify-target", default="")
    args = p.parse_args()

    home = Path(args.hermes_home).expanduser()
    if not home.exists():
        print(f"Hermes home not found: {home}", file=sys.stderr)
        return 2

    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    target = skills_dir / "lumicc-launch"
    if target.exists():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    shutil.copytree(SKILL_ROOT, target)
    print(f"✓ Skill copied to {target}")

    if not args.no_cron:
        cron_path = home / "cron.yaml"
        notify_args = ""
        if args.notify_channel:
            notify_args = f' --notify-channel {args.notify_channel} --notify-target "{args.notify_target}"'

        entry = (
            f"# {CRON_MARKER}\n"
            f"- id: {CRON_MARKER}\n"
            f"  schedule: \"0 9 * * *\"\n"
            f"  command: python3 {target}/scripts/day_advance.py --all-stores{notify_args} --quiet-stdout\n"
            f"  description: \"lumicc-launch daily cold-start task push (managed by install-hermes.py)\"\n"
            f"# /{CRON_MARKER}\n"
        )
        existing = cron_path.read_text(encoding="utf-8") if cron_path.exists() else ""
        pattern = re.compile(r"# " + re.escape(CRON_MARKER) + r"\n.*?# /" + re.escape(CRON_MARKER) + r"\n", re.DOTALL)
        content = pattern.sub(entry, existing) if pattern.search(existing) else existing + ("\n" if existing and not existing.endswith("\n") else "") + entry
        cron_path.write_text(content, encoding="utf-8")
        print(f"✓ Cron entry added to {cron_path}")
        print("  Restart Hermes daemon to pick up changes (or `hermes cron reload`).")

    print("\n----------------------------------------------------------------------")
    print("lumicc-launch installed for Hermes.")
    print(f"Skill: {target}")
    print(f"Cron:  {'daily 09:00' if not args.no_cron else 'skipped'}")
    print("\nNext steps:")
    print(f"  1) Start a campaign: python3 {target}/scripts/plan.py --store-id <YOUR_STORE_ID>")
    print('  2) Or naturally: "Start a new 30-day cold-start plan for my pet accessories store"')
    print("----------------------------------------------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
