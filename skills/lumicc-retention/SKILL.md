---
name: lumicc-retention
description: LTV (Lifetime Value), RFM (Recency / Frequency / Monetary), and repeat-purchase engine for cross-border e-commerce stores. Imports customer + orders CSV (Shopify export format, or any compatible tool), classifies customers into 6 RFM segments (Champions / Loyal / At Risk / Lost / New / Promising), identifies subscription opportunities, flags 90-day inactive customers for win-back, generates email drafts per segment, and surfaces top-5% VIP customers. Persists segments + insights to ~/.commerce-os/store.db so trends compound across months. Triggers on phrases like "customer LTV", "RFM analysis", "repeat purchase", "winback", "VIP customers", "subscription opportunity", "客户分层", "复购分析", "RFM", "VIP 客户", "唤醒断签客户", "订阅化机会", "客户生命周期价值". MUST be used whenever the user wants to understand or improve customer retention / LTV / repeat purchase patterns.
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
    tags: [ecommerce, retention, rfm, ltv, customer-segmentation]
    category: marketing
    suggested_cronjobs:
      - schedule: "0 9 1 * *"
        command: "lumicc-retention --mode rfm --notify-channel feishu"
        purpose: "Monthly first-day RFM refresh"
      - schedule: "0 9 * * 1"
        command: "lumicc-retention --mode winback --notify-channel feishu"
        purpose: "Weekly winback trigger scan"
  openclaw:
    suggested_cron:
      - cron: "0 9 1 * *"
        command: "python3 .../scripts/run.py --mode rfm --quiet-stdout"
      - cron: "0 9 * * 1"
        command: "python3 .../scripts/run.py --mode winback --quiet-stdout"
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: []
---

# lumicc-retention

The retention pillar. Cross-border sellers obsess over CAC but neglect LTV — **a 20% LTV lift roughly equals a 20% CAC reduction = doubled net profit**. This skill is the analytics layer.

Built around 6 modes:
- **rfm**: classify customers via Recency × Frequency × Monetary into 6 segments
- **repeat**: find which products lead to repeat purchases (gateway SKUs)
- **winback**: surface 90-day inactive customers + draft outreach emails
- **subscription**: scan order history for SKUs that should be sold as subscriptions
- **vip**: top 5% customers by lifetime value, with one-on-one outreach drafts
- **all**: run rfm + repeat + winback + subscription + vip in one pass

## Persona

