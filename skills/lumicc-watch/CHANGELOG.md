# Changelog — lumicc-watch

## [0.1.0] — 2026-05-08

### Added — initial implementation
- `scripts/snapshot.py` — public-page-only competitor snapshot
  - Uses stdlib only (urllib, no Playwright dep)
  - Obeys robots.txt (urllib.robotparser)
  - Configurable crawl-delay (default 3000 ms)
  - Extracts: title, meta description, og:image, h1/h2, products via sitemap.xml + homepage anchors, social handles, announcement banners
- `scripts/diff.py` — two-snapshot diff with weighted categories
  - new_product (3.0), removed_product (2.5), promo_banner (1.8), hero (1.5), sitemap swing (1.4), meta SEO (0.8), social handles (0.7)
  - Sorts by severity; outputs `summary` + `high_priority_changes`
- `scripts/notify.py` — dual-mode dispatcher
  - Coder mode: print to stdout
  - Agent mode: write to `~/.commerce-os/outbox/<uuid>.json` (agent runtime gateway delivers)
  - Channels supported: feishu, discord, telegram, slack, email, stdout
- `scripts/run.py` — orchestrator
  - Reads watchtower targets from `preferences['watchtower_targets']` or CLI flags
  - Loops snapshot → diff → write report.md + result.json → append events/runs rows
  - Coder mode: prints markdown report; Agent mode: --quiet-stdout + optional notify
- `scripts/install-openclaw.sh` — one-shot install + HEARTBEAT.md cron block
  - Auto-detects OpenClaw workspace
  - Adds `0 9,21 * * *` cron between BEGIN/END markers (replayable)
- `scripts/install-hermes.py` — one-shot install + ~/.hermes/cron.yaml entry
  - Detects Hermes home
  - Block markers for idempotent replace
- `scripts/test_watch.py` — end-to-end smoke test
  - Spins up local HTTP server with synthetic Shopify-like HTML + sitemap.xml
  - **24/24 assertions pass**: snapshot extraction, diff categories, run.py coder mode, run.py agent mode (outbox notify), notify CLI

### Tested
- Snapshot parser correctly extracts: title, h1, sitemap (3 products), Instagram handle, banner
- Diff correctly classifies: new_product, removed_product, promo_banner_change
- run.py coder mode prints markdown to stdout
- run.py agent mode keeps stdout quiet AND drops notification request to outbox
- notify CLI dispatches both stdout and outbox paths

### Frontmatter (agentskills.io + dual runtime metadata)
```yaml
metadata:
  hermes:
    suggested_cronjobs:
      - schedule: "0 9,21 * * *"
        command: "lumicc-watch --all-stores --notify-channel feishu"
  openclaw:
    heartbeat: "30m"
    suggested_cron:
      - cron: "0 9,21 * * *"
        command: "python3 .../scripts/run.py --all-stores --notify-channel feishu"
```

## [Unreleased] — Roadmap to 0.2.0
- Optional Playwright path (`--use-playwright`) for JS-heavy storefronts (Hydrogen / SPA)
- Amazon ASIN snapshots (BSR + price diff)
- TikTok Shop fronts (public catalog page)
- Severity-based notification filtering (e.g., only notify on `high`)
- Inventory signal extraction ("only 3 left" badges)
- Review velocity tracking (count delta vs trailing avg)
