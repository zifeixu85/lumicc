---
name: lumicc-dashboard
description: Render the user's local Lumicc data (`~/.commerce-os/store.db` + memory + run results) into an interactive multi-page HTML dashboard so the user can browse stores, campaign progress, skill-run results, and three-layer memory visually instead of reading raw markdown. Triggers on phrases like "show me my dashboard", "open store dashboard", "render my progress", "visualize my data", "查看我的店", "看进度", "打开仪表盘", "可视化". MUST be used whenever the user wants a human-readable view of their accumulated Lumicc state instead of running queries by hand. Also auto-triggered after major skill runs (cold-start day-advance, watchtower diff) when configured.
license: MIT
version: 1.0.0
platforms: [macos, linux, windows]
required_environment_variables: []
metadata:
  lumicc:
    pillar: ops
    runtime_modes: [coder, agent]
    data_root: "~/.commerce-os"
    output_root: "~/.commerce-os/dashboard"
    parent_skill: lumicc
    no_persona: true   # intentionally no Persona section — this is a passive viewer page
  hermes:
    tags: [ecommerce, dashboard, visualization]
    category: ops
    suggested_cronjobs:
      - schedule: "*/30 9-22 * * *"
        command: "python3 ~/.claude/skills/lumicc-dashboard/scripts/render.py --quiet-stdout --no-open"
        purpose: "Refresh dashboard every 30 min during business hours"
  openclaw:
    suggested_cron:
      - cron: "*/30 9-22 * * *"
        command: "python3 ~/.openclaw/skills/lumicc-dashboard/scripts/render.py --quiet-stdout --no-open"
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: []
---

# lumicc-dashboard

Generate a self-contained, interactive HTML dashboard from `~/.commerce-os/`. **No build step, no node_modules.** Pure stdlib Python writes static HTML files the user opens directly in a browser. Later optional: deploy to Vercel/Cloudflare for remote access (see `lumicc-publish` future skill).

## When to Use

- User wants to **see** what their store is doing (instead of running CLI queries).
- After a major run (cold-start day finished, watchtower diff completed, crisis triaged) — auto-refresh.
- Once a day in agent mode (cron `*/30 9-22 * * *`) so the dashboard is always current.
- Before a stakeholder meeting / supplier call / VA handoff.

## Workflow

1. **Read** `~/.commerce-os/store.db` (stores, products, campaigns, events, insights, runs) + `~/.commerce-os/memory/*.md` + `SOUL.md` + `runs/*/result.json`.
2. **Render** each page from `templates/` using a stdlib template engine.
3. **Write** to `~/.commerce-os/dashboard/`:
   - `index.html` — store overview + KPIs + recent activity
   - `stores.html` — store list + product catalog
   - `campaigns.html` — active + historical campaigns with day-progress bars
   - `runs.html` — all skill-run history (filterable, drill-down to per-run page)
   - `memory.html` — three-layer memory browser (events / insights / SOUL)
   - `assets/style.css` — shared styling
4. **Open** the resulting `index.html` in the user's default browser (coder mode) or notify user via outbox (agent mode).

## Inputs

```json
{
  "data_root": "string  // default ~/.commerce-os",
  "output_root": "string  // default ~/.commerce-os/dashboard",
  "open_browser": "boolean  // default true in coder mode, false in agent mode",
  "notify_channel": "string?  // agent mode: post dashboard link to IM",
  "notify_target": "string?"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-dashboard",
  "status": "success | partial | failed",
  "pages_rendered": 5,
  "total_size_kb": 0,
  "dashboard_index_path": "string  // absolute path to index.html",
  "warnings": ["string"]
}
```

## Tools & Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `scripts/render.py` | Main generator: reads DB + memory, writes all HTML pages | ✅ |
| `scripts/templates.py` | Python-side template functions (one per page) | — |
| `scripts/test_render.py` | End-to-end test with synthetic data | ✅ |

All scripts use Python 3 stdlib only. No external template engine, no jinja, no node.

## Runtime modes

| Mode | Behavior |
|------|----------|
| **Coder** | Render → open default browser via `webbrowser.open` |
| **Agent** | Render quietly; write outbox notification with dashboard path (or deployed URL when `lumicc-publish` is configured) |

## Remote access (preview)

When `lumicc-publish` (future skill) is configured with a Vercel / Cloudflare Pages / Surge adapter, dashboard files are auto-deployed and the public URL is included in outbox notifications. Users on Feishu / Discord click a link → see live data without local access.

Until then, share the dashboard via:
- Local browser (default)
- `python3 -m http.server` in `~/.commerce-os/dashboard/` for LAN access
- Cloudflare Tunnel / ngrok for temporary public access

## Memory boundary

This skill only **reads** Lumicc's own `~/.commerce-os/` data. It never reads, writes, or touches agent-native memory (OpenClaw's MEMORY.md, Hermes user-profile). See `docs/09-memory-boundary.md`.

## Anti-patterns

- ❌ Bundle JS frameworks that require build steps (React / Vue / Next).
- ❌ Use CDN-only assets that break offline (we bundle critical CSS).
- ❌ Auto-deploy without explicit user opt-in.
- ❌ Embed credentials or full API tokens in any rendered page.
- ❌ Server-side rendering or any always-on backend — dashboards are static files.

## Privacy

- All HTML output is local under `~/.commerce-os/dashboard/`.
- Store URLs, supplier links, and SKUs render verbatim (assumes user trusts their own machine).
- For external sharing, run `scripts/render.py --redact` (planned v0.2.0): hashes URLs and masks supplier names.

## References

- `references/page-map.md` — what data each page shows + which DB tables it reads
- `references/template-system.md` — how the stdlib template engine works
- `references/styling.md` — design tokens + how to theme

## Versioning & License

Semver. Current 0.1.0. MIT. Designed for 繁星计划·Fun Skills 全国大赛 2026.
