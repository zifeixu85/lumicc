#!/usr/bin/env python3
"""Prompt templates for the 9 content types.

Each template returns a list of `Item` dicts:
{
  "subject": str,             # short title shown on the card
  "category": str,            # poster|product_image|pdp|video|...
  "prompt_text": str,         # the prompt the user copies (or we send to API)
  "target_tool_hint": str,    # which tool this prompt is meant for
  "external_link": str?,      # optional "open Midjourney / Runway / etc." URL
  "image_gen_params": dict?,  # if provided AND user has API key, we will gen
  "video_gen_params": dict?,  # same for video, opt-in only
  "language": "en" | "zh",
}
"""
from __future__ import annotations

from typing import Any


# ---------- Helpers ----------
def _normalize_style(style: str | None) -> str:
    return (style or "").strip() or "warm and natural"


def _is_zh(language: str | None) -> bool:
    return (language or "en").lower().startswith("zh")


# One-line prompt modifier per landing_style choice id (see lumicc/scripts/picker.py)
STYLE_PROMPT_MOD: dict[str, str] = {
    "aesop_apothecary": (
        "shot on dark wood surface, natural side light, serif typography overlay, "
        "beige paper texture, refined apothecary feel, deep umber and warm taupe palette"
    ),
    "kinfolk_editorial": (
        "soft daylight from a window, warm linen and cream tones, magazine-grade composition, "
        "Georgia serif headline overlay, slow-living mood, gentle film grain"
    ),
    "apple_silicon_minimal": (
        "studio seamless white, hard center alignment, crisp specular highlights, "
        "SF Pro Display sans-serif overlay, premium device-launch aesthetic, near-zero shadow"
    ),
    "brutalist_zine": (
        "high-contrast flat lighting, neon yellow + jet black palette, thick Helvetica black headline, "
        "deliberate misalignment, zine-poster energy, no soft shadows"
    ),
    "neon_y2k": (
        "gradient pink-to-purple background, glassy bubble UI accents, chrome reflections, "
        "Y2K stickers and sparkles, glossy product, dreamy cyber haze"
    ),
    "luxury_boutique": (
        "deep navy backdrop, single warm key light from upper-left, champagne gold accents, "
        "symmetric Trajan-style serif overlay, museum-grade product staging, slow cinematic feel"
    ),
}


def style_modifier(choice: dict | None) -> str:
    """Convert a landing_style choice dict into a prompt-language suffix."""
    if not choice:
        return ""
    sid = choice.get("selected_id") or choice.get("id")
    if not sid:
        return ""
    mod = STYLE_PROMPT_MOD.get(sid)
    if mod:
        return mod
    # Generic fallback: derive from tagline + fonts if a custom style was picked
    parts = [choice.get("tagline"), choice.get("fonts"), choice.get("rhythm")]
    return ", ".join(p for p in parts if p)


def _apply_style(prompt: str, style_choice: dict | None) -> str:
    mod = style_modifier(style_choice)
    if not mod:
        return prompt
    return prompt.rstrip() + f" Style direction: {mod}."


