#!/usr/bin/env python3
"""Visual choice picker for Lumicc.

Some decisions can't happen in chat — choosing a landing style, a color palette,
or a product-card layout is something the user has to *see*. This module renders
a local HTML page with rich, clickable preview cards. The user clicks a card,
confirms, and a ``choice-<kind>.json`` lands inside the session directory.

Pure stdlib. Inherits the Lumicc 4-theme shell via ``html_lib.page()``.

CLI::

    python3 picker.py --list
    python3 picker.py --kind landing_style --session <sid> [--open]
    python3 picker.py --read landing_style --session <sid>

Set ``LUMICC_DATA_ROOT`` to override ``~/.commerce-os`` (used by tests).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

import html_lib as H
import session as S

# =============================================================================
# Catalog — the design-direction kits
# =============================================================================

_AESOP_PREVIEW = """
<div style="background:#1a1814;color:#d4cab8;padding:28px 22px;font-family:'Iowan Old Style','Times New Roman',serif;letter-spacing:.04em;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:.32em;color:#a89478;margin-bottom:24px;">APOTHECARY · NO.4</div>
  <div style="font-size:22px;line-height:1.3;margin-bottom:18px;">Resurrection<br/>Hand Balm</div>
  <div style="height:1px;background:#5b4f3e;margin:14px 0 12px;"></div>
  <div style="font-size:12px;color:#a89478;display:flex;justify-content:space-between;"><span>75 mL</span><span>$48</span></div>
</div>
"""

_KINFOLK_PREVIEW = """
<div style="background:#f6f1e7;color:#1f1a14;padding:24px 22px;font-family:Georgia,serif;">
  <div style="font-size:9px;text-transform:uppercase;letter-spacing:.4em;color:#766b56;margin-bottom:18px;">ISSUE TWELVE — SLOW LIVING</div>
  <div style="font-size:30px;line-height:1.05;font-style:italic;font-weight:400;margin-bottom:14px;">A quiet<br/>kitchen.</div>
  <div style="font-size:11px;line-height:1.7;color:#3d362a;column-count:2;column-gap:14px;">Linen aprons, ceramic bowls, and the soft clink of teaspoons. We slow down with intention.</div>
</div>
"""

_APPLE_PREVIEW = """
<div style="background:#fafcff;color:#0a0d12;padding:30px 22px;font-family:'SF Pro Display',-apple-system,system-ui,sans-serif;text-align:center;">
  <div style="font-size:26px;font-weight:600;letter-spacing:-.02em;margin-bottom:8px;">Pro. Beyond.</div>
  <div style="font-size:12px;color:#737373;margin-bottom:18px;">硅光级影像，触手可及。</div>
  <a style="display:inline-block;background:#0a0d12;color:#fff;padding:8px 18px;border-radius:999px;font-size:11px;text-decoration:none;">了解更多 ›</a>
</div>
"""

_BRUTALIST_PREVIEW = """
<div style="background:#fef200;color:#0a0a0a;padding:22px;font-family:'Helvetica Neue',Arial,sans-serif;border:3px solid #0a0a0a;">
  <div style="font-size:34px;line-height:.92;font-weight:900;text-transform:uppercase;margin-bottom:10px;">CHEAP<br/>FAST<br/>LOUD.</div>
  <div style="background:#0a0a0a;color:#fef200;font-size:10px;padding:4px 8px;display:inline-block;font-weight:700;">NEW DROP →</div>
</div>
"""

_Y2K_PREVIEW = """
<div style="background:linear-gradient(135deg,#ff6ec7 0%,#7873f5 100%);color:#fff;padding:26px 22px;font-family:'Verdana',sans-serif;">
  <div style="font-size:24px;font-weight:900;text-shadow:2px 2px 0 #00f0ff;letter-spacing:-.02em;margin-bottom:14px;">cyberglow ✨</div>
  <div style="background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.4);border-radius:14px;padding:8px 12px;font-size:11px;backdrop-filter:blur(6px);">▸ click to enter the y2k zone</div>
</div>
"""

_LUXURY_PREVIEW = """
<div style="background:#0b1220;color:#f3ecd9;padding:30px 22px;font-family:'Times New Roman',serif;text-align:center;">
  <div style="font-size:9px;letter-spacing:.5em;color:#d4af37;margin-bottom:18px;">SINCE MCMV</div>
  <div style="font-size:24px;font-style:italic;margin-bottom:8px;">Submariner</div>
  <div style="height:1px;width:30px;background:#d4af37;margin:10px auto;"></div>
  <div style="font-size:10px;letter-spacing:.3em;color:#a89260;">A LEGEND, REDEFINED</div>
