#!/usr/bin/env python3
"""Render lumicc-listing report.html — visual companion to markdown reports.

Visual layout:
  - Top KPI strip: avg health · sick / improvable / healthy counts
  - Tabs grouped by severity (🔴 重病 / 🟡 待改善 / 🟢 健康)
  - Each tab: card_grid of products. Each card shows score, 8 check rows,
    and "Top 3 fixes" highlighted block.
  - Summary section: avg score per check across products + fix template.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
sys.path.insert(0, str(HERE))
import html_lib as H  # noqa: E402
import checks as checks_mod  # noqa: E402


# Severity → label / tag color / emoji
SEVERITY_META = {
    "sick": ("重病", "rose", "🔴"),
    "improvable": ("待改善", "amber", "🟡"),
    "healthy": ("健康", "emerald", "🟢"),
}

# Check key → 中文 label
CHECK_LABEL = {
    "image_count": "图片数量",
    "title_seo": "标题 SEO",
    "bullets": "卖点 Bullets",
    "description": "描述 Description",
    "price_ladder": "价格阶梯",
    "reviews": "评论",
    "scarcity": "稀缺 / 紧迫感",
    "mobile": "移动端 LCP",
}

# Per-check generic fix template (for summary section)
CHECK_FIX_TEMPLATE = {
    "image_count": "至少 6 张图：主图 ≥1000px、生活场景、比例尺、细节特写、包装。",
    "title_seo": "60-80 字符；主关键词 + 品牌 + 差异点；避免 ALL CAPS。",
    "bullets": "5 条 bullets，每条 ≤200 字，以收益开头。",
    "description": "200-400 词，含可扫描小标题与明确 CTA。",
    "price_ladder": "设置 compare_at_price ≥ 1.15× price；季度检查竞品价。",
    "reviews": "通过 post-purchase 邮件冲到 10+ 评论，月度保持新鲜度。",
    "scarcity": "库存 < 20 时显示 'Only X left' 徽章。",
    "mobile": "压缩 hero 图、延后第三方脚本，目标 LCP < 3000 ms。",
}


def _truncate(text: str, n: int = 64) -> str:
    text = text or "—"
    return text if len(text) <= n else text[: n - 1] + "…"


def _score_color(score: float) -> str:
    """0-10 score → token color name for badge."""
    if score >= 8:
        return "emerald"
    if score >= 5:
        return "amber"
    return "rose"


def _total_color(total: float) -> str:
    if total >= 85:
        return "emerald"
    if total >= 65:
        return "amber"
    return "rose"


def render_product_card(a: dict) -> str:
    """Render one product as a card. `a` is the audit entry from run.py."""
    audit = a["audit"]
    total = audit["total"]
    severity = audit["severity"]
    sev_label, sev_color, sev_emoji = SEVERITY_META.get(
        severity, ("—", "zinc", "·")
    )
    checks = audit["checks"]

    # Big score
    score_html = (
        f'<div class="kpi-value" style="font-size:42px;line-height:1;'
        f'color:var(--accent);margin-bottom:6px;">{total:.0f}'
        f'<span style="font-size:14px;color:var(--ink-muted);font-weight:400;"> / 100</span>'
        f'</div>'
    )

    # 8 check rows
    rows = []
    for key, label in CHECK_LABEL.items():
        c = checks.get(key) or {}
        score = c.get("score", 0)
        evidence = c.get("evidence", "—")
        rows.append([
            label,
            H.badge(f"{score:.1f}/10", _score_color(score)),
            f'<span class="muted" style="font-size:12px;">{H.esc(evidence)}</span>',
        ])
    checks_table = H.table(
        ["检查项", "分数", "Evidence"],
        rows,
        align=["left", "center", "left"],
    )

    # Top 3 fixes
    fixes = audit.get("top_fixes") or []
    if fixes:
        items = []
        for fx in fixes:
            check_label = CHECK_LABEL.get(fx["check"], fx["check"])
            items.append(
                f'<li style="margin-bottom:6px;">'
                f'<b style="color:var(--accent);">{H.esc(check_label)}</b> '
                f'<span class="muted mono" style="font-size:11px;">'
                f'impact {fx["impact"]:.2f}</span><br>'
                f'<span style="font-size:12px;color:var(--ink-muted);">'
                f'{H.esc(fx["evidence"])}</span><br>'
                f'<span style="font-size:13px;color:var(--ink);">→ '
                f'{H.esc(fx["fix"])}</span></li>'
            )
        fixes_html = (
            '<div style="margin-top:10px;padding:10px;'
            'background:var(--surface-2);border-left:3px solid var(--accent);'
            'border-radius:4px;">'
            '<div style="font-size:12px;color:var(--ink-muted);'
            'margin-bottom:6px;font-weight:600;">Top 3 修复（按影响 × 容易度）</div>'
            f'<ol style="padding-left:20px;margin:0;">{"".join(items)}</ol>'
            '</div>'
        )
    else:
        fixes_html = (
            '<div style="margin-top:10px;font-size:12px;color:var(--ink-muted);">'
            '✓ 各项检查均强势，无需重点修复。</div>'
        )

    sku = a.get("sku") or "—"
    meta = (
        f'<span class="mono" style="font-size:12px;color:var(--ink-muted);">'
        f'SKU <code>{H.esc(sku)}</code></span>'
    )

    body = score_html + checks_table + fixes_html

    return H.card(
        title=_truncate(a.get("title") or "—", 60),
        tag=f"{sev_emoji} {sev_label}",
        tag_color=sev_color,
        meta=meta,
        body=body,
    )


def render_summary_section(audits: list[dict]) -> str:
    """Per-check avg score across products + fix template (one row per check)."""
    if not audits:
        return H.empty_state("无审计数据。")

    rows = []
    n = len(audits)
    for key, label in CHECK_LABEL.items():
        total = 0.0
        for a in audits:
            c = (a["audit"]["checks"].get(key) or {})
            total += c.get("score", 0)
        avg = total / max(1, n)
        weight = checks_mod.WEIGHTS.get(key, 0)
        rows.append([
            label,
            H.badge(f"{avg:.1f}/10", _score_color(avg)),
            f'<span class="mono" style="font-size:11px;color:var(--ink-muted);">'
            f'{weight * 100:.0f}%</span>',
            f'<span style="font-size:12px;color:var(--ink-muted);">'
            f'{H.esc(CHECK_FIX_TEMPLATE.get(key, "—"))}</span>',
        ])

    return H.table(
        ["检查项", "平均分", "权重", "通用修复模板"],
        rows,
        align=["left", "center", "right", "left"],
    )


def _group_by_severity(audits: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"sick": [], "improvable": [], "healthy": []}
    for a in audits:
        sev = a["audit"]["severity"]
        out.setdefault(sev, []).append(a)
    return out


def render_recommended_pickers_section(recommended: list[dict]) -> str:
    """Render the 'recommended hero re-design' block. Empty string if none."""
    if not recommended:
        return ""
    items = []
    for r in recommended:
        title = H.esc(r.get("product_title") or r.get("product_sku") or "—")
        cmd = H.esc(r.get("command") or "")
        reason = H.esc(r.get("reason") or "")
        items.append(
            "<li style='margin-bottom:10px;'>"
            f"<b>{title}</b> "
            f"<span class='muted' style='font-size:12px;'>· {reason}</span>"
            "<div style='margin-top:4px;font-size:12.5px;'>建议重做 hero。点这里开本地选择器：</div>"
            f"<pre class='mono' style='margin:6px 0 0;padding:8px 10px;background:var(--surface-2);"
            f"border-radius:6px;font-size:11.5px;overflow-x:auto;'>{cmd}</pre>"
            "</li>"
        )
    body = (
        "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
        "这些商品的 hero 图评分较低，建议用本地 picker 重新挑一个 landing 风格再重做 hero。</p>"
        f"<ol style='padding-left:20px;margin:0;'>{''.join(items)}</ol>"
    )
    return H.section("🎨 建议重做的 hero 图风格", body)


def render_page(*, run_id: str, store_name: str,
                audits: list[dict], html_path: Path,
                recommended_pickers: list[dict] | None = None) -> str:
    """Master entrypoint: returns full themed HTML string."""
    n = len(audits)
    if n == 0:
        body = (
            H.page_head(f"Listing 体检 · {store_name or '—'}",
                        f"Run <code>{H.esc(run_id[:8])}</code>")
            + H.empty_state("还没有可审计的商品。",
                            "导入 store.db 后再跑一次。")
        )
        return H.page(
            title=f"Listing 体检 · {store_name or 'Lumicc'}",
            body=body,
            right_meta=f"products: 0",
        )

    avg_total = sum(a["audit"]["total"] for a in audits) / n
    by_sev = _group_by_severity(audits)
    n_sick = len(by_sev["sick"])
    n_imp = len(by_sev["improvable"])
    n_healthy = len(by_sev["healthy"])

    kpi = H.kpi_strip([
        (f"{avg_total:.0f}", "平均健康度",
         "0-100 加权综合分", _total_color(avg_total)),
        (n_sick, "🔴 重病数",
         "< 65，优先处理", "rose" if n_sick else "zinc"),
        (n_imp, "🟡 待改善数",
         "65-84，可优化", "amber" if n_imp else "zinc"),
        (n_healthy, "🟢 健康数",
         "≥ 85，保持节奏", "emerald" if n_healthy else "zinc"),
    ])

    # Tabs by severity
    tab_defs: list[tuple[str, str, str]] = []
    for sev_key in ("sick", "improvable", "healthy"):
        items = by_sev.get(sev_key) or []
        label_zh, _, emoji = SEVERITY_META[sev_key]
        if not items:
            content = H.empty_state(f"暂无【{label_zh}】商品。")
        else:
            cards = [render_product_card(a) for a in items]
            content = H.card_grid(cards, min_width=360)
        tab_defs.append((
            sev_key,
            f"{emoji} {label_zh} ({len(items)})",
            content,
        ))

    summary = H.section(
        "各检查项平均表现 · 全店概览",
        "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
        "每一项跨全部商品的平均得分。低分项 = 全店通病，应优先模板化整改。</p>"
        + render_summary_section(audits),
    )

    head = H.page_head(
        f"Listing 体检 · {store_name or '—'}",
        f"{n} 个商品 · Run <code>{H.esc(run_id[:8])}</code>",
    )

    picker_block = render_recommended_pickers_section(recommended_pickers or [])

    body = head + kpi + picker_block + H.tabs(tab_defs) + summary

    return H.page(
        title=f"Listing 体检 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"products: {n}",
    )
