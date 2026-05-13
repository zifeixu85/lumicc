#!/usr/bin/env python3
"""Winback engine — find 90-day inactive customers + generate email drafts.

Pulls customers from `classified` (RFM output) whose `recency_days >= threshold`
and segment is in (At Risk, Lost, Hibernating). Generates per-customer
1-on-1 outreach drafts the user reviews + sends manually via their ESP.
"""
from __future__ import annotations

from typing import Any


def find_eligible(classified: list[dict], days_inactive: int = 90) -> list[dict]:
    """Filter classified RFM customers to those needing winback."""
    eligible = []
    for c in classified:
        if c["recency_days"] >= days_inactive and c["segment"] in ("At Risk", "Lost", "Promising"):
            eligible.append(c)
    eligible.sort(key=lambda x: -x["ltv_usd"])
    return eligible


def draft_email(customer: dict, store_name: str | None = None,
                offer_code: str = "WB20", offer_pct: int = 20) -> dict:
    """Generate a per-customer winback email draft.

    Returns {subject, preview, body_md, send_time_hint}.
    """
    seg = customer["segment"]
    last_skus = customer.get("skus_purchased") or []
    # Take the user's last meaningfully-distinct SKU (last unique)
    last_sku = next((s for s in reversed(last_skus) if s), None)
    name_part = f"，{store_name or 'our store'}" if store_name else ""

    if seg == "At Risk":
        subject = "Did we do something wrong?"
        preview = "We noticed you haven't visited in a while…"
        body = f"""Hi there,

It's been **{customer['recency_days']} days** since your last order{name_part} — we miss you.

If anything about your previous experience could've been better, we'd love to hear it. Reply to this email; a real human reads every response.

As a thank-you for coming back, here's **{offer_pct}% off your next order**:

> **Code: {offer_code}** (valid 14 days)

{f"Your last purchase was `{last_sku}`. If you loved it, we have a few new SKUs you might enjoy too." if last_sku else ""}

— The team"""
        when = "Send within 24h"

    elif seg == "Lost":
        subject = "One last invitation — 30% off"
        preview = "We don't usually do this discount publicly…"
        body = f"""Hi,

We haven't seen you in {customer['recency_days']} days. Before we say goodbye, here's a one-time **30% off** code we don't share publicly:

> **Code: LAST30** (valid 7 days only)

If this isn't for you anymore, no worries — just reply with "unsubscribe" and we'll take you off the list permanently.

— The team"""
        when = "Send within 48h; do not retry"

    else:  # Promising
        subject = f"Quick check-in — anything we can help with?"
        preview = "Just a friendly hello…"
        body = f"""Hi,

It's been {customer['recency_days']} days since we last connected. Nothing pressing — just wanted to see if there's anything we can help you find.

If you'd like to browse what's new, here's a small **{offer_pct}% off** code valid for 14 days:

> **Code: {offer_code}**

— The team"""
        when = "Low priority; can batch"

    return {
        "subject": subject,
        "preview": preview,
        "body_md": body,
        "send_time_hint": when,
        "to_email_masked": _mask(customer.get("email")),
        "customer_id": customer["customer_id"],
        "segment": seg,
        "ltv_usd": customer["ltv_usd"],
    }


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    if len(local) <= 4:
        return f"{local[:1]}***@{domain}"
    return f"{local[:1]}***{local[-2:]}@{domain}"


def render_segment_csv(eligible: list[dict]) -> str:
    """Output CSV-format for direct upload to Klaviyo / Mailchimp."""
    lines = ["email,segment,recency_days,frequency,monetary_usd,ltv_usd,rfm_code"]
    for c in eligible:
        lines.append(",".join(str(x) for x in [
            c.get("email") or "",
            c["segment"], c["recency_days"], c["frequency"],
            c["monetary_usd"], c["ltv_usd"], c["rfm_code"],
        ]))
    return "\n".join(lines) + "\n"


def render_drafts_md(drafts: list[dict]) -> str:
    if not drafts:
        return "_未发现需要 winback 的客户。_"
    lines = [f"# Winback 邮件草稿 ({len(drafts)} 封)", ""]
    by_seg: dict[str, list[dict]] = {}
    for d in drafts:
        by_seg.setdefault(d["segment"], []).append(d)
    for seg in ["At Risk", "Lost", "Promising"]:
        items = by_seg.get(seg, [])
        if not items:
            continue
        lines.append(f"\n## {seg} ({len(items)})\n")
        for d in items[:5]:  # show first 5 per segment as samples
            lines.append(f"### 📧 {d['to_email_masked']} · LTV ${d['ltv_usd']}")
            lines.append(f"- **Send**: {d['send_time_hint']}")
            lines.append(f"- **Subject**: {d['subject']}")
            lines.append(f"- **Preview**: {d['preview']}")
            lines.append("")
            lines.append("```")
            lines.append(d["body_md"])
            lines.append("```")
            lines.append("")
        if len(items) > 5:
            lines.append(f"...还有 {len(items) - 5} 封 — 见 CSV 导出")
    return "\n".join(lines)