</div>
"""

KINDS: dict[str, dict] = {
    "landing_style": {
        "title": "Landing 风格选择",
        "subtitle": "你的 landing 应该给访客什么第一印象？",
        "options": [
            {
                "id": "aesop_apothecary",
                "label": "Aesop · 药剂铺",
                "tagline": "克制、留白、衬线、深色木质感",
                "fit_for": "护肤 / 香氛 / 茶 / 高端食品",
                "palette": ["#1a1814", "#a89478", "#d4cab8", "#5b4f3e"],
                "fonts": "Iowan Old Style / Times",
                "rhythm": "大留白 · 单列阅读 · 不闪",
                "preview_html": _AESOP_PREVIEW,
            },
            {
                "id": "kinfolk_editorial",
                "label": "Kinfolk · 杂志感",
                "tagline": "暖白底、衬线、双栏、生活方式",
                "fit_for": "家居 / 餐具 / 文创 / 慢生活",
                "palette": ["#f6f1e7", "#2d5a3d", "#1f1a14", "#766b56"],
                "fonts": "Georgia / Source Serif",
                "rhythm": "杂志网格 · 大图配长文",
                "preview_html": _KINFOLK_PREVIEW,
            },
            {
                "id": "apple_silicon_minimal",
                "label": "Apple · 极简硅谷",
                "tagline": "通屏白、无衬线、强 CTA、对称",
                "fit_for": "3C / 数码 / SaaS / 工具",
                "palette": ["#fafcff", "#0a0d12", "#0066ff", "#737373"],
                "fonts": "SF Pro Display / SF Pro Text",
                "rhythm": "全屏分段 · 中心对齐 · 微动画",
                "preview_html": _APPLE_PREVIEW,
            },
            {
                "id": "brutalist_zine",
                "label": "Brutalist · 锐利杂志",
                "tagline": "高饱和、粗黑体、硬边框、反美学",
                "fit_for": "潮牌 / 球鞋 / 滑板 / 音乐",
                "palette": ["#fef200", "#0a0a0a", "#ff003c", "#ffffff"],
                "fonts": "Helvetica Neue Black / Arial",
                "rhythm": "块状版式 · 粗体压字 · 不对齐",
                "preview_html": _BRUTALIST_PREVIEW,
            },
            {
                "id": "neon_y2k",
                "label": "Y2K · 千禧霓虹",
                "tagline": "渐变粉紫、玻璃感、闪烁、复古图标",
                "fit_for": "美妆 / Z世代 / 二次元 / IP",
                "palette": ["#ff6ec7", "#7873f5", "#00f0ff", "#ffffff"],
                "fonts": "Verdana / Comic Neue",
                "rhythm": "贴纸堆叠 · 故障特效 · 表情符号",
                "preview_html": _Y2K_PREVIEW,
            },
            {
                "id": "luxury_boutique",
                "label": "Rolex · 奢侈品店",
                "tagline": "深海军蓝 + 香槟金 · 衬线 · 中心对齐",
                "fit_for": "腕表 / 珠宝 / 皮具 / 收藏",
                "palette": ["#0b1220", "#d4af37", "#f3ecd9", "#a89260"],
                "fonts": "Times New Roman / Trajan",
                "rhythm": "对称仪式感 · 慢淡入 · 罗马数字",
                "preview_html": _LUXURY_PREVIEW,
            },
        ],
    },
    "color_palette": {
        "title": "主色方案",
        "subtitle": "你的品牌色应该传达什么情绪？",
        "options": [
            {"id": "terracotta_sage", "label": "赤陶 + 鼠尾草",
             "swatches": ["#b85c38", "#6b7d56", "#f9efe6", "#2a221b"],
             "mood": "温暖 / 自然 / 成熟"},
            {"id": "midnight_emerald", "label": "深夜翡翠",
             "swatches": ["#0a0d12", "#34d399", "#fafcff", "#1f2937"],
             "mood": "现代 / 科技 / 高端"},
            {"id": "champagne_navy", "label": "香槟金 + 深海军蓝",
             "swatches": ["#0b1220", "#d4af37", "#f3ecd9", "#a89260"],
             "mood": "奢侈 / 经典 / 权威"},
            {"id": "linen_forest", "label": "亚麻 + 森林",
             "swatches": ["#f6f1e7", "#2d5a3d", "#1f1a14", "#766b56"],
             "mood": "杂志感 / 编辑 / 克制"},
            {"id": "soft_pastel", "label": "柔和粉彩",
             "swatches": ["#f8d7d0", "#c8e0d4", "#fef6e8", "#9a8c7a"],
             "mood": "亲和 / 女性 / 柔软"},
            {"id": "monochrome_gray", "label": "纯灰阶",
             "swatches": ["#0a0a0a", "#737373", "#fafafa", "#262626"],
             "mood": "极简 / 中性 / 工业"},
        ],
    },
    "product_card_layout": {
        "title": "商品卡布局",
        "subtitle": "在 listing / category 页里产品卡怎么呈现？",
        "options": [
            {"id": "image_top_minimal", "label": "图上文下 · 极简",
             "ratio": "1:1 image, 价格 + 标题，无装饰",
             "fit_for": "SKU 多 · 重图弱字"},
            {"id": "overlay_label", "label": "图上叠色块标签",
             "ratio": "1:1, 角标 '新品 / 限量'",
             "fit_for": "促销 / 上新 / 库存提示"},
            {"id": "horizontal_split", "label": "左图右文",
             "ratio": "适合长描述、有 USP 列表",
             "fit_for": "高客单 · 教育型购买"},
            {"id": "magazine_card", "label": "杂志大图卡",
             "ratio": "16:10 大图，标题压在底部",
             "fit_for": "品牌感 · 故事驱动"},
        ],
    },
    "hero_composition": {
        "title": "首屏构图",
        "subtitle": "落地页第一屏给访客看什么？",
        "options": [
            {"id": "centered_headline", "label": "居中标题 + CTA",
             "fit_for": "新品发布 / 单 SKU 焦点"},
            {"id": "split_image_text", "label": "左字右图",
             "fit_for": "需要展示产品本体"},
            {"id": "fullbleed_image_overlay", "label": "通屏图 + 文字叠加",
             "fit_for": "氛围 / 故事 / 品牌"},
            {"id": "video_loop_hero", "label": "视频背景循环",
             "fit_for": "服装 / 动态产品"},
            {"id": "asymmetric_editorial", "label": "杂志非对称排版",
             "fit_for": "品牌内容驱动"},
        ],
    },
    "brand_direction": {
        "title": "品牌方向选择",
        "subtitle": "你这家店要给访客留下什么第一印象？",
        "options": [
            {
                "id": "challenger_disruptor",
                "label": "挑战者 · 颠覆者",
                "tagline": "敢说、犀利、直球",
                "fit_for": "新品类 / 价格战 / 反传统",
                "voice_sample": "市面 9 块的它们卖 99，我们 19。",
                "color_hint": "#dc2626",
            },
            {
                "id": "trusted_advisor",
                "label": "可靠顾问 · 专家",
                "tagline": "稳重、专业、权威",
                "fit_for": "高单价 / 信任驱动 / 服务型",
                "voice_sample": "我们写了 8000 字告诉你这款产品的全部细节。",
                "color_hint": "#1e40af",
            },
            {
                "id": "community_curator",
                "label": "社群策展 · 生活方式",
                "tagline": "亲密、共鸣、有梗",
                "fit_for": "美妆 / 服饰 / 兴趣社群",
                "voice_sample": "这周新到的 3 件，我自己先穿了一周才上架。",
                "color_hint": "#db2777",
            },
            {
                "id": "craft_artisan",
                "label": "匠人 · 手工感",
                "tagline": "克制、有故事、不喧嚣",
                "fit_for": "食品 / 文创 / 慢工出细活",
                "voice_sample": "这批咖啡我们烘了 11 次才定稿。",
                "color_hint": "#92400e",
            },
            {
                "id": "tech_efficiency",
                "label": "效率工具 · 科技感",
                "tagline": "硬核、数据、ROI 导向",
                "fit_for": "工具 / SaaS / B2B",
                "voice_sample": "实测节省 17.3% 时间，附完整数据表。",
                "color_hint": "#0891b2",
            },
        ],
    },
    "typography_pairing": {
        "title": "字体搭配",
        "subtitle": "标题 + 正文的字体组合",
        "options": [
            {"id": "serif_serif", "label": "衬线 + 衬线",
             "stack": "'Iowan Old Style','Source Serif',Georgia,serif",
             "body_stack": "'Source Serif Pro',Georgia,serif",
             "feeling": "编辑、传统、慢"},
            {"id": "serif_sans", "label": "衬线标题 + 无衬线正文",
             "stack": "'Playfair Display','Times New Roman',serif",
             "body_stack": "-apple-system,'SF Pro Text',system-ui,sans-serif",
             "feeling": "杂志、轻奢"},
            {"id": "sans_sans", "label": "无衬线 + 无衬线",
             "stack": "-apple-system,'SF Pro Display',system-ui,sans-serif",
             "body_stack": "-apple-system,'SF Pro Text',system-ui,sans-serif",
             "feeling": "硅谷、现代、效率"},
            {"id": "display_sans", "label": "展示字 + 无衬线",
             "stack": "'DM Serif Display','Times New Roman',serif",
             "body_stack": "'Karla',-apple-system,sans-serif",
             "feeling": "建筑感、Aesop 调"},
        ],
    },
}


# =============================================================================
# Public Python API
# =============================================================================

PICKER_DIR_NAME = "picker"


def list_kinds() -> list[str]:
    """Return all available picker kinds."""
    return list(KINDS.keys())


def _picker_path(session_id: str, kind: str) -> Path:
    return S.session_dir(session_id) / f"picker-{kind}.html"


def _choice_path(session_id: str, kind: str) -> Path:
    return S.session_dir(session_id) / f"choice-{kind}.json"


def render_picker(kind: str, session_id: str, *,
                  custom_options: list[dict] | None = None) -> Path:
    """Generate HTML at ``sessions/<id>/picker-<kind>.html`` and return path.

    If ``custom_options`` is given, use those instead of the built-in catalog
    (for ad-hoc choices the caller assembles at runtime).
    """
    if kind in KINDS:
        spec = KINDS[kind]
        title = spec["title"]
        subtitle = spec["subtitle"]
        options = custom_options if custom_options is not None else spec["options"]
    else:
        if custom_options is None:
            raise ValueError(f"unknown kind {kind!r} and no custom_options provided")
        title = f"选择 · {kind}"
        subtitle = "请挑一个最贴合你意图的选项。"
        options = custom_options

    cards = [_render_option_card(kind, opt) for opt in options]
    grid = H.card_grid(cards, min_width=320)

    # If there is picker history for this (store, kind), show a "continue?" banner.
    state = S.read_state(session_id) or {}
    store_id = state.get("store_id")
    history = S.get_picker_history(store_id, kind)
    history_banner = _history_banner_html(kind, session_id, history) if history else ""

    body = (
        H.page_head(title, subtitle)
        + history_banner
        + H.section("", grid)
        + _confirm_bar_html(kind, session_id)
        + _picker_script(kind, session_id)
    )

    html = H.page(
        title=title,
        body=body,
        back_link=None,
        right_meta=f"session · {session_id[:8]}",
    )

    out = _picker_path(session_id, kind)
    out.write_text(html, encoding="utf-8")
    S.append_event(session_id, "picker_rendered", kind, path=str(out))
    return out


def read_choice(session_id: str, kind: str) -> dict | None:
    """Read the saved choice JSON, or None if the user hasn't confirmed yet."""
    p = _choice_path(session_id, kind)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def has_choice(session_id: str, kind: str) -> bool:
    """Quick existence check."""
    return _choice_path(session_id, kind).exists()


