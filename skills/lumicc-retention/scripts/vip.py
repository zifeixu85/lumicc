#!/usr/bin/env python3
"""VIP customer engine — top X% by lifetime spend + 1-on-1 outreach drafts.

VIPs deserve human attention, not generic email blasts. We generate
personalized outreach drafts the founder/manager reviews & sends.
"""
from __future__ import annotations


def find_vips(classified: list[dict], top_percent: float = 5.0) -> list[dict]:
    """Take top X% of customers by LTV."""
    if not classified:
        return []
    n = max(1, int(len(classified) * top_percent / 100.0))
    return classified[:n]  # classified is pre-sorted by LTV desc in rfm.py


def draft_outreach(customer: dict, store_name: str | None = None) -> dict:
    """Per-customer personalized outreach. Tone: founder-to-customer, not marketing-team."""
    skus = customer.get("skus_purchased") or []
    unique_skus = sorted(set(skus))
    sku_clause = (
        f"You've bought `{unique_skus[0]}`" if len(unique_skus) == 1
        else f"You've bought `{unique_skus[0]}` and {len(unique_skus)-1} other items" if unique_skus
        else "You've supported us across multiple orders"
    )
    body = f"""Hi,

I run {store_name or 'this store'} and I noticed you're one of our top customers — **{customer['frequency']} orders, ${customer['ltv_usd']:,.2f} total**. {sku_clause}, and I genuinely wanted to say thank you.

Two things:

**1. Anything we should fix?** You've had more touchpoints with us than most. If anything has bothered you — packaging, shipping, product quality — reply and tell me. I read every word.

**2. Want early access?** We're working on {unique_skus[0] + ' v2' if unique_skus else 'something new'}. I'd love your eyes on it before public launch. Reply "I'm in" and I'll add you to the beta list.

Thanks again,
— [Your name]
Founder, {store_name or 'the store'}"""
    return {
        "subject": "A personal note",
        "preview": "Genuinely just saying thanks…",
        "body_md": body,
        "to_email_masked": _mask(customer.get("email")),
        "customer_id": customer["customer_id"],
        "ltv_usd": customer["ltv_usd"],
        "segment": customer["segment"],
        "send_time_hint": "Send manually from a real person; never automate",
    }


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    if len(local) <= 4:
        return f"{local[:1]}***@{domain}"
    return f"{local[:1]}***{local[-2:]}@{domain}"


def render_report_md(vips: list[dict], drafts: list[dict]) -> str:
    if not vips:
        return "_未发现 VIP 客户。_"
    total_vip_ltv = sum(v["ltv_usd"] for v in vips)
    lines = [f"# VIP 客户清单 (top {len(vips)} 位)", ""]
    lines.append(f"**总 LTV**: ${total_vip_ltv:,.2f} · "
                 f"**平均 LTV**: ${total_vip_ltv/len(vips):,.2f}")
    lines.append("")
    lines.append("| # | 客户 | 单数 | 总消费 | RFM | 分群 |")
    lines.append("|---|------|------|--------|-----|------|")
    for i, v in enumerate(vips, 1):
        lines.append(f"| {i} | {_mask(v.get('email'))} | {v['frequency']} | "
                     f"${v['ltv_usd']:,.2f} | {v['rfm_code']} | {v['icon']} {v['segment']} |")
    lines.append("")
    lines.append("## 1-on-1 外联草稿（创始人手动发送）")
    lines.append("")
    for d in drafts[:5]:
        lines.append(f"### {d['to_email_masked']} · LTV ${d['ltv_usd']}")
        lines.append(f"- **Subject**: {d['subject']}")
        lines.append("")
        lines.append("```")
        lines.append(d["body_md"])
        lines.append("```")
        lines.append("")
    if len(drafts) > 5:
        lines.append(f"...还有 {len(drafts) - 5} 位 VIP 的草稿在完整 JSON。")
    return "\n".join(lines)
