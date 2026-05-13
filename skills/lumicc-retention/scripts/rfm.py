#!/usr/bin/env python3
"""RFM (Recency × Frequency × Monetary) scoring + 6-segment classification.

Per-customer compute:
  R = days since last order (smaller = better → quintile 5)
  F = order count (higher = better → quintile 5)
  M = total spent (higher = better → quintile 5)

Quintile via numpy-style percentile cuts (pure Python, no numpy dep).

Segment mapping:
  Champions      R≥4, F≥4, M≥4
  Loyal          F≥3, M≥3 AND R≥3 (not Champion)
  New            R≥4, F≤2
  At Risk        R≤2, F≥3, M≥3
  Lost           R=1, F≤2, M≤2
  Promising      everyone else
"""
from __future__ import annotations

import datetime
from typing import Any

SEGMENTS = ("Champions", "Loyal", "New", "At Risk", "Lost", "Promising")
SEGMENT_ICON = {
    "Champions": "🏆", "Loyal": "💚", "New": "🌱",
    "At Risk": "🔥", "Lost": "💔", "Promising": "🟡",
}


def quintile(values: list[float], higher_is_better: bool = True) -> list[int]:
    """Assign each value a quintile (1-5). The BEST values get 5.

    If `higher_is_better=True` (e.g., F, M): larger value → quintile 5.
    If `higher_is_better=False` (e.g., R): smaller value → quintile 5.

    Pure stdlib via sort + index buckets. Handles small N gracefully.
    """
    n = len(values)
    if n == 0:
        return []
    # Sort so the "best" values come first (rank 0)
    indexed = sorted(range(n), key=lambda i: values[i], reverse=higher_is_better)
    quintiles = [0] * n
    for rank, orig_idx in enumerate(indexed):
        # rank 0 = best → q=5; rank n-1 = worst → q=1
        q = 5 - min(4, rank * 5 // max(1, n))
        quintiles[orig_idx] = q
    return quintiles


def assign_segment(r: int, f: int, m: int) -> str:
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r <= 2 and f >= 3 and m >= 3:
        return "At Risk"
    if r == 1 and f <= 2 and m <= 2:
        return "Lost"
    if r >= 4 and f <= 2:
        return "New"
    if r >= 3 and f >= 3 and m >= 3:
        return "Loyal"
    return "Promising"


def classify(customers: dict[str, dict], today: datetime.date | None = None) -> list[dict]:
    """Classify all customers. Returns a list of segment-annotated dicts.

    `customers` is the output of csv_parser.aggregate_by_customer().
    """
    today = today or datetime.date.today()
    if not customers:
        return []
    cust_list = list(customers.values())

    # Compute raw R, F, M
    raw_r = [(today - c["last_order_date"]).days for c in cust_list]
    raw_f = [c["order_count"] for c in cust_list]
    raw_m = [c["total_spent"] for c in cust_list]

    # Quintile each: smaller recency = better; larger F & M = better
    r_q = quintile(raw_r, higher_is_better=False)
    f_q = quintile(raw_f, higher_is_better=True)
    m_q = quintile(raw_m, higher_is_better=True)

    out: list[dict] = []
    for i, c in enumerate(cust_list):
        seg = assign_segment(r_q[i], f_q[i], m_q[i])
        ltv = c["total_spent"]  # crude LTV = total spent (real LTV would predict future)
        out.append({
            "customer_id": c["customer_id"],
            "email": c.get("email"),
            "recency_days": raw_r[i],
            "frequency": raw_f[i],
            "monetary_usd": round(raw_m[i], 2),
            "ltv_usd": round(ltv, 2),
            "r_score": r_q[i],
            "f_score": f_q[i],
            "m_score": m_q[i],
            "rfm_code": f"{r_q[i]}{f_q[i]}{m_q[i]}",
            "segment": seg,
            "icon": SEGMENT_ICON[seg],
            "first_order_date": c["first_order_date"].isoformat(),
            "last_order_date": c["last_order_date"].isoformat(),
            "skus_purchased": c["skus_purchased"],
        })
    out.sort(key=lambda x: -x["ltv_usd"])
    return out


def segment_summary(classified: list[dict]) -> dict:
    """Aggregate stats per segment."""
    by_seg: dict[str, list[dict]] = {}
    for c in classified:
        by_seg.setdefault(c["segment"], []).append(c)
    summary: dict = {}
    for seg in SEGMENTS:
        items = by_seg.get(seg, [])
        if not items:
            summary[seg] = {"count": 0, "total_ltv": 0, "avg_ltv": 0, "share": 0}
            continue
        total_ltv = sum(c["ltv_usd"] for c in items)
        summary[seg] = {
            "count": len(items),
            "total_ltv": round(total_ltv, 2),
            "avg_ltv": round(total_ltv / len(items), 2),
            "share": round(len(items) / max(1, len(classified)), 3),
        }
    return summary


def render_report_md(classified: list[dict]) -> str:
    if not classified:
        return "_未找到客户数据。_"
    summ = segment_summary(classified)
    total = len(classified)
    total_ltv = sum(c["ltv_usd"] for c in classified)
    lines = ["# RFM 客户分群报告", ""]
    lines.append(f"**总客户**: {total} · **总 LTV**: ${total_ltv:,.2f} · **平均 LTV**: ${total_ltv/total:,.2f}")
    lines.append("")
    lines.append("| 分群 | 数量 | 占比 | 总 LTV | 平均 LTV |")
    lines.append("|------|------|------|--------|----------|")
    for seg in SEGMENTS:
        s = summ[seg]
        icon = SEGMENT_ICON[seg]
        lines.append(f"| {icon} {seg} | {s['count']} | {s['share']*100:.1f}% | ${s['total_ltv']:,.2f} | ${s['avg_ltv']:,.2f} |")
    lines.append("")
    lines.append("## Top 10 客户（按 LTV）")
    lines.append("")
    from csv_parser import mask_email
    for c in classified[:10]:
        lines.append(
            f"- {c['icon']} **{mask_email(c['email'])}** — "
            f"${c['ltv_usd']:,.2f} · {c['frequency']} 单 · 上次 {c['recency_days']} 天前 · "
            f"RFM {c['rfm_code']} ({c['segment']})"
        )
    return "\n".join(lines)
