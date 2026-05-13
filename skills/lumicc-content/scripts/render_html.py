#!/usr/bin/env python3
"""Render the content studio HTML page.

One page with cards per item. Each card:
- Title + category badge + model name + credit cost
- If image generated: <img> preview + Download button
- Prompt text (collapsed by default) + Copy button
- Action buttons: Copy prompt, Download image, Open external tool, Enable video gen

Self-contained CSS + JS, no CDN dependency.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
from pathlib import Path

# Make lumicc html_lib importable for embed_image
_HERE = Path(__file__).resolve().parent
_LUMICC_SCRIPTS = _HERE.parent.parent / "lumicc" / "scripts"
if str(_LUMICC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LUMICC_SCRIPTS))
try:
    import html_lib as H  # type: ignore
except ImportError:  # pragma: no cover
    H = None  # type: ignore


def esc(s) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


CATEGORY_LABEL = {
    "pdp": "详情页", "poster": "海报", "product_image": "商品图",
    "product_enhance": "图片增强", "video": "视频",
    "tiktok_script": "TikTok 脚本", "blog_brief": "博客 brief",
    "ad_creative": "广告创意", "email_sequence": "邮件序列",
}

CATEGORY_COLOR = {
    "pdp": "sky", "poster": "emerald", "product_image": "emerald",
    "product_enhance": "amber", "video": "rose",
    "tiktok_script": "indigo", "blog_brief": "sky",
    "ad_creative": "amber", "email_sequence": "indigo",
}


def _rel_path_to_html(target: Path, html_dir: Path) -> str:
    """Compute relative path so the HTML works after a folder move."""
    try:
        return os.path.relpath(target, html_dir).replace(os.sep, "/")
    except ValueError:
        return target.as_uri()


CSS = """
:root {
  --bg: #08090b; --surface: #0d0f12; --surface-2: #15181d;
  --line: #2a2f38; --line-soft: #1f242c;
  --ink: #e6e8ec; --ink-muted: #9ca3af; --ink-dim: #6b7280;
  --accent: #10b981; --accent-soft: #34d399;
  --amber: #f59e0b; --rose: #f43f5e; --sky: #38bdf8; --indigo: #6366f1;
  --radius: 12px;
  --font: 'Inter','Noto Sans SC',system-ui,-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
  --mono: 'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font); line-height: 1.5; -webkit-font-smoothing: antialiased; }
body {
  background-image:
    radial-gradient(at 8% 0%, rgba(16,185,129,0.06) 0, transparent 36%),
    radial-gradient(at 90% 4%, rgba(99,102,241,0.04) 0, transparent 38%);
  background-attachment: fixed;
}
a { color: var(--accent-soft); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; }

.topbar { position: sticky; top: 0; z-index: 50; background: rgba(13,15,18,0.85); backdrop-filter: blur(8px); border-bottom: 1px solid var(--line); }
.topbar-row { display: flex; align-items: center; justify-content: space-between; height: 56px; padding: 0 24px; }
.brand { display: flex; align-items: baseline; gap: 8px; }
.brand-mark { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: linear-gradient(135deg, var(--accent), #047857); color: var(--bg); font-weight: 800; transform: translateY(2px); }
.brand-name { font-weight: 700; }
.brand-tag { font-size: 12px; color: var(--ink-dim); margin-left: 4px; }
.topbar-right { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--ink-dim); font-family: var(--mono); }
.topbar-back { color: var(--ink-muted); padding: 6px 10px; border-radius: 6px; }
.topbar-back:hover { color: var(--ink); background: var(--surface-2); text-decoration: none; }

.page-head { padding: 24px 0 8px; }
.page-head h1 { font-size: 1.75rem; font-weight: 800; margin: 0 0 6px; letter-spacing: -0.02em; }
.page-meta { color: var(--ink-muted); font-size: 14px; }
.cost { color: var(--accent-soft); font-family: var(--mono); }

.filter-row { display: flex; gap: 6px; flex-wrap: wrap; padding: 16px 0 24px; border-bottom: 1px solid var(--line); position: sticky; top: 56px; background: var(--bg); z-index: 40; }
.filter-btn { background: var(--surface); border: 1px solid var(--line); color: var(--ink-muted); padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 13px; font-family: var(--font); }
.filter-btn:hover { background: var(--surface-2); color: var(--ink); }
.filter-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 16px; padding: 24px 0 80px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; transition: border-color 0.15s; }
.card:hover { border-color: rgba(16,185,129,0.30); }
.card-head { padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--line-soft); }
.card-title { font-weight: 600; color: var(--ink); font-size: 15px; }
.card-body { padding: 14px 18px; }

.tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; font-family: var(--mono); border: 1px solid transparent; }
.tag-emerald { background: rgba(16,185,129,0.15); color: #6ee7b7; border-color: rgba(16,185,129,0.30); }
.tag-sky     { background: rgba(56,189,248,0.15); color: #7dd3fc; border-color: rgba(56,189,248,0.30); }
.tag-amber   { background: rgba(245,158,11,0.15); color: #fcd34d; border-color: rgba(245,158,11,0.30); }
.tag-rose    { background: rgba(244,63,94,0.15);  color: #fda4af; border-color: rgba(244,63,94,0.30); }
.tag-indigo  { background: rgba(99,102,241,0.15); color: #a5b4fc; border-color: rgba(99,102,241,0.30); }
.tag-zinc    { background: var(--surface-2); color: var(--ink-muted); border-color: var(--line); }

.image-preview { width: 100%; aspect-ratio: 1; background: var(--surface-2); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.image-preview img { width: 100%; height: 100%; object-fit: cover; display: block; }
.image-placeholder { color: var(--ink-dim); font-size: 13px; padding: 30px; text-align: center; }
.images-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; padding: 14px 18px; background: var(--surface-2); }
.images-grid .image-preview { aspect-ratio: 1; border-radius: 8px; border: 1px solid var(--line-soft); }

.meta { display: flex; flex-wrap: wrap; gap: 8px 14px; font-size: 12px; color: var(--ink-muted); margin-bottom: 12px; font-family: var(--mono); }
.meta b { color: var(--ink); font-weight: 500; }

.prompt-box { position: relative; background: var(--surface-2); border: 1px solid var(--line-soft); border-radius: 8px; padding: 12px 14px; font-family: var(--mono); font-size: 13px; color: var(--ink); line-height: 1.55; max-height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; }
.prompt-box::-webkit-scrollbar { width: 6px; }
.prompt-box::-webkit-scrollbar-thumb { background: var(--line); border-radius: 3px; }

.actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 14px 18px; border-top: 1px solid var(--line-soft); background: var(--surface); }
.btn { background: var(--surface-2); border: 1px solid var(--line); color: var(--ink); padding: 7px 14px; border-radius: 8px; cursor: pointer; font-size: 13px; font-family: var(--font); display: inline-flex; align-items: center; gap: 6px; transition: all 0.15s; text-decoration: none; }
.btn:hover { background: var(--line); text-decoration: none; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--bg); font-weight: 600; }
.btn.primary:hover { background: var(--accent-soft); }
.btn.warn { background: rgba(245,158,11,0.15); border-color: rgba(245,158,11,0.30); color: #fcd34d; }
.btn.warn:hover { background: rgba(245,158,11,0.25); }
.btn.ghost { background: transparent; color: var(--ink-muted); }
.btn.ghost:hover { color: var(--ink); }
.btn.small { padding: 4px 10px; font-size: 12px; }

.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(20px); background: var(--ink); color: var(--bg); padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; opacity: 0; pointer-events: none; transition: opacity 0.2s, transform 0.2s; z-index: 100; }
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

.video-banner { background: linear-gradient(135deg, rgba(245,158,11,0.10), rgba(244,63,94,0.10)); border: 1px solid rgba(245,158,11,0.30); border-radius: var(--radius); padding: 14px 18px; margin: 12px 0; }
.video-banner h3 { margin: 0 0 4px; font-size: 14px; color: #fcd34d; }
.video-banner p { margin: 0; font-size: 13px; color: var(--ink-muted); }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: none; align-items: center; justify-content: center; z-index: 200; backdrop-filter: blur(4px); }
.modal-overlay.show { display: flex; }
.modal { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 24px; max-width: 500px; width: 90%; }
.modal h2 { margin: 0 0 12px; font-size: 1.25rem; }
.modal p { color: var(--ink-muted); font-size: 14px; line-height: 1.6; }
.modal-actions { display: flex; gap: 8px; margin-top: 20px; }

.footer { border-top: 1px solid var(--line); padding: 16px 0; font-size: 12px; color: var(--ink-dim); }
.footer .container { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 12px; }

.empty-state { text-align: center; padding: 80px 20px; color: var(--ink-muted); }
"""


JS = r"""
function copyText(btn, text) {
  navigator.clipboard.writeText(text).then(() => showToast('✓ 已复制 prompt'));
}
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}
function filterCategory(cat) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = (cat === 'all' || c.dataset.cat === cat) ? '' : 'none';
  });
}
function openVideoModal() { document.getElementById('video-modal').classList.add('show'); }
function closeVideoModal() { document.getElementById('video-modal').classList.remove('show'); }
"""


def render_card(item: dict, html_dir: Path) -> str:
    cat = item.get("category", "pdp")
    color = CATEGORY_COLOR.get(cat, "zinc")
    label = CATEGORY_LABEL.get(cat, cat)
    title = esc(item.get("subject", "—"))
    prompt = item.get("prompt_text", "")
    model = item.get("model") or (item.get("image_gen_params") or {}).get("model") or ""
    credits = item.get("credits") or 0
    local_paths: list[str] = item.get("image_local_paths") or item.get("video_local_paths") or []
    target_tool = item.get("target_tool_hint", "")
    external_link = item.get("external_link", "")
    is_video = cat == "video"
    video_enabled = bool(item.get("video_gen_enabled"))

    # Header
    head = f"""