# =============================================================================
# Card rendering — visually-rich per kind
# =============================================================================


def _render_option_card(kind: str, opt: dict) -> str:
    oid = opt["id"]
    label = opt.get("label", oid)
    json_payload = H.esc(json.dumps(opt, ensure_ascii=False))

    if kind == "color_palette":
        preview = _palette_preview(opt.get("swatches", []))
        meta = f'<div class="opt-meta">{H.esc(opt.get("mood", ""))}</div>'
    elif kind == "landing_style":
        preview = f'<div class="opt-preview">{opt.get("preview_html", "")}</div>'
        meta = (
            f'<div class="opt-tagline">{H.esc(opt.get("tagline", ""))}</div>'
            f'<div class="opt-meta">适合 · {H.esc(opt.get("fit_for", ""))}</div>'
            f'<div class="opt-meta">{H.esc(opt.get("fonts", ""))} · {H.esc(opt.get("rhythm", ""))}</div>'
        )
    elif kind == "typography_pairing":
        head_stack = opt.get("stack", "serif")
        body_stack = opt.get("body_stack", "sans-serif")
        preview = (
            f'<div class="opt-preview" style="background:var(--surface);padding:22px 18px;">'
            f'<div style="font-family:{head_stack};font-size:30px;line-height:1.15;color:var(--text);margin-bottom:10px;">Aa Headline</div>'
            f'<div style="font-family:{body_stack};font-size:13px;line-height:1.55;color:var(--text-muted);">'
            f'The quick brown fox leaps over a lazy product description.</div>'
            f'</div>'
        )
        meta = (
            f'<div class="opt-meta">{H.esc(opt.get("feeling", ""))}</div>'
            f'<div class="opt-meta opt-mono">{H.esc(opt.get("stack", ""))}</div>'
        )
    elif kind == "product_card_layout":
        preview = _layout_preview(oid)
        meta = (
            f'<div class="opt-meta">{H.esc(opt.get("ratio", ""))}</div>'
            f'<div class="opt-meta">适合 · {H.esc(opt.get("fit_for", ""))}</div>'
        )
    elif kind == "hero_composition":
        preview = _hero_preview(oid)
        meta = f'<div class="opt-meta">适合 · {H.esc(opt.get("fit_for", ""))}</div>'
    else:
        preview = ""
        meta = "".join(
            f'<div class="opt-meta">{H.esc(k)} · {H.esc(v)}</div>'
            for k, v in opt.items() if k not in ("id", "label")
        )

    return (
        f'<button type="button" class="opt-card" '
        f'data-opt-id="{H.esc(oid)}" data-opt-payload="{json_payload}" '
        f'aria-pressed="false">'
        f'{preview}'
        f'<div class="opt-body">'
        f'  <div class="opt-label">{H.esc(label)}</div>'
        f'  {meta}'
        f'</div>'
        f'<span class="opt-check" aria-hidden="true">✓</span>'
        f'</button>'
    )


