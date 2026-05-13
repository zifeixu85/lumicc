#!/usr/bin/env python3
"""Lumicc shared HTML component library.

A single-file, stdlib-only set of helpers used by every Lumicc sub-skill that
emits HTML reports. Centralized here so:

1. **Visual consistency** — every page looks like the same product
2. **Token efficiency** — sub-skill HTML generators stay small, just compose pieces
3. **Maintainability** — change colors/fonts/components once, all pages update

Usage from a sub-skill (assumes the main `lumicc` skill is installed alongside):

    import sys
    from pathlib import Path
    LUMICC_SCRIPTS = Path(__file__).parent.parent.parent / "lumicc" / "scripts"
    sys.path.insert(0, str(LUMICC_SCRIPTS))
    import html_lib as H

    body = H.section("KPIs", H.kpi_strip([
        ("Stores", 3, "active"),
        ("Revenue", "$5,200", "MRR"),
    ])) + H.section("Recent runs", H.table(
        ["Time", "Skill", "Status"],
        [[H.fmt_rel(r["ts"]), r["skill"], H.badge(r["status"])] for r in runs],
    ))

    html = H.page(title="My Store", active="overview", body=body)
    Path("report.html").write_text(html, encoding="utf-8")
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

VERSION = "0.1.0"

# =============================================================================
# Helpers
# =============================================================================

def esc(s: Any) -> str:
    """HTML-escape any value. None → empty string."""
    if s is None:
        return ""
    return _html.escape(str(s), quote=True)


_IMAGE_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def _svg_placeholder(text: str) -> str:
    """Inline SVG data: URI with the given placeholder text."""
    safe = _html.escape(text, quote=True).replace("#", "%23")
    return (
        "data:image/svg+xml;utf8,"
        "<svg xmlns='http://www.w3.org/2000/svg' width='200' height='40'>"
        f"<text x='10' y='25' fill='%239aa4b2' font-family='monospace' "
        f"font-size='12'>{safe}</text></svg>"
    )


def embed_image(path: str | Path, max_kb: int = 500,
                placeholder: str = "[图过大，请查看本地文件]") -> str:
    """Read a local image file and return a data:image/...;base64,... URI string.

    Args:
        path: absolute path to local image
        max_kb: refuse to embed images larger than this; return placeholder text
        placeholder: shown in lieu of a real img src when oversize / missing

    Returns:
        A string suitable for use as <img src="...">. Either a data: URI or
        a small inline SVG placeholder.
    """
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return _svg_placeholder(placeholder)
        size = p.stat().st_size
        if size > max_kb * 1024:
            return _svg_placeholder(placeholder)
        mime = _IMAGE_MIME_MAP.get(p.suffix.lower(), "application/octet-stream")
        content = p.read_bytes()
        b64 = base64.b64encode(content).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except (OSError, ValueError):
        return _svg_placeholder(placeholder)


def fmt_ts(ts: int | float | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not ts:
        return "—"
    try:
        return time.strftime(fmt, time.localtime(int(ts)))
    except (ValueError, OSError):
        return "—"


def fmt_rel(ts: int | float | None) -> str:
    """Relative time: '3m ago' / '2h ago' / '5d ago' / fallback to absolute."""
    if not ts:
        return "—"
    delta = int(time.time() - int(ts))
    if delta < 0:
        delta = 0
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    if delta < 7 * 86400:
        return f"{delta // 86400}d ago"
    return fmt_ts(ts, "%Y-%m-%d")


def fmt_currency(amount: float | int | None, currency: str = "USD") -> str:
    if amount is None:
        return "—"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "CNY": "¥", "JPY": "¥"}.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"


def fmt_pct(ratio: float | None, decimals: int = 1) -> str:
    if ratio is None:
        return "—"
    return f"{ratio * 100:.{decimals}f}%"


def rel_path(target: Path | str, html_dir: Path) -> str:
    """Compute filesystem-relative path so HTML stays valid when files are moved."""
    try:
        return os.path.relpath(str(target), str(html_dir)).replace(os.sep, "/")
    except ValueError:
        return f"file://{target}"


# =============================================================================
# Status badges
# =============================================================================

BADGE_COLORS = {
    # Semantic
    "success": "emerald", "running": "emerald", "active": "emerald", "pass": "emerald",
    "completed": "emerald", "champions": "emerald", "loyal": "emerald", "healthy": "emerald",
    "planned": "sky", "info": "sky", "new": "sky",
    "warn": "amber", "warning": "amber", "partial": "amber", "draft": "amber",
    "paused": "amber", "improvable": "amber", "skeleton": "amber", "at risk": "amber",
    "failed": "rose", "error": "rose", "fail": "rose", "cancelled": "rose",
    "removed": "rose", "sick": "rose", "lost": "rose", "critical": "rose",
    "decision": "indigo", "task": "indigo", "promising": "indigo",
    "observation": "zinc", "done": "zinc",
}


def badge(text: str | None, color: str | None = None) -> str:
    """Render a status pill. Color auto-detected from text if not given.

    Available colors: emerald, sky, amber, rose, indigo, zinc.
    """
    if text is None or text == "":
        return '<span class="tag tag-zinc">—</span>'
    if color is None:
        color = BADGE_COLORS.get(str(text).lower().strip(), "zinc")
    return f'<span class="tag tag-{color}">{esc(text)}</span>'


# =============================================================================
# Layout primitives
# =============================================================================

NAV_DEFAULT = [
    ("../../../dashboard/index.html", "概览"),
    ("../../../dashboard/stores.html", "店铺"),
    ("../../../dashboard/campaigns.html", "活动"),
    ("../../../dashboard/runs.html", "跑次"),
    ("../../../dashboard/memory.html", "记忆"),
]


def page(*, title: str, body: str, active: str | None = None,
         brand_subtitle: str = "Cross-Border Commerce OS",
         back_link: str | None = "../../../dashboard/index.html",
         back_text: str = "← 返回仪表盘",
         right_meta: str = "",
         show_nav: bool = False,
         theme: str | None = None) -> str:
    """Wrap a page body in the canonical Lumicc HTML shell.

    `theme`: optional theme name override. If None, resolved via:
      1. env var LUMICC_THEME
      2. ~/.commerce-os/design.md (`## Theme: name`)
      3. default 'midnight-emerald'
    """
    nav_html = ""
    if show_nav:
        nav_items = []
        for href, label in NAV_DEFAULT:
            cls = "nav-link active" if active and active.lower() in label.lower() else "nav-link"
            nav_items.append(f'<a href="{esc(href)}" class="{cls}">{esc(label)}</a>')
        nav_html = '<nav class="nav">' + "".join(nav_items) + "</nav>"

    back_html = (
        f'<a href="{esc(back_link)}" class="topbar-back">{esc(back_text)}</a>'
        if back_link else ""
    )

    css_text = get_css(theme)
    theme_name = resolve_theme_name(theme)

    return f"""<!doctype html>
<html lang="zh-CN" data-theme="{esc(theme_name)}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{esc(title)} · Lumicc</title>
<style>{css_text}</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.06 0"/></filter>
  </defs>
</svg>
<div class="grain-overlay" aria-hidden="true"></div>
<header class="topbar">
  <div class="container topbar-row">
    <a href="../../../dashboard/index.html" class="brand">
      <span class="brand-mark"><span class="brand-mark-glyph">L</span></span>
      <span class="brand-text">
        <span class="brand-name">Lumicc</span>
        <span class="brand-tag">{esc(brand_subtitle)}</span>
      </span>
    </a>
    {nav_html}
    <div class="topbar-right">
      {back_html}
      <span class="topbar-meta">{esc(right_meta)}</span>
      <div class="theme-switch" role="radiogroup" aria-label="切换主题">
        <button type="button" class="ts-btn" data-set-theme="midnight-emerald" title="Midnight Emerald — 编辑深色" aria-label="Midnight Emerald"></button>
        <button type="button" class="ts-btn" data-set-theme="linen-warm" title="Linen Warm — 杂志暖白" aria-label="Linen Warm"></button>
        <button type="button" class="ts-btn" data-set-theme="slate-premium" title="Slate Premium — 深蓝金箔" aria-label="Slate Premium"></button>
        <button type="button" class="ts-btn" data-set-theme="dawn-coral" title="Dawn Coral — 黎明赤陶" aria-label="Dawn Coral"></button>
      </div>
    </div>
  </div>
</header>
<main class="container main">
{body}
</main>
<footer class="footer">
  <div class="container footer-row">
    <span class="footer-mark">~/.commerce-os/</span>
    <span class="footer-divider">·</span>
    <span>static</span>
    <span class="footer-divider">·</span>
    <span>privacy-first</span>
    <span class="footer-divider">·</span>
    <span>no telemetry</span>
    <span class="footer-spacer"></span>
    <span class="footer-meta">Generated {fmt_ts(int(time.time()))}</span>
  </div>