<div class="card-head">
  <div class="card-title">{title}</div>
  <span class="tag tag-{color}">{label}</span>
</div>"""

    # Image preview block
    image_block = ""
    if cat in ("poster", "product_image") and local_paths:
        if len(local_paths) == 1:
            rel = _rel_path_to_html(Path(local_paths[0]), html_dir)
            image_block = f"""<div class="image-preview"><img src="{esc(rel)}" alt="{title}" loading="lazy" /></div>"""
        else:
            thumbs = "".join(
                f'<div class="image-preview"><img src="{esc(_rel_path_to_html(Path(p), html_dir))}" alt="{title} {i+1}" loading="lazy" /></div>'
                for i, p in enumerate(local_paths)
            )
            image_block = f'<div class="images-grid">{thumbs}</div>'
    elif cat in ("poster", "product_image"):
        image_block = '<div class="image-preview"><div class="image-placeholder">📷 仅生成 prompt<br><small>配置 EVOLINK_API_KEY 后可直接生图</small></div></div>'

    # Video card has its own banner
    video_banner = ""
    if is_video:
        if video_enabled and local_paths:
            rel = _rel_path_to_html(Path(local_paths[0]), html_dir)
            video_banner = f'''<div class="image-preview" style="aspect-ratio: 9/16; max-height: 480px;"><video src="{esc(rel)}" controls style="width:100%;height:100%;object-fit:contain;background:#000;"></video></div>'''
        elif video_enabled:
            video_banner = '<div class="image-preview"><div class="image-placeholder">🎬 视频生成中或失败 — 查看日志</div></div>'
        else:
            video_banner = '''<div class="video-banner">
  <h3>🎬 视频默认仅生成 prompt</h3>
  <p>视频生成质量不稳，且消耗更多 credits。如需自动生成视频，请点击下方"⚡ 启用视频生成"。</p>
</div>'''

    # Meta line
    meta_parts = []
    if model:
        meta_parts.append(f"<b>模型</b> {esc(model)}")
    if (item.get("image_gen_params") or {}).get("size"):
        meta_parts.append(f"<b>比例</b> {esc(item['image_gen_params']['size'])}")
    if credits:
        meta_parts.append(f"<b>消耗</b> {credits} credits")
    if target_tool and not local_paths:
        meta_parts.append(f"<b>建议工具</b> {esc(target_tool)}")
    meta_block = f'<div class="meta">{" · ".join(meta_parts)}</div>' if meta_parts else ""

    # Prompt box (escaped)
    prompt_block = f'<div class="prompt-box">{esc(prompt)}</div>' if prompt else ""

    # Action buttons
    actions: list[str] = []
    if prompt:
        # JS string-safe encoding
        safe = json.dumps(prompt, ensure_ascii=False)
        actions.append(f'<button class="btn primary" onclick="copyText(this, {esc(safe)})">📋 复制 prompt</button>')
    if local_paths and not is_video:
        if len(local_paths) == 1:
            rel = _rel_path_to_html(Path(local_paths[0]), html_dir)
            actions.append(f'<a class="btn" href="{esc(rel)}" download>⬇️ 下载图片</a>')
        else:
            for i, p in enumerate(local_paths, 1):
                rel = _rel_path_to_html(Path(p), html_dir)
                actions.append(f'<a class="btn small" href="{esc(rel)}" download>⬇️ #{i}</a>')
    if is_video:
        if video_enabled and local_paths:
            rel = _rel_path_to_html(Path(local_paths[0]), html_dir)
            actions.append(f'<a class="btn primary" href="{esc(rel)}" download>⬇️ 下载视频</a>')
        else:
            actions.append('<button class="btn warn" onclick="openVideoModal()">⚡ 启用视频生成</button>')
    if external_link and not local_paths:
        actions.append(f'<a class="btn ghost" href="{esc(external_link)}" target="_blank" rel="noopener">↗ 打开工具</a>')
    actions_block = f'<div class="actions">{"".join(actions)}</div>' if actions else ""

    return f"""