def _palette_preview(swatches: list[str]) -> str:
    if not swatches:
        return ""
    chips = "".join(
        f'<span class="swatch" style="background:{H.esc(c)}" title="{H.esc(c)}"></span>'
        for c in swatches
    )
    return f'<div class="opt-preview opt-preview-swatches">{chips}</div>'


def _layout_preview(oid: str) -> str:
    if oid == "image_top_minimal":
        inner = (
            '<div style="background:var(--surface-2);aspect-ratio:1/1;border-radius:4px;margin-bottom:8px;"></div>'
            '<div style="height:8px;background:var(--text);width:60%;margin-bottom:4px;"></div>'
            '<div style="height:6px;background:var(--text-muted);width:30%;"></div>'
        )
    elif oid == "overlay_label":
        inner = (
            '<div style="position:relative;background:var(--surface-2);aspect-ratio:1/1;border-radius:4px;margin-bottom:8px;">'
            '<span style="position:absolute;top:6px;left:6px;background:var(--accent);color:#fff;font-size:9px;padding:2px 6px;border-radius:2px;">NEW</span>'
            '</div>'
            '<div style="height:8px;background:var(--text);width:55%;"></div>'
        )
    elif oid == "horizontal_split":
        inner = (
            '<div style="display:flex;gap:8px;align-items:stretch;">'
            '<div style="background:var(--surface-2);width:42%;aspect-ratio:1/1;border-radius:4px;"></div>'
            '<div style="flex:1;display:flex;flex-direction:column;gap:5px;padding-top:4px;">'
            '<div style="height:8px;background:var(--text);width:80%;"></div>'
            '<div style="height:5px;background:var(--text-muted);width:60%;"></div>'
            '<div style="height:5px;background:var(--text-muted);width:70%;"></div>'
            '<div style="height:5px;background:var(--text-muted);width:50%;"></div>'
            '</div></div>'
        )
    elif oid == "magazine_card":
        inner = (
            '<div style="position:relative;background:var(--surface-2);aspect-ratio:16/10;border-radius:4px;overflow:hidden;">'
            '<div style="position:absolute;left:10px;bottom:10px;height:9px;background:#fff;width:60%;opacity:.95;"></div>'
            '<div style="position:absolute;left:10px;bottom:24px;height:6px;background:#fff;width:30%;opacity:.7;"></div>'
            '</div>'
        )
    else:
        inner = '<div style="background:var(--surface-2);aspect-ratio:1/1;border-radius:4px;"></div>'
    return f'<div class="opt-preview" style="padding:16px;background:var(--surface);">{inner}</div>'


