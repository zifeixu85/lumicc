# Changelog — lumicc-launch

## [0.1.0] — 2026-05-08

### Added — initial implementation
- `scripts/plan.py` — 30-day cold-start plan generator
  - Reads store info from `~/.commerce-os/store.db` or CLI flags
  - Runs `resource_estimator` → feasibility tier (Lean / Standard / Comfortable)
  - Generates 30-day schedule (4 phases: validation, setup, content, monitor)
  - Writes `campaigns` row with full plan in `results_json`, status=running
  - Writes markdown plan file + events row + runs row
  - Notification support (feishu / discord / etc.) via outbox protocol
- `scripts/day_advance.py` — daily task pusher (cron-friendly)
  - Computes `day_offset` from `campaigns.started_at`
  - Outputs today's task list as markdown
  - Marks campaign complete when day > 30
  - Agent mode: writes to outbox for messaging gateway pickup
- `scripts/listing_csv.py` — Shopify bulk-import CSV generator
  - Built-in fallback when Platform Write slot is empty
  - Standard Shopify schema: Handle, Title, Body, variants, images, SEO fields
  - User uploads directly via Shopify Admin → Products → Import
- `scripts/niche_worksheet.py` — niche validation worksheet
  - Built-in fallback when Amazon revenue data slot is empty
  - Same 3-signal structure as the API path (Google Trends + TikTok + Amazon BSR)
  - User fills in ~45 min by hand
- `scripts/outreach_pack.py` — micro-influencer outreach drafts
  - 3 rotating templates with placeholders user must personalize
  - Recommendation: max 10 sends/day to avoid spam flags
- `scripts/resource_estimator.py` — feasibility classifier (carried from skeleton)
- `scripts/install-openclaw.sh` — auto-detects workspace, adds cron block
- `scripts/install-hermes.py` — auto-detects Hermes home, adds cron entry
- `scripts/test_launch.py` — end-to-end test
  - **26/26 assertions pass**: estimator, plan generation, day_advance day-1, day_advance past day-30, agent mode outbox, listing CSV correctness, niche worksheet content, outreach pack drafts

### Frontmatter (agentskills.io + dual runtime metadata)
```yaml
metadata:
  hermes:
    suggested_cronjobs:
      - schedule: "0 9 * * *"
        command: "lumicc-launch day_advance --all-stores --notify-channel feishu"
  openclaw:
    suggested_cron:
      - cron: "0 9 * * *"
        command: "python3 .../scripts/day_advance.py --all-stores --notify-channel feishu"
```

### Capability slots actually exercised
- amazon_revenue_data (week 1) — falls back to niche-worksheet
- b2b_supplier_matching (week 1) — falls back to manual search-query template
- landed_cost_duty (week 1) — falls back to user 8% default
- platform_write (week 2) — falls back to listing_csv.py output
- image_video_gen (week 2-3) — falls back to supplier images + flag
- social_publishing (week 3) — falls back to draft files
- review_ticket_signal (week 4) — falls back to user pasted text

Every fallback is implemented and tested. Lumicc-launch is fully runnable without any external skill.

## [Unreleased] — Roadmap to 0.2.0
- Day-level checkpointing (mark individual tasks done via memory.py log)
- Adaptive schedule (skip / reorder based on previous day's outcomes)
- Multi-store concurrent campaigns
- Localization (zh-CN UI for worksheets and outreach)
- Real API path implementations for top adapter providers
