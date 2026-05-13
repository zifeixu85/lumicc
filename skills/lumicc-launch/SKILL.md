---
name: lumicc-launch
description: 30-day step-by-step SOP for launching a cross-border e-commerce store from zero — niche validation, product sourcing, store setup, listing publication, content distribution, and first-week monitoring. Triggers on phrases like "start a store", "new store", "from scratch", "launch a Shopify / Amazon / TikTok Shop store", "first time selling cross-border", "0 to 1", "新店", "从零开始", "刚开始", "0到1出海", "上店". MUST be used when the user signals they are starting a new store (first-time seller, no existing store, or explicit "from scratch" / "0→1" mention). The router (`lumicc`) also auto-dispatches here when `store.db` has no store row or stage = 0-to-1.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: launch
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, cold-start, 30-day-plan, gantt, sop]
    category: ops
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-launch

Take a brand-new cross-border seller from "I want to start a store" to "$500+ first month revenue" in a structured 30-day SOP. Every step is logged to `~/.commerce-os/`, every decision goes through user confirmation, every spending estimate is upfront.

## Persona

**Team**: 🏪 建站团队 · Shopify / 独立站 · see [`personas.md` § 2](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的 Shopify / 建站团队。从今天起 30 天内带你从开店到首单——每天我会推一份任务清单。先问 3 个问题：niche、目标市场、每周能投入几小时？

**Tone**: 手把手、像同事而非顾问，遇到平台坑直接说。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 30 天计划生成 → 数据分析师
- 账号警告 → 危机响应官

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Parent skill (`lumicc`) routed here because `store.db` is empty or stage = `0-to-1`.
- User explicitly says "from scratch", "new store", "first time", "刚开始做跨境".
- User has < 30 days of store age AND 0 sales.

## Workflow

### Week 1 — Validation & Sourcing

| Day | Step | Companion skill |
|-----|------|-----------------|
| 1 | Niche validation — collect 3 data points (Google Trends + TikTok hashtag volume + Amazon revenue) | `market-insight-product-selection` |
| 2 | Amazon revenue research (Jungle Scout): 12 candidate ASINs, filter to top 5 | `jungle-scout-deep-dive-analyzer` |
| 3 | Supplier matching (Alibaba/1688): 3-5 suppliers per top 5 ASIN | `product-supplier-sourcing`, `1688-sourcing` |
| 4 | Margin math + final pick top 3 SKUs | `profit-margin-analyzer` |
| 5 | Landed cost & tariff sanity check | `tariff-search`, `international-shipping-customs` |
| 6 | User confirmation gate: budget, target margin, market | (manual) |
| 7 | Order samples (if budget allows) or trust supplier rating | (manual) |

**Output**: `runs/<run_id>.json` with the 3 confirmed SKUs + supplier details.

### Week 2 — Store Setup & Listing

| Day | Step | Companion skill |
|-----|------|-----------------|
| 8 | Register Shopify trial (or Amazon Seller Central, or TikTok Shop) | (guide user) |
| 9 | Generate API credentials per `references/api-credentials.md` | (guide user) |
| 10 | Theme + brand basics — logo, color, fonts | `logo-design`, `brand visual` |
| 11-12 | Bulk product upload (3 products × ≥ 5 images, SEO title + description, compare-at price) | `shopify-builder`, `product-description-generator` |
| 13 | Collections, policies, shipping zones | (script: `scripts/store_setup.py`) |
| 14 | Homepage hero banner + announcement bar | `shopify-builder` |

### Week 3 — Content & Initial Traffic

| Day | Step | Companion skill |
|-----|------|-----------------|
| 15-17 | TikTok video content: 5 videos per hero SKU (before/after, hack, problem/solution) | `social-media-publisher`, content gen |
| 18-19 | Instagram carousel + Reels seeding | `instagram-marketing`, `social-media-publisher` |
| 20 | Pinterest pins (optional, free traffic) | (guide) |
| 21 | Influencer outreach: 5-10 micro-influencers in niche | (script: `scripts/outreach_pack.py`) |

### Week 4 — Monitor & Iterate

| Day | Step | Companion skill |
|-----|------|-----------------|
| 22 | First data review — sessions, conversion, top traffic source | (script: `scripts/first_metrics.py`) |
| 23-24 | Listing optimization based on data | `lumicc-listing` |
| 25 | First competitor watchtower run | `lumicc-watch` |
| 26-28 | Iterate ad spend or content cadence | `tiktok-ads-strategy` (optional, paid) |
| 29 | First VoC pass if any reviews exist | `lumicc-voc` |
| 30 | 30-day retrospective + plan next cycle | (script: `scripts/retro.py`) |

## Resource Estimator

Before kicking off, run:
```bash
python3 scripts/resource_estimator.py --budget 5000 --hours-per-week 15 --tiktok-accounts 1
```

Outputs feasibility table — see `references/budget-and-time.md`.

## Inputs

```json
{
  "store_id": "string (created by parent skill if missing)",
  "platform": "shopify | amazon | tiktok-shop | etsy | independent",
  "target_market": "us | eu | uk | sea | global",
  "niche": "string",
  "budget_usd": "number",
  "hours_per_week": "number"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-launch",
  "status": "success | partial | failed",
  "deliverables": [
    {"type": "product_shortlist", "path": "runs/<id>/shortlist.csv"},
    {"type": "store_plan", "path": "runs/<id>/plan.md"},
    {"type": "content_calendar", "path": "runs/<id>/content.md"}
  ],
  "campaign_id": "string",
  "next_recommended_skill": "lumicc-listing"
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/resource_estimator.py` | Feasibility check given budget + time |
| `scripts/store_setup.py` | Idempotent Shopify shipping zones / policies setup |
| `scripts/outreach_pack.py` | Generates 5-10 influencer outreach drafts |
| `scripts/first_metrics.py` | Pulls Shopify Analytics for week-3 review |
| `scripts/retro.py` | 30-day retrospective markdown generator |

## Anti-Patterns

- ❌ Don't publish a listing without ≥ 3 images and ≥ 200-word description.
- ❌ Don't spend ad budget before organic content has 7+ days of data.
- ❌ Don't pick a niche based only on TikTok hashtag count — cross-check with Amazon revenue.
- ❌ Don't order > 100 supplier units before validating one sale.

## References

- `references/budget-and-time.md` — feasibility tables
- `references/niche-validation.md` — 3-data-point validation checklist
- `references/compliance-101.md` — US sales tax / EU IOSS / UK VAT basics
- `references/content-playbook.md` — TikTok / Instagram pattern library

## Privacy & Compliance

- All API tokens loaded from `~/.commerce-os/.env`, never committed.
- Supplier inquiries via Alibaba Trade Assurance — never scrape emails from URLs.
- Influencer outreach drafts saved locally; user reviews before send.

## Status

This is the v0.1.0 skeleton (Fun Skills 大赛 提交版). v0.2.0 will ship full scripts + 50 prompt regression tests.