def _hero_preview(oid: str) -> str:
    if oid == "centered_headline":
        inner = (
            '<div style="text-align:center;padding:20px 8px;">'
            '<div style="height:10px;background:var(--text);width:60%;margin:0 auto 6px;"></div>'
            '<div style="height:6px;background:var(--text-muted);width:35%;margin:0 auto 12px;"></div>'
            '<div style="display:inline-block;background:var(--accent);height:14px;width:60px;border-radius:7px;"></div>'
            '</div>'
        )
    elif oid == "split_image_text":
        inner = (
            '<div style="display:flex;gap:10px;padding:14px;align-items:center;">'
            '<div style="flex:1;display:flex;flex-direction:column;gap:5px;">'
            '<div style="height:9px;background:var(--text);width:80%;"></div>'
            '<div style="height:6px;background:var(--text-muted);width:60%;"></div>'
            '<div style="height:6px;background:var(--text-muted);width:50%;"></div>'
            '<div style="background:var(--accent);height:11px;width:50px;border-radius:6px;margin-top:6px;"></div>'
            '</div>'
            '<div style="background:var(--surface-2);width:42%;aspect-ratio:1/1;border-radius:4px;"></div>'
            '</div>'
        )
    elif oid == "fullbleed_image_overlay":
        inner = (
            '<div style="position:relative;background:linear-gradient(135deg,var(--surface-2),var(--accent));aspect-ratio:16/9;">'
            '<div style="position:absolute;left:14px;bottom:14px;">'
            '<div style="height:10px;background:#fff;width:140px;margin-bottom:5px;opacity:.95;"></div>'
            '<div style="height:6px;background:#fff;width:80px;opacity:.7;"></div>'
            '</div></div>'
        )
    elif oid == "video_loop_hero":
        inner = (
            '<div style="position:relative;background:#0a0a0a;aspect-ratio:16/9;">'
            '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">'
            '<div style="width:0;height:0;border-left:14px solid #fff;border-top:9px solid transparent;border-bottom:9px solid transparent;opacity:.9;"></div>'
            '</div></div>'
        )
    elif oid == "asymmetric_editorial":
        inner = (
            '<div style="position:relative;padding:18px 14px;min-height:120px;">'
            '<div style="height:14px;background:var(--text);width:70%;"></div>'
            '<div style="height:8px;background:var(--text-muted);width:40%;margin-top:32px;margin-left:35%;"></div>'
            '<div style="background:var(--surface-2);position:absolute;right:10px;top:14px;width:38%;aspect-ratio:3/4;border-radius:3px;"></div>'
            '</div>'
        )
    else:
        inner = '<div style="background:var(--surface-2);aspect-ratio:16/9;"></div>'
    return f'<div class="opt-preview" style="background:var(--surface);overflow:hidden;">{inner}</div>'


