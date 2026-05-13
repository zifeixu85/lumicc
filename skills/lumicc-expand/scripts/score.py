#!/usr/bin/env python3
"""5-factor candidate SKU scorer.

Implements the rubric in references/scoring-matrix.md as pure functions.
Each candidate dict feeds in; a scored copy with `total`, per-factor scores,
and an action tag comes out.

Used both as a library (imported by run.py) and as a CLI for manual scoring.

Usage:
    python3 score.py < candidate.json > scored.json
    python3 score.py --batch candidates.json --out scored.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Default factor weights (sum = 1.0). Override via preferences['expansion_weights'].
DEFAULT_WEIGHTS = {
    "margin": 0.25,
    "demand": 0.25,
    "content": 0.20,
    "supplier": 0.15,
    "fulfillment": 0.15,
}


# ---------- Per-factor scoring ----------
def score_margin(landed_cost: float, retail_price: float, soul_min_margin: float = 0.0) -> tuple[float, str]:
    """Return (0-10 score, evidence string). Auto-fails below SOUL minimum."""
    if not retail_price or retail_price <= 0:
        return 0.0, "no retail price"
    margin_pct = 1.0 - (landed_cost / retail_price)
    if margin_pct < soul_min_margin:
        return 0.0, f"margin {margin_pct:.0%} below SOUL minimum {soul_min_margin:.0%}"
    if margin_pct >= 0.75:
        return 10.0, f"{margin_pct:.0%} margin (excellent)"
    if margin_pct >= 0.65:
        return 8.0, f"{margin_pct:.0%} margin (good)"
    if margin_pct >= 0.50:
        return 6.0, f"{margin_pct:.0%} margin (acceptable)"
    if margin_pct >= 0.35:
        return 4.0, f"{margin_pct:.0%} margin (thin)"
    if margin_pct >= 0.20:
        return 2.0, f"{margin_pct:.0%} margin (very thin)"
    return 1.0, f"{margin_pct:.0%} margin (red flag)"


def score_demand(signals: dict) -> tuple[float, str]:
    """Combine 3 sub-signals: amazon_revenue_yoy_pct, tiktok_hashtag_growth_pct, google_trends_slope.
    Each contributes ~3.3 max."""
    score = 0.0
    parts: list[str] = []
    yoy = signals.get("amazon_revenue_yoy_pct")
    if yoy is not None:
        s = max(0.0, min(3.3, yoy / 10.0 * 1.0))
        score += s
        parts.append(f"Amazon YoY {yoy:+.0%}={s:.1f}")
    tt = signals.get("tiktok_hashtag_growth_pct")
    if tt is not None:
        s = max(0.0, min(3.3, tt / 25.0 * 1.0))
        score += s
        parts.append(f"TikTok 90d {tt:+.0%}={s:.1f}")
    gt = signals.get("google_trends_slope")
    if gt is not None:
        s = max(0.0, min(3.3, gt / 10.0 * 1.0))
        score += s
        parts.append(f"Trends slope {gt:+.0f}={s:.1f}")
    if not parts:
        return 5.0, "no demand signals provided — neutral default"
    return min(10.0, score), "; ".join(parts)


def score_content(angle: str | None, has_visual_hook: bool) -> tuple[float, str]:
    table = {
        "before_after": (10.0, "strong visual hook (before/after)"),
        "transformation": (10.0, "strong visual hook (transformation)"),
        "unboxing_reveal": (10.0, "strong visual hook (unboxing reveal)"),
        "lifestyle": (8.0, "good lifestyle angle"),
        "aesthetic": (8.0, "aesthetic appeal"),
        "educational": (6.0, "educational/how-to angle"),
        "hack": (6.0, "hack/tip angle"),
        "generic": (4.0, "generic — creative work needed"),
        "difficult": (2.0, "difficult to show on video"),
    }
    if angle and angle in table:
        return table[angle]
    if has_visual_hook:
        return 7.0, "visual hook present (unclassified)"
    return 5.0, "no angle declared — neutral default"


def score_supplier(supplier: dict) -> tuple[float, str]:
    existing = bool(supplier.get("existing_relationship"))
    verified = bool(supplier.get("alibaba_verified") or supplier.get("verified"))
    moq = supplier.get("moq") or 0
    response_rate = supplier.get("response_rate") or 0
    has_sample = bool(supplier.get("sample_ordered"))
    if existing:
        return 10.0, "existing trusted supplier — add SKU on next order"
    if verified and response_rate >= 0.9 and moq <= 50:
        return 8.0, f"verified, fast response ({response_rate:.0%}), MOQ {moq}"
    if verified and moq <= 100:
        return 6.0, f"verified, MOQ {moq}"
    if has_sample:
        return 4.0, "untested supplier but sample on hand"
    if supplier.get("name"):
        return 3.0, "supplier known but not verified"
    return 0.0, "no supplier"


def score_fulfillment(profile: dict) -> tuple[float, str]:
    """Lower risk = higher score."""
    if profile.get("hazardous") or profile.get("trademarked"):
        return 0.0, "hazardous or trademarked — DO NOT proceed"
    if profile.get("battery") or profile.get("liquid"):
        return 4.0, "battery / liquid — restricted by some carriers"
    if profile.get("oversized") or (profile.get("weight_g") or 0) > 2000:
        return 6.0, "heavy/oversized — higher shipping cost"
    if profile.get("fragile"):
        return 8.0, "lightweight but fragile — needs packaging"
    return 10.0, "lightweight, durable, low-risk"


# ---------- Main scoring ----------
@dataclass(frozen=True)
class ScoredCandidate:
    rank: int
    title: str
    total: float
    factors: dict
    action: str
    reason: str
    raw: dict


def score_one(candidate: dict, soul_min_margin: float = 0.0,
              weights: dict | None = None) -> dict:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    margin_s, margin_ev = score_margin(
        landed_cost=candidate.get("landed_cost_usd") or 0,
        retail_price=candidate.get("suggested_retail_usd") or 0,
        soul_min_margin=soul_min_margin,
    )
    demand_s, demand_ev = score_demand(candidate.get("demand_signals") or {})
    content_s, content_ev = score_content(
        candidate.get("content_angle"), bool(candidate.get("has_visual_hook")),
    )
    supplier_s, supplier_ev = score_supplier(candidate.get("supplier") or {})
    fulfillment_s, fulfillment_ev = score_fulfillment(candidate.get("fulfillment") or {})

    total = (
        margin_s * w["margin"] + demand_s * w["demand"]
        + content_s * w["content"] + supplier_s * w["supplier"]
        + fulfillment_s * w["fulfillment"]
    )

    if margin_s == 0.0 and "SOUL" in margin_ev:
        action = "reject"
        reason = "below SOUL minimum margin"
    elif fulfillment_s == 0.0:
        action = "reject"
        reason = fulfillment_ev
    elif total >= 8.0:
        action = "order_sample"
        reason = "strong candidate"
    elif total >= 6.5:
        action = "watchlist"
        reason = "watchlist — order sample if budget allows"
    else:
        action = "reject"
        reason = f"total {total:.1f} below threshold 6.5"

    return {
        "title": candidate.get("title", "—"),
        "total": round(total, 2),
        "factors": {
            "margin": {"score": round(margin_s, 1), "weight": w["margin"], "evidence": margin_ev},
            "demand": {"score": round(demand_s, 1), "weight": w["demand"], "evidence": demand_ev},
            "content": {"score": round(content_s, 1), "weight": w["content"], "evidence": content_ev},
            "supplier": {"score": round(supplier_s, 1), "weight": w["supplier"], "evidence": supplier_ev},
            "fulfillment": {"score": round(fulfillment_s, 1), "weight": w["fulfillment"], "evidence": fulfillment_ev},
        },
        "action": action,
        "reason": reason,
        "raw": candidate,
    }


def rank(candidates: list[dict], **kw) -> list[dict]:
    scored = [score_one(c, **kw) for c in candidates]
    scored.sort(key=lambda x: -x["total"])
    for i, s in enumerate(scored, 1):
        s["rank"] = i
    return scored


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch", help="JSON file with a list of candidates")
    p.add_argument("--soul-min-margin", type=float, default=0.0)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    if args.batch:
        data = json.loads(Path(args.batch).read_text(encoding="utf-8"))
    else:
        data = json.loads(sys.stdin.read())
    if isinstance(data, dict):
        data = [data]
    out = rank(data, soul_min_margin=args.soul_min_margin)
    s = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(s, encoding="utf-8")
        print(json.dumps({"saved": args.out, "ranked": len(out)}))
    else:
        sys.stdout.write(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
