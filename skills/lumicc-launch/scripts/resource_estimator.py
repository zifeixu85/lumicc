#!/usr/bin/env python3
"""Cold-start resource feasibility estimator.

Given budget and hours-per-week, classify into Lean / Standard / Comfortable
and emit a recommendations JSON.

Usage:
    python3 resource_estimator.py --budget 1800 --hours-per-week 12 [--tiktok-accounts 1]
"""
from __future__ import annotations

import argparse
import json
import sys


TIERS = [
    # (max_budget_usd, max_hours_week, label)
    (700, 10, "Lean"),
    (2500, 18, "Standard"),
    (10000, 40, "Comfortable"),
]


def classify(budget: float, hours_week: float) -> str:
    for max_b, max_h, label in TIERS:
        if budget <= max_b and hours_week <= max_h:
            return label
    return "Comfortable"


def recommend(budget: float, hours_week: float, tiktok_accounts: int) -> dict:
    tier = classify(budget, hours_week)

    issues: list[str] = []
    actions: list[str] = []

    if budget < 400:
        issues.append("Budget below recommended floor ($400). Validation risk is high.")
        actions.append("Use dropship-only model (no inventory). See lumicc-expand for low-cost suppliers.")
    if hours_week < 8:
        issues.append("Fewer than 8 hours/week is too lean for full 30-day SOP.")
        actions.append("Halve catalog to 1-2 SKUs and reduce content cadence to 1/week.")
    if tiktok_accounts == 0:
        issues.append("No TikTok account.")
        actions.append("Register and warm up an account for at least 7 days before commercial posts.")

    # Estimate first-sale probability rough heuristic
    score = 0
    score += 2 if budget >= 1500 else 1 if budget >= 700 else 0
    score += 2 if hours_week >= 15 else 1 if hours_week >= 8 else 0
    score += 1 if tiktok_accounts >= 1 else 0
    probability = {0: "<10%", 1: "~15%", 2: "~30%", 3: "~50%", 4: "~70%", 5: "~85%"}.get(score, "?")

    return {
        "tier": tier,
        "first_sale_in_30d_probability": probability,
        "issues": issues,
        "recommended_actions": actions,
        "next_step": "Confirm 3 SKUs from lumicc-expand or jungle-scout shortlist before week 2.",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--budget", type=float, required=True)
    p.add_argument("--hours-per-week", type=float, required=True)
    p.add_argument("--tiktok-accounts", type=int, default=1)
    args = p.parse_args()
    out = recommend(args.budget, args.hours_per_week, args.tiktok_accounts)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