# =============================================================================
# Confirm bar + client script
# =============================================================================


def _history_banner_html(kind: str, session_id: str, history: dict) -> str:
    """Render a "上次你选了 X，继续吗？" banner above the picker grid."""
    label = history.get("label") or history.get("selected_id") or history.get("id") or "上一次的选择"
    payload = H.esc(json.dumps(history, ensure_ascii=False))
    return f"""
<div class="picker-history-banner" role="region" aria-label="历史选择"
     data-history-payload="{payload}">
  <div class="picker-history-inner">
    <div class="picker-history-text">
      <strong>上次你选了「{H.esc(str(label))}」</strong>
      <span class="picker-history-hint">继续使用这个选择，或者下方挑一个新的。</span>
    </div>
    <button type="button" id="picker-history-continue" class="btn btn-primary">继续使用</button>
  </div>
</div>
<style>
.picker-history-banner {{
  background:color-mix(in oklab, var(--accent) 10%, var(--card-bg));
  border:1px solid var(--accent);
  border-radius:12px;
  padding:14px 18px;
  margin:0 0 20px;
}}
.picker-history-inner {{ display:flex;align-items:center;gap:16px;flex-wrap:wrap; }}
.picker-history-text {{ flex:1;min-width:200px;font-size:13px;color:var(--text-muted); }}
.picker-history-text strong {{ display:block;color:var(--text);font-size:14px;margin-bottom:2px; }}
.picker-history-hint {{ font-size:12px;opacity:.8; }}
</style>
"""