<div class="card" data-cat="{esc(cat)}">
  {head}
  {image_block}
  {video_banner}
  <div class="card-body">
    {meta_block}
    {prompt_block}
  </div>
  {actions_block}
</div>"""


def _style_block(style_choice: dict | None, palette_choice: dict | None) -> str:
    """Optional 'You chose' prelude shown above the cards grid."""
    if not style_choice:
        return ""
    label = esc(style_choice.get("label") or style_choice.get("selected_id", ""))
    tagline = esc(style_choice.get("tagline", ""))
    fit_for = esc(style_choice.get("fit_for", ""))
    palette = style_choice.get("palette") or []
    if palette_choice and palette_choice.get("swatches"):
        palette = palette_choice["swatches"]
    chips = "".join(
        f'<span style="display:inline-block;width:22px;height:22px;border-radius:6px;'
        f'background:{esc(c)};border:1px solid var(--line-soft);margin-right:6px;"></span>'
        for c in palette[:6]
    )
    pal_label = esc(palette_choice.get("label", "")) if palette_choice else ""
    pal_line = (f'<div class="meta" style="margin-top:8px;">{chips}'
                f'<b>调色板</b> {pal_label}</div>') if chips else ""
    return f"""
  <section style="margin:18px 0 4px;padding:16px 18px;background:var(--surface);
                  border:1px solid var(--line);border-radius:var(--radius);">
    <div style="font-size:11px;letter-spacing:.18em;color:var(--ink-dim);
                text-transform:uppercase;margin-bottom:6px;">你选的设计方向</div>
    <div style="font-size:18px;font-weight:700;color:var(--ink);">{label}</div>
    <div class="page-meta" style="margin-top:4px;">{tagline} · 适合 {fit_for}</div>
    {pal_line}
  </section>"""


def _render_generated_assets(generated: list[dict], total_cost: float) -> str:
    """Grid of cards showing inline-embedded generated images via H.embed_image.

    Each card shows image, model badge, cost, prompt (truncated + tooltip), local path.
    Footer KPI strip: total images / total cost / cost by model.
    """
    if not generated:
        return ""
    cards: list[str] = []
    by_model: dict[str, float] = {}
    for g in generated:
        path = g.get("path", "")
        model = g.get("model") or "?"
        cost = float(g.get("cost_usd") or 0.0)
        by_model[model] = by_model.get(model, 0.0) + cost
        prompt = g.get("prompt") or ""
        truncated = (prompt[:80] + "…") if len(prompt) > 80 else prompt
        if H is not None:
            src = H.embed_image(path, max_kb=500, placeholder="原图过大，请查看本地文件")
        else:
            src = ""
        is_data_uri = src.startswith("data:image/")
        if is_data_uri:
            img_html = f'<img src="{src}" alt="generated" style="width:100%;display:block;" loading="lazy" />'
        else:
            img_html = (f'<div class="image-placeholder">📂 原图在 '
                        f'<code style="font-size:11px">{esc(path)}</code></div>')
        cards.append(f"""
<div class="card" data-cat="generated">
  <div class="image-preview" style="aspect-ratio:1;">{img_html}</div>
  <div class="card-body">
    <div class="meta">
      <span class="tag tag-emerald">{esc(model)}</span>
      <span><b>成本</b> ${cost:.4f}</span>
    </div>
    <div class="prompt-box" title="{esc(prompt)}" style="max-height:90px;">{esc(truncated)}</div>
    <div class="meta" style="margin-top:8px;font-size:11px;">
      <b>本地</b> <code>{esc(path)}</code>
    </div>
  </div>
</div>""")
    breakdown = " · ".join(f"{esc(m)} ${c:.4f}" for m, c in by_model.items())
    kpi = (f'<div class="meta" style="margin-top:14px;">'
           f'<b>共 {len(generated)} 张</b> · <b>${total_cost:.4f}</b> · {breakdown}</div>')
    return f"""
<section style="margin:24px 0 8px;">
  <h2 style="font-size:1.1rem;margin:0 0 12px;color:var(--ink);">已生成的素材</h2>
  <div class="cards" style="padding:0;">{''.join(cards)}</div>
  {kpi}
