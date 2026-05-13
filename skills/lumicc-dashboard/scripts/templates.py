#!/usr/bin/env python3
"""Dashboard page templates — built on the shared html_lib.

Each template renders ONE page of the dashboard (index/stores/campaigns/runs/memory)
using H.page() so all 4 themes + the live theme switcher Just Work.

The render.py orchestrator wraps these with data loading.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H  # noqa: E402
try:
    import secret_form as _secret_form  # noqa: E402
except Exception:  # noqa: BLE001
    _secret_form = None  # type: ignore[assignment]
try:
    import assets as _assets  # noqa: E402
except Exception:  # noqa: BLE001
    _assets = None  # type: ignore[assignment]


# ---------- shared helpers ----------
NAV_PAGES = [
    ("index.html", "概览"),
    ("stores.html", "店铺"),
    ("campaigns.html", "活动"),
    ("runs.html", "跑次"),
    ("memory.html", "记忆"),
]

STATUS_COLORS = {
    "running": "emerald", "planned": "sky", "done": "zinc",
    "paused": "amber", "cancelled": "rose", "success": "emerald",
    "partial": "amber", "failed": "rose", "active": "emerald",
    "draft": "zinc", "removed": "rose",
    "task": "indigo", "warning": "amber", "decision": "indigo",
    "observation": "sky", "info": "sky",
}

STAGE_LABEL = {
    "0-to-1": "新店 0→1",
    "1-to-10": "成长 1→10",
    "10-to-100": "规模 10→100",
    "100+": "成熟 100+",
}


def _status_badge(status: str | None) -> str:
    color = STATUS_COLORS.get((status or "").lower(), "zinc")
    return H.badge(status or "—", color=color)


def _nav_html(active: str) -> str:
    items = []
    for href, label in NAV_PAGES:
        key = href.replace(".html", "")
        cls = "nav-link active" if key == active else "nav-link"
        items.append(f'<a href="{H.esc(href)}" class="{cls}">{H.esc(label)}</a>')
    return '<nav class="nav">' + "".join(items) + "</nav>"


def _wrap(*, title: str, active: str, body: str, store_count: int) -> str:
    """Wrap a body with H.page() but inject the dashboard's own multi-page nav."""
    # H.page already supports show_nav, but the default NAV is hard-coded for skill
    # report pages. The dashboard has its own page set, so we inject custom nav by
    # adding it to the body just below the topbar via the right_meta + a manual
    # nav row inserted at the start of body.
    nav_row = (
        '<div class="dashboard-nav" '
        'style="margin:-20px 0 28px 0;display:flex;gap:4px;flex-wrap:wrap;'
        'padding-bottom:14px;border-bottom:1px solid var(--line);">'
        + _nav_html(active)
        + "</div>"
    )
    return H.page(
        title=title,
        body=nav_row + body,
        brand_subtitle="Cross-Border Commerce OS",
        back_link=None,
        right_meta=f"{store_count} 家店铺",
    )


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v or 0):,.2f}"
    except (TypeError, ValueError):
        return "—"


# ---------- secrets ----------
def _render_secrets_section() -> str:
    """Render API 凭据 card listing every known provider's state."""
    if _secret_form is None:
        return ""
    try:
        rows_data = _secret_form.list_secrets()
    except Exception:  # noqa: BLE001
        return ""
    if not rows_data:
        return ""

    rows: list[list[str]] = []
    for key, info in rows_data.items():
        label = H.esc(info.get("label") or key)
        cred_cell = (
            f"<div><b>{label}</b></div>"
            f"<div class='mono muted' style='font-size:11px;'>{H.esc(key)}</div>"
        )
        if info.get("missing"):
            status_cell = H.badge("未配置", "rose")
            fp_cell = "<span class='muted'>—</span>"
            btn_label = "配置"
        else:
            status_cell = H.badge("已配置", "emerald")
            fp = info.get("fingerprint") or "***"
            fp_cell = f"<code class='mono' style='font-size:11.5px;'>{H.esc(fp)}</code>"
            btn_label = "更换"
        cmd = (
            f"python3 ~/.claude/skills/lumicc/scripts/secret_form.py "
            f"--generate {key} --open"
        )
        action_cell = (
            f"<div style='font-size:11px;'>{H.esc(btn_label)}：</div>"
            f"<code class='mono' style='display:block;font-size:11px;"
            f"padding:4px 6px;background:var(--surface-2);border-radius:4px;"
            f"overflow-x:auto;'>{H.esc(cmd)}</code>"
        )
        rows.append([cred_cell, status_cell, fp_cell, action_cell])

    table = H.table(
        headers=["凭据", "状态", "Fingerprint", "操作"],
        rows=rows,
        align=["left", "center", "left", "left"],
    )
    return H.section(
        "API 凭据",
        "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
        "凭据存在本地 <code>~/.commerce-os/secrets/</code>（0600 权限），从不进入 LLM 对话。</p>"
        + table,
    )


