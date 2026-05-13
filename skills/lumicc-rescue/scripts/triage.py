#!/usr/bin/env python3
"""3-question triage tree for crisis response.

Pure decision logic. Inputs are explicit answers to 3 binary/categorical
questions; output is a hypothesis branch + confidence + recommended playbook.

This is the rule-based diagnostic engine. The run.py orchestrator wraps it
with data collection (recent changes, account warnings) and notification.
"""
from __future__ import annotations

from dataclasses import dataclass

# Branch definitions: (branch_id, hypothesis, typical_resolution, playbook_file)
BRANCHES = {
    "A": ("account_warning",   "Account health drop / suspension imminent",  "2-7 days",  "account-warning"),
    "B": ("ad_disapproval",    "Ad creative or policy rejection",            "1-3 days",  "ad-disapproval"),
    "C": ("listing_suppression", "Listing/ASIN suppressed by platform",      "1-14 days", "listing-suppression"),
    "D": ("self_inflicted",    "Recent self-change caused the drop",         "hours",     "self-inflicted"),
    "E": ("price_war",         "Competitor undercut",                        "days",      "price-war"),
    "F": ("ecosystem_event",   "Platform-wide issue",                        "1-7 days",  "ecosystem"),
    "G": ("algorithm_shift",   "Organic algorithm change",                   "7-30 days", "algorithm-shift"),
    "H": ("other_platform_event", "Other platform notification",             "varies",    "other-platform"),
}

PLAYBOOKS = {
    "account-warning": [
        "Open the platform's Account Health page; screenshot every flagged metric.",
        "Identify the specific policy violation. Do NOT submit a generic appeal.",
        "Pause any related listings or ads while you investigate.",
        "Draft an appeal: acknowledge the issue, root cause, corrective actions, prevention plan.",
        "Submit the appeal; track every 24h. Escalate via account manager if available.",
    ],
    "ad-disapproval": [
        "Read the disapproval reason in the ad platform notification (don't guess).",
        "If creative: identify which element triggers the rejection (claim / image / text).",
        "Revise creative removing the trigger; preserve the hook.",
        "Resubmit. If rejected again, contact ad rep with original + revised side-by-side.",
        "Meanwhile, pause spend on the offending campaign; reallocate budget to organic.",
    ],
    "listing-suppression": [
        "Find the official suppression message (Amazon Variations / Account Health).",
        "Common causes: image quality, prohibited claims, brand authorization, duplicate listing.",
        "Fix the specific cause (don't just edit and resubmit).",
        "Request reinstatement with evidence of fix.",
        "If brand-related: check Brand Registry status.",
    ],
    "self-inflicted": [
        "Identify the change you made in the last 48h (price / listing / ad / inventory).",
        "REVERT the change immediately.",
        "Observe metrics for 24h after revert — sales should recover.",
        "If they recover: the change was the cause. Reintroduce the change in a small A/B test.",
        "If they don't recover within 48h: the change wasn't the only cause; re-triage.",
    ],
    "price-war": [
        "Run lumicc-watch on top 3 competitors; confirm undercut hypothesis.",
        "Decide: match price (margin hit), bundle (preserve AOV), or differentiate (value-add).",
        "Don't blanket-match — only match on the hero SKU; preserve margin on others.",
        "Track for 14 days; competitor may revert if they were testing.",
    ],
    "algorithm-shift": [
        "Check platform community forums for confirmation (Helium 10 / FBA Insiders / etc.).",
        "Audit listing quality: title, images, reviews, conversion rate.",
        "If algorithm change favors freshness: refresh content (new images, A+ content).",
        "If favors conversion: prioritize CR work via lumicc-listing audit.",
        "Be patient — algorithm shifts typically settle in 14-30 days.",
    ],
    "ecosystem": [
        "Check platform status page (status.shopify.com / Amazon Seller Forums).",
        "If platform-wide: wait, document impact, file claim for any lost revenue.",
        "Communicate to your customers if shipping/payment is affected.",
    ],
    "other-platform": [
        "Read the full notification — do not guess.",
        "Search the platform's Seller Help for the exact policy referenced.",
        "Take the action(s) the notification requests; do not over-engineer.",
    ],
}


@dataclass(frozen=True)
class TriageInput:
    """All three questions plus optional details."""
    platform_notification: str = "none"  # none | account_warning | ad_disapproval | listing_suppression | other
    recent_change_kind: str = "none"     # none | price | listing | ad | inventory
    scope: str = "store_wide"             # single_sku | store_wide


def diagnose(inp: TriageInput) -> dict:
    """Return {branch, hypothesis, confidence, alternatives, playbook, resolution_time}."""
    branch_id = None
    confidence = 0.7

    # Q1: platform notification dominates
    if inp.platform_notification == "account_warning":
        branch_id, confidence = "A", 0.92
    elif inp.platform_notification == "ad_disapproval":
        branch_id, confidence = "B", 0.92
    elif inp.platform_notification == "listing_suppression":
        branch_id, confidence = "C", 0.92
    elif inp.platform_notification == "other":
        branch_id, confidence = "H", 0.70
    # Q2: self-change in last 48h
    elif inp.recent_change_kind != "none":
        branch_id, confidence = "D", 0.85
    # Q3: scope determines external cause
    elif inp.scope == "single_sku":
        branch_id, confidence = "C", 0.55  # most likely a listing-level issue (sub-C)
    else:
        # store-wide, no signals — could be price war or algorithm shift
        branch_id, confidence = "E", 0.55  # default to price war (most actionable first)

    bid, hyp, res_time, pb = BRANCHES[branch_id]
    alternatives = []
    if branch_id == "E" and inp.scope == "store_wide":
        alternatives.append({"branch_id": "G", "hypothesis": BRANCHES["G"][1], "reason": "store-wide without competitor delta hints at algorithm"})
    if branch_id == "C" and inp.scope == "single_sku" and inp.platform_notification == "none":
        alternatives.append({"branch_id": "D", "hypothesis": BRANCHES["D"][1], "reason": "single-SKU could be self-inflicted listing edit you forgot"})
    if branch_id == "D":
        # Self-inflicted with no platform notice could still have crossover with crisis
        if inp.recent_change_kind == "ad":
            alternatives.append({"branch_id": "B", "hypothesis": BRANCHES["B"][1], "reason": "ad change may have hit disapproval pending"})

    return {
        "branch_id": branch_id, "branch_key": bid, "hypothesis": hyp,
        "confidence": confidence, "resolution_time": res_time,
        "playbook_id": pb, "playbook_steps": PLAYBOOKS.get(pb, []),
        "alternatives": alternatives,
    }