</footer>
<div id="toast" class="toast"></div>
<script>{JS}</script>
</body>
</html>"""


def container(body: str) -> str:
    return f'<div class="container">{body}</div>'


def page_head(title: str, subtitle: str = "") -> str:
    sub = f'<p class="page-meta">{esc(subtitle)}</p>' if subtitle else ""
    return f'<section class="page-head"><h1>{esc(title)}</h1>{sub}</section>'


def section(title: str = "", body: str = "", action_link: tuple[str, str] | None = None) -> str:
    """Generic section with optional title + body + top-right action link."""
    head = ""
    if title or action_link:
        action = ""
        if action_link:
            href, label = action_link
            action = f'<a href="{esc(href)}" class="section-link">{esc(label)}</a>'
        title_html = f"<h2>{esc(title)}</h2>" if title else "<span></span>"
        head = f'<div class="section-head">{title_html}{action}</div>'
    return f'<section class="section">{head}{body}</section>'


# =============================================================================
# KPI strip
# =============================================================================

def kpi_card(value: Any, label: str, hint: str = "", color: str = "") -> str:
    color_cls = f" kpi-{color}" if color else ""
    hint_html = f'<div class="kpi-hint">{esc(hint)}</div>' if hint else ""
    return (
        f'<div class="kpi-card{color_cls}">'
        f'<div class="kpi-value">{esc(value)}</div>'
        f'<div class="kpi-label">{esc(label)}</div>'
        f'{hint_html}</div>'
    )


def kpi_strip(items: Iterable[tuple]) -> str:
    """items: list of (value, label) or (value, label, hint) or (value, label, hint, color)."""
    cards = []
    for it in items:
        if len(it) == 2:
            cards.append(kpi_card(it[0], it[1]))
        elif len(it) == 3:
            cards.append(kpi_card(it[0], it[1], it[2]))
        elif len(it) >= 4:
            cards.append(kpi_card(it[0], it[1], it[2], it[3]))
    return f'<section class="kpi-grid">{"".join(cards)}</section>'


# =============================================================================
# Cards
# =============================================================================

def card(*, title: str = "", tag: str = "", tag_color: str = "zinc",
         status: str | None = None, meta: str = "", body: str = "",
         actions: list[str] | None = None, klass: str = "") -> str:
    head_parts: list[str] = []
    if title:
        head_parts.append(f'<div class="card-title">{esc(title)}</div>')
    if tag:
        head_parts.append(f'<span class="tag tag-{tag_color}">{esc(tag)}</span>')
    if status:
        head_parts.append(badge(status))
    head_html = (
        f'<div class="card-head">{"".join(head_parts)}</div>' if head_parts else ""
    )
    meta_html = f'<div class="card-meta">{meta}</div>' if meta else ""
    actions_html = ""
    if actions:
        actions_html = f'<div class="actions">{"".join(actions)}</div>'
    return (
        f'<div class="card {esc(klass)}">'
        f'{head_html}<div class="card-body">{meta_html}{body}</div>'
        f'{actions_html}</div>'
    )


def card_grid(cards: list[str], min_width: int = 280) -> str:
    """Auto-fill responsive grid."""
    style = f'style="grid-template-columns: repeat(auto-fill, minmax({min_width}px, 1fr));"'
    return f'<div class="card-grid" {style}>{"".join(cards)}</div>'


def empty_state(text: str, hint: str = "") -> str:
    hint_html = f"<br><small>{esc(hint)}</small>" if hint else ""
    return f'<div class="empty-state">{esc(text)}{hint_html}</div>'


# =============================================================================
# Tables
# =============================================================================

def table(headers: list[str], rows: list[list[Any]],
          align: list[str] | None = None,
          empty_message: str = "—") -> str:
    """Render a data table. Headers/rows can contain HTML directly.

    `align`: optional list of 'left' | 'right' | 'center' per column.
    """
    if align is None:
        align = ["left"] * len(headers)

    thead = "<tr>" + "".join(
        f'<th style="text-align:{esc(align[i] if i < len(align) else "left")}">{esc(h)}</th>'
        for i, h in enumerate(headers)
    ) + "</tr>"

    if not rows:
        body = (
            f'<tr><td colspan="{len(headers)}" class="empty-state-row">'
            f'{esc(empty_message)}</td></tr>'
        )
    else:
        body = ""
        for row in rows:
            cells = []
            for i, c in enumerate(row):
                a = align[i] if i < len(align) else "left"
                cells.append(f'<td style="text-align:{esc(a)}">{c if isinstance(c, str) else esc(c)}</td>')
            body += "<tr>" + "".join(cells) + "</tr>"

    return f'<table class="data-table"><thead>{thead}</thead><tbody>{body}</tbody></table>'


# =============================================================================
# Progress + confidence bars
# =============================================================================

def progress_bar(pct: float, label: str = "") -> str:
    """pct: 0-100. Returns animated bar."""
    pct = max(0, min(100, pct))
    label_html = f'<div class="progress-meta">{esc(label)}</div>' if label else ""
    return (
        f'<div class="progress"><div class="progress-bar" style="--pct:{pct}%"></div></div>'
        f'{label_html}'
    )


def confidence_bar(pct: float) -> str:
    """0-100 colored amber→emerald."""
    pct = max(0, min(100, pct))
    return (
        f'<div class="confidence">'
        f'<div class="confidence-bar" style="--pct:{pct}%"></div>'
        f'<span class="muted mono">{pct:.0f}% confidence</span></div>'
    )


# =============================================================================
# Filter row + Tabs
# =============================================================================

def filter_row(categories: list[tuple[str, str]], active: str = "all") -> str:
    """A horizontal filter bar. categories: list of (cat_key, label).

    Always prepended with a "全部" / All button.
    """
    items = [("all", "全部")] + categories
    btns = []
    for key, label in items:
        cls = "filter-btn active" if key == active else "filter-btn"
        btns.append(
            f'<button class="{cls}" data-cat="{esc(key)}" '
            f"onclick=\"filterCategory('{esc(key)}')\">{esc(label)}</button>"
        )
    return f'<div class="filter-row">{"".join(btns)}</div>'


def tabs(tab_definitions: list[tuple[str, str, str]], default: str | None = None) -> str:
    """Tab switcher. Each tab: (key, label, content_html).

    Renders the tab bar AND the panels.
    """
    if not tab_definitions:
        return ""
    default_key = default or tab_definitions[0][0]
    nav = '<div class="tabs" data-tabs>'
    for key, label, _ in tab_definitions:
        cls = "tab active" if key == default_key else "tab"
        nav += f'<button data-tab="{esc(key)}" class="{cls}">{esc(label)}</button>'
    nav += "</div>"
    panels = ""
    for key, _, content in tab_definitions:
        hidden = "" if key == default_key else " hidden"
        panels += f'<section class="tab-panel{hidden}" data-panel="{esc(key)}">{content}</section>'
    return nav + panels


# =============================================================================
# Action buttons
# =============================================================================

def copy_button(text_to_copy: str, label: str = "📋 复制",
                style: str = "primary") -> str:
    safe = json.dumps(text_to_copy, ensure_ascii=False)
    return f'<button class="btn {esc(style)}" onclick="copyText(this, {esc(safe)})">{esc(label)}</button>'


def download_link(local_path: str, html_dir: Path | str,
                  label: str = "⬇️ 下载") -> str:
    rel = rel_path(local_path, Path(html_dir))
    return f'<a class="btn" href="{esc(rel)}" download>{esc(label)}</a>'


def external_link(url: str, label: str | None = None,
                  style: str = "ghost") -> str:
    label = label or url
    return (
        f'<a class="btn {esc(style)}" href="{esc(url)}" target="_blank" '
        f'rel="noopener">{esc(label)} ↗</a>'
    )


def collapsible(summary: str, body: str, open_: bool = False) -> str:
    open_attr = " open" if open_ else ""
    return (
        f'<details class="daily-log"{open_attr}>'
        f'<summary>{esc(summary)}</summary>{body}</details>'
    )


# =============================================================================
# Specialized visualizations
# =============================================================================

def sparkline(values: list[float], *, width: int = 120, height: int = 28,
              color: str = "#34d399", stroke: int = 2) -> str:
    """Inline SVG mini-line chart. Best for trend per row in a table."""
    if not values:
        return f'<span class="muted mono">—</span>'
    vmin = min(values)
    vmax = max(values)
    rng = max(0.0001, vmax - vmin)
    n = len(values)
    points = []
    for i, v in enumerate(values):
        x = (i / max(1, n - 1)) * width
        y = height - ((v - vmin) / rng) * height
        points.append(f"{x:.1f},{y:.1f}")
    path = " ".join(points)
    return (
        f'<svg viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" '
        f'style="display:inline-block;vertical-align:middle">'
        f'<polyline fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round" points="{path}"/>'
        f'</svg>'
    )


def heatmap_cell(value: float, *, label: str = "", tooltip: str = "",
                 scale: tuple[float, float] = (0, 1.0)) -> str:
    """One cell of a heatmap. value 0..1 → opacity. label shown centered."""
    lo, hi = scale
    norm = 0.0 if hi == lo else max(0, min(1, (value - lo) / (hi - lo)))
    opacity = 0.10 + norm * 0.75
    color = f"rgba(16,185,129,{opacity:.3f})"
    title_attr = f' title="{esc(tooltip)}"' if tooltip else ""
    return (
        f'<td class="heatmap-cell"{title_attr} '
        f'style="background:{color}">{esc(label)}</td>'
    )


def timeline(entries: list[dict]) -> str:
    """entries: list of {ts, title, body?, severity?}

    Renders a vertical timeline with markers.
    """
    if not entries:
        return empty_state("No events.")
    items = []
    for e in entries:
        sev = (e.get("severity") or "info").lower()
        color_class = {"info": "tl-info", "warn": "tl-warn", "error": "tl-error",
                       "decision": "tl-decision"}.get(sev, "tl-info")
        body = e.get("body", "")
        body_html = f'<div class="tl-body">{esc(body)}</div>' if body else ""
        items.append(
            f'<div class="timeline-row"><div class="tl-marker {color_class}"></div>'
            f'<div class="tl-content"><div class="tl-head">'
            f'<span class="tl-ts">{esc(fmt_rel(e.get("ts")))}</span>'
            f'<span class="tl-title">{esc(e.get("title", ""))}</span></div>'
            f'{body_html}</div></div>'
        )
    return f'<div class="timeline">{"".join(items)}</div>'


# =============================================================================
# Modal (warning / opt-in confirmation)
# =============================================================================

def modal(modal_id: str, title: str, body_html: str,
          buttons: list[str] | None = None) -> str:
    btn_html = "".join(buttons or [])
    return f"""
