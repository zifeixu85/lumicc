#!/usr/bin/env python3
"""Cluster review/ticket/return text into VoC themes — keyword-based fallback.

Pure stdlib. When an embedding adapter is configured (future), a richer mode
in run.py uses semantic similarity; this fallback uses the keyword groups in
references/cluster-keywords.md.

Each input item: {"text": str, "sku": str?, "source": str?, "ts": int?}
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

# Cluster keyword tables (EN + CN). Order = priority on tie.
CLUSTERS = [
    ("packaging_damage", ["broken", "damaged", "crushed", "dented", "leaked", "smashed", "torn", "破损", "压坏", "漏", "撞坏", "凹陷"]),
    ("size_mismatch", ["too small", "too big", "wrong size", "doesn't fit", "smaller than expected", "太小", "太大", "尺寸不对", "偏小", "偏大"]),
    ("quality_issue", ["cheap", "flimsy", "fell apart", "low quality", "poor build", "质量差", "易坏", "做工差"]),
    ("delivery_late", ["late", "slow", "took weeks", "never arrived", "lost", "慢", "迟到", "没收到"]),
    ("not_as_described", ["misleading", "photos lie", "different color", "fake", "与图不符", "货不对板", "颜色不同"]),
    ("instructions_missing", ["confusing", "no manual", "hard to use", "instructions", "说明书没有", "不会用", "复杂"]),
    ("compatibility", ["doesn't work with", "incompatible", "not suitable", "不兼容", "不适配"]),
    ("smell_taste", ["smell", "odor", "plastic smell", "chemical", "味道", "异味", "化学味"]),
    ("customer_service", ["rude", "no response", "refund refused", "客服", "退款", "售后"]),
    ("value_for_money", ["overpriced", "not worth", "too expensive", "贵", "不值", "性价比低"]),
]


@dataclass(frozen=True)
class ClusterResult:
    topic: str
    size: int
    products_affected: list
    exemplars: list
    recency_score: float


def _match(text: str) -> str | None:
    text_l = (text or "").lower()
    for topic, kws in CLUSTERS:
        for kw in kws:
            if kw.lower() in text_l:
                return topic
    return None


def cluster(items: list[dict]) -> list[dict]:
    """Group items by topic; ignore items that don't match any cluster.

    Returns sorted by (recency-weighted) size descending.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    unmatched = []
    for it in items:
        topic = _match(it.get("text", ""))
        if topic:
            buckets[topic].append(it)
        else:
            unmatched.append(it)

    import time as _t
    now = _t.time()
    out: list[dict] = []
    for topic, hits in buckets.items():
        products = sorted({h.get("sku") for h in hits if h.get("sku")})
        exemplars = [h.get("text", "")[:140] for h in hits[:3]]
        # Recency boost: items within 14 days weighted 1.5x
        rec_weight = sum(1.5 if (h.get("ts") and (now - h["ts"]) < 14 * 86400) else 1.0 for h in hits)
        out.append({
            "topic": topic,
            "size": len(hits),
            "products_affected": list(products),
            "exemplars": exemplars,
            "recency_weighted_size": round(rec_weight, 2),
        })
    out.sort(key=lambda x: -x["recency_weighted_size"])
    return out


# Fix templates per cluster
FIX_TEMPLATES = {
    "packaging_damage": [
        ("operation", "Ask supplier to add corner protectors / bubble wrap"),
        ("listing_edit", "Add 'Heavy-duty packaging' to bullets"),
    ],
    "size_mismatch": [
        ("listing_edit", "Add scale/size reference image as image #4"),
        ("listing_edit", "Fix size chart with explicit dimensions and weight"),
    ],
    "quality_issue": [
        ("supplier", "Issue quality complaint to supplier; request samples from a backup"),
        ("listing_edit", "Add transparency: materials section + warranty terms"),
    ],
    "delivery_late": [
        ("operation", "Offer ePacket+ or DHL eCommerce as paid option"),
        ("listing_edit", "Show explicit ETA based on destination market"),
    ],
    "not_as_described": [
        ("listing_edit", "Replace stock images with shot-on-actual-product photos"),
        ("listing_edit", "Rewrite description: remove any aspirational claim not verifiable"),
    ],
    "instructions_missing": [
        ("operation", "Create 1-page PDF + 30-sec video; add QR on packaging"),
        ("listing_edit", "Embed video on product page"),
    ],
    "compatibility": [
        ("listing_edit", "Add a compatibility table (works with X, Y; NOT with Z)"),
    ],
    "smell_taste": [
        ("supplier", "Request alternative material from supplier; air-out before shipping"),
    ],
    "customer_service": [
        ("operation", "Define SLA: respond within 24h; refund decision within 48h"),
    ],
    "value_for_money": [
        ("operation", "A/B test a value bundle (product + accessory) at higher AOV"),
        ("listing_edit", "Add value-add bullets: warranty, support, free returns"),
    ],
}


def propose_fixes(clusters: list[dict]) -> list[dict]:
    out = []
    for c in clusters:
        fixes = [{"type": ftype, "detail": detail} for ftype, detail in FIX_TEMPLATES.get(c["topic"], [])]
        out.append({**c, "proposed_fixes": fixes})
    return out
