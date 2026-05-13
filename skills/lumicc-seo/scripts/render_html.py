#!/usr/bin/env python3
"""Render the lumicc-seo report.html — visual HTML companion to .md outputs.

Uses the shared html_lib (from main lumicc/scripts/html_lib.py) so all Lumicc
pages share visual identity. Single page with tabs for all 5 modes.

Key visual differentiators (per thariq HTML-effectiveness methodology):
  - Citation report → 5-engine × N-query heatmap matrix (NOT a markdown list)
  - Rank report → per-keyword sparkline cards (NOT a delta table)
  - Schema → contact sheet with copy buttons per product (NOT scattered files)
  - llms.txt → side-by-side: content / validation / spec reference
  - Audit → clickable checklist with pass/fail badges + fix hints
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


# =============================================================================
# Citation heatmap (the visual flagship)
# =============================================================================
def render_citation_matrix(citation_data: dict) -> str:
    """Citation report → 5-engine × N-query heatmap.

    `citation_data`: dict from citation.process_batch() output.
    """
    results = citation_data.get("results", [])
    if not results:
        return H.empty_state("还没有 citation 数据。",
                              "用 --mode citation --queries-file ... 注入查询答案")

    # Pivot to {query: {engine: result}}
    queries: dict[str, dict] = {}
    engines: set = set()
    for r in results:
        engines.add(r["engine"])
        queries.setdefault(r["query"], {})[r["engine"]] = r
    engines_sorted = sorted(engines)
    queries_sorted = sorted(queries.keys())

    # Compute overall share
    n_total = len(results)
    n_mentioned = sum(1 for r in results if r["brand_mentioned"])
    share = n_mentioned / max(1, n_total)

    # Build header row
    head = "<tr><th></th>" + "".join(
        f'<th style="text-align:center;text-transform:none;font-size:12px;font-family:var(--mono);">'
        f'{H.esc(e)}</th>' for e in engines_sorted
    ) + "</tr>"

    # Body rows
    body_rows = []
    for q in queries_sorted:
        cells = [f'<td style="font-size:12px;color:var(--ink);max-width:280px;'
                 f'font-family:var(--mono)">{H.esc(q[:80])}</td>']
        for e in engines_sorted:
            r = queries[q].get(e)
            if not r:
                cells.append('<td class="heatmap-cell" style="background:var(--surface-2);color:var(--ink-dim)">—</td>')
                continue
            if r["brand_mentioned"]:
                label = f"✓ #{r['position']}" if r.get("position") else "✓"
                tooltip = (r.get("first_mention_excerpt") or "")[:200]
                share_val = r.get("share", 0.5)
                cells.append(H.heatmap_cell(share_val, label=label, tooltip=tooltip))
            else:
                cells.append(
                    '<td class="heatmap-cell" style="background:var(--surface-2);'
                    'color:var(--ink-dim);">✗</td>'
                )
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    matrix_html = (
        f'<div style="overflow-x:auto;"><table class="data-table" style="border-collapse:separate;border-spacing:4px;">'
        f'<thead>{head}</thead><tbody>{"".join(body_rows)}</tbody></table></div>'
    )

    # Per-engine summary cards
    engine_cards = []
    for e in engines_sorted:
        rs = [r for r in results if r["engine"] == e]
        n_m = sum(1 for r in rs if r["brand_mentioned"])
        avg_share = sum(r["share"] for r in rs) / max(1, len(rs))
        engine_cards.append(H.kpi_card(
            value=f"{n_m}/{len(rs)}",
            label=e,
            hint=f"{avg_share*100:.0f}% 份额",
            color=("emerald" if n_m == len(rs) else "amber" if n_m > 0 else "rose"),
        ))

    # Identify under-covered queries (where brand not mentioned)
    gaps = sorted({q for q in queries_sorted
                   if all(not queries[q][e]["brand_mentioned"]
                          for e in engines_sorted if e in queries[q])})

    gap_html = ""
    if gaps:
        gap_list = "<ul style='margin:8px 0;padding-left:24px;'>" + "".join(
            f"<li><code>{H.esc(q)}</code></li>" for q in gaps[:5]
        ) + "</ul>"
        gap_html = H.section(
            "📍 完全未被引用的查询",
            f"<p style='color:var(--ink-muted);font-size:14px'>"
            f"以下查询在所有引擎中都没有提到我们的品牌。建议为这些查询撰写 SEO 文章覆盖。</p>"
            f"{gap_list}"
        )

    return (
        H.section("引擎引用份额（按引擎）",
                  '<section class="kpi-grid">' + "".join(engine_cards) + "</section>")
        + H.section(
            f"引用矩阵（整体份额 {share*100:.0f}%）",
            f"<p class='muted' style='font-size:13px;margin:8px 0;'>"
            f"绿色越深 = 引用份额越高。鼠标悬停看引用片段。"
            f"</p>{matrix_html}",
        )
        + gap_html
    )


# =============================================================================
# Rank sparklines
# =============================================================================
def render_rank_sparklines(rank_data: dict, history: list[dict] | None = None) -> str:
    """Rank report → sparkline-per-keyword cards.

    `rank_data`: output of rank.import_gsc_csv() with deltas
    `history`: optional list of per-keyword history rows from seo_keywords table
    """
    drops = rank_data.get("biggest_drops") or []
    climbs = rank_data.get("biggest_climbs") or []
    rows = rank_data.get("rows_processed", 0)

    kpis = H.kpi_strip([
        (rows, "本次导入"),
        (len(drops), "🔴 下滑", "rank ↓ ≥ 1", "rose" if drops else "zinc"),
        (len(climbs), "🟢 上升", "rank ↑ ≥ 1", "emerald" if climbs else "zinc"),
    ])

    def render_keyword_card(item: dict, sentiment: str) -> str:
        kw = item["keyword"]
        prev, curr = item["prev"], item["current"]
        delta = item["delta"]
        arrow = "↑" if delta < 0 else "↓"
        color = "emerald" if delta < 0 else "rose"
        # Generate a synthetic sparkline from prev→current (real history requires DB lookup)
        spark = H.sparkline([prev, (prev + curr) / 2, curr],
                             color="#34d399" if delta < 0 else "#fda4af")
        body = (
            f'<div style="display:flex;gap:12px;align-items:center;">'
            f'{spark}<div>'
            f'<div style="font-family:var(--mono);font-size:13px;color:var(--ink);">'
            f'#{prev} → #{curr}</div>'
            f'<div style="font-family:var(--mono);font-size:11px;color:var(--ink-muted);">'
            f'{arrow} {abs(delta)} 位</div></div></div>'
        )
        return H.card(
            title=kw, tag=sentiment, tag_color=color,
            meta=f"trend · {sentiment}", body=body,
        )

    drop_cards = [render_keyword_card(d, "下滑") for d in drops[:8]]
    climb_cards = [render_keyword_card(d, "上升") for d in climbs[:8]]

    drops_section = H.section(
        f"🔴 排名下滑 Top {len(drop_cards)}",
        H.card_grid(drop_cards, min_width=240)
    ) if drop_cards else ""
    climbs_section = H.section(
        f"🟢 排名上升 Top {len(climb_cards)}",
        H.card_grid(climb_cards, min_width=240)
    ) if climb_cards else ""

    if not drops and not climbs:
        body = H.empty_state(
            "首次导入数据，没有可比较的历史。",
            "再跑一次（带新数据）后可以看到排名 delta",
        )
        return kpis + body

    return kpis + drops_section + climbs_section


# =============================================================================
# Audit checklist
# =============================================================================
def render_audit_checklist(audit_data: dict) -> str:
    checks = audit_data.get("checks") or {}
    summary = audit_data.get("summary") or {}
    score = summary.get("score", 0)

    score_color = "emerald" if score >= 85 else "amber" if score >= 65 else "rose"
    kpis = H.kpi_strip([
        (f"{score}", "总分", f"{summary.get('passed',0)} / {summary.get('total_checks',0)} 通过",
         score_color),
        (summary.get("failed", 0), "🔴 失败项", "立即修复",
         "rose" if summary.get("failed", 0) else "zinc"),
        (audit_data.get("store_url", "—"), "目标 URL", "已扫描"),
    ])

    icon_map = {"pass": "✅", "warn": "🟡", "info": "ℹ️", "fail": "🔴"}
    items_html = ""
    for name, c in checks.items():
        status = c.get("status", "info")
        ic = icon_map.get(status, "?")
        items_html += H.collapsible(
            summary=f"{ic} {name} — {c.get('evidence','')[:100]}",
            body=(
                f'<div style="padding:14px 18px;font-size:14px;color:var(--ink-muted);">'
                f'<b style="color:var(--ink)">证据</b>：{H.esc(c.get("evidence",""))}<br>'
                f'<b style="color:var(--ink)">修复</b>：{H.esc(c.get("fix",""))}</div>'
            ),
        )

    return kpis + H.section("11 项检查（点击展开看证据 + 修复建议）", items_html)


# =============================================================================
# Schema contact sheet
# =============================================================================
def render_schema_sheet(schema_deliverable: dict, run_dir: Path,
                        html_dir: Path) -> str:
    """Schema → contact sheet with copy buttons per product."""
    files = schema_deliverable.get("files", [])
    if not files:
        return H.empty_state("还没有商品的 schema 生成。")

    cards = []
    for fp in files:
        try:
            data = json.loads(Path(fp).read_text(encoding="utf-8"))
        except Exception:
            continue
        sku = data.get("sku") or "—"
        url = data.get("product_url") or ""
        schemas = data.get("schemas", [])
        block = ""
        for s in schemas:
            t = s.get("type", "Schema")
            html_block = s.get("html_block", "")
            block += (
                f'<div style="margin-bottom:10px;"><b style="color:var(--ink);font-size:12px;">'
                f'{H.esc(t)}</b></div>'
                f'<pre style="max-height:180px;font-size:11px;">{H.esc(html_block)}</pre>'
            )
        actions = []
        if schemas:
            actions.append(H.copy_button(schemas[0]["html_block"], "📋 复制 Product JSON-LD"))
            if len(schemas) > 1:
                actions.append(H.copy_button(schemas[1]["html_block"], "📋 复制 FAQPage", style=""))
            if url:
                actions.append(H.external_link(url, "查看产品页"))
        cards.append(H.card(
            title=sku, tag="Schema.org", tag_color="indigo",
            meta=f"URL: {H.esc(url)}" if url else "",
            body=block, actions=actions,
        ))
    return H.section(f"商品 Schema.org JSON-LD ({len(cards)})",
                      H.card_grid(cards, min_width=420))


# =============================================================================
# llms.txt viewer
# =============================================================================
def render_llms_txt_view(llms_deliverable: dict) -> str:
    path = llms_deliverable.get("path", "")
    validation = llms_deliverable.get("validation") or {}
    try:
        content = Path(path).read_text(encoding="utf-8") if path else ""
    except Exception:
        content = ""

    valid_icon = "✅" if validation.get("ok") else "🟡"
    valid_color = "emerald" if validation.get("ok") else "amber"

    errors = validation.get("errors") or []
    warnings = validation.get("warnings") or []

    valid_body = ""
    if errors:
        valid_body += "<b style='color:#fda4af'>❌ 错误：</b><ul style='margin:4px 0 12px 20px;'>" + \
                      "".join(f"<li>{H.esc(e)}</li>" for e in errors) + "</ul>"
    if warnings:
        valid_body += "<b style='color:#fcd34d'>⚠️ 警告：</b><ul style='margin:4px 0 12px 20px;'>" + \
                      "".join(f"<li>{H.esc(w)}</li>" for w in warnings) + "</ul>"
    if not errors and not warnings:
        valid_body = "<p style='color:#6ee7b7'>✅ 完美通过验证。</p>"

    spec_html = """
