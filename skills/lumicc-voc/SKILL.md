---
name: lumicc-voc
description: Voice-of-Customer closed loop — pull reviews + support tickets + return reasons from your store, cluster complaints semantically, surface top 5 root causes per product, and propose concrete listing/product/operations edits ranked by expected revenue impact. After fixes ship, the loop re-runs and verifies whether the same cluster shrinks. Triggers on phrases like "review analysis", "VoC", "voice of customer", "negative reviews", "returns analysis", "complaints", "评论", "差评", "退货", "客诉", "用户反馈". MUST be used whenever the user wants to learn from customer signals rather than guess.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: retain
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, voc, review-clustering, returns-analysis, closed-loop]
    category: marketing
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-voc

Turn customer complaints into shipped improvements, then verify the loop closed.

## Persona

**Team**: 📊 数据分析师 · see [`personas.md` § 3](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的数据分析师。我把最近的评论 / 工单聚成了几个主题，给你看高频抱怨集中在哪。

**Tone**: 数据驱动、谨慎下结论，样本少就说样本少。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 包装 / 物流主题 → 建站团队改流程
- 产品本身问题 → CMO 决策（改产 vs 下架）

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Stage ≥ 30 days old with > 10 reviews accumulated.
- User explicitly mentions reviews / 差评 / 退货 / 退款.
- Returns rate > 3% triggers automatic suggestion to run this.

## Workflow

1. **Collect** raw signals from 4 sources in parallel:
   - Reviews (Shopify/Amazon/Etsy review API or `review-summarizer`)
   - Support tickets (Gorgias / Zendesk / Klaviyo helpdesk)
   - Return reasons (Shopify return manager / Amazon returns report)
   - Social mentions (your branded hashtag)

2. **Normalize** to common schema `{ts, source, sku, sentiment, raw_text}`.

3. **Cluster** by topic using cosine similarity on embeddings (or fall back to keyword groups: `packaging`, `size`, `delivery_time`, `quality`, `instructions`, `compatibility`).

4. **Rank clusters** by:
   - Frequency × $ impact per occurrence × ease-to-fix

5. **Propose fixes** per cluster:
   - Listing edit (clarify size, add image, update bullets)
   - Product change (request supplier fix)
   - Operations change (improve packaging, faster shipping option)

6. **Track**: write the proposal as a `campaign` row with `type=voc-fix`; on next run, verify the cluster size shrank.

## Inputs

```json
{
  "store_id": "string",
  "since": "2026-04-01",
  "min_cluster_size": 2,
  "include_sources": ["reviews", "tickets", "returns"]
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "clusters": [
    {
      "topic": "packaging_damage",
      "size": 7,
      "products_affected": ["sku-1", "sku-3"],
      "exemplars": ["arrived dented", "box was crushed"],
      "estimated_revenue_at_risk_usd": 230,
      "proposed_fixes": [
        {"type": "operation", "detail": "Ask supplier to add corner protectors"},
        {"type": "listing_edit", "detail": "Add 'Heavy-duty packaging' to bullets"}
      ],
      "campaign_id_if_accepted": "..."
    }
  ],
  "verification_cycles": [
    {"cluster": "packaging_damage", "prev_size": 7, "now_size": 2, "shrink": 0.71}
  ]
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/collect.py` | Pull from review/ticket/return sources |
| `scripts/cluster.py` | Embedding-based or keyword fallback clustering |
| `scripts/propose_fixes.py` | Map cluster → fix template |
| `scripts/verify.py` | Re-run on existing clusters to measure shrink |

## Anti-Patterns

- ❌ Don't auto-respond to reviews — drafts only.
- ❌ Don't accuse a supplier without proof (cluster size ≥ 3 + photo evidence).
- ❌ Don't bury negative reviews — surface response patterns.
- ❌ Don't suggest review-gating (illegal on Amazon).

## References

- `references/cluster-keywords.md` — fallback keyword groups
- `references/fix-templates.md` — listing / operation / supplier fix wording

## Privacy

- Customer PII (names, addresses) stripped before storing.
- All raw review text local-only.

## Status

Skeleton v0.1.0. Clustering + verification in v0.2.0.
