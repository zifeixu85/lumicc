#!/usr/bin/env python3
"""Render lumicc-retention report.html — visual companion to markdown reports.

Visual differentiators:
  - RFM → 5×5 matrix heatmap (R quintile × F quintile, cell color = avg LTV)
  - Segment breakdown → KPI cards with counts + LTV share
  - VIP → individual cards with embedded 1-on-1 email drafts + copy
  - Winback → 3-tab UI (At Risk / Lost / Promising) with email drafts per card
  - Subscription candidates → cadence visualization cards
  - Repeat funnel → SKU-by-SKU sparklines
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


SEGMENT_COLORS = {
    "Champions": "emerald", "Loyal": "emerald", "New": "sky",
    "At Risk": "amber", "Lost": "rose", "Promising": "indigo",
}


# =============================================================================
# RFM 2D matrix
# =============================================================================
def render_rfm_matrix(classified: list[dict]) -> str:
    """5×5 grid: X = R quintile, Y = F quintile. Cell color = avg LTV in bucket."""
    if not classified:
        return H.empty_state("还没有 RFM 分群数据。")

    # Build 5×5 bucket
    buckets: dict[tuple[int, int], list[dict]] = {}
    for c in classified:
        key = (c["r_score"], c["f_score"])
        buckets.setdefault(key, []).append(c)

    # Find LTV scale for color mapping
    all_avg_ltv = [
        sum(x["ltv_usd"] for x in items) / len(items)
        for items in buckets.values() if items
    ]
    max_ltv = max(all_avg_ltv) if all_avg_ltv else 1
    min_ltv = min(all_avg_ltv) if all_avg_ltv else 0

    # Render grid (header row + 5 rows for F=5..1)
    cells: list[str] = []
    cells.append('<div class="axis-label">F →</div>')
    # Column headers (R=1..5)
    for r in range(1, 6):
        cells.append(f'<div class="axis-label">R={r}</div>')

    for f in range(5, 0, -1):
        cells.append(f'<div class="axis-label">F={f}</div>')
        for r in range(1, 6):
            items = buckets.get((r, f), [])
            n = len(items)
            avg_ltv = sum(x["ltv_usd"] for x in items) / n if items else 0

            if n == 0:
                cells.append(
                    '<div class="rfm-cell" style="background:var(--surface-2);'
                    'color:var(--ink-dim);"><div class="n">·</div></div>'
                )
                continue

            norm = (
                (avg_ltv - min_ltv) / max(0.001, max_ltv - min_ltv)
                if max_ltv > min_ltv else 0.5
            )
            pct = int((0.18 + norm * 0.72) * 100)
            cells.append(
                f'<div class="rfm-cell" style="background:color-mix(in srgb, var(--accent) {pct}%, transparent);" '
                f'title="R={r}, F={f}: {n} customers · avg LTV ${avg_ltv:.0f}">'
                f'<div class="n">{n}</div>'
                f'<div class="ltv">${avg_ltv:.0f}</div></div>'
            )

    matrix_html = f'<div class="rfm-matrix">{"".join(cells)}</div>'

    legend = (
        '<div style="display:flex;align-items:center;gap:12px;font-size:12px;color:var(--ink-muted);margin-top:8px;">'
        '<span>低 LTV</span>'
        '<div style="height:8px;width:120px;border-radius:4px;'
        'background:linear-gradient(90deg, color-mix(in srgb, var(--accent) 18%, transparent), color-mix(in srgb, var(--accent) 90%, transparent));"></div>'
        '<span>高 LTV</span>'
        '</div>'
    )

    return matrix_html + legend


# =============================================================================
# Segment KPI strip
# =============================================================================
def render_segment_kpis(classified: list[dict]) -> str:
    by_seg: dict[str, list[dict]] = {}
    for c in classified:
        by_seg.setdefault(c["segment"], []).append(c)

    total = len(classified)
    total_ltv = sum(c["ltv_usd"] for c in classified)

    segments_order = ["Champions", "Loyal", "New", "At Risk", "Lost", "Promising"]
    cards = []
    for seg in segments_order:
        items = by_seg.get(seg, [])
        if not items:
            continue
        seg_ltv = sum(c["ltv_usd"] for c in items)
        seg_pct = (seg_ltv / max(0.01, total_ltv)) * 100
        cards.append(H.kpi_card(
            value=len(items),
            label=f"{items[0].get('icon','')} {seg}",
            hint=f"${seg_ltv:,.0f} · {seg_pct:.0f}% LTV",
            color=SEGMENT_COLORS.get(seg, "zinc"),
        ))

    top_kpis = H.kpi_strip([
        (total, "总客户"),
        (H.fmt_currency(total_ltv), "总 LTV"),
        (H.fmt_currency(total_ltv / total) if total else "—", "平均 LTV"),
        (len(by_seg), "分群数"),
    ])

    return top_kpis + '<section class="kpi-grid">' + "".join(cards) + "</section>"


# =============================================================================
# VIP cards
# =============================================================================
def render_vip_cards(vips: list[dict], drafts: list[dict]) -> str:
    if not vips:
        return H.empty_state("还没有 VIP 客户。")

    cards = []
    drafts_by_id = {d["customer_id"]: d for d in drafts}
    for v in vips:
        d = drafts_by_id.get(v["customer_id"])
        body = (
            f'<div style="font-size:13px;color:var(--ink-muted);margin-bottom:8px;">'
            f'{v["frequency"]} 单 · 上次 {v["recency_days"]} 天前 · RFM {v["rfm_code"]}'
            f'</div>'
            f'<div style="font-size:18px;font-weight:700;color:var(--ink);margin-bottom:8px;">'
            f'{H.fmt_currency(v["ltv_usd"])}</div>'
        )
        if d:
            body += (
                f'<div style="margin-top:10px;"><b style="font-size:12px;color:var(--ink-muted);">'
                f'1-on-1 草稿（创始人手发）</b></div>'
                f'<pre style="max-height:140px;font-size:11px;margin-top:6px;">'
                f'{H.esc(d["body_md"])}</pre>'
            )
        actions = []
        if d:
            actions.append(H.copy_button(d["body_md"], "📋 复制邮件"))
        cards.append(H.card(
            title=_mask_email(v.get("email")),
            tag=v["segment"], tag_color=SEGMENT_COLORS.get(v["segment"], "zinc"),
            body=body, actions=actions,
        ))
    return H.card_grid(cards, min_width=320)


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    if len(local) <= 4:
        return f"{local[:1]}***@{domain}"
    return f"{local[:1]}***{local[-2:]}@{domain}"


# =============================================================================
# Winback drafts tabs
# =============================================================================
def render_winback_tabs(drafts: list[dict]) -> str:
    if not drafts:
        return H.empty_state("没有需要 winback 的客户。")

    by_seg: dict[str, list[dict]] = {}
    for d in drafts:
        by_seg.setdefault(d["segment"], []).append(d)

    tab_defs: list[tuple[str, str, str]] = []
    for seg in ["At Risk", "Lost", "Promising"]:
        items = by_seg.get(seg, [])
        if not items:
            continue
        cards = []
        for d in items:
            body = (
                f'<div style="font-size:12px;color:var(--ink-muted);margin-bottom:8px;">'
                f'LTV {H.fmt_currency(d["ltv_usd"])} · {H.esc(d["send_time_hint"])}</div>'
                f'<div style="font-weight:500;color:var(--ink);margin-bottom:4px;">'
                f'{H.esc(d["subject"])}</div>'
                f'<div style="font-size:12px;color:var(--ink-muted);margin-bottom:6px;">'
                f'{H.esc(d["preview"])}</div>'
                f'<pre style="max-height:160px;font-size:11px;">{H.esc(d["body_md"])}</pre>'
            )
            cards.append(H.card(
                title=d["to_email_masked"],
                tag=seg, tag_color=SEGMENT_COLORS.get(seg, "zinc"),
                body=body,
                actions=[H.copy_button(d["body_md"], "📋 复制邮件正文")],
            ))
        tab_defs.append((
            seg.replace(" ", "_").lower(),
            f"{seg} ({len(items)})",
            H.card_grid(cards, min_width=320),
        ))

    return H.tabs(tab_defs) if tab_defs else H.empty_state("没有 winback 草稿。")


# =============================================================================
# Subscription cadence cards
# =============================================================================
def render_subscription_cards(candidates: list[dict]) -> str:
    if not candidates:
        return H.empty_state("还没有订阅化候选 SKU。",
                              "用 ≥ 3 个月订单数据再跑一次")

    cards = []
    for c in candidates:
        # Visualize cadence as a horizontal bar with markers
        median = c.get("median_interval_days", 30)
        # Show a 90-day axis with markers every {median} days
        markers = []
        for d in range(0, 91, max(1, int(median))):
            pct = (d / 90) * 100
            markers.append(
                f'<div style="position:absolute;left:{pct:.1f}%;top:0;'
                f'width:2px;height:100%;background:var(--accent);"></div>'
            )
        viz = (
            f'<div style="position:relative;height:24px;background:var(--surface-2);'
            f'border-radius:4px;margin:8px 0;overflow:hidden;">'
            f'{"".join(markers)}'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;font-family:var(--mono);'
            f'font-size:10px;color:var(--ink-dim);">'
            f'<span>0d</span><span>30d</span><span>60d</span><span>90d</span></div>'
        )
        body = (
            f'<div style="margin-bottom:8px;">'
            f'<b style="color:var(--ink);">{c["buyers"]} 个买家</b> · '
            f'<span style="color:var(--accent-soft)">{c["repeat_rate"]*100:.0f}% 复购</span>'
            f'</div>'
            f'<div style="font-size:12px;color:var(--ink-muted);">中位间隔 '
            f'{c["median_interval_days"]} 天 · 推荐分 {c["score"]:.2f}</div>'
            f'{viz}'
            f'<div style="font-size:13px;color:var(--accent-soft);margin-top:8px;">'
            f'建议订阅周期：每 <b>{c["suggested_subscription_interval_days"]}</b> 天 '
            f'(8-12% off)</div>'
        )
        cards.append(H.card(
            title=c["sku"], tag="订阅候选", tag_color="emerald",
            body=body,
        ))
    return H.card_grid(cards, min_width=300)


# =============================================================================
# Repeat funnel
# =============================================================================
def render_repeat_funnel(analysis: dict) -> str:
    funnel = analysis.get("funnel") or []
    if not funnel:
        return H.empty_state("无足够订单数据。")

    kpis = H.kpi_strip([
        (analysis.get("total_first_purchase_skus", 0), "首购 SKU 数"),
        (analysis.get("total_customers_analyzed", 0), "分析客户数"),
        (
            f'{analysis.get("overall_repeat_rate", 0) * 100:.1f}%',
            "整体复购率",
            "首单 → 复购",
            "emerald" if analysis.get("overall_repeat_rate", 0) > 0.15 else "amber",
        ),
    ])

    rows = []
    for f in funnel[:15]:
        top_2nd = ", ".join(
            f'<code>{H.esc(x["sku"])}</code>×{x["count"]}'
            for x in f.get("top_2nd_purchase_skus", [])[:3]
        ) or "—"
        rate_color = "emerald" if f["repeat_rate"] > 0.20 else "amber" if f["repeat_rate"] > 0.10 else "rose"
        rows.append([
            f'<code>{H.esc(f["first_sku"])}</code>',
            f["first_purchase_customers"],
            f["repeat_purchase_customers"],
            H.badge(f'{f["repeat_rate"]*100:.1f}%', rate_color),
            top_2nd,
        ])

    funnel_table = H.table(
        ["首购 SKU", "首购客户", "复购客户", "复购率", "Top 复购 SKU"],
        rows,
        align=["left", "right", "right", "center", "left"],
    )

    return kpis + H.section("首购 → 复购 漏斗", funnel_table)


# =============================================================================
# Master render
# =============================================================================
def render_page(*, run_id: str, mode: str, store_name: str,
                metrics: dict, deliverables: list[dict],
                rfm_classified: list[dict] | None = None,
                winback_drafts: list[dict] | None = None,
                vip_drafts: list[dict] | None = None,
                vips: list[dict] | None = None,
                subscription_candidates: list[dict] | None = None,
                repeat_analysis: dict | None = None,
                html_path: Path) -> str:
    """Render unified report.html. Sections only render if data exists."""
    has_rfm = rfm_classified is not None and len(rfm_classified) > 0
    has_winback = winback_drafts is not None
    has_vip = vips is not None
    has_subscription = subscription_candidates is not None
    has_repeat = repeat_analysis is not None

    tab_defs: list[tuple[str, str, str]] = []

    if has_rfm:
        rfm_body = (
            render_segment_kpis(rfm_classified)
            + H.section(
                "RFM 矩阵 — 谁是金主，谁在流失",
                "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
                "X 轴 = Recency（5 最近 / 1 最远）· Y 轴 = Frequency（5 最频繁 / 1 最少）· "
                "颜色深浅 = 该格平均 LTV。鼠标悬停看详情。</p>"
                + render_rfm_matrix(rfm_classified),
            )
        )
        tab_defs.append(("rfm", f"🏆 RFM ({metrics.get('total_customers', 0)} 客户)", rfm_body))

    if has_vip and vips:
        vip_body = render_vip_cards(vips, vip_drafts or [])
        tab_defs.append(("vip", f"💎 VIP ({len(vips)})", vip_body))

    if has_winback:
        wb_body = render_winback_tabs(winback_drafts)
        n = len(winback_drafts)
        tab_defs.append(("winback", f"📧 Winback ({n})", wb_body))

    if has_subscription:
        sub_body = render_subscription_cards(subscription_candidates)
        n = len(subscription_candidates)
        tab_defs.append(("subscription", f"🔁 订阅化 ({n})", sub_body))

    if has_repeat:
        rep_body = render_repeat_funnel(repeat_analysis)
        tab_defs.append(("repeat", "↻ 复购漏斗", rep_body))

    if not tab_defs:
        body = H.empty_state("还没有 retention 数据。", "用 --mode all --csv orders.csv 跑一次")
    else:
        head = H.page_head(
            f"客户留存 · {store_name or '—'}",
            f"mode <code>{H.esc(mode)}</code> · Run <code>{H.esc(run_id[:8])}</code>",
        )
        body = head + H.tabs(tab_defs)

    return H.page(
        title=f"留存报告 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"mode: {mode}",
    )