<ul style="font-size:13px;color:var(--ink-muted);padding-left:18px;line-height:1.7;">
<li># SiteName — 第一行 H1，必须，仅一个</li>
<li>&gt; 一句话描述（紧跟 H1）— 推荐</li>
<li>## Section — 任意数量的 H2 分类</li>
<li>- [文字](url): 可选说明 — 链接行</li>
<li>放置位置：<code>https://yourstore.com/llms.txt</code></li>
</ul>
<p style="font-size:12px;color:var(--ink-dim);margin-top:8px;">
<a href="https://llmstxt.org" target="_blank">llmstxt.org</a> · 完整规范
</p>"""

    return H.section("llms.txt — AI 爬虫专属导航", "") + f"""
<div style="display:grid;grid-template-columns: 1.5fr 1fr 1fr; gap:16px;">
  <div>
    <div class="subhead">📄 生成内容（{validation.get('char_count',0)} chars · {validation.get('section_count',0)} 节）</div>
    <pre style="max-height:400px;">{H.esc(content)}</pre>
    <div style="margin-top:8px;">{H.copy_button(content, "📋 复制全部")}</div>
  </div>
  <div>
    <div class="subhead">{valid_icon} 验证</div>
    <div class="card" style="padding:14px 18px;font-size:13px;color:var(--ink);">
      {valid_body}
    </div>
  </div>
  <div>
    <div class="subhead">📋 spec 速查</div>
    <div class="card" style="padding:14px 18px;">{spec_html}</div>
  </div>