# ============================================================
#  1. Product Detail Page (PDP) — prompt-only
# ============================================================
def pdp(*, sku: str, title: str | None = None, niche: str | None = None,
        target_market: str = "us", language: str = "en", **_: Any) -> list[dict]:
    label = title or sku
    if _is_zh(language):
        body = f"""你是一位资深跨境电商文案。为商品「{label}」（品类：{niche or '—'}，目标市场：{target_market.upper()}）写一套完整的详情页文案：

1. **SEO 标题**（60-80 字符，主关键词在前）
2. **5 条 bullets**，每条 ≤ 200 字符，必须以利益点开头（不是功能）
3. **长描述**（200-400 字），含 2-3 个 H2 副标题、结尾 CTA
4. **Meta description**（≤ 160 字符）
5. **Schema.org JSON-LD**（Product + Offer + AggregateRating 三类）
6. **FAQ section**（3-5 个 Q&A，GEO 友好的引用胶囊格式）

请保证：
- 卖点真实可查，不夸张
- 关键词自然密度 1.5-2.5%
- 写完后给我一个 80 字以内的"为什么这版好"自评"""
    else:
        body = f"""You are a senior cross-border e-commerce copywriter. Write a complete PDP copy set for SKU "{label}" (niche: {niche or '—'}, target market: {target_market.upper()}):

1. **SEO title** (60-80 chars, primary keyword first)
2. **5 bullets** (≤ 200 chars each, MUST start with a benefit, not a feature)
3. **Long description** (200-400 words with 2-3 H2 subheadings, end with CTA)
4. **Meta description** (≤ 160 chars)
5. **Schema.org JSON-LD** (Product + Offer + AggregateRating)
6. **FAQ section** (3-5 Q&A pairs in GEO-friendly citation-capsule format)

Requirements:
- All claims verifiable; no exaggeration
- Keyword density 1.5–2.5% (natural)
- After writing, give an 80-word self-review of why this version works"""
    return [{
        "subject": f"PDP · {label}",
        "category": "pdp",
        "prompt_text": body,
        "target_tool_hint": "ChatGPT / Claude Sonnet 4.6",
        "external_link": "https://chat.openai.com",
        "language": language,
    }]


# ============================================================
#  2. Poster — real image gen (or prompt-only if no API)
# ============================================================
def poster(*, sku: str, title: str | None = None, occasion: str | None = None,
           style: str | None = None, count: int = 1, size: str = "16:9",
           language: str = "en", model: str | None = None,
           style_choice: dict | None = None, **_: Any) -> list[dict]:
    label = title or sku
    style_resolved = _normalize_style(style)
    items: list[dict] = []
    for i in range(1, max(1, min(count, 5)) + 1):
        if _is_zh(language):
            prompt = (
                f"为商品「{label}」生成一张{occasion or '日常'}促销海报，{style_resolved}风格。"
                f"构图：三分法构图，左 1/3 留白放品牌名 + 折扣文字（请保留中文字符清晰可读，"
                f"避免乱码或形似字符变形）；右 2/3 展示商品自然摆放在生活场景中。"
                f"光照：柔和自然光，色调偏暖。"
                f"画质：电商主图级别，4K 清晰度，无水印。"
                f"输出比例：{size}。"
                + (" 变体方向：尝试不同的视角。" if i > 1 else "")
            )
        else:
            prompt = (
                f"A {style_resolved} promotional poster for "
                f"\"{label}\"{(' · ' + occasion) if occasion else ''}. "
                f"Composition: rule-of-thirds, left third negative space for headline + price tag, "
                f"right two-thirds shows the product naturally placed in a lifestyle setting. "
                f"Lighting: soft natural light, warm tones. "
                f"Quality: e-commerce hero-image grade, 4K, no watermark. "
                f"Aspect: {size}."
                + (f" Variation #{i}: try a different camera angle." if i > 1 else "")
            )
        prompt = _apply_style(prompt, style_choice)
        items.append({
            "subject": f"海报 · {label}" + (f" · {occasion}" if occasion else "") + (f" #{i}" if count > 1 else ""),
            "category": "poster",
            "prompt_text": prompt,
            "target_tool_hint": ("GPT Image 2 (recommended for Chinese text)" if _is_zh(language)
                                 else "Nano Banana Pro"),
            "image_gen_params": {
                "model": model or ("gpt-image-2" if _is_zh(language) else "gemini-3-pro-image-preview"),
                "size": size,
                "n": 1,  # generate one at a time to make iteration cheap
            },
            "language": language,
        })
    return items