# ---------- assets ----------
def _render_assets_section() -> str:
    """Render 资产 section showing recent generated images/videos + 30-day KPIs."""
    if _assets is None:
        return ""
    try:
        stats = _assets.asset_stats(days=30)
        recent = _assets.list_assets(limit=12)
    except Exception:  # noqa: BLE001
        return ""

    n_image = stats.get("by_kind", {}).get("image", 0)
    n_video = stats.get("by_kind", {}).get("video", 0)
    total_cost = stats.get("total_cost_usd", 0.0)
    total = stats.get("total", 0)

    header = (
        "<p class='muted' style='font-size:13px;margin:6px 0 14px;'>"
        f"过去 30 天生成 <b>{n_image}</b> 张图 · <b>{n_video}</b> 个视频 · 累计 "
        f"<b>${total_cost:,.2f}</b></p>"
    )

    if not recent or total == 0:
        body = header + H.empty_state(
            "还没有生成的资产。",
            "运行 lumicc-content 生成首批图片。",
        )
        return H.section("资产", body)

    # Grid of recent asset thumbnails
    tiles: list[str] = []
    for a in recent:
        path = a.get("path") or ""
        kind = a.get("kind") or "?"
        sku = a.get("sku") or "—"
        model = a.get("model") or "—"
        cost = a.get("cost_usd") or 0.0
        ts = a.get("created_at")
        size = a.get("size_bytes") or 0
        exists = a.get("exists_on_disk")

        # Thumbnail: try embed image if small enough
        thumb_html = ""
        if kind == "image" and exists and 0 < size <= 500 * 1024:
            try:
                thumb_html = H.embed_image(path, max_kb=500)
            except Exception:  # noqa: BLE001
                thumb_html = ""
        if not thumb_html:
            icon = {"image": "🖼", "video": "🎬", "prompt": "✏️"}.get(kind, "📄")
            thumb_html = (
                "<div style='aspect-ratio:1/1;display:flex;align-items:center;"
                "justify-content:center;background:var(--surface-2);"
                "border-radius:8px;font-size:32px;color:var(--muted);'>"
                f"{icon}</div>"
            )

        tile = (
            "<div style='border:1px solid var(--line);border-radius:10px;"
            "padding:10px;background:var(--surface);'>"
            + thumb_html
            + f"<div style='margin-top:8px;font-size:12px;'>"
            f"<div class='mono'><b>{H.esc(sku)}</b></div>"
            f"<div class='muted' style='font-size:11px;'>{H.esc(model)}</div>"
            f"<div class='muted' style='font-size:11px;'>"
            f"${cost:,.3f} · {H.fmt_rel(ts)}</div>"
            "</div></div>"
        )
        tiles.append(tile)

    grid = (
        "<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));"
        "gap:12px;'>" + "".join(tiles) + "</div>"
    )

    folder_link = "file://" + str(Path.home() / ".commerce-os" / "assets")
    return H.section(
        "资产",
        header + grid,
        action_link=(folder_link, "查看全部 →"),
    )


