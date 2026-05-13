# Store Stages — Decision Tree

This document is the **source of truth** for `route.py`. Update here, regenerate router.

## Stages

| Stage | Definition | KPI signal |
|-------|------------|------------|
| `0-to-1` | No store, or store < 30 days old, or 0 sales | No store record OR `created_at` < 30 days OR sales = 0 |
| `1-to-10` | Has sales but pre-scale ($0 – $10K/month) | sales_total > 0 AND < $10K monthly |
| `10-to-100` | Scaling phase ($10K – $100K/month) | $10K ≤ sales_monthly ≤ $100K |
| `100+` | Mature business | sales_monthly > $100K |

`100+` stage is out of MVP scope (different problems: team scaling, multi-channel, M&A).

## Decision Tree

```
ROOT: Check ~/.commerce-os/store.db

[NO store record]
  → matched: lumicc-launch
  → reason: "First-time user, no store memory yet"
  → ask: store_url, platform, target_market, niche_intent

[STORE EXISTS] → read store.stage

  Stage = "0-to-1":
    Check active campaigns:
      [Has active cold-start campaign, age < 30d]
        → continue cold-start workflow
      [Cold-start expired (≥ 30d) AND sales = 0]
        → matched: lumicc-listing
        → reason: "Cold-start window ended without sales — diagnose listings"
      [Cold-start expired AND sales > 0]
        → upgrade stage to "1-to-10"
        → re-enter tree

  Stage = "1-to-10":
    Parse user intent keywords:
      keywords = ["expansion", "next product", "扩品", "下一个"]
        → matched: lumicc-expand

      keywords = ["sales drop", "drop", "掉了", "暴跌", "异常"]
        → matched: lumicc-rescue

      keywords = ["review", "voc", "feedback", "评论", "差评", "退货"]
        → matched: lumicc-voc

      keywords = ["competitor", "竞品", "对手"]
        → matched: lumicc-watch

      keywords = ["listing", "page", "转化", "conversion"]
        → matched: lumicc-listing

      [No clear intent]
        → matched: lumicc-listing (highest leverage default)
        → reason: "1-to-10 default: optimize active listings first"

  Stage = "10-to-100":
    Default running mode (cron):
      - daily: lumicc-watch
      - weekly: lumicc-voc summary
      - monthly: lumicc-expand review

    On user pull:
      keywords ["expansion"] → lumicc-expand
      keywords ["crisis"] → lumicc-rescue
      others → suggest "console dashboard" (see commerce-os-console)
```

## Confidence Scoring

```
base = 0.6
+0.2 if matched stage AND matched intent keyword
+0.1 if store has > 5 events in last 7 days (active user)
+0.1 if user explicitly mentioned the sub-skill name
−0.2 if multiple intents matched equally
```

## Alternative Suggestions

When confidence < 0.7, output `alternative_subskills` (top 2) instead of forcing one match. Ask user to confirm.

## Edge Cases

| Case | Handling |
|------|----------|
| User has multiple stores | Ask which one (or use `--store-id`) |
| Stage unknown (legacy memory) | Run `lumicc-listing` as safe default |
| Memory corrupted | Re-init with `init_store.py --reset` (with user confirm) |
| User on platform other than Shopify | Sub-skills check `platform` and adapt or fall back to generic SOP |
| Multi-language user input | Detect language, route on translated intent |