# ============================================================
#  3. Product Image (5 angles) — real gen
# ============================================================
def product_image(*, sku: str, title: str | None = None,
                  angles: list[str] | None = None,
                  language: str = "en", model: str | None = None,
                  size: str = "1:1",
                  style_choice: dict | None = None, **_: Any) -> list[dict]:
    label = title or sku
    if not angles:
        angles = ["hero", "lifestyle", "scale", "feature", "packaging"]
    descriptions = {
        "hero": "Clean white background, centered product, e-commerce hero shot, 1000×1000 minimum, no shadow other than soft drop-shadow at base.",
        "lifestyle": "Product naturally placed in its real use environment (e.g., kitchen for kitchen tools), warm natural lighting, soft depth of field, no humans in frame.",
        "scale": "Product shown next to a familiar everyday object (a hand at the edge of frame, a coffee cup, a smartphone) to convey size.",
        "feature": "Extreme close-up macro shot of one key feature (e.g., texture, mechanism, joint) with crisp focus.",
        "packaging": "Product in its retail packaging, side angle, slight 3/4 rotation so logo + label are readable.",
    }
    items: list[dict] = []
    for angle in angles:
        desc = descriptions.get(angle, f"{angle} angle of the product")
        base = (f"E-commerce product image of \"{label}\" — {angle} angle. {desc} "
                f"No watermark. Output ratio {size}.")
        items.append({
            "subject": f"商品图 · {label} · {angle}",
            "category": "product_image",
            "prompt_text": _apply_style(base, style_choice),
            "target_tool_hint": "GPT Image 2 (excellent for white-background hero shots)",
            "image_gen_params": {
                "model": model or "gpt-image-2",
                "size": size,
                "n": 1,
            },
            "language": language,
        })
    return items


# ============================================================
#  4. Product enhance — prompt only (recommends Photoroom workflow)
# ============================================================
def product_enhance(*, sku: str, title: str | None = None, language: str = "en", **_: Any) -> list[dict]:
    label = title or sku
    txt = (
        f"For SKU \"{label}\", produce a cleanup + enhancement workflow:\n\n"
        "1. **Photoroom batch settings** (background removal + shadow add + auto-crop):\n"
        "   - Recommended preset: 'E-commerce Pure White'\n"
        "   - Output size: 2000×2000 px\n"
        "   - Margin: 8%\n\n"
        "2. **Stable Diffusion ControlNet prompt** (if you prefer SD over Photoroom):\n"
        "   - Use Canny edge ControlNet to preserve product shape\n"
        "   - Background prompt: 'pristine white seamless infinity background, "
        "soft studio lighting from upper-left, subtle drop shadow below product'\n"
        "   - Strength: 0.75-0.85\n\n"
        "3. **Midjourney V6 prompt** (lifestyle composite):\n"
        "   - Use product reference image, then prompt the surrounding scene\n"
        "   - Aspect: 4:5 (Instagram-friendly)\n"
    )
    return [{
        "subject": f"商品图增强 · {label}",
        "category": "product_enhance",
        "prompt_text": txt,
        "target_tool_hint": "Photoroom / Stable Diffusion / Midjourney",
        "external_link": "https://www.photoroom.com",
        "language": language,
    }]


# ============================================================
#  5. Video prompt — prompt only by default
# ============================================================
def video(*, sku: str, title: str | None = None, style: str = "before_after",
          duration_s: int = 6, aspect: str = "9:16",
          language: str = "en", model: str | None = None,
          enable_video_gen: bool = False, **_: Any) -> list[dict]:
    label = title or sku
    style_recipes = {
        "before_after": "Open on the 'before' state (dirty / messy / cluttered) — 1.5s. Quick cut to product reveal — 0.5s. Then 'after' state (clean / organized / transformed) hold — 3s. Subtle product close-up in last 1s.",
        "hack_trick": "Static shot of someone struggling with a common problem — 2s. Quick zoom to product — 0.5s. Reveal the trick / hack — 3s. Outcome — 0.5s.",
        "problem_solution": "Open on the problem visualized — 2s. Cut to product label — 1s. Cut to product in use — 2s. Close on satisfied result — 1s.",
        "asmr_texture": "Slow macro pan over product texture — 6s with soft ambient sound.",
        "unboxing": "Hand opening the package — 1.5s. Reveal — 1s. Slow rotation showing the product — 3s. Final beauty shot — 0.5s.",
    }
    recipe = style_recipes.get(style, style_recipes["before_after"])
    chosen_model = model or "seedance-2.0-image-to-video"

    prompt_body = (
        f"Generate a {duration_s}-second {style} short video for \"{label}\". "
        f"Aspect ratio {aspect}. {recipe} "
        f"Style: cinematic but ad-friendly, natural color grading, no synthetic-looking 3D. "
        f"No on-screen text overlay (will be added later). Synced audio: ambient kitchen sounds for kitchen products, "
        f"light upbeat music otherwise."
    )

    item: dict = {
        "subject": f"视频 · {label} · {style}",
        "category": "video",
        "prompt_text": prompt_body,
        "target_tool_hint": "Seedance 2.0 (image-to-video) / HappyHorse 1.0",
        "external_link": "https://docs.evolink.ai/cn/api-manual/video-series",
        "language": language,
        "video_gen_params": {
            "model": chosen_model,
            "duration_s": duration_s,
            "aspect_ratio": aspect,
            "resolution": "720p",
        },
        "video_gen_enabled": enable_video_gen,
    }
    return [item]


