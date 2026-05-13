#!/usr/bin/env python3
"""Render lumicc-expand decision-board.html — throwaway drag-drop editor.

This is the prototypical "throwaway editor" from the thariq HTML-effectiveness
methodology: instead of asking the user to read a markdown table and decide,
we give them an interactive board where they drag candidates between three
buckets (Order Sample / Watchlist / Reject) and export their final JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


ACTION_LABEL = {
    "order_sample": "🟢 立即下样",
    "watchlist": "🟡 观察名单",
    "reject": "🔴 拒绝",
}
ACTION_COLOR = {"order_sample": "emerald", "watchlist": "amber", "reject": "rose"}


def render_factor_radar(factors: dict) -> str:
    """Mini 5-point radar chart as SVG, showing 5 factor scores 0-10."""
    names = ["margin", "demand", "content", "supplier", "fulfillment"]
    cx, cy, r = 60, 60, 40
    import math
    angle_step = (2 * math.pi) / 5
    points = []
    grid_points_outer = []
    for i, name in enumerate(names):
        f = factors.get(name) or {}
        score = (f.get("score") or 0) / 10  # normalize 0..1
        angle = -math.pi / 2 + i * angle_step
        x = cx + math.cos(angle) * r * score
        y = cy + math.sin(angle) * r * score
        points.append(f"{x:.1f},{y:.1f}")
        # Outer grid label
        gx = cx + math.cos(angle) * (r + 8)
        gy = cy + math.sin(angle) * (r + 8)
        grid_points_outer.append((gx, gy, name[:3]))

    # Grid rings at 25/50/75/100%
    rings = ""
    for pct in (0.25, 0.5, 0.75, 1.0):
        pr = r * pct
        rings += f'<circle cx="{cx}" cy="{cy}" r="{pr}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>'

    poly = (
        f'<polygon points="{" ".join(points)}" '
        f'fill="rgba(16,185,129,0.30)" stroke="rgba(16,185,129,0.80)" stroke-width="1.5"/>'
    )

    labels = ""
    for gx, gy, lbl in grid_points_outer:
        labels += (
            f'<text x="{gx:.1f}" y="{gy:.1f}" font-size="9" '
            f'fill="rgba(255,255,255,0.4)" font-family="monospace" '
            f'text-anchor="middle" dominant-baseline="middle">{H.esc(lbl)}</text>'
        )

    return (
        f'<svg viewBox="0 0 120 120" width="120" height="120" '
        f'style="display:block;margin:0 auto;">{rings}{poly}{labels}</svg>'
    )


def render_dd_item(candidate: dict) -> str:
    """One draggable card."""
    title = candidate.get("title", "—")
    total = candidate.get("total", 0)
    rank = candidate.get("rank", "?")
    reason = candidate.get("reason", "")
    factors = candidate.get("factors") or {}
    sku_id = candidate.get("id") or f"cand-{rank}"
    raw = candidate.get("raw") or {}

    factors_summary = " ".join(
        f"<span class='tag tag-zinc' style='font-size:10px;'>"
        f"{H.esc(k[:1].upper())}{(v.get('score') if isinstance(v, dict) else 0):.0f}</span>"
        for k, v in factors.items()
    )

    return (
        f'<div class="dd-item" draggable="true" data-id="{H.esc(sku_id)}">'
        f'<div style="display:flex;gap:10px;align-items:flex-start;">'
        f'<div style="flex:0 0 auto;">{render_factor_radar(factors)}</div>'
        f'<div style="flex:1;min-width:0;">'
        f'<div class="name">#{rank} · {H.esc(title)}</div>'
        f'<div class="meta">total <b style="color:var(--ink);">{total}</b> · {H.esc(reason)}</div>'
        f'<div style="margin-top:6px;">{factors_summary}</div>'
        f'<div class="meta">${(raw.get("landed_cost_usd") or 0):.2f} cost → '
        f'${(raw.get("suggested_retail_usd") or 0):.2f} retail</div>'
        f'</div></div></div>'
    )


def render_decision_board(candidates: list[dict]) -> str:
    """3-bucket drag-drop board with pre-filled initial action."""
    by_action: dict[str, list[dict]] = {"order_sample": [], "watchlist": [], "reject": []}
    for c in candidates:
        a = c.get("action", "watchlist")
        by_action.setdefault(a, []).append(c)

    buckets_html = ""
    for action in ("order_sample", "watchlist", "reject"):
        items = by_action.get(action, [])
        items_html = "".join(render_dd_item(c) for c in items)
        buckets_html += (
            f'<div class="dd-bucket" data-action="{H.esc(action)}">'
            f'<h3>{ACTION_LABEL[action]} <span class="count">({len(items)})</span></h3>'
            f'<div class="dd-list">{items_html}</div></div>'
        )

    actions_html = (
        '<div style="margin:20px 0;display:flex;gap:8px;justify-content:center;">'
        '<button class="btn primary" onclick="window.exportDecisions()">📥 导出决策 JSON</button>'
        '<span class="muted" style="font-size:12px;align-self:center;">'
        '拖拽卡片在桶之间移动 → 点击导出生成 <code>decisions.json</code></span>'
        '</div>'
    )

    return (
        '<div class="dd-board">'
        + buckets_html +
        '</div>'
        + actions_html
    )


def render_page(*, run_id: str, store_name: str, candidates: list[dict],
                soul_min_margin: float,
                existing_winners: list[str],
                html_path: Path) -> str:
    n_order = sum(1 for c in candidates if c.get("action") == "order_sample")
    n_watch = sum(1 for c in candidates if c.get("action") == "watchlist")
    n_reject = sum(1 for c in candidates if c.get("action") == "reject")

    kpis = H.kpi_strip([
        (len(candidates), "候选总数"),
        (n_order, "🟢 立即下样", "推荐", "emerald"),
        (n_watch, "🟡 观察", "watchlist", "amber"),
        (n_reject, "🔴 拒绝", "auto-rejected", "rose"),
    ])

    head = H.page_head(
        f"扩品决策板 · {store_name or 'Lumicc'}",
        f"5 因子评分自动初始化分桶 · 你可以拖拽调整 · Run <code>{H.esc(run_id[:8])}</code>"
        + (
            f' · SOUL 最低毛利 <code>{soul_min_margin*100:.0f}%</code>'
            if soul_min_margin else ""
        ),
    )

    winners_html = ""
    if existing_winners:
        winners_html = H.section(
            "现有爆款（用于推荐相邻 SKU）",
            "<p class='muted' style='font-size:13px;'>"
            + " · ".join(f"<code>{H.esc(w)}</code>" for w in existing_winners)
            + "</p>"
        )

    instructions = (
        '<div class="card" style="padding:18px 20px;margin:16px 0;">'
        '<b style="color:var(--ink);">如何使用</b><br>'
        '<ol style="font-size:13px;color:var(--ink-muted);padding-left:24px;line-height:1.8;margin:8px 0 0;">'
        '<li><b>查看</b>每张卡片：迷你雷达图显示 5 因子得分</li>'
        '<li><b>拖拽</b>卡片在三个桶之间调整你的判断</li>'
        '<li><b>导出</b>最终决策 JSON，可喂给后续流程或归档</li>'
        '</ol></div>'
    )

    board = render_decision_board(candidates)

    body = head + kpis + winners_html + instructions + board

    return H.page(
        title=f"扩品决策板 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"{len(candidates)} candidates",
    )