# ---------- index ----------
def render_index(ctx: dict) -> str:
    stores = ctx["stores"]
    campaigns = ctx["active_campaigns"]
    events = ctx["recent_events"]
    runs = ctx["recent_runs"]
    kpis = ctx["kpis"]

    if not stores:
        body = H.page_head(
            "还没有店铺 · Lumicc",
            "跑一次 lumicc 主 skill 让它问你几个问题，就会创建第一家店。",
        )
        body += H.empty_state(
            "运行 init_store.py 创建第一家店铺",
            "python3 ~/.commerce-os/skills/lumicc/scripts/init_store.py",
        )
        return _wrap(title="概览", active="index", body=body, store_count=0)

    first = stores[0]
    subtitle = (
        f"{H.esc(first.get('platform', '—'))} · "
        f"{H.esc(STAGE_LABEL.get(first.get('stage'), first.get('stage') or '未知'))} · "
        f"{H.esc(first.get('niche', '—'))} · "
        f"{H.esc((first.get('target_market') or '—').upper())}"
    )
    if first.get("url"):
        subtitle += f" · <a href='{H.esc(first['url'])}' target='_blank' rel='noopener'>{H.esc(first['url'])}</a>"
    head = H.page_head(first.get("name", "店铺"), subtitle)

    kpi_strip = H.kpi_strip([
        (kpis["stores"], "店铺", None, "emerald"),
        (kpis["active_campaigns"], "运行中的活动", None, "sky"),
        (kpis["runs_7d"], "本周 skill 跑次", None, "amber"),
        (kpis["events_7d"], "本周事件", None, "indigo"),
    ])

    # Active campaigns
    if campaigns:
        cards = []
        for c in campaigns:
            try:
                plan = json.loads(c.get("results_json") or "{}")
            except json.JSONDecodeError:
                plan = {}
            day = max(1, (int(time.time()) - (c.get("started_at") or int(time.time()))) // 86400 + 1)
            schedule = plan.get("schedule", [])
            day_total = len(schedule) or 30
            pct = min(100, int(day / max(day_total, 1) * 100))
            today = next((d for d in schedule if d.get("day") == day), None)
            tasks_html = ""
            if today:
                tasks_html = (
                    "<div class='card-sub'>今日 · " + H.esc(today.get("phase", "—")) + "</div>"
                    + "<ul class='task-list'>"
                    + "".join(f"<li>{H.esc(t)}</li>" for t in today.get("tasks", []))
                    + "</ul>"
                )
            progress = (
                f"<div class='progress'><div class='progress-bar' style='--pct:{pct}%'></div></div>"
                f"<div class='progress-meta'>Day {day} / {day_total} · 完成 {pct}%</div>"
            )
            cards.append(H.card(
                title=f"活动 · {H.esc((c.get('id', '—'))[:8])}",
                tag=c.get("type", "—"),
                tag_color="emerald" if c.get("status") == "running" else "sky",
                status=c.get("status"),
                meta=f"开始于 {H.fmt_rel(c.get('started_at'))} · 预算 {_fmt_money(c.get('budget_usd'))}",
                body=progress + tasks_html,
            ))
        campaigns_block = H.section(
            "运行中的活动",
            H.card_grid(cards, min_width=300),
            action_link=("campaigns.html", "查看全部 →"),
        )
    else:
        campaigns_block = H.section(
            "运行中的活动",
            H.empty_state(
                "还没有运行中的活动",
                "跑 lumicc-launch 开启 30 天 cold-start，或调用 lumicc-watch 添加竞品监控。",
            ),
        )

    # Recent events table
    if events:
        rows = [
            [
                f"<span class='mono muted'>{H.fmt_rel(e.get('ts'))}</span>",
                _status_badge(e.get("category")),
                H.esc(e.get("content", "")),
            ]
            for e in events[:8]
        ]
        events_block = H.table(headers=["时间", "类型", "内容"], rows=rows)
    else:
        events_block = H.empty_state("还没有事件记录。")
    events_section = H.section(
        "最近活动", events_block,
        action_link=("memory.html", "完整日志 →"),
    )

    # Recent runs table
    if runs:
        rows = [
            [
                f"<span class='mono muted'>{H.fmt_rel(r.get('started_at'))}</span>",
                f"<span class='mono'>{H.esc(r.get('skill', '—'))}</span>",
                _status_badge(r.get("status")),
                f"<span class='mono muted'>{H.esc((r.get('run_id', '—'))[:8])}</span>",
            ]
            for r in runs[:6]
        ]
        runs_block = H.table(headers=["时间", "Skill", "状态", "运行 ID"], rows=rows)
    else:
        runs_block = H.empty_state("还没有 skill 跑过。")
    runs_section = H.section(
        "最近 skill 跑次", runs_block,
        action_link=("runs.html", "完整历史 →"),
    )

    secrets_section = _render_secrets_section()
    assets_section = _render_assets_section()

    body = head + kpi_strip + campaigns_block + events_section + runs_section + secrets_section + assets_section
    return _wrap(title="概览", active="index", body=body, store_count=len(stores))


# ---------- stores ----------
def render_stores(ctx: dict) -> str:
    stores = ctx["stores"]
    products_by_store = ctx["products_by_store"]
    events_by_store = ctx["events_by_store"]

    head = H.page_head("店铺", f"共 {len(stores)} 家店铺")
    if not stores:
        body = head + H.empty_state(
            "还没有店铺。",
            "运行 python3 scripts/init_store.py 创建第一家。",
        )
        return _wrap(title="店铺", active="stores", body=body, store_count=0)

    sections = ""
    for s in stores:
        products = products_by_store.get(s["id"], [])
        events = events_by_store.get(s["id"], [])

        prod_rows = [
            [
                f"<span class='mono'>{H.esc(p.get('sku', '—'))}</span>",
                H.esc(p.get("title", "—")),
                _status_badge(p.get("status")),
                f"<span class='mono'>{_fmt_money(p.get('cost_usd'))}</span>",
                f"<span class='mono'>{_fmt_money(p.get('price_usd'))}</span>",
            ]
            for p in products
        ]
        prod_block = (
            H.table(headers=["SKU", "标题", "状态", "成本", "售价"], rows=prod_rows)
            if prod_rows
            else H.empty_state("还没有商品。")
        )

        evt_rows = [
            [
                f"<span class='mono muted'>{H.fmt_rel(e.get('ts'))}</span>",
                _status_badge(e.get("category")),
                H.esc(e.get("content", "")),
            ]
            for e in events[:10]
        ]
        evt_block = (
            H.table(headers=["时间", "类型", "内容"], rows=evt_rows)
            if evt_rows
            else H.empty_state("还没有事件。")
        )

        store_subtitle = " · ".join(filter(None, [
            H.esc(s.get("platform", "—")),
            H.esc(STAGE_LABEL.get(s.get("stage"), s.get("stage") or "—")),
            H.esc((s.get("target_market") or "—").upper()),
        ]))
        if s.get("url"):
            store_subtitle += (
                f" · <a href='{H.esc(s['url'])}' target='_blank' rel='noopener'>{H.esc(s['url'])}</a>"
            )

        sections += H.section(
            H.esc(s.get("name", "—")),
            f"<p class='muted' style='margin:-6px 0 18px;font-size:13px;'>{store_subtitle}</p>"
            + f"<h3 class='subhead'>商品（{len(products)}）</h3>" + prod_block
            + f"<h3 class='subhead'>最近事件</h3>" + evt_block,
        )

    body = head + sections
    return _wrap(title="店铺", active="stores", body=body, store_count=len(stores))


# ---------- campaigns ----------
def render_campaigns(ctx: dict) -> str:
    camps = ctx["campaigns"]
    store_count = ctx.get("store_count", 0)
    head = H.page_head("运营活动", f"共 {len(camps)} 个活动")

    if not camps:
        body = head + H.empty_state("还没有活动。")
        return _wrap(title="运营活动", active="campaigns", body=body, store_count=store_count)

    cards = []
    for c in camps:
        try:
            plan = json.loads(c.get("results_json") or "{}")
        except json.JSONDecodeError:
            plan = {}
        schedule = plan.get("schedule", [])
        day_total = len(schedule) or 30
        if c.get("status") == "running":
            day = max(1, (int(time.time()) - (c.get("started_at") or int(time.time()))) // 86400 + 1)
            pct = min(100, int(day / max(day_total, 1) * 100))
        else:
            day = day_total
            pct = 100 if c.get("status") == "done" else 0

        progress = (
            f"<div class='progress'><div class='progress-bar' style='--pct:{pct}%'></div></div>"
            f"<div class='progress-meta'>Day {day} / {day_total} · {pct}%</div>"
        )
        cards.append(H.card(
            title=f"活动 · {H.esc((c.get('id', '—'))[:8])}",
            tag=c.get("type", "—"),
            tag_color="emerald" if c.get("status") == "running" else "zinc",
            status=c.get("status"),
            meta=f"开始于 {H.fmt_ts(c.get('started_at'))} · 预算 {_fmt_money(c.get('budget_usd'))}",
            body=progress,
        ))
    body = head + H.card_grid(cards, min_width=300)
    return _wrap(title="运营活动", active="campaigns", body=body, store_count=store_count)


# ---------- runs ----------
def render_runs(ctx: dict) -> str:
    runs = ctx["runs"]
    store_count = ctx.get("store_count", 0)
    head = H.page_head("Skill 运行历史", f"共 {len(runs)} 条记录 · 按时间倒序")

    if not runs:
        body = head + H.empty_state("还没有 skill 跑过。")
        return _wrap(title="跑次记录", active="runs", body=body, store_count=store_count)

    rows = []
    for r in runs:
        deliv = "—"
        result_path = r.get("result_path")
        try:
            if result_path:
                p = Path(result_path)
                if p.exists():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    items = data.get("deliverables") or []
                    if isinstance(items, list) and items:
                        deliv = " · ".join(H.esc(i.get("type", "?")) for i in items[:3])
        except (json.JSONDecodeError, OSError):
            pass
        rows.append([
            f"<span class='mono muted'>{H.fmt_ts(r.get('started_at'))}</span>",
            f"<span class='mono'>{H.esc(r.get('skill', '—'))}</span>",
            _status_badge(r.get("status")),
            f"<span class='mono muted'>{H.esc((r.get('run_id', '—'))[:12])}</span>",
            f"<span class='muted'>{deliv}</span>",
        ])
    body = head + H.table(headers=["开始时间", "Skill", "状态", "运行 ID", "产出物"], rows=rows)
    return _wrap(title="跑次记录", active="runs", body=body, store_count=store_count)


# ---------- memory ----------
def render_memory(ctx: dict) -> str:
    events = ctx["events"]
    insights = ctx["insights"]
    soul = ctx["soul"]
    daily_logs = ctx["daily_logs"]
    store_count = ctx.get("store_count", 0)

    # Layer 1 — events tab
    if events:
        rows = [
            [
                f"<span class='mono muted'>{H.fmt_ts(e.get('ts'))}</span>",
                _status_badge(e.get("category")),
                f"<span class='mono muted'>{H.esc((e.get('store_id') or '—')[:8])}</span>",
                H.esc(e.get("content", "")),
            ]
            for e in events[:50]
        ]
        events_tab = H.table(headers=["时间", "类型", "店铺", "内容"], rows=rows)
    else:
        events_tab = H.empty_state("还没有事件。")

    # Layer 1 — daily logs tab
    if daily_logs:
        daily_html = ""
        for d in daily_logs[:7]:
            content = d["content"] or ""
            short = content[:1200]
            truncated = "\n…（已截断）" if len(content) > 1200 else ""
            daily_html += (
                f"<details class='daily-log'><summary>{H.esc(d['date'])} "
                f"<span class='muted'>({len(content)} 字符)</span></summary>"
                f"<pre class='md-snippet'>{H.esc(short + truncated)}</pre></details>"
            )
        daily_tab = daily_html
    else:
        daily_tab = H.empty_state(
            "还没有日志。",
            "Lumicc 会在每次决策时追加事件到当天的 .md 文件。",
        )

    # Layer 2 — insights tab
    if insights:
        cards = []
        for ins in insights:
            conf_pct = int((ins.get("confidence") or ins.get("置信度") or 0) * 100)
            body_html = (
                f"<div style='font-size:13.5px;line-height:1.6;'>"
                f"{H.esc(ins.get('content', ''))}</div>"
                f"<div class='confidence' style='margin-top:14px;'>"
                f"<div class='confidence-bar' style='--pct:{conf_pct}%'></div>"
                f"<span class='mono muted'>{conf_pct}% 置信度</span></div>"
            )
            cards.append(H.card(
                title=H.esc(ins.get("category", "—")),
                tag=f"×{ins.get('verified_count', 1)} verified",
                tag_color="indigo",
                body=body_html,
            ))
        insights_tab = H.card_grid(cards, min_width=320)
    else:
        insights_tab = H.empty_state(
            "还没有 curated insight。",
            "当同一模式被验证 ≥ 2 次后会自动加入。",
        )

    # Layer 3 — SOUL tab
    soul_tab = H.card(
        title="用户编辑的铁律",
        tag="SOUL.md",
        tag_color="indigo",
        body=f"<pre class='md-snippet'>{H.esc(soul or '(空 — 编辑 ~/.commerce-os/SOUL.md 来添加你的运营铁律)')}</pre>",
    )

    head = H.page_head(
        "记忆 · 三层结构",
        "业务事实存储 — 与 agent 原生 memory 完全独立",
    )

    tabs_html = H.tabs([
        ("events", f"Layer 1 · Events ({len(events)})", events_tab),
        ("daily", f"Layer 1 · Daily logs ({len(daily_logs)})", daily_tab),
        ("insights", f"Layer 2 · Insights ({len(insights)})", insights_tab),
        ("soul", "Layer 3 · SOUL", soul_tab),
    ])

    body = head + tabs_html
    return _wrap(title="记忆系统", active="memory", body=body, store_count=store_count)
