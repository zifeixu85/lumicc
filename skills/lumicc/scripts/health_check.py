#!/usr/bin/env python3
"""Health check: verify Python, SQLite, ~/.commerce-os, recommended skills, credentials.

Prints a JSON report and exits 0 (all green), 1 (warnings), 2 (errors).

Usage:
    python3 health_check.py [--json | --pretty]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path.home() / ".commerce-os"

TIER1_SKILLS = [
    "jungle-scout-deep-dive-analyzer",
    "product-supplier-sourcing",
    "product-selection",
    "shopify-builder",
    "review-summarizer",
]
TIER2_SKILLS = [
    "1688-sourcing", "aliexpress-supplier-evaluator", "tariff-search",
    "social-media-publisher", "xiaohongshu-content-creator", "instagram-marketing",
    "tiktok-shop-setup", "amazon-listing-expert", "customer-voice-analyzer",
    "competitor-deep-analysis", "profit-margin-analyzer", "ecommerce-marketing",
]

SKILL_SEARCH_PATHS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".openclaw" / "skills",
    Path.home() / ".accio" / "accounts",  # nested; we glob
    Path.home() / ".cursor" / "skills",
    Path.home() / ".codex" / "skills",
]

REQUIRED_ENV = {
    "shopify": ["SHOPIFY_STORE_DOMAIN", "SHOPIFY_ADMIN_TOKEN"],
    "amazon": ["AMAZON_LWA_CLIENT_ID", "AMAZON_LWA_CLIENT_SECRET", "AMAZON_LWA_REFRESH_TOKEN"],
    "tiktok-shop": ["TIKTOK_SHOP_APP_KEY", "TIKTOK_SHOP_APP_SECRET", "TIKTOK_SHOP_ACCESS_TOKEN"],
    "etsy": ["ETSY_API_KEY"],
}


def check_python() -> dict:
    return {
        "python_version": sys.version.split()[0],
        "ok": sys.version_info >= (3, 8),
    }


def check_sqlite() -> dict:
    try:
        sqlite3.connect(":memory:").close()
        return {"ok": True, "version": sqlite3.sqlite_version}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_root() -> dict:
    return {
        "root": str(ROOT),
        "exists": ROOT.exists(),
        "db": (ROOT / "store.db").exists(),
        "soul": (ROOT / "SOUL.md").exists(),
        "memory_dir": (ROOT / "memory").exists(),
        "env_file": (ROOT / ".env").exists(),
    }


def find_skill(name: str) -> list[str]:
    """Search common skill installation directories for a folder named `name`."""
    found: list[str] = []
    for base in SKILL_SEARCH_PATHS:
        if not base.exists():
            continue
        for path in base.rglob(name):
            if path.is_dir() and (path / "SKILL.md").exists():
                found.append(str(path))
                break
    return found


def check_skills() -> dict:
    tier1 = {s: bool(find_skill(s)) for s in TIER1_SKILLS}
    tier2 = {s: bool(find_skill(s)) for s in TIER2_SKILLS}
    return {
        "tier1_installed": tier1,
        "tier1_count": sum(tier1.values()),
        "tier1_total": len(tier1),
        "tier2_installed": tier2,
        "tier2_count": sum(tier2.values()),
        "tier2_total": len(tier2),
    }


def load_env_with_dotenv() -> dict[str, str]:
    env = dict(os.environ)
    dot = ROOT / ".env"
    if dot.exists():
        for line in dot.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def check_credentials() -> dict:
    env = load_env_with_dotenv()
    result = {}
    for platform, keys in REQUIRED_ENV.items():
        result[platform] = {
            "configured": all(env.get(k) for k in keys),
            "missing": [k for k in keys if not env.get(k)],
        }
    return result


def check_optional_tools() -> dict:
    return {
        "playwright": shutil.which("playwright") is not None,
        "git": shutil.which("git") is not None,
        "jq": shutil.which("jq") is not None,
    }


def check_secrets() -> dict:
    """Inspect ~/.commerce-os/secrets/ — never returns cleartext values."""
    try:
        HERE = Path(__file__).resolve().parent
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        import secret_form  # type: ignore[import-not-found]
        catalog = secret_form.list_secrets()
        configured = sum(1 for v in catalog.values() if not v.get("missing"))
        return {
            "secrets_dir": str(secret_form.SECRETS_DIR),
            "total_known": len(catalog),
            "configured_count": configured,
            "missing_count": len(catalog) - configured,
            "by_key": catalog,  # already redacted to fingerprint by secret_form
        }
    except Exception as e:
        return {"error": str(e), "secrets_dir": None, "configured_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    report = {
        "python": check_python(),
        "sqlite": check_sqlite(),
        "commerce_os_root": check_root(),
        "skills": check_skills(),
        "credentials": check_credentials(),
        "secrets": check_secrets(),
        "optional_tools": check_optional_tools(),
    }

    errors: list[str] = []
    warnings: list[str] = []

    if not report["python"]["ok"]:
        errors.append("Python >= 3.8 required")
    if not report["sqlite"]["ok"]:
        errors.append("sqlite3 unavailable")
    if not report["commerce_os_root"]["exists"]:
        warnings.append(f"{ROOT} not initialized — run init_store.py")
    if report["skills"]["tier1_count"] == 0:
        warnings.append("No Tier 1 companion skills installed — many workflows will degrade")
    if not any(p["configured"] for p in report["credentials"].values()) \
       and report["secrets"].get("configured_count", 0) == 0:
        warnings.append(
            "No credentials configured — run "
            "`python3 secret_form.py --generate <KEY>` to add API keys securely."
        )

    report["status"] = {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
    }

    print(json.dumps(report, indent=2 if args.pretty else None, ensure_ascii=False))
    if errors:
        return 2
    if warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