</section>"""


def _cost_banner(total_cost_usd: float, n_images: int) -> str:
    if total_cost_usd <= 0:
        return ""
    return f"""
<div style="background:linear-gradient(135deg,rgba(16,185,129,0.12),rgba(56,189,248,0.08));
            border:1px solid rgba(16,185,129,0.30);border-radius:var(--radius);
            padding:12px 18px;margin:12px 0;font-size:14px;color:var(--ink);">
  💸 本次生成花费 <b style="color:var(--accent-soft);font-family:var(--mono);">${total_cost_usd:.4f}</b>
  · {n_images} 张图 · 来自 evolink (Nano Banana / GPT Image 2)
</div>"""


def render_page(*, run_id: str, store_name: str | None, items: list[dict],
                credits_consumed: float, dry_run: bool, html_path: Path,
                style_choice: dict | None = None,
                palette_choice: dict | None = None,
                generated_images: list[dict] | None = None,
                total_cost_usd: float = 0.0) -> str:
    html_dir = html_path.parent
    # Compute filter set
    cats = sorted({i.get("category", "pdp") for i in items})
    filter_buttons = '<button class="filter-btn active" data-cat="all" onclick="filterCategory(\'all\')">全部</button>'
    for c in cats:
        label = CATEGORY_LABEL.get(c, c)
        filter_buttons += f'<button class="filter-btn" data-cat="{esc(c)}" onclick="filterCategory({json.dumps(c)})">{esc(label)}</button>'

    cards_html = "\n".join(render_card(it, html_dir) for it in items) or '<div class="empty-state">还没有内容产出。</div>'

    cost_str = "0 credits（dry-run，未调 API）" if dry_run else f"{credits_consumed} credits"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Content Studio · Lumicc</title>
<style>{CSS}</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-row">
    <a href="index.html" class="brand" style="color:var(--ink); text-decoration:none;">
      <span class="brand-mark">L</span>
      <span class="brand-name">Lumicc</span>
      <span class="brand-tag">Content Studio</span>
    </a>
    <div class="topbar-right">
      <a href="../../dashboard/index.html" class="topbar-back">← 返回仪表盘</a>
      <span>Run {esc(run_id[:8])}</span>
    </div>
  </div>
</header>

<main class="container">
  <div class="page-head">
    <h1>{esc(store_name or '内容工厂')}</h1>
    <p class="page-meta">
      生成于 {time.strftime('%Y-%m-%d %H:%M')} · {len(items)} 个产出 · <span class="cost">{esc(cost_str)}</span>
    </p>
  </div>

  {_cost_banner(total_cost_usd, len(generated_images or []))}

  {_style_block(style_choice, palette_choice)}

  {_render_generated_assets(generated_images or [], total_cost_usd)}

  <div class="filter-row">{filter_buttons}</div>

  <div class="cards">
    {cards_html}
  </div>
</main>

<footer class="footer">
  <div class="container">
    <span>~/.commerce-os/runs/{esc(run_id)}/ · 静态文件 · 隐私本地</span>
    <span>{esc(run_id)}</span>
  </div>
</footer>

<div id="toast" class="toast"></div>

<div id="video-modal" class="modal-overlay" onclick="if(event.target===this) closeVideoModal()">
  <div class="modal">
    <h2>⚡ 启用视频生成</h2>
    <p>视频生成默认关闭。原因：</p>
    <ul style="color:var(--ink-muted); font-size:14px; padding-left:20px; line-height:1.8;">
      <li>消耗 credits 较高（每秒约 1-2 credits）</li>
      <li>质量浮动较大，需要多次试错</li>
      <li>生成耗时 1-3 分钟（异步轮询）</li>
    </ul>
    <p>如需启用，请在命令行重新跑：</p>
    <pre style="background:var(--surface-2); padding:12px; border-radius:6px; font-size:12px; color:var(--ink); margin:8px 0;">python3 run.py --type video --sku &lt;SKU&gt; \\
  --enable-video-gen --model seedance-2.0-image-to-video</pre>
    <p>支持模型：Seedance 2.0（全系列 + Fast 变体）/ HappyHorse 1.0（4 个变体）</p>
    <div class="modal-actions">
      <a class="btn primary" href="https://docs.evolink.ai/cn/api-manual/video-series/seedance2.0/seedance-2.0-overview" target="_blank">查看 Seedance 文档 ↗</a>
      <button class="btn ghost" onclick="closeVideoModal()">关闭</button>
    </div>
  </div>
</div>

<script>{JS}</script>
</body>
</html>"""
