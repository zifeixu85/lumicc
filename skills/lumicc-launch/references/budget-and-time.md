# Budget & Time Feasibility

Use this table to set realistic expectations before kicking off a 30-day cold-start.

## Minimum viable inputs

| Item | Minimum | Comfortable | Notes |
|------|---------|-------------|-------|
| Total budget | $500 | $3,000 | Excludes ad spend |
| Ad spend reserve (optional) | $0 | $1,500 | Use only after Week 3 |
| Founder hours / week | 8 | 15 | Excludes setup week 1 (~25h) |
| TikTok / IG accounts | 1 | 1-2 fresh | New accounts have algorithm cooldown |
| Sample order budget | $30-100 | $200-500 | Per SKU, 5-20 units |

## Cost breakdown (typical, $)

| Item | Lean | Standard | Comfortable |
|------|------|----------|-------------|
| Shopify (Basic) trial→paid | $0 (trial) | $39/mo | $39/mo |
| Domain | $12/yr | $12/yr | $12/yr |
| Logo (Looka or Photoroom) | $0 | $20 | $80 |
| Sample products | $100 | $300 | $800 |
| Initial inventory (10 units × 3 SKUs) | $300 | $900 | $1,800 |
| Content creation tools (Canva, CapCut) | $0 | $0 | $30/mo |
| Email tool (Klaviyo free tier) | $0 | $0 | $0 (free < 250 contacts) |
| Influencer micro (5 × $50 gift+fee) | $0 | $250 | $500 |
| Ad spend reserve | $0 | $300 | $1,500 |
| **TOTAL (30 days)** | **~$400** | **~$1,800** | **~$5,000** |

## Time breakdown (typical, hours)

| Phase | Lean | Standard | Comfortable |
|-------|------|----------|-------------|
| Week 1 — research & sourcing | 12 | 20 | 30 |
| Week 2 — store setup & listing | 15 | 22 | 30 |
| Week 3 — content & traffic | 15 | 25 | 40 |
| Week 4 — monitor & iterate | 8 | 15 | 25 |
| **TOTAL** | **~50h** | **~82h** | **~125h** |

## Reality checks

### "Can I do this with $200 and 5 hours/week?"
No. A reasonable floor is $400 + 50 hours total. Below that, expect to ship slower (45-60 days) and risk no first sale in month 1.

### "Can I run this on a side job with full-time work?"
Yes if 8-10 hours/week, but expect:
- Week 1 sourcing: ~12 hours non-negotiable (do this on a weekend)
- Days 11-14: store setup (~20 hours) — best on a 3-day weekend
- Content creation: 2-3 hours/week sustained

### "What if I outsource content to a freelancer?"
Add ~$300-800 for a freelance video creator. Quality varies wildly — favor portfolio reviews over price. See `references/content-playbook.md`.

## Failure modes to flag

| Symptom | Diagnostic | Recommended action |
|---------|------------|---------------------|
| Budget < $400 | Too lean to validate properly | Bootstrap with dropship only (no inventory) |
| Time < 8h/week | Cannot sustain content cadence | Halve catalog to 1-2 SKUs, defer content to 1/week |
| No TikTok presence ever | New account = cold-start algorithm penalty | Spend 10 days warming up the account before posting commercial content |
| Niche overlap with > 50 mature competitors | Margin will compress quickly | Pivot to a sub-niche or specific use-case angle |

## Idempotent estimator

`scripts/resource_estimator.py` returns this same table parameterized to the user's inputs. Re-run any time inputs change.