<div id="{esc(modal_id)}" class="modal-overlay" onclick="if(event.target===this) closeModal('{esc(modal_id)}')">
  <div class="modal">
    <h2>{esc(title)}</h2>
    {body_html}
    <div class="modal-actions">{btn_html}</div>
  </div>
</div>"""


# =============================================================================
# Theme system
# =============================================================================

# Default tokens (midnight-emerald). Other themes override these.
TOKENS_DEFAULT = {
    # === midnight-emerald — Bloomberg Terminal × Apothecary ===
    "tone": "dark",
    "brand-style": "tech",
    # Palette
    "bg": "#0a0d12",
    "bg-alt": "#0d1117",
    "surface": "#11161d",
    "surface-2": "#171d26",
    "surface-3": "#1f2632",
    "line": "#252d3a",
    "line-soft": "#1b212a",
    "line-strong": "#323b4a",
    "ink": "#e9eef5",
    "ink-strong": "#fafcff",
    "ink-muted": "#9aa4b2",
    "ink-dim": "#6b7585",
    "ink-faint": "#4a5260",
    # Accents — emerald lead, violet + amber support, rose for risk
    "accent": "#34d399",
    "accent-soft": "#6ee7b7",
    "accent-deep": "#059669",
    "accent-glow": "rgba(52,211,153,0.20)",
    "accent-2": "#a78bfa",
    "accent-3": "#fbbf24",
    "sky": "#60a5fa",
    "amber": "#fbbf24",
    "rose": "#fb7185",
    "indigo": "#a78bfa",
    # Typography — system fonts only. Numbers use SF Pro Display / Segoe UI Variable
    # with tabular-nums for clean tabular display.
    "font-display": "ui-serif,'Iowan Old Style','Palatino Linotype',Palatino,'Songti SC','STSong',Georgia,'Times New Roman',serif",
    "font": "-apple-system,BlinkMacSystemFont,'SF Pro Text','Helvetica Neue','PingFang SC','Microsoft YaHei',system-ui,sans-serif",
    "font-num": "-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue','Segoe UI Variable','Segoe UI',system-ui,sans-serif",
    "mono": "ui-monospace,'SF Mono','Cascadia Mono',Menlo,Consolas,monospace",
    "font-features": "'tnum' 1, 'lnum' 1",
    "display-weight": "600",
    "display-tracking": "-0.025em",
    "eyebrow-tracking": "0.18em",
    # Geometry
    "radius": "10px",
    "radius-lg": "16px",
    "radius-sharp": "3px",
    # Atmosphere
    "body-bg-image": (
        "radial-gradient(ellipse 90% 50% at 8% -10%, rgba(52,211,153,0.14), transparent 55%),"
        "radial-gradient(ellipse 70% 50% at 100% 0%, rgba(167,139,250,0.10), transparent 60%),"
        "radial-gradient(ellipse 80% 60% at 50% 110%, rgba(251,191,36,0.05), transparent 70%)"
    ),
    "body-grain": "0.04",
    "card-shadow": "0 1px 0 rgba(255,255,255,0.03) inset, 0 0 0 1px rgba(255,255,255,0.015)",
    "card-hover-shadow": "0 16px 48px -16px rgba(0,0,0,0.7), 0 0 0 1px rgba(52,211,153,0.30), 0 0 32px rgba(52,211,153,0.06)",
    "topbar-bg": "rgba(10,13,18,0.78)",
    "rule-color": "linear-gradient(90deg, transparent, rgba(52,211,153,0.4), transparent)",
    "kbd-bg": "#171d26",
}

THEMES = {
    "midnight-emerald": TOKENS_DEFAULT,

    # === linen-warm — Kinfolk Magazine Editorial ===
    "linen-warm": {
        "tone": "light",
        "brand-style": "editorial",
        "bg": "#f6f1e7",
        "bg-alt": "#efe8d8",
        "surface": "#fdfaf2",
        "surface-2": "#f0e9d8",
        "surface-3": "#e8dfca",
        "line": "#d8cdb3",
        "line-soft": "#e7dec8",
        "line-strong": "#bcae8e",
        "ink": "#1f1a14",
        "ink-strong": "#0f0c08",
        "ink-muted": "#5e5142",
        "ink-dim": "#8a7860",
        "ink-faint": "#b8a486",
        # Deep forest + ink as primary, terracotta + ochre as warm support
        "accent": "#2d5a3d",
        "accent-soft": "#4a7c5e",
        "accent-deep": "#1a3d29",
        "accent-glow": "rgba(45,90,61,0.12)",
        "accent-2": "#a0522d",
        "accent-3": "#b8860b",
        "sky": "#2c5e7f",
        "amber": "#a0522d",
        "rose": "#9b3434",
        "indigo": "#4a4577",
        # Serif everywhere — Kinfolk treatment (system serif stack)
        "font-display": "ui-serif,'Iowan Old Style','Palatino Linotype',Palatino,'Songti SC','STSong',Georgia,'Times New Roman',serif",
        "font": "ui-serif,'Iowan Old Style','Palatino Linotype',Palatino,'Songti SC','Source Han Serif SC',Georgia,'Times New Roman',serif",
        # KPI numbers still use a clean tabular sans for legibility, italic for editorial flavor
        "font-num": "-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue','Segoe UI Variable',system-ui,sans-serif",
        "mono": "ui-monospace,'SF Mono','Cascadia Mono',Menlo,Consolas,monospace",
        "font-features": "'tnum' 1, 'lnum' 1",
        "display-weight": "500",
        "display-tracking": "-0.02em",
        "eyebrow-tracking": "0.22em",
        "radius": "4px",
        "radius-lg": "8px",
        "radius-sharp": "0px",
        "body-bg-image": (
            "radial-gradient(ellipse 60% 40% at 0% 0%, rgba(45,90,61,0.04), transparent 60%),"
            "radial-gradient(ellipse 50% 40% at 100% 20%, rgba(160,82,45,0.05), transparent 65%),"
            "radial-gradient(ellipse 80% 40% at 50% 100%, rgba(184,134,11,0.03), transparent 70%)"
        ),
        "body-grain": "0.08",
        "card-shadow": "0 1px 0 rgba(0,0,0,0.02), 0 1px 3px rgba(31,26,20,0.04)",
        "card-hover-shadow": "0 2px 0 rgba(0,0,0,0.02), 0 12px 36px -12px rgba(31,26,20,0.18)",
        "topbar-bg": "rgba(246,241,231,0.85)",
        "rule-color": "linear-gradient(90deg, transparent, rgba(31,26,20,0.25), transparent)",
        "kbd-bg": "#f0e9d8",
    },

    # === slate-premium — Rolex Boutique × Manhattan Penthouse ===
    "slate-premium": {
        "tone": "dark",
        "brand-style": "luxury",
        "bg": "#0b1220",
        "bg-alt": "#0d1729",
        "surface": "#131c30",
        "surface-2": "#1a2640",
        "surface-3": "#22324f",
        "line": "#2f3f5e",
        "line-soft": "#1f2d47",
        "line-strong": "#c9a45c",
        "ink": "#f3ecd9",
        "ink-strong": "#fffaee",
        "ink-muted": "#a8b2c5",
        "ink-dim": "#7588a3",
        "ink-faint": "#4f5e7a",
        # Champagne gold with deep navy. Gold is THE accent.
        "accent": "#d4af37",
        "accent-soft": "#e9c87a",
        "accent-deep": "#9a7a1f",
        "accent-glow": "rgba(212,175,55,0.22)",
        "accent-2": "#cd7f32",
        "accent-3": "#b08d57",
        "sky": "#8db4d4",
        "amber": "#d4af37",
        "rose": "#d97b7b",
        "indigo": "#9d8fc7",
        # Didot + Hoefler + Bodoni for luxury display (system on macOS), system sans elsewhere
        "font-display": "'Didot','Bodoni 72','Hoefler Text','Big Caslon','Songti SC','STSong',ui-serif,Georgia,'Times New Roman',serif",
        "font": "-apple-system,BlinkMacSystemFont,'SF Pro Text','Helvetica Neue','PingFang SC',system-ui,sans-serif",
        # KPI numbers in clean tabular sans — best for financial-style readouts
        "font-num": "-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue','Segoe UI Variable',system-ui,sans-serif",
        "mono": "ui-monospace,'SF Mono','Cascadia Mono',Menlo,Consolas,monospace",
        "font-features": "'tnum' 1, 'lnum' 1",
        "display-weight": "500",
        "display-tracking": "-0.015em",
        "eyebrow-tracking": "0.28em",
        "radius": "2px",
        "radius-lg": "4px",
        "radius-sharp": "0px",
        "body-bg-image": (
            "radial-gradient(ellipse 70% 40% at 0% 0%, rgba(212,175,55,0.10), transparent 60%),"
            "radial-gradient(ellipse 60% 50% at 100% 0%, rgba(157,143,199,0.06), transparent 65%),"
            "linear-gradient(180deg, transparent 0%, rgba(212,175,55,0.025) 50%, transparent 100%)"
        ),
        "body-grain": "0.05",
        "card-shadow": "0 1px 0 rgba(212,175,55,0.08) inset, 0 0 0 1px rgba(212,175,55,0.06)",
        "card-hover-shadow": "0 24px 64px -16px rgba(0,0,0,0.7), 0 0 0 1px rgba(212,175,55,0.35), 0 0 40px rgba(212,175,55,0.08)",
        "topbar-bg": "rgba(11,18,32,0.85)",
        "rule-color": "linear-gradient(90deg, transparent, rgba(212,175,55,0.55), transparent)",
        "kbd-bg": "#1a2640",
    },

    # === dawn-coral — Aesop Storefront (architectural Mediterranean) ===
    "dawn-coral": {
        "tone": "light",
        "brand-style": "warm",
        "bg": "#f9efe6",
        "bg-alt": "#f4e3d2",
        "surface": "#fdf6ed",
        "surface-2": "#f0e0cd",
        "surface-3": "#e8d3b8",
        "line": "#d9bf9f",
        "line-soft": "#e8d3b8",
        "line-strong": "#a8835a",
        "ink": "#2a1f15",
        "ink-strong": "#180f08",
        "ink-muted": "#6e5945",
        "ink-dim": "#9a8268",
        "ink-faint": "#c9b193",
        # Burnt terracotta + sage + ochre — mature, never childish
        "accent": "#b85c38",
        "accent-soft": "#d97a55",
        "accent-deep": "#8a3f1f",
        "accent-glow": "rgba(184,92,56,0.14)",
        "accent-2": "#6b7d56",
        "accent-3": "#c19a6b",
        "sky": "#5a7d8c",
        "amber": "#c19a6b",
        "rose": "#a64d4d",
        "indigo": "#6e6b9c",
        # Iowan / Palatino serif for headings, system sans body — architectural, considered
        "font-display": "'Iowan Old Style','Palatino Linotype',Palatino,'Songti SC','STSong',ui-serif,Georgia,'Times New Roman',serif",
        "font": "-apple-system,BlinkMacSystemFont,'SF Pro Text','Helvetica Neue','PingFang SC',system-ui,sans-serif",
        "font-num": "-apple-system,BlinkMacSystemFont,'SF Pro Display','Helvetica Neue','Segoe UI Variable',system-ui,sans-serif",
        "mono": "ui-monospace,'SF Mono','Cascadia Mono',Menlo,Consolas,monospace",
        "font-features": "'tnum' 1, 'lnum' 1",
        "display-weight": "500",
        "display-tracking": "-0.01em",
        "eyebrow-tracking": "0.24em",
        "radius": "6px",
        "radius-lg": "10px",
        "radius-sharp": "1px",
        "body-bg-image": (
            "radial-gradient(ellipse 60% 50% at 0% 0%, rgba(184,92,56,0.10), transparent 60%),"
            "radial-gradient(ellipse 50% 40% at 100% 10%, rgba(107,125,86,0.08), transparent 65%),"
            "radial-gradient(ellipse 70% 40% at 50% 100%, rgba(193,154,107,0.06), transparent 70%)"
        ),
        "body-grain": "0.06",
        "card-shadow": "0 1px 0 rgba(184,92,56,0.05), 0 1px 4px rgba(42,31,21,0.05)",
        "card-hover-shadow": "0 2px 0 rgba(184,92,56,0.06), 0 16px 40px -12px rgba(184,92,56,0.18)",
        "topbar-bg": "rgba(249,239,230,0.85)",
        "rule-color": "linear-gradient(90deg, transparent, rgba(184,92,56,0.45), transparent)",
        "kbd-bg": "#f0e0cd",
    },
}


def _parse_design_md(text: str) -> dict:
    """Extract theme + custom overrides from a design.md file.

    Recognized format:
        ## Theme: linen-warm

        ## Custom overrides
        - accent: #0d9488
        - font: "PingFang SC", system-ui

    Returns {"theme": str?, "overrides": dict}.
    """
    import re
    out: dict = {"theme": None, "overrides": {}}
    m = re.search(r"^##\s*Theme\s*:\s*([\w-]+)", text, re.MULTILINE | re.IGNORECASE)
    if m:
        out["theme"] = m.group(1).strip()
    # Find any bullet of form `- key: value`
    for m in re.finditer(r"^-\s*([\w-]+)\s*:\s*(.+)$", text, re.MULTILINE):
        key = m.group(1).strip().lower()
        val = m.group(2).strip().rstrip(",;")
        # Only allow known token names
        if key in TOKENS_DEFAULT:
            out["overrides"][key] = val
    return out


def resolve_theme_name(explicit: str | None = None) -> str:
    """Resolve which theme to use. Order: explicit > env > design.md > default."""
    if explicit:
        return explicit if explicit in THEMES else "midnight-emerald"
    env = os.environ.get("LUMICC_THEME", "").strip()
    if env and env in THEMES:
        return env
    design_md = Path.home() / ".commerce-os" / "design.md"
    if design_md.exists():
        try:
            parsed = _parse_design_md(design_md.read_text(encoding="utf-8"))
            if parsed["theme"] and parsed["theme"] in THEMES:
                return parsed["theme"]
        except Exception:
            pass
    return "midnight-emerald"


def get_theme_tokens(explicit: str | None = None) -> dict:
    """Merge: TOKENS_DEFAULT < theme overrides < design.md custom overrides."""
    name = resolve_theme_name(explicit)
    tokens = {**TOKENS_DEFAULT, **THEMES.get(name, {})}
    # User design.md custom overrides on top
    design_md = Path.home() / ".commerce-os" / "design.md"
    if design_md.exists():
        try:
            parsed = _parse_design_md(design_md.read_text(encoding="utf-8"))
            tokens.update(parsed["overrides"])
        except Exception:
            pass
    tokens["__name__"] = name
    return tokens


def _theme_block(name: str, tokens: dict) -> str:
    """Emit a CSS block for one theme scoped under [data-theme="<name>"].

    Includes the CSS-variable declarations + tone-derived rules + brand-style rules.
    All themes are emitted into every page so the switcher can flip live.
    """
    sel = f'[data-theme="{name}"]'
    lines = [f"{sel} {{"]
    for k, v in tokens.items():
        if k.startswith("_") or k == "tone":
            continue
        lines.append(f"  --{k}: {v};")
    lines.append("}")

    tone = tokens.get("tone", "dark")
    bg_image = tokens.get("body-bg-image", "none")
    card_shadow = tokens.get("card-shadow", "none")
    card_hover_shadow = tokens.get("card-hover-shadow", card_shadow)
    topbar_bg = tokens.get("topbar-bg", "var(--surface)")
    grain_opacity = tokens.get("body-grain", "0")
    brand_style = tokens.get("brand-style", "tech")
    blend = "multiply" if tone == "light" else "screen"

    derived = f"""
{sel} body {{ background-image: {bg_image}; }}
{sel} .grain-overlay {{ opacity: {grain_opacity}; mix-blend-mode: {blend}; }}
{sel} .card {{ box-shadow: {card_shadow}; }}
{sel} .card:hover {{ box-shadow: {card_hover_shadow}; }}
{sel} .topbar {{ background: {topbar_bg}; }}
"""

    if tone == "light":
        derived += f"""
{sel} .tag-emerald {{ background: color-mix(in srgb, var(--accent) 10%, transparent); color: var(--accent-deep); border-color: color-mix(in srgb, var(--accent) 30%, transparent); }}
{sel} .tag-sky     {{ background: color-mix(in srgb, var(--sky) 10%, transparent); color: var(--sky); border-color: color-mix(in srgb, var(--sky) 30%, transparent); }}
{sel} .tag-amber   {{ background: color-mix(in srgb, var(--amber) 12%, transparent); color: var(--amber); border-color: color-mix(in srgb, var(--amber) 35%, transparent); }}
{sel} .tag-rose    {{ background: color-mix(in srgb, var(--rose) 10%, transparent); color: var(--rose); border-color: color-mix(in srgb, var(--rose) 30%, transparent); }}
{sel} .tag-indigo  {{ background: color-mix(in srgb, var(--indigo) 10%, transparent); color: var(--indigo); border-color: color-mix(in srgb, var(--indigo) 30%, transparent); }}
{sel} .tag-zinc    {{ background: var(--surface-2); color: var(--ink-muted); border-color: var(--line); }}
{sel} .btn.primary {{ background: var(--accent); color: var(--surface); }}
{sel} .btn.primary:hover {{ background: var(--accent-deep); color: #fff; }}
{sel} .kpi-card.kpi-emerald {{ background: linear-gradient(160deg, color-mix(in srgb, var(--accent) 6%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--accent) 30%, transparent); }}
{sel} .kpi-card.kpi-amber   {{ background: linear-gradient(160deg, color-mix(in srgb, var(--amber) 6%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--amber) 30%, transparent); }}
{sel} .kpi-card.kpi-rose    {{ background: linear-gradient(160deg, color-mix(in srgb, var(--rose) 6%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--rose) 30%, transparent); }}
{sel} .kpi-card.kpi-sky     {{ background: linear-gradient(160deg, color-mix(in srgb, var(--sky) 6%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--sky) 30%, transparent); }}
{sel} .kpi-card.kpi-indigo  {{ background: linear-gradient(160deg, color-mix(in srgb, var(--indigo) 6%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--indigo) 30%, transparent); }}
{sel} .confidence-bar::after {{ background: linear-gradient(90deg, var(--accent-2, var(--amber)), var(--accent)); }}
{sel} .data-table tbody tr:nth-child(even) td {{ background: color-mix(in srgb, var(--surface-2) 35%, transparent); }}
"""
    else:
        derived += f"""
{sel} .tag-emerald {{ background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent-soft); border-color: color-mix(in srgb, var(--accent) 35%, transparent); }}
{sel} .tag-sky     {{ background: color-mix(in srgb, var(--sky) 18%, transparent); color: color-mix(in srgb, var(--sky) 80%, white); border-color: color-mix(in srgb, var(--sky) 35%, transparent); }}
{sel} .tag-amber   {{ background: color-mix(in srgb, var(--amber) 18%, transparent); color: color-mix(in srgb, var(--amber) 80%, white); border-color: color-mix(in srgb, var(--amber) 35%, transparent); }}
{sel} .tag-rose    {{ background: color-mix(in srgb, var(--rose) 18%, transparent); color: color-mix(in srgb, var(--rose) 80%, white); border-color: color-mix(in srgb, var(--rose) 35%, transparent); }}
{sel} .tag-indigo  {{ background: color-mix(in srgb, var(--indigo) 18%, transparent); color: color-mix(in srgb, var(--indigo) 80%, white); border-color: color-mix(in srgb, var(--indigo) 35%, transparent); }}
{sel} .tag-zinc    {{ background: var(--surface-2); color: var(--ink-muted); border-color: var(--line); }}
{sel} .btn.primary {{ background: var(--accent); color: var(--bg); }}
{sel} .btn.primary:hover {{ background: var(--accent-soft); }}
{sel} .kpi-card.kpi-emerald {{ background: linear-gradient(160deg, color-mix(in srgb, var(--accent) 8%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--accent) 35%, transparent); }}
{sel} .kpi-card.kpi-amber   {{ background: linear-gradient(160deg, color-mix(in srgb, var(--amber) 8%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--amber) 35%, transparent); }}
{sel} .kpi-card.kpi-rose    {{ background: linear-gradient(160deg, color-mix(in srgb, var(--rose) 8%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--rose) 35%, transparent); }}
{sel} .kpi-card.kpi-sky     {{ background: linear-gradient(160deg, color-mix(in srgb, var(--sky) 8%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--sky) 35%, transparent); }}
{sel} .kpi-card.kpi-indigo  {{ background: linear-gradient(160deg, color-mix(in srgb, var(--indigo) 8%, var(--surface)), var(--surface)); border-color: color-mix(in srgb, var(--indigo) 35%, transparent); }}
{sel} .confidence-bar::after {{ background: linear-gradient(90deg, var(--accent-3, var(--amber)), var(--accent)); }}
"""

    if brand_style == "luxury":
        derived += f"""
{sel} .page-head {{ border-bottom: 1px solid transparent; border-image: linear-gradient(90deg, var(--accent), transparent) 1; padding-bottom: 18px; }}
{sel} .brand-mark {{ background: linear-gradient(135deg, var(--accent), var(--accent-deep)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 50%, transparent), 0 2px 12px color-mix(in srgb, var(--accent) 25%, transparent); }}
{sel} .brand-mark-glyph {{ color: var(--bg); font-family: var(--font-display); font-style: italic; font-weight: 700; }}
{sel} .brand-name {{ font-family: var(--font-display); letter-spacing: 0.04em; font-weight: 600; }}
{sel} .section h2 {{ font-weight: 500; }}
"""
    elif brand_style == "editorial":
        derived += f"""
{sel} .brand-mark {{ background: var(--ink); border-radius: 0; }}
{sel} .brand-mark-glyph {{ color: var(--surface); font-family: var(--font-display); font-weight: 600; font-style: italic; }}
{sel} .brand-name {{ font-family: var(--font-display); font-weight: 500; letter-spacing: -0.01em; }}
{sel} .page-head {{ border-bottom: 1px solid var(--line); padding-bottom: 20px; }}
{sel} .section h2 {{ font-style: italic; font-weight: 500; }}
"""
    elif brand_style == "warm":
        derived += f"""
{sel} .brand-mark {{ background: var(--accent); border-radius: var(--radius); }}
{sel} .brand-mark-glyph {{ color: var(--surface); font-family: var(--font-display); font-weight: 500; }}
{sel} .brand-name {{ font-family: var(--font-display); font-weight: 500; }}
{sel} .page-head {{ border-bottom: 1px solid var(--line-soft); padding-bottom: 18px; }}
"""
    else:  # tech
        derived += f"""
{sel} .brand-mark {{ background: linear-gradient(135deg, var(--accent), var(--accent-deep)); box-shadow: 0 0 16px color-mix(in srgb, var(--accent) 35%, transparent); }}
{sel} .brand-mark-glyph {{ color: var(--bg); font-family: var(--font-display); font-weight: 700; }}
{sel} .brand-name {{ font-family: var(--font); font-weight: 700; letter-spacing: -0.01em; }}
"""

    return "\n".join(lines) + derived


def get_css(theme: str | None = None) -> str:
    """Emit CSS for ALL themes (scoped via [data-theme="..."]) plus the static rules.

    All four themes ship in every page so the in-page switcher can toggle live
    without reloading. The `theme` arg only affects the initial `<html data-theme>`
    attribute (handled in page()).
    """
    # design.md custom overrides apply on top of all themes
    extra_overrides = {}
    design_md = Path.home() / ".commerce-os" / "design.md"
    if design_md.exists():
        try:
            parsed = _parse_design_md(design_md.read_text(encoding="utf-8"))
            extra_overrides = parsed.get("overrides") or {}
        except Exception:
            pass

    blocks: list[str] = []
    for name, override in THEMES.items():
        tokens = {**TOKENS_DEFAULT, **override, **extra_overrides}
        blocks.append(_theme_block(name, tokens))
    return "\n".join(blocks) + "\n" + _STATIC_CSS


_STATIC_CSS = """
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg); color: var(--ink);
  font-family: var(--font);
  font-feature-settings: var(--font-features);
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  line-height: 1.55; font-size: 15px;
}
body { min-height: 100vh; background-attachment: fixed; position: relative; transition: background-color 0.4s ease, color 0.4s ease; }
::selection { background: color-mix(in srgb, var(--accent) 35%, transparent); color: var(--ink-strong); }

