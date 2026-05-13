---
name: lumicc-listing
description: Audit product detail pages (PDP) on Shopify, Amazon, TikTok Shop, Etsy for conversion blockers and SEO weaknesses, then produce an ordered remediation plan with concrete edits. Checks: title structure, image count + quality + dimensions, bullet copy strength, description SEO density, schema/markup, price ladder, scarcity signals, reviews freshness, mobile responsiveness. Triggers on phrases like "listing optimization", "product page", "low conversion", "PDP audit", "ASIN audit", "listing 优化", "产品页", "详情页", "转化率低". MUST be used whenever sales > 0 but conversion < 2% or as the default fallback for stage 1-to-10 health checks.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: convert
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, pdp-audit, listing-quality, conversion-rate]
    category: ops
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-listing

Listing health check + ordered fix plan. The default first-line response when a store is alive but underperforming.

## Persona

**Team**: 🏪 建站团队 · Shopify / 独立站 · see [`personas.md` § 2](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的建站团队，专门看商详页能不能转化。我先扫一遍你的活跃 listing，5 秒后给你打分单。

**Tone**: 手把手、像同事而非顾问，遇到平台坑直接说。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 平均健康度低 → 品牌内容师重做图文
- 评分高但销量低 → 数据分析师看流量来源

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Sales > 0 but CR < industry benchmark (≈ 2% for Shopify, 8% for Amazon).
- Stage `0-to-1` cold-start without any sales by day 14.
- Default fallback when parent skill detects no clearer intent at stage `1-to-10`.

## Workflow

1. Pull listing data (title, images, bullets, description, price, reviews) via platform API.
2. Run 8 checks (see `references/checks-catalog.md`).
3. Score each check 0-10, total 0-100.
4. Sort issues by `impact × ease_of_fix`.
5. Generate fix plan: top 5 changes with concrete before/after copy.
6. Optional: apply approved changes via API + verify next-day metrics.

## Inputs

```json
{
  "store_id": "string",
  "product_ids": ["..."] | "all_active",
  "platform": "shopify | amazon | tiktok-shop | etsy",
  "apply_changes": false,
  "include_competitive_pricing": true
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "summary": {"score_avg": 64, "products_audited": 5, "high_impact_fixes": 8},
  "by_product": [
    {
      "product_id": "...",
      "score": 58,
      "issues": [
        {"check": "image_count", "current": 2, "target": 5, "impact": "high", "fix": "Generate 3 more lifestyle/feature shots"},
        {"check": "title_seo", "current": "Cleaning Sponge", "target": "Magic Cleaning Sponge — Kitchen Bathroom Multi-Surface", "impact": "medium"}
      ]
    }
  ],
  "fix_plan_path": "runs/<id>/fix-plan.md"
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/fetch_listing.py` | Pull current state of a listing |
| `scripts/run_checks.py` | All 8 checks; output JSON |
| `scripts/apply_fixes.py` | Apply approved fixes via API |
| `scripts/score.py` | Aggregate to 0-100 |

## Anti-Patterns

- ❌ Don't auto-apply changes without user approval — preview every edit.
- ❌ Don't suggest cargo-culted SEO keywords; pull from actual Helium 10 / Cerebro data.
- ❌ Don't generate fake reviews to boost social proof.
- ❌ Don't recommend price changes that violate SOUL minimum margin.

## References

- `references/checks-catalog.md` — 8 checks with rubric
- `references/copy-patterns.md` — title/bullet/description templates
- `references/image-spec.md` — image size/angle/lighting requirements per platform

## Status

Skeleton v0.1.0. Full checks/fix implementation in v0.2.0.