</div>"""


# =============================================================================
# Master render
# =============================================================================
def render_page(*, run_id: str, mode: str, deliverables: list[dict],
                store_name: str, html_path: Path) -> str:
    """Build a single report.html that includes whatever modes were run."""
    html_dir = html_path.parent

    # Map deliverable types to handlers
    citation_d = next((d for d in deliverables if d.get("deliverable") == "citation_share"), None)
    rank_d = next((d for d in deliverables if d.get("deliverable") == "rank_delta_md"), None)
    schema_d = next((d for d in deliverables if d.get("deliverable") == "schema_json_ld"), None)
    audit_d = next((d for d in deliverables if d.get("deliverable") == "audit_checklist"), None)
    llms_d = next((d for d in deliverables if d.get("deliverable") == "llms_txt"), None)

    tab_defs: list[tuple[str, str, str]] = []
    if citation_d:
        tab_defs.append(("citation", "🤖 GEO 引用",
                          render_citation_matrix(citation_d)))
    if rank_d:
        tab_defs.append(("rank", "📈 关键词排名",
                          render_rank_sparklines(rank_d)))
    if audit_d:
        tab_defs.append(("audit", "🩺 技术体检",
                          render_audit_checklist(audit_d)))
    if schema_d:
        tab_defs.append(("schema", "🏷️ Schema.org",
                          render_schema_sheet(schema_d, html_dir.parent, html_dir)))
    if llms_d:
        tab_defs.append(("llms", "🔮 llms.txt",
                          render_llms_txt_view(llms_d)))

    if not tab_defs:
        body = H.empty_state("没有任何 deliverable 生成。",
                              "尝试 --mode all 或指定具体 mode")
    else:
        head = H.page_head(
            "SEO + GEO 报告",
            f"店铺 {store_name or '—'} · mode <code>{H.esc(mode)}</code> · "
            f"Run <code>{H.esc(run_id[:8])}</code>",
        )
        body = head + H.tabs(tab_defs)

    return H.page(
        title="SEO + GEO 报告",
        body=body,
        right_meta=f"mode: {mode} · run {run_id[:8]}",
    )