/* Grain overlay base — per-theme opacity/blend set via [data-theme] block */
.grain-overlay { position: fixed; inset: 0; pointer-events: none; z-index: 1; filter: url(#grain); transition: opacity 0.4s ease; }
.card, .topbar, .kpi-card, .data-table, .dd-bucket, .dd-item, .daily-log, .modal, .btn, .filter-btn { transition: background-color 0.35s ease, border-color 0.35s ease, color 0.25s ease, box-shadow 0.2s ease, transform 0.18s cubic-bezier(.16,.84,.32,1); }

/* Theme switcher — 4 color swatches in topbar */
.theme-switch { display: inline-flex; gap: 7px; align-items: center; padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; background: color-mix(in srgb, var(--surface-2) 50%, transparent); }
.ts-btn { width: 16px; height: 16px; border-radius: 50%; border: 1px solid color-mix(in srgb, var(--ink) 20%, transparent); cursor: pointer; padding: 0; position: relative; transition: transform 0.18s cubic-bezier(.16,.84,.32,1), box-shadow 0.18s; outline: none; }
.ts-btn:hover { transform: scale(1.18); }
.ts-btn:focus-visible { box-shadow: 0 0 0 2px var(--bg), 0 0 0 4px var(--accent); }
.ts-btn.active { box-shadow: 0 0 0 2px var(--bg), 0 0 0 3px var(--accent); transform: scale(1.1); }
.ts-btn[data-set-theme="midnight-emerald"] { background: linear-gradient(135deg, #34d399 0% 50%, #0a0d12 50% 100%); }
.ts-btn[data-set-theme="linen-warm"]       { background: linear-gradient(135deg, #2d5a3d 0% 50%, #f6f1e7 50% 100%); }
.ts-btn[data-set-theme="slate-premium"]    { background: linear-gradient(135deg, #d4af37 0% 50%, #0b1220 50% 100%); }
.ts-btn[data-set-theme="dawn-coral"]       { background: linear-gradient(135deg, #b85c38 0% 50%, #f9efe6 50% 100%); }

a { color: var(--accent); text-decoration: none; transition: color 0.15s; }
a:hover { color: var(--accent-soft); text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
a.muted-link { color: var(--ink-muted); }
code { font-family: var(--mono); font-size: 0.86em; background: var(--surface-2); padding: 1px 6px; border-radius: 3px; border: 1px solid var(--line-soft); }
pre { font-family: var(--mono); background: var(--surface-2); padding: 14px 16px; border-radius: var(--radius); overflow-x: auto; font-size: 0.85rem; line-height: 1.6; border: 1px solid var(--line-soft); }
hr { border: 0; height: 1px; background: var(--rule-color, var(--line)); margin: 40px 0; }
.muted { color: var(--ink-muted); }
.mono { font-family: var(--mono); font-size: 0.86em; }
.num { font-family: var(--font-num); font-variant-numeric: tabular-nums lining-nums; }

/* Eyebrow — small-caps tag for above-headline accent */
.eyebrow { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: var(--eyebrow-tracking); color: var(--accent); margin-bottom: 10px; }
.eyebrow::before { content: ""; display: inline-block; width: 18px; height: 1px; background: var(--accent); }

/* Layout */
.container { max-width: 1280px; margin: 0 auto; padding: 0 28px; }
.main { padding-top: 40px; padding-bottom: 96px; position: relative; z-index: 2; }
.main > * { animation: lumi-rise 0.7s cubic-bezier(.16,.84,.32,1) backwards; }
.main > *:nth-child(1) { animation-delay: 0.05s; }
.main > *:nth-child(2) { animation-delay: 0.12s; }
.main > *:nth-child(3) { animation-delay: 0.19s; }
.main > *:nth-child(4) { animation-delay: 0.26s; }
.main > *:nth-child(5) { animation-delay: 0.33s; }
.main > *:nth-child(6) { animation-delay: 0.40s; }
.main > *:nth-child(7) { animation-delay: 0.47s; }
@keyframes lumi-rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@media (prefers-reduced-motion: reduce) {
  .main > * { animation: none; }
  *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

/* Topbar */
.topbar { position: sticky; top: 0; z-index: 50; border-bottom: 1px solid var(--line); backdrop-filter: saturate(140%) blur(14px); -webkit-backdrop-filter: saturate(140%) blur(14px); }
.topbar-row { display: flex; align-items: center; justify-content: space-between; height: 64px; gap: 24px; }
.brand { display: inline-flex; align-items: center; gap: 12px; color: var(--ink); text-decoration: none; }
.brand:hover { text-decoration: none; }
.brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: var(--radius-sharp); }
.brand-mark-glyph { font-size: 16px; line-height: 1; }
.brand-text { display: flex; flex-direction: column; line-height: 1.1; gap: 1px; }
.brand-name { font-size: 17px; font-weight: 700; color: var(--ink-strong); }
.brand-tag { font-size: 10.5px; color: var(--ink-dim); font-family: var(--mono); letter-spacing: 0.06em; text-transform: uppercase; }
.nav { display: flex; gap: 2px; }
.nav-link { padding: 7px 14px; border-radius: var(--radius-sharp); color: var(--ink-muted); font-size: 13.5px; font-weight: 500; transition: color 0.15s, background 0.15s; }
.nav-link:hover { background: var(--surface-2); color: var(--ink); text-decoration: none; }
.nav-link.active { color: var(--ink-strong); background: var(--surface-2); box-shadow: inset 0 -2px 0 var(--accent); }
.topbar-right { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--ink-dim); }
.topbar-back { color: var(--ink-muted); padding: 6px 12px; border-radius: var(--radius-sharp); font-size: 13px; }
.topbar-back:hover { color: var(--ink); background: var(--surface-2); text-decoration: none; }
.topbar-meta { font-family: var(--mono); font-size: 11px; letter-spacing: 0.04em; }

/* Page head — editorial hero */
.page-head { padding: 24px 0 20px; margin-bottom: 8px; }
.page-head h1 {
  font-family: var(--font-display);
  font-size: clamp(1.9rem, 1.5rem + 1.8vw, 2.85rem);
  font-weight: var(--display-weight);
  line-height: 1.08;
  letter-spacing: var(--display-tracking);
  color: var(--ink-strong);
  margin: 0 0 10px;
  max-width: 64ch;
}
.page-meta { color: var(--ink-muted); font-size: 14px; margin: 0; max-width: 72ch; line-height: 1.6; }
.page-meta code { font-size: 12px; }

/* Section */
.section { margin: 48px 0; position: relative; }
.section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 18px; gap: 16px; padding-bottom: 10px; border-bottom: 1px solid var(--line-soft); }
.section h2 { font-family: var(--font-display); font-size: 1.3rem; font-weight: var(--display-weight); color: var(--ink-strong); margin: 0; letter-spacing: var(--display-tracking); }
.section-link { font-size: 12px; color: var(--ink-muted); font-family: var(--mono); letter-spacing: 0.05em; text-transform: uppercase; }
.section-link:hover { color: var(--accent); }
.subhead { font-family: var(--font-display); font-size: 1.05rem; font-weight: var(--display-weight); color: var(--ink-strong); margin: 28px 0 12px; }

/* KPI strip — editorial number cards with accent rule */
.kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 28px 0; }
@media (max-width: 900px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }
.kpi-card { position: relative; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 22px 24px 20px; transition: transform 0.2s cubic-bezier(.16,.84,.32,1), border-color 0.2s, box-shadow 0.2s; overflow: hidden; }
.kpi-card::before { content: ""; position: absolute; left: 0; top: 14%; bottom: 14%; width: 2px; background: var(--accent); opacity: 0.7; border-radius: 2px; transition: opacity 0.2s, width 0.2s; }
.kpi-card:hover { transform: translateY(-2px); }
.kpi-card:hover::before { opacity: 1; width: 3px; }
.kpi-card.kpi-amber::before { background: var(--amber); }
.kpi-card.kpi-rose::before { background: var(--rose); }
.kpi-card.kpi-sky::before { background: var(--sky); }
.kpi-card.kpi-indigo::before { background: var(--indigo); }
.kpi-value {
  font-family: var(--font-num);
  font-size: clamp(2rem, 1.6rem + 1vw, 2.6rem);
  font-weight: 600; line-height: 1;
  color: var(--ink-strong);
  letter-spacing: -0.025em;
  font-variant-numeric: tabular-nums lining-nums;
}
.kpi-label { font-family: var(--mono); font-size: 10.5px; color: var(--ink-muted); margin-top: 12px; text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600; }
.kpi-hint { font-size: 12px; color: var(--ink-muted); margin-top: 6px; font-style: italic; }

/* Cards — layered editorial surface */
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 0; transition: transform 0.2s cubic-bezier(.16,.84,.32,1), border-color 0.2s, box-shadow 0.25s; overflow: hidden; position: relative; }
.card:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 40%, var(--line)); }
.card-head { padding: 16px 20px 10px; display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.card-title { font-weight: 600; color: var(--ink-strong); font-size: 15px; letter-spacing: -0.005em; }
.card-body { padding: 4px 20px 16px; }
.card-meta { font-size: 11px; color: var(--ink-muted); margin-bottom: 10px; font-family: var(--mono); letter-spacing: 0.04em; text-transform: uppercase; }
.card-sub { font-size: 13px; color: var(--ink-muted); margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line-soft); }
.task-list { font-size: 13.5px; color: var(--ink); padding-left: 20px; margin-top: 8px; line-height: 1.65; }
.task-list li { margin: 5px 0; }
.task-list li::marker { color: var(--accent); }

/* Progress + confidence */
.progress { background: var(--surface-2); height: 4px; border-radius: 999px; overflow: hidden; margin-top: 8px; }
.progress-bar { background: linear-gradient(90deg, var(--accent-deep), var(--accent), var(--accent-soft)); height: 100%; width: var(--pct, 0%); transition: width 1.1s cubic-bezier(.16,.84,.32,1); border-radius: 999px; }
.progress-meta { font-size: 11px; color: var(--ink-muted); margin-top: 6px; font-family: var(--mono); letter-spacing: 0.04em; }
.confidence { display: flex; align-items: center; gap: 10px; }
.confidence-bar { flex: 0 0 84px; height: 3px; background: var(--surface-2); border-radius: 999px; overflow: hidden; position: relative; }
.confidence-bar::after { content: ""; display: block; height: 100%; width: var(--pct, 0%); transition: width 1.1s cubic-bezier(.16,.84,.32,1); border-radius: 999px; }

/* Data table */
.data-table { width: 100%; border-collapse: collapse; font-size: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; font-variant-numeric: tabular-nums; }
.data-table thead th { background: var(--surface-2); color: var(--ink-muted); font-weight: 600; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; padding: 12px 16px; border-bottom: 1px solid var(--line); font-family: var(--mono); text-align: left; }
.data-table tbody td { padding: 12px 16px; border-bottom: 1px solid var(--line-soft); color: var(--ink); vertical-align: top; }
.data-table tbody tr:last-child td { border-bottom: 0; }
.data-table tbody tr { transition: background 0.12s; }
.data-table tbody tr:hover { background: color-mix(in srgb, var(--accent) 6%, var(--surface)); }
.empty-state-row { text-align: center; color: var(--ink-muted); padding: 28px; font-style: italic; }
.empty-state { text-align: center; padding: 48px 24px; background: var(--surface); border: 1px dashed var(--line); border-radius: var(--radius); color: var(--ink-muted); line-height: 1.8; font-style: italic; }

/* Heatmap (citation, generic) */
.heatmap-cell { text-align: center; font-family: var(--mono); font-size: 12px; padding: 16px 8px; transition: filter 0.15s, transform 0.15s; cursor: help; border-radius: var(--radius-sharp); }
.heatmap-cell:hover { filter: brightness(1.15); transform: scale(1.03); z-index: 5; position: relative; }

/* Tags */
.tag { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 600; font-family: var(--mono); letter-spacing: 0.06em; text-transform: uppercase; border: 1px solid transparent; }

/* Buttons */
.actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--line-soft); background: color-mix(in srgb, var(--surface-2) 50%, var(--surface)); }
.btn {
  background: var(--surface-2); border: 1px solid var(--line); color: var(--ink);
  padding: 8px 16px; border-radius: var(--radius-sharp); cursor: pointer;
  font-size: 13px; font-family: var(--font); font-weight: 500;
  display: inline-flex; align-items: center; gap: 6px;
  transition: all 0.18s cubic-bezier(.16,.84,.32,1);
  text-decoration: none; letter-spacing: 0.01em;
}
.btn:hover { background: var(--surface-3, var(--line)); border-color: var(--line-strong, var(--line)); transform: translateY(-1px); text-decoration: none; }
.btn:active { transform: translateY(0); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--bg); font-weight: 600; }
.btn.primary:hover { background: var(--accent-soft); border-color: var(--accent-soft); box-shadow: 0 6px 20px -6px var(--accent-glow); }
.btn.warn { background: color-mix(in srgb, var(--amber) 16%, transparent); border-color: color-mix(in srgb, var(--amber) 35%, transparent); color: var(--amber); }
.btn.warn:hover { background: color-mix(in srgb, var(--amber) 25%, transparent); }
.btn.ghost { background: transparent; color: var(--ink-muted); border-color: var(--line); }
.btn.ghost:hover { color: var(--ink); background: var(--surface-2); }
.btn.small { padding: 5px 11px; font-size: 12px; }

/* Filter row */
.filter-row { display: flex; gap: 6px; flex-wrap: wrap; padding: 14px 0 8px; }
.filter-btn { background: transparent; border: 1px solid var(--line); color: var(--ink-muted); padding: 6px 13px; border-radius: 999px; cursor: pointer; font-size: 12.5px; font-family: var(--font); font-weight: 500; transition: all 0.15s; }
.filter-btn:hover { background: var(--surface-2); color: var(--ink); border-color: var(--line-strong, var(--line)); }
.filter-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }

/* Tabs — underline style, not filled pills */
.tabs { display: inline-flex; gap: 4px; border-bottom: 1px solid var(--line); padding: 0; margin-bottom: 22px; flex-wrap: wrap; }
.tab { background: transparent; border: 0; color: var(--ink-muted); font-family: var(--font); font-size: 13.5px; padding: 10px 16px; border-radius: 0; cursor: pointer; font-weight: 500; position: relative; transition: color 0.15s; letter-spacing: 0.01em; }
.tab::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2px; background: var(--accent); transform: scaleX(0); transform-origin: center; transition: transform 0.25s cubic-bezier(.16,.84,.32,1); }
.tab:hover { color: var(--ink); }
.tab.active { color: var(--ink-strong); font-weight: 600; }
.tab.active::after { transform: scaleX(1); }
.tab-panel { animation: fadeIn 0.3s cubic-bezier(.16,.84,.32,1); }
.tab-panel.hidden { display: none; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

/* Daily logs / collapsibles */
.daily-log { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 18px; margin-bottom: 10px; transition: border-color 0.15s; }
.daily-log:hover { border-color: var(--line-strong, var(--line)); }
.daily-log summary { cursor: pointer; font-weight: 500; color: var(--ink); padding: 4px 0; font-family: var(--mono); font-size: 0.9rem; list-style: none; display: flex; align-items: center; gap: 10px; }
.daily-log summary::before { content: "▸"; color: var(--accent); font-size: 12px; transition: transform 0.2s; }
.daily-log[open] summary::before { transform: rotate(90deg); }
.daily-log[open] summary { margin-bottom: 14px; }
.md-snippet { background: var(--surface-2); border: 1px solid var(--line-soft); padding: 16px 18px; border-radius: var(--radius-sharp); max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; color: var(--ink); line-height: 1.7; font-family: var(--mono); }

/* Timeline */
.timeline { padding: 8px 0; position: relative; }
.timeline::before { content: ""; position: absolute; left: 4px; top: 12px; bottom: 12px; width: 1px; background: var(--line); }
.timeline-row { display: flex; gap: 16px; margin-bottom: 22px; position: relative; }
.tl-marker { width: 9px; height: 9px; border-radius: 50%; margin-top: 7px; flex-shrink: 0; box-shadow: 0 0 0 3px var(--bg), 0 0 0 4px currentColor; }
.tl-info { background: var(--sky); color: var(--sky); }
.tl-warn { background: var(--amber); color: var(--amber); }
.tl-error { background: var(--rose); color: var(--rose); }
.tl-decision { background: var(--accent); color: var(--accent); }
.tl-content { flex: 1; }
.tl-head { display: flex; gap: 12px; align-items: baseline; }
.tl-ts { font-family: var(--mono); font-size: 11px; color: var(--ink-muted); letter-spacing: 0.04em; }
.tl-title { font-size: 14px; color: var(--ink-strong); font-weight: 500; }
.tl-body { font-size: 13px; color: var(--ink-muted); margin-top: 4px; line-height: 1.65; }

/* Toast */
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%) translateY(20px); background: var(--ink-strong); color: var(--bg); padding: 12px 22px; border-radius: var(--radius); font-size: 13px; font-weight: 600; opacity: 0; pointer-events: none; transition: opacity 0.25s, transform 0.25s cubic-bezier(.16,.84,.32,1); z-index: 100; box-shadow: 0 20px 40px -10px rgba(0,0,0,0.4); }
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* Modal */
.modal-overlay { position: fixed; inset: 0; background: color-mix(in srgb, var(--bg) 75%, transparent); display: none; align-items: center; justify-content: center; z-index: 200; backdrop-filter: blur(8px); }
.modal-overlay.show { display: flex; animation: fadeIn 0.2s; }
.modal { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 32px; max-width: 560px; width: 90%; max-height: 80vh; overflow-y: auto; box-shadow: 0 32px 80px -16px rgba(0,0,0,0.5); }
.modal h2 { font-family: var(--font-display); margin: 0 0 14px; font-size: 1.4rem; font-weight: var(--display-weight); }
.modal p, .modal ul { color: var(--ink-muted); font-size: 14px; line-height: 1.7; }
.modal-actions { display: flex; gap: 10px; margin-top: 24px; }

