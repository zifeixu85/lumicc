#!/usr/bin/env python3
"""8 listing-quality checks. Pure functions returning (score 0-10, evidence, suggested_fix).

Operates on a normalized product dict; the run.py orchestrator converts platform-specific
payloads (Shopify / Amazon / etc.) to this schema before invoking.

Normalized product schema:
{
  "title": str,
  "description": str,                 // markdown or HTML
  "bullets": [str, str, ...],
  "images": [{"url": str, "width": int?, "height": int?, "alt": str?}, ...],
  "price": float,
  "compare_at_price": float?,
  "reviews": {"count": int, "avg": float, "last_review_ts": int?},
  "scarcity_signal": bool,
  "mobile_lcp_ms": int?,
  "competitor_avg_price": float?,
  "primary_keywords": [str, str, ...],     // for SEO density
}
"""
from __future__ import annotations

import re
from typing import Any

WEIGHTS = {
    "image_count": 0.20, "title_seo": 0.15, "bullets": 0.15,
    "description": 0.10, "price_ladder": 0.10, "reviews": 0.10,
    "scarcity": 0.10, "mobile": 0.10,
}


def _ev(score: float, evidence: str, fix: str) -> dict:
    return {"score": round(score, 1), "evidence": evidence, "fix": fix}


def check_images(p: dict) -> dict:
    imgs = p.get("images") or []
    n = len(imgs)
    hero = imgs[0] if imgs else {}
    hero_w = hero.get("width") or 0
    if n == 0:
        return _ev(0, "no images", "Upload at least 5 images including hero, lifestyle, scale, feature close-up, packaging.")
    score = 10 if n >= 6 else 8 if n >= 5 else 6 if n >= 4 else 4 if n >= 3 else 2
    if hero_w and hero_w < 1000:
        score = min(score, 4)
        evidence = f"{n} images but hero is {hero_w}px wide (Amazon minimum 1000px)"
        fix = "Replace hero with a ≥1000×1000 px image."
    else:
        evidence = f"{n} images (target ≥ 6)"
        fix = "Add more angles." if n < 6 else "Already strong."
    return _ev(score, evidence, fix)


def check_title_seo(p: dict) -> dict:
    title = (p.get("title") or "").strip()
    n = len(title)
    if not title:
        return _ev(0, "empty title", "Write a 60-80 char title: primary keyword + brand + differentiator.")
    has_keyword = any((kw or "").lower() in title.lower() for kw in (p.get("primary_keywords") or []))
    has_caps_problem = title.isupper() or sum(1 for c in title if c.isupper()) > n * 0.5
    if 60 <= n <= 80 and has_keyword and not has_caps_problem:
        return _ev(10, f"{n} chars, primary keyword present, casing OK", "Already strong.")
    if 40 <= n <= 100 and has_keyword:
        return _ev(7, f"{n} chars with keyword (recommend 60-80)", "Tighten to 60-80 chars.")
    if has_caps_problem:
        return _ev(4, "ALL CAPS or aggressive capitalization", "Use Title Case; remove ALL CAPS words.")
    return _ev(3, f"{n} chars; keyword present={has_keyword}", "Restructure: primary keyword first, brand, differentiator.")


def check_bullets(p: dict) -> dict:
    bullets = [b.strip() for b in (p.get("bullets") or []) if b and b.strip()]
    n = len(bullets)
    if n == 0:
        return _ev(0, "no bullet points", "Add 5 bullets, each starting with a benefit.")
    long = sum(1 for b in bullets if len(b) > 200)
    starts_with_benefit = sum(1 for b in bullets if re.match(r"^[A-Z一-鿿]\w+\s", b))
    if n >= 5 and long == 0 and starts_with_benefit >= 3:
        return _ev(10, f"{n} bullets, formatted well, benefit-first", "Already strong.")
    if n >= 5 and long == 0:
        return _ev(7, f"{n} bullets, but not benefit-first", "Reorder bullets to lead with benefit, not feature.")
    if long > 0:
        return _ev(5, f"{long} of {n} bullets > 200 chars", "Tighten bullets to ≤ 200 chars each.")
    return _ev(3, f"only {n} bullets", f"Add {5 - n} more bullets.")


def check_description(p: dict) -> dict:
    desc = (p.get("description") or "").strip()
    # Strip HTML tags for word count
    plain = re.sub(r"<[^>]+>", " ", desc)
    words = len(plain.split())
    if not desc:
        return _ev(0, "no description", "Write 200-400 word description with headings + CTA.")
    has_heading = bool(re.search(r"<h[1-3]|^#{1,3}\s", desc, re.MULTILINE))
    has_cta = any(w in desc.lower() for w in ["shop now", "buy now", "add to cart", "立即购买", "加入购物车"])
    if 200 <= words <= 400 and has_heading and has_cta:
        return _ev(10, f"{words} words, headings + CTA", "Already strong.")
    if 200 <= words <= 400:
        return _ev(7, f"{words} words, missing headings or CTA", "Add scannable subheadings and a clear CTA.")
    if words < 150:
        return _ev(3, f"{words} words (target 200-400)", "Expand: add features, use cases, materials, care instructions.")
    return _ev(5, f"{words} words", "Tighten to 200-400 words and add CTA.")