# ============================================================
#  6. TikTok / Reels script — prompt only
# ============================================================
def tiktok_script(*, sku: str, title: str | None = None, niche: str | None = None,
                  language: str = "en", count: int = 5, **_: Any) -> list[dict]:
    label = title or sku
    if _is_zh(language):
        body = f"""为商品「{label}」（品类：{niche or '—'}）写 {count} 条 TikTok / Reels 短视频脚本。

每条 30-45 秒，包含：
- **Hook（前 3 秒，5 个不同变体）** — 必须能独立吸引点击
- **分镜脚本**（每秒级，含镜头语言）
- **配音文案**
- **Caption**（含 4-6 个 hashtag，2 个大流量 + 2 个中流量 + 1-2 个精准）
- **CTA**（link in bio / comment '链接' / save for later）

不同视频不同风格：before/after / hack-trick / problem-solution / ASMR / 真实用户分享。

最后给一个表格对比 5 条视频的优劣势。"""
    else:
        body = f"""Write {count} TikTok/Reels scripts for \"{label}\" (niche: {niche or '—'}).

Each 30-45s with:
- **Hook (first 3 sec, 5 different variants)** — must stand alone to grab clicks
- **Shot-by-shot script** (per-second, including camera language)
- **Voiceover copy**
- **Caption** (4-6 hashtags: 2 high-volume + 2 mid + 1-2 niche-specific)
- **CTA** (link in bio / comment 'LINK' / save for later)

Different videos: before/after / hack-trick / problem-solution / ASMR / UGC-style.

End with a comparison table of strengths/weaknesses of all 5."""
    return [{
        "subject": f"TikTok 脚本 ×{count} · {label}",
        "category": "tiktok_script",
        "prompt_text": body,
        "target_tool_hint": "Claude Sonnet 4.6",
        "external_link": "https://claude.ai",
        "language": language,
    }]


# ============================================================
#  7. Blog brief — for article-writing skill or LLM
# ============================================================
def blog_brief(*, sku: str, title: str | None = None, niche: str | None = None,
               primary_keyword: str | None = None,
               language: str = "en", **_: Any) -> list[dict]:
    label = title or sku
    kw = primary_keyword or label
    body = (
        f"Write a 1,500-word SEO blog post.\n\n"
        f"**Primary keyword**: {kw}\n"
        f"**Topic**: how \"{label}\" solves a problem in the {niche or 'home'} niche\n"
        f"**Target intent**: informational + commercial\n\n"
        f"Structure:\n"
        f"- H1: {kw}\n"
        f"- 5-7 H2 sections (use answer-engine format: each H2 starts with a question, first 40-60 chars is a self-contained answer = citation capsule for GEO)\n"
        f"- FAQ section (3-5 Q&A using Schema.org FAQPage JSON-LD)\n"
        f"- Internal links: at least 3 to existing PDPs in the same niche\n"
        f"- Internal links: at least 1 to a category collection\n\n"
        f"Voice: aligned with brand-voice profile if available.\n"
        f"Output: full Markdown + Schema.org JSON-LD blocks (Article + FAQPage)."
    )
    return [{
        "subject": f"博客 brief · {kw}",
        "category": "blog_brief",
        "prompt_text": body,
        "target_tool_hint": "article-writing skill / Claude Sonnet 4.6",
        "external_link": "https://claude.ai",
        "language": language,
    }]