/* Footer */
.footer { border-top: 1px solid var(--line); padding: 24px 0; margin-top: 80px; font-size: 11.5px; color: var(--ink-dim); font-family: var(--mono); letter-spacing: 0.04em; }
.footer-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.footer-mark { color: var(--accent); font-weight: 600; }
.footer-divider { color: var(--ink-faint, var(--line)); }
.footer-spacer { flex: 1; }
.footer-meta { color: var(--ink-muted); }

/* Scrollbar */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 999px; border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--ink-dim); }

/* Drag-and-drop board */
.dd-board { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin: 28px 0; }
@media (max-width: 900px) { .dd-board { grid-template-columns: 1fr; } }
.dd-bucket { background: color-mix(in srgb, var(--surface) 80%, transparent); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px; min-height: 220px; transition: border-color 0.2s, background 0.2s, transform 0.2s; }
.dd-bucket.over { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, var(--surface)); transform: scale(1.01); box-shadow: 0 0 0 1px var(--accent), 0 12px 32px -8px var(--accent-glow); }
.dd-bucket h3 { margin: 0 0 16px; font-size: 13px; color: var(--ink-strong); font-family: var(--mono); letter-spacing: 0.1em; text-transform: uppercase; display: flex; align-items: center; justify-content: space-between; padding-bottom: 10px; border-bottom: 1px solid var(--line-soft); }
.dd-bucket .count { color: var(--accent); font-family: var(--font-num); font-weight: 600; font-size: 16px; letter-spacing: 0; text-transform: none; }
.dd-item { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sharp); padding: 12px 14px; margin-bottom: 8px; cursor: grab; transition: transform 0.15s cubic-bezier(.16,.84,.32,1), box-shadow 0.18s, border-color 0.15s; }
.dd-item:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--accent) 50%, var(--line)); box-shadow: 0 6px 18px -6px var(--accent-glow); }
.dd-item.dragging { opacity: 0.4; cursor: grabbing; transform: rotate(1.5deg); }
.dd-item .name { font-weight: 600; color: var(--ink-strong); font-size: 13.5px; line-height: 1.4; }
.dd-item .meta { color: var(--ink-muted); font-family: var(--mono); font-size: 10.5px; margin-top: 6px; letter-spacing: 0.04em; }

