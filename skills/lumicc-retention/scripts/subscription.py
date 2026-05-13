#!/usr/bin/env python3
"""Subscription-opportunity scanner — find SKUs that should be sold as subscriptions.

Rule of thumb: a SKU is a subscription candidate if:
- ≥ 5 customers bought it
- ≥ 20% of those customers bought it again within 90 days
- Mean repurchase interval is < 90 days (regular cadence)
"""
from __future__ import annotations

from statistics import mean, median


def analyze(orders: list[dict], min_repeat_rate: float = 0.20,
            min_buyers: int = 5, max_interval_days: int = 90) -> list[dict]:
    """Analyze orders to find SKUs with subscription potential.

    `orders`: list of {customer_id, order_date, skus} dicts.
    """
    # Per SKU per customer: list of order dates
    sku_cust_dates: dict[str, dict[str, list]] = {}
    for o in orders:
        for sku in o["skus"]:
            sku_cust_dates.setdefault(sku, {}).setdefault(o["customer_id"], []).append(o["order_date"])

    candidates: list[dict] = []
    for sku, cust_map in sku_cust_dates.items():
        buyers = len(cust_map)
        if buyers < min_buyers:
            continue
        repeat_buyers = 0
        intervals_days: list[int] = []
        for dates in cust_map.values():
            if len(dates) < 2:
                continue
            dates_sorted = sorted(dates)
            # Did they buy again within 90 days?
            for i in range(1, len(dates_sorted)):
                delta = (dates_sorted[i] - dates_sorted[i - 1]).days
                intervals_days.append(delta)
            # Count this customer as repeater if any interval ≤ max
            if any((dates_sorted[i] - dates_sorted[i - 1]).days <= max_interval_days
                   for i in range(1, len(dates_sorted))):
                repeat_buyers += 1

        repeat_rate = repeat_buyers / buyers
        if repeat_rate < min_repeat_rate:
            continue

        if not intervals_days:
            continue

        mean_interval = mean(intervals_days)
        median_interval = median(intervals_days)

        # Subscription candidates: repurchase happens regularly
        if median_interval > max_interval_days:
            continue

        # Score: balance of repeat rate × cadence regularity
        cadence_stability = 1.0 - min(1.0, abs(mean_interval - median_interval) / max(1, median_interval))
        score = repeat_rate * 0.5 + cadence_stability * 0.3 + (1 - median_interval / 365) * 0.2

        candidates.append({
            "sku": sku,
            "buyers": buyers,
            "repeat_buyers": repeat_buyers,
            "repeat_rate": round(repeat_rate, 3),
            "mean_interval_days": round(mean_interval, 1),
            "median_interval_days": round(median_interval, 1),
            "cadence_stability": round(cadence_stability, 3),
            "score": round(score, 3),
            "suggested_subscription_interval_days": int(round(median_interval)),
        })
    candidates.sort(key=lambda x: -x["score"])
    return candidates


def render_report_md(candidates: list[dict]) -> str:
    if not candidates:
        return "_未发现明显的订阅化候选 SKU。_\n\n建议：跑过 3-6 个月订单数据后再分析。"
    lines = [f"# 订阅化机会扫描 ({len(candidates)} 个候选)", ""]
    lines.append("**判定规则**: ≥5 个买家 · ≥20% 90 天内复购 · 中位复购间隔 ≤90 天")
    lines.append("")
    lines.append("| SKU | 买家 | 复购率 | 中位间隔 | 建议订阅周期 | 推荐分 |")
    lines.append("|-----|------|--------|----------|----------------|---------|")
    for c in candidates[:15]:
        lines.append(
            f"| `{c['sku']}` | {c['buyers']} | {c['repeat_rate']*100:.1f}% | "
            f"{c['median_interval_days']} 天 | 每 {c['suggested_subscription_interval_days']} 天 | "
            f"{c['score']:.2f} |"
        )
    lines.append("")
    if candidates:
        top = candidates[0]
        lines.append("## 优先行动")
        lines.append(f"- 🎯 **`{top['sku']}`** 是最强的订阅候选 — 复购率 {top['repeat_rate']*100:.1f}%，"
                     f"建议设置 **{top['suggested_subscription_interval_days']} 天订阅**（中位间隔）。")
        lines.append(f"- 推荐折扣：订阅 8-12% off 比一次性购买便宜 → 锁定 LTV 同时降低 CAC。")
        lines.append(f"- 工具建议：Shopify 用 ReCharge / Bold Subscriptions / Loop。")
    return "\n".join(lines)
