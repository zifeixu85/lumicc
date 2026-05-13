# Changelog

All notable changes to **lumicc** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-05-08

### Added
- Main `SKILL.md` orchestrator with stage-based routing.
- `references/store-stages.md` decision tree.
- `references/routing-table.md` intent → sub-skill keyword map (EN + CN).
- `references/memory-schema.md` SQLite + Markdown layered memory design.
- `references/required-skills.md` companion skill catalog (recommended atomic tools).
- `references/api-credentials.md` Shopify / Amazon / TikTok Shop / Etsy / Jungle Scout / Klaviyo setup.
- `scripts/init_store.py` — idempotent migration runner for `~/.commerce-os/store.db`.
- `scripts/route.py` — keyword-weighted decision tree.
- `scripts/memory.py` — three-layer memory CRUD; never auto-writes Layer 3 SOUL.
- `scripts/health_check.py` — Python / SQLite / companion skill / credentials probe.
- `scripts/test_smoke.py` — 21 end-to-end assertions; passes against a temp HOME.
- `examples/walkthrough.md` — 30-day cold-start to first revenue narrative.
- Privacy section: all data local under `~/.commerce-os/`, no telemetry.

### Tested
- Idempotent re-init: ✅
- Routing on EN intent: ✅
- Routing on CN intent (中文意图): ✅
- Insight merge & verified_count bump: ✅
- Layer 3 SOUL protection (never auto-write): ✅
- Health check exits 0/1/2 per warning/error policy: ✅

### Known Limitations
- Sub-skills `cb-*` are skeletons in this initial release; full SOP and scripts
  are flagged for the 0.2.0 milestone.
- `commerce-os-console` Electron app is planned but not bundled.
- Migrations: only v1 schema; v2 planned for multi-shop link tables.

## [Unreleased] — Roadmap to 0.2.0
- Sub-skill complete SOPs (one per CR_sub-skill milestone).
- SkillLens deepReviewCertificate verified.
- `commerce-os-console` v0 (read-only dashboard reading `~/.commerce-os`).
- Cron / Apple ScheduledTask integration for daily watchtower runs.
- Test corpus expansion: 100 intent samples, 95%+ routing accuracy.
- Optional `--dry-run` flag on all writes.

## License
MIT.
