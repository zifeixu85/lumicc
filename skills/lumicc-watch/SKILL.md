---
name: lumicc-watch
description: Daily/weekly competitor monitoring for cross-border e-commerce stores. Snapshots 3-5 public competitor storefronts (Shopify / Amazon listings / TikTok Shop fronts), diffs against the last snapshot, and emits a structured change report covering new products, price moves, promotional banners, social activity, and review velocity. Triggers on phrases like "competitor", "spy", "monitor competition", "what are others doing", "竞品", "盯店", "对手", "对标". MUST be used whenever the user wants ongoing competitive intelligence rather than a one-shot search.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []     # all platform credentials optional; we degrade to manual paste
metadata:
  lumicc:
    pillar: attract
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, competitor-intel, scheduled]
    category: ops
    suggested_cronjobs:
      - schedule: "0 9,21 * * *"
        command: "lumicc-watch --all-stores --notify-channel feishu"
        purpose: "Daily competitor snapshot (morning + evening)"
  openclaw:
    heartbeat: "30m"
    heartbeat_purpose: "Pick up critical alerts (price war, new product launch) without waiting for next cron"
    suggested_cron:
      - cron: "0 9,21 * * *"
        command: "python3 ~/.openclaw/skills/lumicc-watch/scripts/run.py --all-stores --notify-channel feishu"
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: [playwright]
---

# lumicc-watch

A repeatable spy-glass on 3-5 of your closest competitors. Run it daily via cron or on demand; it stores snapshots in `~/.commerce-os/watchtower/` and diffs each run against the previous one.

## Persona

**Team**: 🔭 市场情报员 · see [`personas.md` § 4](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的市场情报员。今天巡了 [N] 个竞品，[M] 个目标有动作——先看高优先级的。

**Tone**: 冷静、像侦察兵，先报观察+严重度，再给建议。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 价格战 → CMO 决断
- 新品上架 → 数据分析师评估对自家影响

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

- Daily passive intel during stage `1-to-10` and `10-to-100`.
- On-demand "what changed last week" review.
- Pre-launch competitor recon (parent skill routes here from cold-start day 25).

## Workflow

1. Read competitor list from `preferences['watchtower_targets']` (JSON array). If empty, ask the user for 3-5 store URLs.
2. For each target:
   - Use Playwright to fetch the homepage + sitemap (or sitemap.xml fallback).
   - Capture: title, hero banner copy, announcement bar, top 8 products (title + price + main image + URL), social handles.
   - Hash content blocks; compare to previous snapshot in `watchtower/<host>/<date>.json`.
3. Generate diff report with categories:
   - `new_products`, `removed_products`, `price_changes`, `promo_banner_changes`,
   - `homepage_copy_changes`, `review_velocity_delta`.
4. Optional: cross-check pricing against your store via `lumicc-listing` price gap analysis.
5. Output `runs/<run_id>/report.md` and append events to memory.
6. **Agent mode only**: write a notification request to `~/.commerce-os/outbox/` so the agent's gateway delivers a summary to the user's chat channel.

## Runtime Modes

### Coder mode (manual)
```bash
python3 scripts/run.py --store-id my-store
```
Output: markdown report to stdout.

### Agent mode (cron / heartbeat triggered)
```bash
python3 scripts/run.py --store-id my-store \
  --notify-channel feishu \
  --notify-target group:跨境运营组 \
  --quiet-stdout
```
Output: JSON to `~/.commerce-os/runs/<id>.json` + notification request to `~/.commerce-os/outbox/<id>.json`.

### OpenClaw setup
Add to your workspace's `HEARTBEAT.md`:
```
## Cron
- `0 9,21 * * *` → python3 ~/.openclaw/skills/lumicc-watch/scripts/run.py --all-stores --notify-channel feishu
```

### Hermes setup
Natural language:
> "Every day at 9am and 9pm, run lumicc-watch and post the diff to my Feishu group 跨境运营组"

See `docs/08-agent-runtimes.md` for full setup per runtime.

## Inputs

```json
{
  "store_id": "string",
  "targets": ["https://competitor1.com", "https://competitor2.com"],
  "include_amazon_asins": ["B0XYZ"],
  "max_targets": 5,
  "delta_threshold_pct": 5
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-watch",
  "status": "success | partial | failed",
  "summary": {
    "targets_scanned": 3,
    "total_changes": 12,
    "high_priority_changes": 2
  },
  "high_priority_changes": [
    {"target": "competitor1.com", "type": "price_change", "sku": "...", "from": 29.99, "to": 24.99}
  ],
  "report_path": "runs/<id>/report.md"
}
```

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/snapshot.py` | One-target snapshot (Playwright) |
| `scripts/diff.py` | Compute diff between two JSON snapshots |
| `scripts/run.py` | Run on all configured targets, write report |
| `scripts/configure.py` | Wizard to set competitor list in preferences |

## Anti-Patterns

- ❌ Don't scrape pages that require login. Public storefronts only.
- ❌ Don't ignore robots.txt; obey crawl-delay if present.
- ❌ Don't share collected data outside the user's machine.
- ❌ Don't claim a "trend" from 1 snapshot — need ≥ 2 data points to compute delta.

## References

- `references/diff-categories.md` — what counts as a change and weighting
- `references/playwright-stealth.md` — minimal stealth config + rate limits
- `references/legal-and-tos.md` — what's safe to scrape (public catalog) and what isn't

## Privacy & Compliance

- Snapshots include only publicly-rendered content.
- No headless login attempts.
- Output reports are local; no upload.
- `referer` and rate limiting enforced — `delay_ms` defaults to 3000 between requests.

## Status

Skeleton v0.1.0. Snapshot/diff implementation in v0.2.0.