def _confirm_bar_html(kind: str, session_id: str) -> str:
    expected_path = _choice_path(session_id, kind)
    return f"""
<div class="picker-bar" role="region" aria-label="确认选择">
  <div class="picker-bar-inner">
    <div class="picker-bar-info">
      <strong>未选择</strong>
      <span class="picker-bar-hint" id="picker-tip">视觉选择只能眼睛看 — 所以我们才弹这个页面给你点 ·
        <button type="button" class="link-btn" id="why-dismiss">知道了</button>
      </span>
    </div>
    <button type="button" id="picker-confirm" class="btn btn-primary" disabled>确认选择</button>
  </div>
  <div class="picker-status" id="picker-status" hidden></div>
  <div class="picker-fallback" id="picker-fallback" hidden>
    <div>已下载到 <code>~/Downloads/choice-{H.esc(kind)}.json</code>。请把它移到 session 目录：</div>
    <div class="picker-cmd">
      <code id="picker-cmd-text">mv ~/Downloads/choice-{H.esc(kind)}.json {H.esc(str(expected_path))}</code>
      <button type="button" class="btn btn-ghost" id="picker-copy-cmd">复制</button>
    </div>
    <div class="picker-bar-hint">移动完成后，回到 chat 跟我说一声「OK」。</div>
  </div>
</div>
"""


def _picker_script(kind: str, session_id: str) -> str:
    expected_path = _choice_path(session_id, kind)
    return f"""
<style>
.opt-card {{
  display:flex;flex-direction:column;align-items:stretch;gap:0;
  text-align:left;background:var(--card-bg);border:1px solid var(--border);
  border-radius:14px;overflow:hidden;cursor:pointer;
  padding:0;font:inherit;color:inherit;
  transition:transform .18s ease, border-color .18s ease, box-shadow .18s ease;
  position:relative;
}}
.opt-card:hover {{ transform:translateY(-2px); border-color:var(--accent); box-shadow:0 8px 24px rgba(0,0,0,.18); }}
.opt-card[aria-pressed="true"] {{
  border:2px solid var(--accent);
  box-shadow:0 0 0 4px color-mix(in oklab, var(--accent) 22%, transparent);
}}
.opt-card[aria-pressed="true"] .opt-check {{ opacity:1; transform:scale(1); }}
.opt-check {{
  position:absolute;top:10px;right:10px;width:26px;height:26px;border-radius:50%;
  background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;
  font-weight:700;opacity:0;transform:scale(.6);transition:.18s ease;
}}
.opt-preview {{ display:block; min-height:120px; }}
.opt-preview-swatches {{ display:flex; height:88px; }}
.opt-preview-swatches .swatch {{ flex:1; }}
.opt-body {{ padding:14px 16px 16px; display:flex; flex-direction:column; gap:4px; border-top:1px solid var(--border); }}
.opt-label {{ font-size:15px; font-weight:600; color:var(--text); margin-bottom:2px; }}
.opt-tagline {{ font-size:12.5px; color:var(--text-muted); margin-bottom:4px; }}
.opt-meta {{ font-size:11.5px; color:var(--text-muted); line-height:1.5; }}
.opt-mono {{ font-family:ui-monospace,Menlo,monospace; font-size:10.5px; opacity:.7; }}

.picker-bar {{
  position:fixed;left:0;right:0;bottom:0;z-index:50;
  background:color-mix(in oklab, var(--card-bg) 95%, transparent);
  backdrop-filter:blur(10px);
  border-top:1px solid var(--border);
  padding:14px 24px;
}}
.picker-bar-inner {{ display:flex; align-items:center; gap:16px; max-width:1200px; margin:0 auto; }}
.picker-bar-info {{ flex:1; font-size:13px; color:var(--text-muted); }}
.picker-bar-info strong {{ color:var(--text); margin-right:10px; }}
.picker-bar-hint {{ font-size:12px; opacity:.7; }}
.link-btn {{ background:none;border:none;color:var(--accent);cursor:pointer;font:inherit;text-decoration:underline; }}
.picker-status {{ max-width:1200px;margin:8px auto 0;font-size:13px;color:var(--accent); }}
.picker-status.err {{ color:var(--danger,#ef4444); }}
.picker-fallback {{ max-width:1200px;margin:10px auto 0;font-size:12.5px;color:var(--text-muted); }}
.picker-cmd {{ display:flex;gap:8px;align-items:center;margin:6px 0; }}
.picker-cmd code {{ flex:1;background:var(--surface-2);padding:6px 10px;border-radius:6px;font-size:11.5px;overflow-x:auto; }}
.main {{ padding-bottom:140px; }}
</style>
<script>
(function() {{
  const KIND = {json.dumps(kind)};
  const SESSION_ID = {json.dumps(session_id)};
  const EXPECTED_PATH = {json.dumps(str(expected_path))};
  const cards = document.querySelectorAll('.opt-card');
  const confirmBtn = document.getElementById('picker-confirm');
  const info = document.querySelector('.picker-bar-info strong');
  const status = document.getElementById('picker-status');
  const fallback = document.getElementById('picker-fallback');
  let selected = null;

  cards.forEach(c => c.addEventListener('click', () => {{
    cards.forEach(x => x.setAttribute('aria-pressed', 'false'));
    c.setAttribute('aria-pressed', 'true');
    selected = JSON.parse(c.getAttribute('data-opt-payload'));
    info.textContent = '已选 · ' + (selected.label || selected.id);
    confirmBtn.disabled = false;
  }}));

  const tip = document.getElementById('why-dismiss');
  if (tip) tip.addEventListener('click', () => {{
    const t = document.getElementById('picker-tip'); if (t) t.style.display = 'none';
  }});

  async function saveChoice(payload) {{
    const text = JSON.stringify(payload, null, 2);
    const filename = 'choice-' + KIND + '.json';
    // Primary: showSaveFilePicker (Chromium)
    if (window.showSaveFilePicker) {{
      try {{
        const handle = await window.showSaveFilePicker({{
          suggestedName: filename, startIn: 'home',
          types: [{{description: 'JSON', accept: {{'application/json': ['.json']}}}}],
        }});
        const w = await handle.createWritable();
        await w.write(text); await w.close();
        status.hidden = false; status.classList.remove('err');
        status.textContent = '✓ 已保存。如果不是存到 ' + EXPECTED_PATH + ' 就 mv 一下，然后回到 chat 跟我说一声。';
        confirmBtn.disabled = true; return;
      }} catch (e) {{
        if (e && e.name === 'AbortError') return; // user canceled
      }}
    }}
    // Fallback: Blob download
    const blob = new Blob([text], {{type: 'application/json'}});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    status.hidden = false; status.classList.remove('err');
    status.textContent = '已下载到 Downloads/。请按下方命令移动文件。';
    fallback.hidden = false;
    confirmBtn.disabled = true;
  }}

  confirmBtn.addEventListener('click', () => {{
    if (!selected) return;
    const payload = Object.assign({{}}, selected, {{
      kind: KIND, selected_id: selected.id,
      picked_at: Math.floor(Date.now() / 1000),
      session_id: SESSION_ID,
    }});
    saveChoice(payload);
  }});

  const historyBanner = document.querySelector('.picker-history-banner');
  const continueBtn = document.getElementById('picker-history-continue');
  if (continueBtn && historyBanner) {{
    continueBtn.addEventListener('click', () => {{
      let hist = null;
      try {{ hist = JSON.parse(historyBanner.getAttribute('data-history-payload') || 'null'); }}
      catch (e) {{ hist = null; }}
      if (!hist) return;
      const payload = Object.assign({{}}, hist, {{
        kind: KIND, selected_id: hist.selected_id || hist.id,
        picked_at: Math.floor(Date.now() / 1000),
        session_id: SESSION_ID,
        from_history: true,
      }});
      saveChoice(payload);
    }});
  }}

  const copyBtn = document.getElementById('picker-copy-cmd');
  if (copyBtn) copyBtn.addEventListener('click', () => {{
    const txt = document.getElementById('picker-cmd-text').textContent;
    navigator.clipboard.writeText(txt).then(() => {{
      copyBtn.textContent = '已复制'; setTimeout(() => copyBtn.textContent = '复制', 1500);
    }});
  }});
}})();
</script>
"""


