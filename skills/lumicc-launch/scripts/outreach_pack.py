#!/usr/bin/env python3
"""Generate micro-influencer outreach drafts (Day 21 of cold-start).

Produces N personalized email/DM drafts. Lumicc does NOT send them — the user
reviews and sends manually (or via their preferred CRM/email tool).

Usage:
    python3 outreach_pack.py --niche "pet accessories" --product "Magnetic Knife Rack" \
        --price 29.99 --product-url https://acme-pets.com/products/magnetic-knife-rack \
        --count 5 --out outreach.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Three templates rotated to keep outreach varied
TEMPLATES = [
    """Subject: Quick question about {niche} content

Hi [Creator],

I caught your recent {niche} reel — the [SPECIFIC THING you noticed, e.g., the lighting in the kitchen shot, the editing pacing] really stood out.

I'm launching a {niche} brand and our hero is **{product}** — solves [PROBLEM] for [AUDIENCE].

Would you be open to a no-strings free unit (worth ${price})? If you organically like it and post about it, we can talk a paid creator partnership.

Reply "yes" and I'll send the unit + a 15% creator code for your followers.

— [Your name]
{product_url}
""",
    """Hey [Creator] 👋

Your [SPECIFIC content piece] is exactly the {niche} vibe I'm building toward. I'm sending a few {product} units (${price} retail) to creators whose audience overlaps with my ICP.

No obligations. If you genuinely love it, a feature post would mean the world — and we'd be happy to set up an affiliate code.

DM me your shipping address if you're interested. Cheers!
{product_url}
""",
    """Hi [Creator],

Big fan of your {niche} content — [SPECIFIC moment].

I run a small new brand: **{product}** (${price}). It's [1-sentence value prop]. I'd love to ship one to you, no strings attached, just to get your honest take.

If it sparks a post, amazing. If not, no worries — keep it.

Reply with your address (or PM me) and it goes out tomorrow.

{product_url}
""",
]


def generate(niche: str, product: str, price: float, product_url: str, count: int = 5) -> str:
    lines: list[str] = []
    lines.append(f"# Influencer Outreach Pack — {niche}")
    lines.append("")
    lines.append(f"**Product**: {product}")
    lines.append(f"**Price**: ${price:.2f}")
    lines.append(f"**Product URL**: {product_url}")
    lines.append("")
    lines.append("## How to use")
    lines.append("- Replace `[Creator]` with the actual handle.")
    lines.append("- Replace `[SPECIFIC THING / moment]` with something genuine you observed in their recent content (this is non-negotiable — bulk templates without personalization perform 5-10x worse).")
    lines.append("- Replace `[PROBLEM]`, `[AUDIENCE]`, `[Your name]`.")
    lines.append("- Send a maximum of 10 per day to avoid platform spam flags.")
    lines.append("")
    for i in range(count):
        tmpl = TEMPLATES[i % len(TEMPLATES)]
        lines.append(f"## Draft {i+1}")
        lines.append("")
        body = tmpl.format(niche=niche, product=product, price=price, product_url=product_url)
        lines.append(body)
        lines.append("---")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--niche", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--product-url", required=True)
    p.add_argument("--count", type=int, default=5)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    md = generate(args.niche, args.product, args.price, args.product_url, args.count)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(json.dumps({"saved": args.out, "count": args.count}, ensure_ascii=False))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
