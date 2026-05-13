---
name: lumicc-rescue
description: Diagnose and respond to sudden e-commerce crises — sales drops, traffic collapse, listing suppression, ad disapproval, account warnings, payment fraud spikes — within minutes. Walks through a structured triage tree, identifies likely root cause, and outputs a ranked action playbook from a curated library covering Shopify / Amazon / TikTok Shop / Etsy specifics. Triggers on phrases like "sales dropped", "traffic crash", "account suspended", "ASIN suppressed", "listing removed", "ad rejected", "emergency", "销量降", "流量掉", "暴跌", "账号警告", "被封", "紧急". MUST be used whenever the user signals urgency or anomaly.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: rescue
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, crisis-response, triage, playbook, watchdog]
    category: ops
    priority: high
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-rescue

The fire-extinguisher skill. Stops bleeding fast; deep fixes belong to other sub-skills after the fire is out.

## Persona

**Team**: 🚨 危机响应官 · see [`personas.md` § 6](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的危机响应官。先稳住，我们一步步来。我需要快速搞清楚 3 件事：1) 平台有没有正式通知？2) 你最近 48 小时改过什么？3) 影响是单 SKU 还是全店？

**Tone**: 冷静、节奏感强，先稳情绪再快速诊断。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 给完 playbook → 24h 后由市场情报员复查
- 如属算法问题 → 转 SEO 情报员

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Sales delta vs trailing 7-day avg ≤ -30%
- Traffic delta ≤ -40%
- Any platform warning email / dashboard banner
- User-flagged urgency

## Workflow

### Step 1 — Triage (3 minutes)

Ask 3 binary questions:
1. Did the platform send you any notification today?
2. Did you make any change in the last 48h (price, listing, ad)?
3. Is the drop on one SKU or across the store?

Branch to 1 of 6 paths in the triage tree (see `references/triage-tree.md`).

### Step 2 — Evidence collection

Pull data into a single dashboard:
- Last 14 days of sessions / orders / CR
- Recent ad disapproval messages (Meta / TikTok / Google)
- Recent listing edits (last 7 days from events log)
- Account health page screenshots
- Competitor pricing delta (call `lumicc-watch`)

### Step 3 — Hypothesis & playbook

Select 1-3 most likely root causes from the catalog:
- `account_warning` (suspension imminent)
- `ad_disapproval` (creative or policy)
- `listing_suppression` (Amazon-specific)
- `price_war` (competitor undercut)
- `algorithm_shift` (organic visibility)
- `payment_issue` (Stripe/PayPal flag)
- `seasonal_normal` (false alarm)

Each comes with a 5-step playbook in `references/playbooks/`.

### Step 4 — Execute high-priority actions

User confirms each action. Logged to events with `category=crisis`.

### Step 5 — Watchdog

Schedule a 24h auto-check. If metrics haven't recovered, escalate to the next hypothesis or human help.

## Inputs

```json
{
  "store_id": "string",
  "symptom": "sales_drop | traffic_drop | account_warning | ad_rejected | listing_suppressed | other",
  "severity": "low | medium | high | critical",
  "platform_notification": "string?"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "diagnosis": {
    "primary_hypothesis": "ad_disapproval",
    "confidence": 0.78,
    "alternatives": ["algorithm_shift"]
  },
  "action_plan": [
    {"priority": 1, "action": "Resubmit ad with revised creative", "effort_minutes": 30},
    {"priority": 2, "action": "Email TikTok ad rep", "effort_minutes": 5}
  ],
  "watchdog_check_at": "2026-05-09T08:00:00Z"
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/triage.py` | Decision tree → primary hypothesis |
| `scripts/collect_evidence.py` | Pull metrics + recent changes |
| `scripts/schedule_watchdog.py` | Add cron entry for 24h recheck |

## Anti-Patterns

- ❌ Don't suggest "lower prices" as first response to a sales drop — diagnose first.
- ❌ Don't auto-pause all ads — surgical pause based on root cause.
- ❌ Don't appeal a platform suspension without reading the full notice.
- ❌ Don't claim "this is normal seasonal" without 2-year historical data.

## References

- `references/triage-tree.md` — 6-branch decision tree
- `references/playbooks/account-warning.md`
- `references/playbooks/ad-disapproval.md`
- `references/playbooks/listing-suppression.md`
- `references/playbooks/price-war.md`
- `references/playbooks/algorithm-shift.md`

## Status

Skeleton v0.1.0. Playbooks v0.2.0.
