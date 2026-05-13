#!/usr/bin/env python3
"""Verify the v0.3 multi-channel install manifest.

Checks:
  1. install.json is well-formed (manifest_version == 1, 11 skills).
  2. All skill paths referenced in the manifest exist on disk.
  3. Every SKILL.md frontmatter has `channels:` under `metadata.compatibility`.
  4. `bash bin/lumicc install --dry-run` prints "would copy" + 11 skill names.

Pure stdlib. Probes the release bundle at ../../../../../releases/lumicc/ first
(when run from inside crossborder-commerce/skills/lumicc/scripts/), and falls
back to the source-side install.json at the crossborder-commerce root.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_bundle_root() -> Path:
    """Return the directory containing install.json + skills/ + bin/lumicc."""
    here = Path(__file__).resolve()
    # crossborder-commerce/skills/lumicc/scripts/test_install_manifest.py
    # → releases/lumicc/ sibling
    candidates = [
        here.parents[4] / "releases" / "lumicc",            # release bundle
        here.parents[3],                                    # crossborder-commerce/ (source)
    ]
    for c in candidates:
        if (c / "install.json").exists():
            return c
    raise SystemExit(f"could not locate install.json (tried: {candidates})")


def check_manifest(bundle: Path) -> dict:
    manifest_path = bundle / "install.json"
    data = json.loads(manifest_path.read_text())
    assert data["manifest_version"] == 1, f"manifest_version != 1: {data['manifest_version']}"
    assert len(data["skills"]) == 12, f"expected 12 skills, got {len(data['skills'])}"
    print(f"  ✓ manifest_version=1, skills=12 ({manifest_path})")
    return data


def check_skill_paths(bundle: Path, data: dict) -> None:
    missing = []
    for s in data["skills"]:
        skill_path = bundle / s["path"]
        skill_md = skill_path / "SKILL.md"
        if not skill_path.is_dir():
            missing.append(f"missing dir: {skill_path}")
        elif not skill_md.is_file():
            missing.append(f"missing SKILL.md: {skill_md}")
    if missing:
        raise AssertionError("\n".join(missing))
    print(f"  ✓ all 12 skill paths exist under {bundle}")


def check_channels_in_frontmatter(bundle: Path, data: dict) -> None:
    missing = []
    for s in data["skills"]:
        skill_md = bundle / s["path"] / "SKILL.md"
        text = skill_md.read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            missing.append(f"{skill_md}: no frontmatter")
            continue
        fm = m.group(1)
        # Look for `channels:` line inside `compatibility:` block
        if not re.search(r"^\s+channels:\s*\[", fm, re.MULTILINE):
            missing.append(f"{skill_md}: no channels: in frontmatter")
    if missing:
        raise AssertionError("\n".join(missing))
    print("  ✓ all 12 SKILL.md frontmatter have `channels:` under compatibility")


def check_dry_run(bundle: Path, data: dict) -> None:
    launcher = bundle / "bin" / "lumicc"
    if not launcher.is_file():
        raise AssertionError(f"missing launcher: {launcher}")
    # Run dry-run in a temp HOME so we don't accidentally trip auto-detect quirks
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["HOME"] = td
        env.pop("LUMICC_TARGET", None)
        res = subprocess.run(
            ["bash", str(launcher), "install", "--dry-run", "--target", "claude-code"],
            capture_output=True,
            text=True,
            env=env,
            cwd=td,
        )
    if res.returncode != 0:
        raise AssertionError(f"dry-run exit={res.returncode}\nstderr:\n{res.stderr}")
    out = res.stdout
    assert "would copy" in out, f"'would copy' not in stdout:\n{out}"
    mentions = out.count("would copy")
    assert mentions == 12, f"expected 12 'would copy' lines, got {mentions}\n{out}"
    # Verify each skill name appears
    missing = [s["name"] for s in data["skills"] if s["name"] not in out]
    if missing:
        raise AssertionError(f"missing skills in dry-run output: {missing}\n{out}")
    print(f"  ✓ dry-run lists 12 skills with 'would copy' (target=claude-code)")


def main() -> int:
    bundle = find_bundle_root()
    print(f"bundle: {bundle}")
    data = check_manifest(bundle)
    check_skill_paths(bundle, data)
    check_channels_in_frontmatter(bundle, data)
    check_dry_run(bundle, data)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
