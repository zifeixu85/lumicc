#!/usr/bin/env python3
"""Gateway-SKU analysis: which first-purchase SKU has highest 2nd-purchase rate?

For each customer with ≥ 1 order, find their first-ever SKU; then for the
subset that placed a 2nd order, count what the 2nd-order SKUs were.

Outputs:
  - First-purchase SKU funnel: SKU → (1st-purchase customers, 2nd-purchase rate)
  - 2nd-purchase composition: SKU → most common 2nd-purchase SKU
"""
from __future__ import annotations


def analyze(orders: list[dict]) -> dict:
    """Compute gateway-SKU stats from raw orders (sorted or unsorted).

    `orders` is a list of {customer_id, order_date, skus} dicts.
    """
    by_cust: dict[str, list[dict]] = {}
    for o in orders:
        by_cust.setdefault(o["customer_id"], []).append(o)
    for orders_list in by_cust.values():
        orders_list.sort(key=lambda x: x["order_date"])

    first_sku_counts: dict[str, int] = {}
    repeat_after_first: dict[str, int] = {}
    second_sku_after: dict[str, dict[str, int]] = {}

    for cust_orders in by_cust.values():
        first_skus = cust_orders[0]["skus"]
        if not first_skus:
            continue
        # If first order has multiple SKUs, attribute to each (count once)
        seen_first: set[str] = set()
        for sku in first_skus:
            if sku in seen_first:
                continue
            seen_first.add(sku)
            first_sku_counts[sku] = first_sku_counts.get(sku, 0) + 1
            if len(cust_orders) >= 2:
                repeat_after_first[sku] = repeat_after_first.get(sku, 0) + 1
                # Count what they bought in 2nd order
                second_skus = cust_orders[1]["skus"]
                bucket = second_sku_after.setdefault(sku, {})
                for s2 in second_skus:
                    bucket[s2] = bucket.get(s2, 0) + 1

    funnel = []
    for sku, first_n in first_sku_counts.items():
        repeated = repeat_after_first.get(sku, 0)
        rate = repeated / first_n if first_n else 0
        # Top 2nd-purchase SKU
        bucket = second_sku_after.get(sku, {})
        top_2nd = sorted(bucket.items(), key=lambda x: -x[1])[:3]
        funnel.append({
            "first_sku": sku,
            "first_purchase_customers": first_n,
            "repeat_purchase_customers": repeated,
            "repeat_rate": round(rate, 3),
            "top_2nd_purchase_skus": [{"sku": s, "count": n} for s, n in top_2nd],
        })
    funnel.sort(key=lambda x: -x["repeat_rate"])

    return {
        "total_first_purchase_skus": len(first_sku_counts),
        "total_customers_analyzed": sum(first_sku_counts.values()),
        "overall_repeat_rate": round(
            sum(repeat_after_first.values()) / max(1, sum(first_sku_counts.values())), 3
        ),
        "funnel": funnel,
    }


def render_report_md(analysis: dict) -> str:
    if not analysis.get("funnel"):
        return "_无足够订单数据进行复购路径分析。_"
    lines = ["# 复购路径分析", ""]
    lines.append(f"**总首购 SKU**: {analysis['total_first_purchase_skus']} · "
                 f"**总客户**: {analysis['total_customers_analyzed']} · "
                 f"**整体复购率**: {analysis['overall_repeat_rate']*100:.1f}%")
    lines.append("")
    lines.append("## 首购 → 复购漏斗（按复购率排序）")
    lines.append("")
    lines.append("| 首购 SKU | 首购客户 | 复购客户 | 复购率 | Top 复购 SKU |")
    lines.append("|----------|----------|----------|--------|----------------|")
    for f in analysis["funnel"][:15]:
        top = ", ".join(f"`{x['sku']}`×{x['count']}" for x in f["top_2nd_purchase_skus"]) or "—"
        lines.append(f"| `{f['first_sku']}` | {f['first_purchase_customers']} | "
                     f"{f['repeat_purchase_customers']} | {f['repeat_rate']*100:.1f}% | {top} |")
    lines.append("")
    lines.append("## 洞察")
    top_gateway = analysis["funnel"][0] if analysis["funnel"] else None
    if top_gateway and top_gateway["repeat_rate"] > 0:
        lines.append(f"- 🎯 **最佳入门 SKU**: `{top_gateway['first_sku']}`，复购率 "
                     f"{top_gateway['repeat_rate']*100:.1f}%。建议给新客降价或主推此 SKU。")
        if top_gateway["top_2nd_purchase_skus"]:
            second = top_gateway["top_2nd_purchase_skus"][0]
            lines.append(f"- 🔁 **首选回购路径**: `{top_gateway['first_sku']}` → `{second['sku']}`。"
                         f"建议在首单确认邮件中推荐 `{second['sku']}`。")
    bad = [f for f in analysis["funnel"] if f["first_purchase_customers"] >= 5 and f["repeat_rate"] < 0.10]
    if bad:
        lines.append(f"- ⚠️ **复购率 < 10% 的 SKU**: {', '.join('`'+b['first_sku']+'`' for b in bad[:5])} "
                     f"→ 优先用 lumicc-voc 分析这些 SKU 的差评")
    return "\n".join(lines)
