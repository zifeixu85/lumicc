# Page Map

Each page in the rendered dashboard reads specific tables/files. This document is the single source of truth: keep `scripts/render.py` in sync with this table.

## `index.html` — Overview

| Section | Source |
|---------|--------|
| KPI strip (stores / campaigns / runs / events) | `COUNT(*)` on `stores`, `campaigns WHERE status='running'`, `runs WHERE finished_at > now-7d`, `events WHERE ts > now-7d` |
| Store cards | `SELECT * FROM stores ORDER BY updated_at DESC` |
| Active campaigns | `SELECT * FROM campaigns WHERE status IN ('planned','running')` |
| Today's tasks (if cold-start active) | parsed from `campaigns.results_json` + computed `day_offset` |
| Recent activity (last 8) | `SELECT * FROM events ORDER BY ts DESC LIMIT 8` |

## `stores.html` — Store detail

| Section | Source |
|---------|--------|
| Store info | one row from `stores` |
| Products | `SELECT * FROM products WHERE store_id=?` |
| Campaigns history | `SELECT * FROM campaigns WHERE store_id=?` |
| Events for this store (last 50) | `SELECT * FROM events WHERE store_id=? ORDER BY ts DESC LIMIT 50` |

## `campaigns.html` — Campaigns list

| Section | Source |
|---------|--------|
| Campaign cards | `SELECT * FROM campaigns ORDER BY started_at DESC` |
| Progress bar (cold-start) | parsed from `results_json.schedule`; today_day_offset = (now - started_at)/86400 + 1 |
| Latest day's tasks | `results_json.schedule[day_offset]` |

## `runs.html` — Skill run history

| Section | Source |
|---------|--------|
| Run table | `SELECT * FROM runs ORDER BY started_at DESC LIMIT 100` |
| Run detail expand | parse `result_path` JSON file |
| Filter by skill | client-side JS on rendered data |

## `memory.html` — Three-layer memory

| Tab | Source |
|-----|--------|
| Layer 1 — events (structured) | `SELECT * FROM events ORDER BY ts DESC LIMIT 200` |
| Layer 1 — daily logs (markdown) | files `~/.commerce-os/memory/YYYY-MM-DD.md` |
| Layer 2 — insights | `SELECT * FROM insights ORDER BY verified_count DESC, confidence DESC` |
| Layer 3 — SOUL | raw text from `~/.commerce-os/SOUL.md` |

## Future pages (v0.2.0)

- `insights.html` — full Layer 2 browser with filters by category/store
- `outbox.html` — view pending/delivered notifications
- `store-<id>.html` — per-store dedicated pages
- `run-<id>.html` — per-run dedicated pages with full deliverables list

## Update frequency

| Trigger | When |
|---------|------|
| Manual | user runs `render.py` |
| Auto after major skill run | `lumicc-watch` / `lumicc-launch` post-run hook (next iteration) |
| Cron | every 30 min during 9:00–22:00 (configurable) |
| Pre-share | before user generates a public URL via `lumicc-publish` |