def check_price_ladder(p: dict) -> dict:
    price = p.get("price") or 0
    compare = p.get("compare_at_price") or 0
    comp = p.get("competitor_avg_price") or 0
    has_discount = compare > price * 1.15
    if not price:
        return _ev(0, "no price", "Set a price.")
    if has_discount and comp and abs(price - comp) / comp <= 0.15:
        return _ev(10, f"compare ${compare:.2f} > price ${price:.2f}, competitive vs ${comp:.2f}", "Already strong.")
    if has_discount:
        return _ev(7, f"compare-at discount applied; no competitor data", "Re-check competitor pricing quarterly.")
    if comp and abs(price - comp) / comp > 0.25:
        return _ev(4, f"price ${price:.2f} differs > 25% from competitor avg ${comp:.2f}", "Investigate: undervalued or overpriced?")
    return _ev(5, "no compare-at price set", "Set compare_at_price ≥ 1.15× price to show savings.")


def check_reviews(p: dict) -> dict:
    rv = p.get("reviews") or {}
    n = rv.get("count") or 0
    avg = rv.get("avg") or 0
    last_ts = rv.get("last_review_ts") or 0
    import time as _t
    fresh = last_ts and (_t.time() - last_ts) < 30 * 86400
    if n == 0:
        return _ev(2, "no reviews yet", "Request reviews via post-purchase email (Klaviyo / lumicc-launch outreach pack).")
    if n >= 10 and avg >= 4.0 and fresh:
        return _ev(10, f"{n} reviews, avg {avg:.1f}, fresh", "Already strong.")
    if avg < 4.0:
        return _ev(3, f"{n} reviews, avg {avg:.1f} (< 4.0)", "Run lumicc-voc to identify and fix root causes.")
    if not fresh:
        return _ev(5, f"{n} reviews, avg {avg:.1f}, none in last 30d", "Reignite review velocity via outreach.")
    return _ev(7, f"{n} reviews, avg {avg:.1f}", "Aim for 10+ reviews + monthly fresh.")


def check_scarcity(p: dict) -> dict:
    if p.get("scarcity_signal"):
        return _ev(8, "scarcity badge present", "Already strong.")
    return _ev(5, "no scarcity / urgency signal", "Show 'Only X left' badge when inventory < 20 units.")


def check_mobile(p: dict) -> dict:
    lcp = p.get("mobile_lcp_ms")
    if lcp is None:
        return _ev(5, "mobile LCP unknown", "Test on mobile; aim for LCP < 3000 ms.")
    if lcp < 2500:
        return _ev(10, f"LCP {lcp} ms (excellent)", "Already strong.")
    if lcp < 3000:
        return _ev(8, f"LCP {lcp} ms (good)", "Trim hero image weight.")
    if lcp < 4000:
        return _ev(5, f"LCP {lcp} ms (medium)", "Compress images, defer non-critical JS.")
    return _ev(2, f"LCP {lcp} ms (slow)", "Critical: reduce image weight, defer 3rd-party scripts.")


CHECKS = {
    "image_count": check_images,
    "title_seo": check_title_seo,
    "bullets": check_bullets,
    "description": check_description,
    "price_ladder": check_price_ladder,
    "reviews": check_reviews,
    "scarcity": check_scarcity,
    "mobile": check_mobile,
}


def audit(product: dict) -> dict:
    results: dict[str, dict] = {}
    for name, fn in CHECKS.items():
        results[name] = fn(product)
    total = sum(results[k]["score"] * WEIGHTS[k] for k in results) * 10
    severity = "healthy" if total >= 85 else "improvable" if total >= 65 else "sick"
    return {
        "total": round(total, 1),
        "severity": severity,
        "checks": results,
        "top_fixes": _top_fixes(results, 3),
    }


def _top_fixes(results: dict, n: int) -> list[dict]:
    """Sort by (weight * (10 - score)) descending = highest-impact fixes."""
    issues = [
        {"check": k, "current_score": v["score"], "weight": WEIGHTS[k],
         "impact": (10 - v["score"]) * WEIGHTS[k],
         "evidence": v["evidence"], "fix": v["fix"]}
        for k, v in results.items() if v["score"] < 9.5
    ]
    issues.sort(key=lambda x: -x["impact"])
    return issues[:n]
