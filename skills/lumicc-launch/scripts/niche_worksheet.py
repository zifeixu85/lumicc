#!/usr/bin/env python3
"""Generate a niche validation worksheet — the built-in fallback when no
Amazon revenue data adapter is configured.

Produces a markdown worksheet the user fills out by hand, structured to
extract the same 3 signals (TikTok hashtag volume, Amazon revenue, Google
Trends) that the API path would have provided.

Usage:
    python3 niche_worksheet.py --niche "pet accessories" \
        --target-market us --out worksheet.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def generate(niche: str, target_market: str = "us") -> str:
    market_label = {"us": "United States", "eu": "European Union", "uk": "United Kingdom",
                    "sea": "Southeast Asia", "global": "Global"}.get(target_market, target_market.upper())

    return f"""# Niche Validation Worksheet — {niche}

> Target market: **{market_label}**.
> Lumicc could not auto-pull data because no Amazon revenue adapter is configured.
> Spend ~45 minutes filling this out by hand; it is intentionally the same shape
> as the API path so future runs (with an adapter) can compare apples to apples.

## Signal 1 — Trend slope (Google Trends)

Open https://trends.google.com → set region to **{market_label}** → search the keyword `{niche}`.

| Item | Value |
|------|-------|
| 12-month slope (positive / flat / declining) | ☐ growing  ☐ flat  ☐ declining |
| Peak month (if seasonal) | _____ |
| Top 5 related rising queries (capture verbatim) | 1. ____ 2. ____ 3. ____ 4. ____ 5. ____ |

🚨 Stop & reconsider if: slope is declining for ≥ 6 months.

## Signal 2 — Social demand (TikTok)

Go to https://www.tiktok.com/discover/{niche.replace(' ', '-')} (or search the niche keyword).

| Item | Value |
|------|-------|
| Total hashtag views for primary tag | _____ M / B |
| Top 5 video styles (e.g., before/after, hack, unboxing) | 1. ____ 2. ____ 3. ____ 4. ____ 5. ____ |
| Are sellers showing direct-buy links / sponsored badges? | ☐ Yes  ☐ No |
| Estimated weekly upload velocity (new videos with the tag) | ____ / week |

🚨 Stop & reconsider if: < 50M views total **and** < 50 new videos/week.

## Signal 3 — Buyer revenue (Amazon Best Sellers)

Go to https://www.amazon.com/Best-Sellers/zgbs (find the closest category for `{niche}`).

| Position | Product name | Price | Rating | Approx. monthly revenue * | Brand age |
|---|---|---|---|---|---|
| 1 | _______ | $___ | ___ | $______ | _____ |
| 2 | _______ | $___ | ___ | $______ | _____ |
| 3 | _______ | $___ | ___ | $______ | _____ |
| 4 | _______ | $___ | ___ | $______ | _____ |
| 5 | _______ | $___ | ___ | $______ | _____ |

* Approx monthly revenue: use Helium 10 X-Ray free Chrome extension or estimate as
  `price × max(rating count delta over 30d, 50)`.

🚨 Stop & reconsider if: top 5 monthly revenue all < $3K or all > $200K (saturated).

## Signal 4 — Saturation pulse (qualitative)

Search Google for `{niche} review 2026`. Count Reddit/YouTube reviews on page 1.

| Item | Value |
|------|-------|
| Number of independent (non-affiliate) reviews on page 1 | ___ |
| Are there 3+ niche-specific blogs or YouTube channels with > 10K subs? | ☐ Yes  ☐ No |
| Existing Shopify stores in this niche (Google `{niche} site:myshopify.com`)? | ___ |

## Decision

| Criterion | Pass? |
|-----------|-------|
| At least one growing signal (Google Trends or TikTok velocity) | ☐ |
| Top 5 Amazon revenue in $3K-$200K range (sweet spot) | ☐ |
| Not over-saturated (< 50 mature Shopify competitors visible) | ☐ |
| You personally can shoot ≥ 2 TikTok angles for this niche | ☐ |

**3 of 4 = proceed.** Otherwise, pick a sub-niche.

---

Save your answers, then re-run plan.py — Lumicc will read this worksheet from
`~/.commerce-os/runs/<run_id>/niche-worksheet.md` and adjust the 30-day SOP if needed.
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--niche", required=True)
    p.add_argument("--target-market", default="us")
    p.add_argument("--out", default=None)
    args = p.parse_args()
    md = generate(args.niche, args.target_market)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(json.dumps({"saved": args.out, "niche": args.niche}, ensure_ascii=False))
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