/* RFM 2D matrix */
.rfm-matrix { display: grid; grid-template-columns: 44px repeat(5, 1fr); gap: 5px; margin: 28px 0; max-width: 760px; }
.rfm-matrix .axis-label { color: var(--ink-muted); font-size: 10.5px; font-family: var(--mono); padding: 10px 4px; text-align: center; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; display: flex; align-items: center; justify-content: center; }
.rfm-cell { aspect-ratio: 1; border-radius: var(--radius-sharp); display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: var(--mono); font-size: 12px; cursor: pointer; transition: transform 0.2s cubic-bezier(.16,.84,.32,1), box-shadow 0.2s, z-index 0s 0s; padding: 6px; position: relative; border: 1px solid color-mix(in srgb, var(--ink) 8%, transparent); }
.rfm-cell:hover { transform: scale(1.08); box-shadow: 0 12px 30px -6px var(--accent-glow), 0 0 0 1.5px var(--accent); z-index: 10; }
.rfm-cell .n { font-family: var(--font-num); font-size: 16px; font-weight: 700; line-height: 1; letter-spacing: -0.02em; }
.rfm-cell .ltv { color: var(--ink-muted); font-size: 9.5px; margin-top: 3px; letter-spacing: 0.04em; }

/* Gantt timeline */
.gantt-grid { display: grid; grid-template-columns: 130px repeat(7, 1fr); gap: 5px; margin: 20px 0; }
.gantt-header { color: var(--ink-muted); font-family: var(--mono); font-size: 10.5px; padding: 8px 4px; text-align: center; letter-spacing: 0.08em; text-transform: uppercase; font-weight: 600; }
.gantt-row-label { color: var(--ink-strong); font-size: 13px; font-weight: 600; padding: 14px 10px; display: flex; align-items: center; border-right: 1px solid var(--line-soft); font-family: var(--font-display); letter-spacing: -0.005em; }
.gantt-day { background: var(--surface); border: 1px solid var(--line-soft); border-radius: var(--radius-sharp); min-height: 64px; padding: 8px 10px; font-size: 11px; color: var(--ink); position: relative; transition: border-color 0.18s, transform 0.18s, box-shadow 0.18s; cursor: default; }
.gantt-day:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); box-shadow: 0 6px 18px -8px var(--accent-glow); z-index: 5; }
.gantt-day.today { border-color: var(--accent); background: linear-gradient(160deg, color-mix(in srgb, var(--accent) 12%, var(--surface)), var(--surface)); box-shadow: 0 0 0 1px var(--accent), 0 12px 28px -8px var(--accent-glow); }
.gantt-day.today::before { content: "● TODAY"; position: absolute; top: -8px; right: 8px; background: var(--accent); color: var(--bg); font-family: var(--mono); font-size: 8.5px; font-weight: 700; padding: 2px 6px; border-radius: 999px; letter-spacing: 0.1em; }
.gantt-day.past { opacity: 0.45; }
.gantt-day.future { opacity: 1; }
.gantt-day .day-num { font-family: var(--mono); color: var(--ink-muted); font-size: 10px; letter-spacing: 0.04em; font-weight: 600; margin-bottom: 2px; }
.gantt-day .task { color: var(--ink); font-size: 11px; margin-top: 5px; line-height: 1.4; }

