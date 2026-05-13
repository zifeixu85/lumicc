#!/usr/bin/env python3
"""Diff two snapshots produced by snapshot.py.

Output is a structured JSON: categorized changes (new products, removed products,
price changes, banner copy changes, headings changes) with weighted severity.

Usage:
    python3 diff.py --prev /path/prev.json --curr /path/curr.json [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Diff category weights (sync with references/diff-categories.md)
WEIGHTS = {
    "new_product": 3.0,
    "removed_product": 2.5,
    "promo_banner_change": 1.8,
    "homepage_hero_change": 1.5,
    "meta_seo_change": 0.8,
    "social_handle_change": 0.7,
    "sitemap_size_swing": 1.4,
}

SEVERITY = {"high": 2.0, "medium": 1.0, "low": 0.0}


def severity_of(weight: float) -> str:
    if weight >= 2.0:
        return "high"
    if weight >= 1.0:
        return "medium"
    return "low"


def diff_snapshots(prev: dict, curr: dict) -> dict:
    changes: list[dict] = []

    prev_home = prev.get("homepage") or {}
    curr_home = curr.get("homepage") or {}

    # Product URLs from homepage anchor + sitemap
    def product_urls(snap: dict) -> set[str]:
        home = snap.get("homepage") or {}
        urls = {p["url"] for p in home.get("products", [])}
        urls.update(snap.get("sitemap_products_sample", []))
        return urls

    prev_urls = product_urls(prev)
    curr_urls = product_urls(curr)

    new_urls = sorted(curr_urls - prev_urls)
    removed_urls = sorted(prev_urls - curr_urls)

    for u in new_urls[:20]:
        changes.append({"category": "new_product", "weight": WEIGHTS["new_product"], "detail": {"url": u}})
    for u in removed_urls[:20]:
        changes.append({"category": "removed_product", "weight": WEIGHTS["removed_product"], "detail": {"url": u}})

    # Sitemap count swing
    p_sz = prev.get("sitemap_product_count") or 0
    c_sz = curr.get("sitemap_product_count") or 0
    if p_sz and abs(c_sz - p_sz) / max(p_sz, 1) > 0.05:
        changes.append({
            "category": "sitemap_size_swing",
            "weight": WEIGHTS["sitemap_size_swing"],
            "detail": {"prev": p_sz, "curr": c_sz, "delta_pct": round(100 * (c_sz - p_sz) / p_sz, 1)},
        })

    # Banner copy
    prev_banner = set(prev_home.get("announcement_candidates") or [])
    curr_banner = set(curr_home.get("announcement_candidates") or [])
    added_banner = sorted(curr_banner - prev_banner)
    if added_banner:
        changes.append({
            "category": "promo_banner_change",
            "weight": WEIGHTS["promo_banner_change"],
            "detail": {"new_lines": added_banner[:5]},
        })

    # Hero / headings
    prev_h = (prev_home.get("headings") or [])[:5]
    curr_h = (curr_home.get("headings") or [])[:5]
    if prev_h != curr_h and (prev_h or curr_h):
        changes.append({
            "category": "homepage_hero_change",
            "weight": WEIGHTS["homepage_hero_change"],
            "detail": {"prev": prev_h, "curr": curr_h},
        })

    # Meta SEO
    if prev_home.get("title") != curr_home.get("title") and (prev_home.get("title") or curr_home.get("title")):
        changes.append({
            "category": "meta_seo_change",
            "weight": WEIGHTS["meta_seo_change"],
            "detail": {"field": "title", "prev": prev_home.get("title"), "curr": curr_home.get("title")},
        })
    if prev_home.get("meta_description") != curr_home.get("meta_description"):
        changes.append({
            "category": "meta_seo_change",
            "weight": WEIGHTS["meta_seo_change"],
            "detail": {"field": "meta_description"},
        })

    # Social handles
    p_soc = prev_home.get("social_handles") or {}
    c_soc = curr_home.get("social_handles") or {}
    for k in set(p_soc) | set(c_soc):
        if p_soc.get(k) != c_soc.get(k):
            changes.append({
                "category": "social_handle_change",
                "weight": WEIGHTS["social_handle_change"],
                "detail": {"platform": k, "prev": p_soc.get(k), "curr": c_soc.get(k)},
            })

    # Compute summary
    total = len(changes)
    high = sum(1 for c in changes if c["weight"] >= 2.0)
    medium = sum(1 for c in changes if 1.0 <= c["weight"] < 2.0)
    low = sum(1 for c in changes if c["weight"] < 1.0)
    # Sort by weight desc
    changes.sort(key=lambda c: -c["weight"])
    for c in changes:
        c["severity"] = severity_of(c["weight"])

    return {
        "prev_url": prev.get("url"),
        "curr_url": curr.get("url"),
        "prev_ts": prev.get("ts"),
        "curr_ts": curr.get("ts"),
        "summary": {"total_changes": total, "high": high, "medium": medium, "low": low},
        "high_priority_changes": [c for c in changes if c["severity"] == "high"],
        "all_changes": changes,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prev", required=True)
    p.add_argument("--curr", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))
    curr = json.loads(Path(args.curr).read_text(encoding="utf-8"))
    result = diff_snapshots(prev, curr)
    txt = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(txt, encoding="utf-8")
        print(json.dumps({"saved": args.out, "summary": result["summary"]}))
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
