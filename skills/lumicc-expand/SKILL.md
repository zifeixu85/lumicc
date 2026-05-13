---
name: lumicc-expand
description: Find the next winning SKU after your first hit. Combines your store's own conversion data with Jungle Scout / 1688 / TikTok signal data to surface 5-10 adjacent product candidates, score them on a 5-factor matrix (margin, demand momentum, content angle, supplier fit, fulfillment risk), and rank for batch evaluation. Triggers on phrases like "next product", "expand catalog", "more SKUs", "find another winner", "diversify", "扩品", "下一个", "新品", "找下一个爆款". MUST be used when an existing store with stage 1-to-10 wants horizontal product growth.
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
    tags: [ecommerce, product-expansion, sku-scoring, sourcing-signal]
    category: ops
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-expand

The "what's next" engine for stores that already have a winner. Uses your real first-90-day data (from `~/.commerce-os/store.db`) plus external signals to rank adjacent products on a 5-factor matrix.

## Persona

**Team**: 📊 数据分析师 · see [`personas.md` § 3](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的数据分析师。SKU 决策板已经准备好——KEEP / WATCH / DROP 三档，按 ROI + 复购 + 退货综合排。

**Tone**: 数据驱动、谨慎下结论，样本少就说样本少。

**Handoff triggers** — 何时主动 announce 团队交棒：

- DROP 列大 → CMO 讨论供应链
- KEEP 列爆品 → 建站团队上首屏

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Stage `1-to-10` and the user asks "what should I add next".
- Triggered automatically after 30 days of cold-start when stage upgrade detected.
- Quarterly review to refresh catalog.

## Workflow

1. **Pull internal signal**: top 3 products by gross margin contribution + last 30-day session data.
2. **Find adjacencies**: 4 paths in parallel:
   - **Co-purchase**: products often bought with your winners (via order history if available).
   - **Same niche, different use-case**: e.g., "magnetic knife rack" → "magnetic spice rack".
   - **Cross-niche, same audience**: e.g., pet → home (if buyer demo matches).
   - **Same supplier upsell**: ask supplier for catalog.
3. **Enrich each candidate** with: Jungle Scout revenue, TikTok hashtag volume, supplier MOQ.
4. **Score on 5 factors** (see `references/scoring-matrix.md`).
5. **Filter** by SOUL rules (min margin, supplier rating).
6. **Output** ranked top 5-10 with action recommendation per candidate.

## Inputs

```json
{
  "store_id": "string",
  "existing_winners": ["sku-1", "sku-2"],
  "target_count": 5,
  "min_score": 7.0,
  "exclude_categories": []
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-expand",
  "status": "success",
  "candidates": [
    {
      "rank": 1,
      "title": "Magnetic Spice Rack",
      "score": 8.4,
      "factors": {
        "margin": 8.0, "demand": 7.5, "content_angle": 9.0,
        "supplier_fit": 8.5, "fulfillment_risk": 8.0
      },
      "supplier_url": "https://...",
      "estimated_landed_cost": 4.20,
      "suggested_retail": 24.99,
      "next_step": "Order sample"
    }
  ],
  "rejected": [{"title": "...", "reason": "margin < 40%"}]
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/internal_signal.py` | Pull top winners from store.db |
| `scripts/score.py` | 5-factor scoring of a candidate JSON |
| `scripts/run.py` | Orchestrate all paths and rank |

## Anti-Patterns

- ❌ Don't suggest products from categories the user has rejected before (check events log).
- ❌ Don't recommend below SOUL margin floor.
- ❌ Don't include candidates without verified supplier link.

## References

- `references/scoring-matrix.md` — full 5-factor rubric
- `references/adjacency-paths.md` — 4 expansion paths and signals
- `references/seasonality-calendar.md` — when to time which categories

## Status

Skeleton v0.1.0. Scoring implementation in v0.2.0.
