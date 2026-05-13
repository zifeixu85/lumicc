# 5-Factor Scoring Matrix

Each candidate scored 0-10 on five factors. Total = weighted sum. Default weights below; user may override via `preferences['expansion_weights']`.

## Factor 1 — Margin (weight 0.25)

| Score | Meaning |
|-------|---------|
| 10 | Landed cost ≤ 25% of retail (≥ 75% margin) |
| 8 | Landed cost ≤ 35% of retail (≥ 65% margin) |
| 6 | Landed cost ≤ 50% of retail (≥ 50% margin) |
| 4 | Landed cost ≤ 65% of retail (≥ 35% margin) |
| 2 | Landed cost ≤ 80% of retail (≥ 20% margin) |
| 0 | Below SOUL minimum |

Auto-fail if below SOUL minimum.

## Factor 2 — Demand Momentum (weight 0.25)

Combine 3 inputs (weight 1/3 each):
- Amazon est. monthly revenue trend (Jungle Scout): +1 per 10% YoY growth, capped at 10
- TikTok hashtag growth rate (90-day): +1 per 25% growth
- Google Trends slope: +1 per +10 points

## Factor 3 — Content Angle (weight 0.20)

| Score | Meaning |
|-------|---------|
| 10 | Strong visual hook (before/after, transformation, unboxing reveal) |
| 8 | Good lifestyle angle (aesthetic, daily-use) |
| 6 | Educational angle (how-to, hack) |
| 4 | Generic — needs creative work |
| 2 | Difficult to show on video |

## Factor 4 — Supplier Fit (weight 0.15)

Check supplier rating + verified status + response rate + your existing relationship.

| Score | Meaning |
|-------|---------|
| 10 | Existing supplier you trust, can add SKU on next order |
| 8 | Top-rated Alibaba Verified, fast response, low MOQ |
| 6 | New but reasonable supplier, low MOQ |
| 4 | Untested supplier, sample required first |
| 0 | Unverifiable / no Alibaba presence |

## Factor 5 — Fulfillment Risk (weight 0.15)

Lower risk = higher score.

| Score | Meaning |
|-------|---------|
| 10 | Lightweight, durable, no batteries, no liquid, no electronics |
| 8 | Lightweight but slightly fragile |
| 6 | Heavy / oversized → higher shipping cost |
| 4 | Batteries / liquid / restricted by some carriers |
| 2 | Trademarked or copycat risk |
| 0 | Banned / hazardous |

## Calculation

```
total = margin*0.25 + demand*0.25 + content*0.20 + supplier*0.15 + fulfillment*0.15
```

## Cut-offs

- `total >= 8.0`: 🟢 Strong candidate, order sample immediately
- `total 6.5-7.9`: 🟡 Watchlist — order sample if budget allows
- `total < 6.5`: 🔴 Reject

## Tie-breaking

If two candidates tie:
1. Prefer the one with existing supplier relationship
2. Prefer the one with stronger content angle (10 vs 8)
3. Prefer the one with smaller SKU count in same Amazon BSR (less saturated)