**Team**: 📊 数据分析师 · see [`personas.md` § 3](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的数据分析师。我刚扫了你过去 90 天的订单——先看哪一块？复购？流失？还是 VIP？

**Tone**: 数据驱动、谨慎下结论，样本少就说样本少。

**Handoff triggers** — 何时主动 announce 团队交棒：

- At Risk 客户多 → 品牌内容师做 winback
- Champion 多 → CMO 看是否升级 VIP 计划

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

Trigger whenever user asks about:
- Customer LTV / lifetime value / repeat rate
- RFM / customer segmentation / cohort analysis
- "How many of my customers come back?" / "Why is my retention so low?"
- Winback / 唤醒 / 断签客户 / 复购
- Subscription / 订阅化 / 自动续订
- VIP / top customer / 重要客户

**Do not** trigger for: sending actual marketing emails (→ Klaviyo / Omnisend / etc.) / customer service (→ Gorgias / Zendesk).

## Workflow

1. **Input**: Shopify customer-orders CSV (or compatible export). Native column detection so most BI tools work.
2. **Compute**: parse → group by customer_id → compute R, F, M → assign quintile (1-5) → map RFM code (e.g., "554") to segment.
3. **Persist**: write to `customer_segments` table for trend analysis.
4. **Render**: Markdown report + segment-specific email drafts.
5. **Notify**: agent mode → outbox alert with segment counts + winback opportunities.
6. **Suggest next**: e.g., "23 customers at risk of churning → trigger `lumicc-content email_sequence --campaign winback`".

## CSV input format

Flexible column detection. The minimum required columns:

```csv
customer_id,email,order_id,order_date,total,product_skus
cust-001,a@b.com,ord-1,2026-01-15,29.99,MKR-16
cust-001,a@b.com,ord-2,2026-02-20,44.99,FH-3PK;CS-MAGIC
cust-002,b@c.com,ord-3,2026-02-01,29.99,MKR-16
```

We auto-detect Shopify-export aliases: `Email` → `email`, `Created at` → `order_date`, `Total` → `total`, `Lineitem sku` → `product_skus`, etc.

## RFM segments (6)

| Segment | RFM code rules | Action |
|---------|----------------|--------|
| 🏆 Champions | R≥4, F≥4, M≥4 | Exclusive early access; ask for referrals/reviews |
| 💚 Loyal | R≥3, F≥3, M≥3 (not Champion) | Loyalty rewards; upsell |
| 🌱 New | R≥4, F=1-2 | Welcome flow; second-purchase nudge |
| 🔥 At Risk | R≤2, F≥3, M≥3 | Immediate winback + discount |
| 💔 Lost | R=1, F≤2, M≤2 | Final-chance reactivation campaign |
| 🟡 Promising | Everyone else | Light nurture |

## Modes

| Mode | Purpose | Frequency |
|------|---------|-----------|
| `rfm` | Full RFM segmentation + customer_segments table refresh | monthly |
| `repeat` | Gateway-SKU analysis: which first-purchase SKU has highest 2nd-purchase rate | quarterly |
| `winback` | Find 90-day inactive customers + email drafts | weekly |
| `subscription` | SKUs bought ≥ 2× by ≥ 20% of buyers → subscription candidates | quarterly |
| `vip` | Top 5% by lifetime spend; per-customer one-on-one outreach drafts | monthly |
| `all` | Run all 5 above in one pass | monthly (default) |

## Inputs

```json
{
  "store_id": "string?",
  "mode": "rfm | repeat | winback | subscription | vip | all",
  "csv_file": "string  // required for rfm/repeat/winback/subscription/vip/all",
  "winback_days_inactive": "int?  // default 90",
  "vip_top_percent": "float?  // default 5",
  "subscription_min_repeat_rate": "float?  // default 0.20 (20%)"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-retention",
  "mode": "string",
  "status": "success | partial | failed",
  "metrics": {
    "total_customers": 0,
    "champions_count": 0,
    "at_risk_count": 0,
    "vip_count": 0,
    "winback_eligible_count": 0,
    "subscription_candidate_count": 0,
    "median_ltv_usd": 0,
    "repeat_rate": 0.0
  },
  "deliverables": [
    {"type": "rfm_report_md", "path": "..."},
    {"type": "winback_segment_csv", "path": "..."},
    {"type": "subscription_candidates_md", "path": "..."},
    {"type": "vip_outreach_drafts_md", "path": "..."}
  ],
  "next_recommended_skill": "lumicc-content"
}
```

## Tools & Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `scripts/csv_parser.py` | Flexible Shopify-export CSV reader | ✅ |
| `scripts/rfm.py` | RFM scoring + 6-segment classification | ✅ |
| `scripts/repeat_paths.py` | Gateway SKU analysis | ✅ |
| `scripts/winback.py` | Inactive-customer segment + email drafts | ✅ |
| `scripts/subscription.py` | Repeat-rate scanner → subscription candidates | ✅ |
| `scripts/vip.py` | Top 5% customers + 1-on-1 outreach drafts | ✅ |
| `scripts/run.py` | Mode dispatcher + report rendering | ✅ |
| `scripts/test_retention.py` | End-to-end test with synthetic CSV | ✅ |
| `scripts/notify.py` | Shared notification | ✅ |

## Memory & state

New table (auto-migrated):

```sql
CREATE TABLE IF NOT EXISTS customer_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id TEXT,
  customer_id TEXT NOT NULL,
  email TEXT,
  segment TEXT,
  recency_days INTEGER,
  frequency INTEGER,
  monetary_usd REAL,
  rfm_code TEXT,
  ltv_usd REAL,
  ts INTEGER NOT NULL
);
```

## Capability slots

| Slot | Required? | Provider | When missing |
|------|-----------|----------|--------------|
| `customer_orders_source` | required (CSV input) | Shopify export / any BI CSV | Cannot run; user must export |
| `email_send` | optional | Klaviyo / Omnisend / Postscript | Drafts saved locally for user to paste |
| `klaviyo_flow_audit` | optional | Klaviyo API | Manual checklist |

## Anti-patterns

- ❌ Do not auto-send emails — drafts only; user controls send through their ESP.
- ❌ Do not store full customer PII unmasked (email is hashed to last-4 in reports).
- ❌ Do not delete `customer_segments` rows — historical segment changes are gold for trend analysis.
- ❌ Do not call paid CRM APIs without user opt-in.

## Privacy

- Email addresses stored as `userXXXX@domain.tld` mask in reports (last 4 chars of local part + full domain).
- Full email kept in DB for matching but never printed to logs or HTML.
- All data local under `~/.commerce-os/`; no remote telemetry.

## References

- `references/rfm-segments.md` — full 6-segment rubric + actions per segment
- `references/csv-formats.md` — Shopify / WooCommerce / TikTok Shop export aliases
- `references/email-drafts.md` — segment-specific email template guide

## Versioning & License

Semver. Current 0.1.0. MIT. Designed for 繁星计划·Fun Skills 全国大赛 2026.
