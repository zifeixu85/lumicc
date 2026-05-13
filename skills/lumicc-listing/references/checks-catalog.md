# 8 Listing Checks

Each check returns `{score: 0-10, evidence: [...], suggested_fix: "..."}`.

## 1. Image count & quality (weight 0.20)

| Score | Criteria |
|-------|----------|
| 10 | ≥ 6 images: hero, lifestyle, scale, feature close-up, packaging, infographic |
| 8 | 5 images covering 4+ angles |
| 6 | 4 images |
| 4 | 3 images, mostly product-only |
| 2 | 1-2 images (worst-case) |

Auto-fail if hero is < 1000×1000 px on Amazon.

## 2. Title SEO & structure (weight 0.15)

Score 10 if title has:
- Primary keyword first
- Brand name (if any) after the descriptor
- 1-2 differentiators (material, count, use)
- 60-80 characters (Amazon), 50-60 (Shopify)
- No ALL CAPS, no emoji except 1 max

## 3. Bullet copy strength (weight 0.15)

5 bullets × score each:
- Starts with benefit, not feature
- Includes a number where relevant
- Has emotional + functional language balance
- < 200 chars per bullet

## 4. Description depth & SEO density (weight 0.10)

- 200-400 words
- Includes secondary keywords 2-3x naturally
- Has scannable subheadings
- Ends with CTA

## 5. Price ladder & compare-at (weight 0.10)

- compare_at_price exists and ≥ 1.15× active price
- Price competitive vs scraped competitor avg (±15%)
- "Free shipping" threshold if applicable

## 6. Reviews freshness & response (weight 0.10)

- At least 1 review in last 30 days
- Average ≥ 4.0
- All ≤ 3-star reviews have a public response

## 7. Scarcity & urgency signals (weight 0.10)

- "Only X left" badge present (when actually low stock)
- Promo countdown if active

## 8. Mobile rendering (weight 0.10)

- LCP < 3s
- No horizontal scroll
- CTA visible on first scroll

## Total score

```
total = sum(score_i × weight_i) × 10  # → 0-100
```

## Action recommendation

- ≥ 85: 🟢 Healthy — leave as-is
- 65-84: 🟡 Improvable — top 3 fixes
- < 65: 🔴 Sick — top 5 fixes, consider relaunch
