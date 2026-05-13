#!/usr/bin/env python3
"""Render lumicc-voc report.html — visual companion to markdown reports.

Sections:
  - KPI strip (4 cards): 总反馈 · 命中主题 · 未匹配 · 最大集群
  - 主题分布: horizontal progress bars per cluster with delta vs prior
  - 主题详情: tabs (top 6 clusters) with exemplars + suggested fix
  - 与上次对比: comparison table; empty_state if no prior
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


TOPIC_LABEL = {
    "packaging_damage": "📦 包装破损",
    "size_mismatch": "📏 尺寸不符",
    "quality_issue": "🔧 质量问题",
    "delivery_late": "🚚 物流慢",
    "not_as_described": "🎭 货不对板",
    "instructions_missing": "📖 说明不清",
    "compatibility": "🔌 兼容性",
    "smell_taste": "👃 气味味道",
    "customer_service": "💬 售后体验",
    "value_for_money": "💰 性价比",
}


SUGGESTED_FIX = {
    "packaging_damage": "联系仓库检查防震包装；考虑双层泡沫或角防护；目标 30 天内将该集群规模降 50%。",
    "size_mismatch": "在主图位置加入尺寸对照图；详情页补齐显式尺寸表与重量；用 7 天验证是否减少退货。",
    "quality_issue": "向供应商发起质量投诉并要求备选样品；详情页加材质与质保说明，提升信任。",
    "delivery_late": "切换更快的物流通道（如 DHL eCommerce），并在详情页按市场显示明确 ETA。",
    "not_as_described": "用实拍图替换库存图；删除无法验证的宣传话术；2 周内复测复购退货率。",
    "instructions_missing": "制作 1 页 PDF + 30 秒视频，包装上加 QR 码；详情页内嵌视频。",
    "compatibility": "在详情页加入兼容性表（兼容 X/Y，不兼容 Z），减少错买导致的差评。",
    "smell_taste": "请供应商更换材料或预先散味；包装内附简短说明告知首次开箱建议。",
    "customer_service": "设定 SLA：24h 内回复 / 48h 内退款决定；建立客服话术模板。",
    "value_for_money": "A/B 测试更高 AOV 的捆绑套餐；详情页强调质保、退换与售后增值服务。",
}


def topic_label(topic: str) -> str:
    return TOPIC_LABEL.get(topic, topic)


# =============================================================================
# KPI strip
# =============================================================================
def render_kpis(*, total_reviews: int, clusters: list[dict],
                unmatched_count: int) -> str:
    biggest = max(clusters, key=lambda c: c["size"]) if clusters else None
    biggest_value = f'{biggest["size"]}' if biggest else "—"
    biggest_hint = topic_label(biggest["topic"]) if biggest else "暂无"
    return H.kpi_strip([
        (total_reviews, "总反馈数", "本轮输入", "emerald"),
        (len(clusters), "命中主题", "聚类成功", "sky"),
        (unmatched_count, "未匹配", "无关键词命中", "zinc"),
        (biggest_value, "最大集群", biggest_hint, "rose"),
    ])


# =============================================================================
# Topic distribution: horizontal bars
# =============================================================================
def _delta_html(prior_size: int | None, curr_size: int) -> str:
    if prior_size is None:
        return (
            '<span class="tag tag-sky" '
            'style="font-family:var(--mono);font-size:11px;">NEW</span>'
        )
    if prior_size == curr_size:
        return (
            '<span style="font-family:var(--mono);font-size:12px;'
            'color:var(--ink-muted);">→ 0</span>'
        )
    diff = curr_size - prior_size
    if diff < 0:
        return (
            f'<span style="font-family:var(--mono);font-size:12px;'
            f'color:var(--accent-soft);">↓ {abs(diff)}</span>'
        )
    return (
        f'<span style="font-family:var(--mono);font-size:12px;'
        f'color:var(--rose);">↑ {diff}</span>'
    )


def render_distribution(clusters: list[dict], prior: dict[str, int],
                        total_reviews: int) -> str:
    if not clusters:
        return H.empty_state("没有命中任何主题。")

    rows: list[str] = []
    for c in clusters:
        pct = (c["size"] / max(1, total_reviews)) * 100
        prior_size = prior.get(c["topic"])
        delta = _delta_html(prior_size, c["size"])
        rows.append(
            '<div style="display:flex;align-items:center;gap:12px;'
            'padding:8px 0;border-bottom:1px solid var(--surface-2);">'
            f'<div style="flex:0 0 160px;color:var(--ink);font-weight:500;">'
            f'{H.esc(topic_label(c["topic"]))}</div>'
            f'<div style="flex:1 1 auto;">{H.progress_bar(pct)}</div>'
            '<div style="flex:0 0 90px;text-align:right;font-family:var(--mono);'
            f'color:var(--ink);">{c["size"]}</div>'
            f'<div style="flex:0 0 70px;text-align:right;">{delta}</div>'
            '</div>'
        )
    return '<div>' + "".join(rows) + '</div>'


# =============================================================================
# Topic detail tabs
# =============================================================================
def _exemplars_block(exemplars: list[str]) -> str:
    if not exemplars:
        return H.empty_state("无样例反馈。")
    items = []
    for ex in exemplars[:5]:
        items.append(
            '<blockquote style="margin:6px 0;padding:8px 12px;'
            'border-left:3px solid var(--surface-2);'
            'color:var(--ink-muted);font-style:italic;font-size:13px;">'
            f'{H.esc(ex)}</blockquote>'
        )
    return "".join(items)


def _detail_tab_body(c: dict) -> str:
    meta = (
        '<div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;'
        'color:var(--ink-muted);margin-bottom:8px;">'
        f'<span>频次 <b style="color:var(--ink);">{c["size"]}</b></span>'
        f'<span>影响 SKU <b style="color:var(--ink);">'
        f'{len(c.get("products_affected") or [])}</b></span>'
        f'<span>近期权重 <b style="color:var(--ink);">'
        f'{c.get("recency_weighted_size", c["size"])}</b></span>'
        '</div>'
    )
    products = c.get("products_affected") or []
    if products:
        prod_html = " ".join(
            f'<code style="margin-right:6px;">{H.esc(p)}</code>' for p in products[:8]
        )
        meta += (
            f'<div style="font-size:12px;color:var(--ink-muted);margin-bottom:8px;">'
            f'SKU: {prod_html}</div>'
        )

    exemplars_card = H.card(
        title="样例反馈",
        body=_exemplars_block(c.get("exemplars") or []),
    )

    fix_text = SUGGESTED_FIX.get(c["topic"], "暂无固定模板，请人工分析。")
    fix_body = (
        f'<div style="font-size:13px;color:var(--ink);line-height:1.6;">'
        f'{H.esc(fix_text)}</div>'
    )
    extra_fixes = c.get("proposed_fixes") or []
    if extra_fixes:
        extras = "".join(
            f'<li style="margin:4px 0;color:var(--ink-muted);font-size:12px;">'
            f'<b style="color:var(--ink);">[{H.esc(fx["type"])}]</b> '
            f'{H.esc(fx["detail"])}</li>'
            for fx in extra_fixes
        )
        fix_body += f'<ul style="margin:8px 0 0;padding-left:18px;">{extras}</ul>'

    fix_card = H.card(
        title="建议修复",
        tag="action", tag_color="emerald",
        body=fix_body,
    )

    return meta + exemplars_card + fix_card


def render_detail_tabs(clusters: list[dict]) -> str:
    if not clusters:
        return H.empty_state("没有可展示的主题。")
    tab_defs: list[tuple[str, str, str]] = []
    for c in clusters[:6]:
        key = c["topic"]
        label = f'{topic_label(c["topic"])} ({c["size"]})'
        tab_defs.append((key, label, _detail_tab_body(c)))
    return H.tabs(tab_defs)


# =============================================================================
# Comparison table
# =============================================================================
def render_comparison(clusters: list[dict], prior: dict[str, int]) -> str:
    if not prior:
        return H.empty_state("没有上次跑次的对比数据。", "再跑一次即可看到变化。")

    by_topic = {c["topic"]: c["size"] for c in clusters}
    all_topics = sorted(set(prior.keys()) | set(by_topic.keys()))
    rows: list[list] = []
    for topic in all_topics:
        prev = prior.get(topic)
        curr = by_topic.get(topic, 0)
        if prev is None:
            change = H.badge("NEW", "sky")
            verdict = "新出现"
        elif curr == 0:
            change = (
                '<span style="font-family:var(--mono);color:var(--accent-soft);">'
                f'↓ {prev} (清零)</span>'
            )
            verdict = "已解决"
        elif curr < prev:
            change = (
                '<span style="font-family:var(--mono);color:var(--accent-soft);">'
                f'↓ {prev - curr}</span>'
            )
            verdict = "好转"
        elif curr > prev:
            change = (
                '<span style="font-family:var(--mono);color:var(--rose);">'
                f'↑ {curr - prev}</span>'
            )
            verdict = "恶化"
        else:
            change = (
                '<span style="font-family:var(--mono);color:var(--ink-muted);">'
                '→ 0</span>'
            )
            verdict = "持平"
        rows.append([
            H.esc(topic_label(topic)),
            "—" if prev is None else prev,
            curr,
            change,
            verdict,
        ])
    return H.table(
        ["主题", "上次 size", "本次 size", "变化", "评价"],
        rows,
        align=["left", "right", "right", "center", "left"],
    )


# =============================================================================
# Master render
# =============================================================================
def render_page(*, run_id: str, store_name: str, clusters: list[dict],
                prior: dict[str, int], total_reviews: int,
                unmatched_count: int, html_path: Path) -> str:
    head = H.page_head(
        f"客户之声 · {store_name or '—'}",
        f"{total_reviews} 条反馈 · {len(clusters)} 个主题 · "
        f"Run <code>{H.esc(run_id[:8])}</code>",
    )

    kpis = render_kpis(
        total_reviews=total_reviews, clusters=clusters,
        unmatched_count=unmatched_count,
    )

    dist = H.section("📊 主题分布 (从大到小)", render_distribution(
        clusters, prior, total_reviews,
    ))

    detail = H.section("🔍 主题详情", render_detail_tabs(clusters))

    compare = H.section("📉 与上次对比", render_comparison(clusters, prior))

    body = head + kpis + dist + detail + compare

    return H.page(
        title=f"客户之声 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"voc · {len(clusters)} topics",
    )