# =============================================================================
# CLI
# =============================================================================


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="list available kinds")
    ap.add_argument("--kind", default=None, help="picker kind")
    ap.add_argument("--session", default=None, help="session id")
    ap.add_argument("--open", action="store_true", help="open the picker in a browser")
    ap.add_argument("--read", default=None, metavar="KIND",
                    help="read saved choice JSON for KIND")
    args = ap.parse_args(argv)

    if args.list:
        for k in list_kinds():
            spec = KINDS[k]
            print(f"{k:24s} {spec['title']}  ({len(spec['options'])} options)")
        return 0

    if args.read:
        if not args.session:
            print("error: --session required with --read", file=sys.stderr)
            return 2
        choice = read_choice(args.session, args.read)
        if choice is None:
            print("null"); return 1
        # Persist as history so future picker renders can offer "continue?"
        state = S.read_state(args.session) or {}
        try:
            S.record_picker_choice(state.get("store_id"), args.read, choice)
        except Exception:  # noqa: BLE001
            pass
        print(json.dumps(choice, indent=2, ensure_ascii=False))
        return 0

    if not args.kind or not args.session:
        ap.error("--kind and --session are required (or use --list / --read)")

    path = render_picker(args.kind, args.session)
    print(str(path))
    if args.open:
        webbrowser.open(f"file://{path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