/* Sparkline — inline SVG, no special CSS needed */
"""

# =============================================================================
# JS bundle
# =============================================================================
JS = r"""
function copyText(btn, text) {
  navigator.clipboard.writeText(text).then(() => showToast('✓ 已复制'));
}
// Theme switcher — persists choice in localStorage, applies live
(function initThemeSwitch() {
  const KEY = 'lumi-theme';
  const VALID = ['midnight-emerald','linen-warm','slate-premium','dawn-coral'];
  function apply(name) {
    if (!VALID.includes(name)) return;
    document.documentElement.dataset.theme = name;
    try { localStorage.setItem(KEY, name); } catch (e) {}
    document.querySelectorAll('.ts-btn').forEach(b => {
      const on = b.dataset.setTheme === name;
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  function init() {
    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) {}
    const initial = (saved && VALID.includes(saved)) ? saved : (document.documentElement.dataset.theme || 'midnight-emerald');
    apply(initial);
    document.querySelectorAll('.ts-btn').forEach(b => {
      b.addEventListener('click', () => apply(b.dataset.setTheme));
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
function showToast(msg) {
  const t = document.getElementById('toast');
  if (!t) { console.log(msg); return; }
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}
function filterCategory(cat) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
  document.querySelectorAll('.card, .filterable').forEach(c => {
    c.style.display = (cat === 'all' || c.dataset.cat === cat) ? '' : 'none';
  });
}
function openModal(id) { const m = document.getElementById(id); if (m) m.classList.add('show'); }
function closeModal(id) { const m = document.getElementById(id); if (m) m.classList.remove('show'); }
// Tab switcher
(function initTabs() {
  document.querySelectorAll('[data-tabs]').forEach(group => {
    const tabs = group.querySelectorAll('[data-tab]');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        tabs.forEach(t => t.classList.toggle('active', t === tab));
        document.querySelectorAll('[data-panel]').forEach(panel => {
          panel.classList.toggle('hidden', panel.dataset.panel !== target);
        });
      });
    });
  });
})();
// Drag-and-drop board (for lumicc-expand)
(function initDragDrop() {
  document.querySelectorAll('.dd-item').forEach(it => {
    it.addEventListener('dragstart', e => { it.classList.add('dragging'); e.dataTransfer.setData('text/plain', it.dataset.id); });
    it.addEventListener('dragend', () => it.classList.remove('dragging'));
  });
  document.querySelectorAll('.dd-bucket').forEach(bucket => {
    bucket.addEventListener('dragover', e => { e.preventDefault(); bucket.classList.add('over'); });
    bucket.addEventListener('dragleave', () => bucket.classList.remove('over'));
    bucket.addEventListener('drop', e => {
      e.preventDefault();
      bucket.classList.remove('over');
      const id = e.dataTransfer.getData('text/plain');
      const item = document.querySelector(`.dd-item[data-id="${id}"]`);
      if (item) { bucket.querySelector('.dd-list').appendChild(item); updateBucketCounts(); }
    });
  });
  function updateBucketCounts() {
    document.querySelectorAll('.dd-bucket').forEach(b => {
      const c = b.querySelectorAll('.dd-item').length;
      const span = b.querySelector('.count');
      if (span) span.textContent = `(${c})`;
    });
  }
  window.exportDecisions = function() {
    const decisions = {};
    document.querySelectorAll('.dd-bucket').forEach(b => {
      const action = b.dataset.action;
      decisions[action] = Array.from(b.querySelectorAll('.dd-item')).map(it => it.dataset.id);
    });
    const blob = new Blob([JSON.stringify(decisions, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'decisions.json'; a.click();
    URL.revokeObjectURL(url);
    showToast('✓ 决策已导出 decisions.json');
  };
})();
"""