# ============================================================
#  8. Ad creative variations
# ============================================================
def ad_creative(*, sku: str, title: str | None = None, platform: str = "meta",
                language: str = "en", **_: Any) -> list[dict]:
    label = title or sku
    body = (
        f"For \"{label}\" on {platform.upper()}, generate 5 ad creative concepts. "
        "Each concept includes:\n\n"
        "1. **Hook** (≤ 15 words, will be the first line of the ad)\n"
        "2. **Visual prompt** (Nano Banana Pro / GPT Image 2 image prompt — ready to paste)\n"
        "3. **Primary text** (≤ 125 chars)\n"
        "4. **Headline** (≤ 40 chars)\n"
        "5. **Description** (≤ 30 chars)\n"
        "6. **CTA** (Shop Now / Learn More / Get Offer)\n"
        "7. **Why this will work** (1 sentence)\n\n"
        "Across the 5 concepts, vary: angle (problem / aspiration / curiosity / social proof / urgency), "
        "visual style (lifestyle / studio / UGC / illustration / product close-up), audience focus."
    )
    return [{
        "subject": f"广告创意 ×5 · {label} · {platform}",
        "category": "ad_creative",
        "prompt_text": body,
        "target_tool_hint": "Claude Sonnet 4.6 → then image prompts go to Nano Banana / GPT Image 2",
        "external_link": "https://claude.ai",
        "language": language,
    }]


# ============================================================
#  9. Email sequence
# ============================================================
def email_sequence(*, sku: str | None = None, campaign: str = "welcome",
                   language: str = "en", **_: Any) -> list[dict]:
    flow_specs = {
        "welcome": "5 emails over 7 days: Day 0 (welcome + 10% off), Day 1 (brand story), Day 3 (best sellers), Day 5 (social proof), Day 7 (urgency: code expires).",
        "abandoned_cart": "3 emails: 1h after abandon (subject: 'Did you forget something?'), 24h (subject: 'Still thinking?'), 72h (subject: '10% off — last chance').",
        "winback": "3 emails over 14 days to customers inactive 90+ days: 'We miss you' (Day 0), 'What's new' (Day 7), 'Last chance: free shipping' (Day 14).",
        "post_purchase": "4 emails: order confirmation, shipping update, review request 7 days after delivery, cross-sell 21 days after delivery.",
        "seasonal": "5-email Black Friday sequence: teaser (Nov 20), early access (Nov 24), main launch (Nov 28), urgency (Nov 30), final hours (Dec 1).",
    }
    spec = flow_specs.get(campaign, flow_specs["welcome"])
    sku_part = f" for SKU \"{sku}\"" if sku else ""
    body = (
        f"Write a {campaign} email sequence{sku_part}. {spec}\n\n"
        "Each email must include:\n"
        "- **Subject line** (≤ 50 chars)\n"
        "- **Preview text** (≤ 90 chars)\n"
        "- **Body** (200-350 words with a single clear CTA button)\n"
        "- **Send time** (relative to trigger)\n"
        "- **Expected open / CTR benchmarks** for this type\n\n"
        "Format: Markdown table per email, then full body below.\n"
        "Brand voice: aligned with brand-voice skill profile if available."
    )
    return [{
        "subject": f"邮件序列 · {campaign}" + (f" · {sku}" if sku else ""),
        "category": "email_sequence",
        "prompt_text": body,
        "target_tool_hint": "Claude Sonnet 4.6 → Klaviyo / Omnisend / Postscript",
        "external_link": "https://claude.ai",
        "language": language,
    }]


# ============================================================
#  Public registry
# ============================================================
TEMPLATES = {
    "pdp": pdp,
    "poster": poster,
    "product_image": product_image,
    "product_enhance": product_enhance,
    "video": video,
    "tiktok_script": tiktok_script,
    "blog_brief": blog_brief,
    "ad_creative": ad_creative,
    "email_sequence": email_sequence,
}


def generate(type_: str, **kwargs) -> list[dict]:
    fn = TEMPLATES.get(type_)
    if not fn:
        raise ValueError(f"Unknown content type: {type_}. Supported: {list(TEMPLATES)}")
    return fn(**kwargs)
