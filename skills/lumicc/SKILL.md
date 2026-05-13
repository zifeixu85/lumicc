---
name: lumicc
description: Run a complete English-market cross-border e-commerce store end-to-end — sourcing, listing, marketing, monitoring, optimization — with persistent store memory across sessions. Triggers a routing decision tree based on the user's store stage (0→1, 1→10, 10→100) and dispatches to specialized sub-skills (cold-start, competitor watchtower, expansion engine, listing doctor, VoC loop, crisis response). Always use this skill when the user mentions cross-border e-commerce, Shopify / Amazon / TikTok Shop / Etsy store operations, dropshipping, independent site (独立站), product sourcing, store launch, listing optimization, competitor monitoring, or any English-market store management task — even when the user does not explicitly say "operate my store". Also triggers on Chinese phrases like "跨境电商", "独立站运营", "选品", "上架", "出海", "竞品", "运营 SOP".
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: orchestrator
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
  hermes:
    tags: [ecommerce, orchestrator, cross-border]
    category: ops
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: [sqlite3, playwright]
---

# Lumicc — Cross-Border Commerce OS

**Replaces 10–15 hours/week of cross-tool context switching** for solo cross-border sellers by orchestrating sourcing, listing, marketing, monitoring and optimization into a single skill that remembers your store across sessions.

## Persona

**Team**: 🎯 CMO 总指挥 · see [`personas.md` § 1](references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你这家店的 CMO，负责帮你判断现在最该做什么、由哪个团队接手。先看一下你的店铺现状……

**Tone**: 稳、克制、不说废话，先听问题看数据再说建议。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 任意 sub-skill 跑完 → 回到 CMO 复盘

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## Target users

- **Indie cross-border seller** (1 store, US/UK/EU market, $0–$10K MRR) — needs a 30-day cold-start runway.
- **One-person company / OPC** (1–3 active stores, $5K–$50K MRR) — needs daily competitor watch + listing health.
- **Small brand team (5–30 people)** ($50K–$500K MRR) — needs SOP standardization + VoC closed loop across SKUs.

Use frequency: 30+ invocations/week on an active store (daily push at 09:00, on-demand audits, crisis triage).

## When to Use

Trigger when any of these is true:
1. User talks about cross-border store ops (Shopify / Amazon / TikTok Shop / Etsy / 独立站 / dropshipping).
2. User describes a stage problem ("starting / store is cold / want to expand / sales dropped / handle reviews").
3. User asks "what should I do next" in an e-commerce context.
4. Any `lumicc-*` sub-skill is referenced but unclear which fits.

**Do not trigger** for: pure Shopify dev questions (→ `shopify-developer`), pure ad copy (→ `copywriting`), one-shot product description (→ `product-description-generator`).

## Compared to alternatives

| Alternative | What they miss vs Lumicc |
|-------------|--------------------------|
| Generic LLM (Claude / GPT alone) | No persistent SQLite memory, no cron, no browser snapshot, no Layer-2 insight accumulation |
| Atomic skill catalogs (single-platform tools) | No orchestration across stage transitions; user has to remember which tool fits which moment |
| Closed SaaS dashboards (Shopify Insights, Helium 10) | Single-platform, no agent integration, no cross-session memory, vendor lock-in |

## Workflow

1. **Init** — `python3 scripts/init_store.py` creates/migrates `~/.commerce-os/store.db` (idempotent).
2. **Route** — `python3 scripts/route.py --intent "<msg>"` returns `{matched_subskill, confidence, missing_inputs}` based on the decision tree in `references/store-stages.md`.
3. **Dispatch** — `Read` the matched sub-skill's `SKILL.md` and follow its workflow. If not installed, degrade per the slot's built-in fallback (every slot has one).
4. **Persist** — Each sub-skill writes `~/.commerce-os/runs/<run_id>.json` (schema in `references/memory-schema.md`); the OS appends to `events`, proposes Layer-2 insights when patterns repeat ≥ 2 times.
5. **Suggest next** — Output a `next_action_suggestion` block (example: "Day 7 cold-start done — run `lumicc-listing` to validate active listings").

### Inputs

```json
{ "user_intent": "string", "store_url": "string?", "platform": "shopify|amazon|tiktok-shop|etsy|independent",
  "target_market": "us|eu|uk|sea|global", "stage_hint": "0-to-1|1-to-10|10-to-100|auto", "language": "en|zh" }
```

### Outputs

```json
{ "decision": { "matched_subskill": "string", "confidence": 0.0, "reason": "string" },
  "store_memory_snapshot": { "stage": "string", "active_campaigns": [] },
  "next_action": { "type": "execute_subskill|ask_user|install_dependency", "payload": {} } }
```

Full schemas in `references/io-schemas.md`. Validated by `scripts/test_smoke.py`.

## Sub-Skill Catalog

| Sub-skill | Fires when | Output |
|-----------|------------|--------|
| `lumicc-launch` | New store, 0→1 stage | 30-day SOP with daily tasks |
| `lumicc-watch` | Daily monitoring | Diff report of 3-5 competitors |
| `lumicc-expand` | "Find next winner" intent | Ranked SKU candidates |
| `lumicc-listing` | Sales low / health check | Listing issues + fixes |
| `lumicc-voc` | Review/ticket analysis | VoC clusters + edits |
| `lumicc-rescue` | Sales drop / account warning | Root-cause + playbook |

## Tools & Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `scripts/init_store.py` | Create / migrate `store.db` | ✅ |
| `scripts/route.py` | Decision tree → sub-skill | ✅ |
| `scripts/memory.py` | 3-layer memory CRUD; never auto-writes Layer 3 SOUL | ✅ |
| `scripts/health_check.py` | Verify deps + adapters | ✅ |
| `scripts/test_smoke.py` | End-to-end smoke test (21/21 pass) | ✅ |

All scripts are pure Python 3 stdlib. No `pip install` required.

## Dependencies

| Name | Type | Required | Paid? | Cost |
|------|------|----------|-------|------|
| Python 3.8+ | runtime | ✅ | free | — |
| sqlite3 | stdlib | ✅ | free | — |
| Playwright | optional CLI | only for `lumicc-watch` JS-rendered sites | free | ~150 MB disk |
| Capability-slot adapters | optional skills/APIs | per sub-skill | user choice | varies |

No required external API. See `references/required-skills.md` for the 8 capability slots and example providers.

## Memory & state

3 layers under `~/.commerce-os/` (never uploaded): Layer 1 events (SQLite + daily `.md`), Layer 2 insights (verified ≥ 2× via `verified_count` increment), Layer 3 user SOUL (`SOUL.md`, user-edited only). Schema versioned; all writes use `INSERT OR REPLACE` + UUID `run_id`. Full schema in `references/memory-schema.md`.

**Boundary**: Lumicc never writes to OpenClaw's `MEMORY.md` or Hermes's user-profile. See `docs/09-memory-boundary.md`.

## Runtime modes

| Mode | Runtimes | Trigger | Output |
|------|----------|---------|--------|
| **Coder** | Claude Code, Codex, Cursor, Gemini CLI | User invokes on demand | stdout / IDE panel |
| **Agent** | OpenClaw, Hermes | Cron / heartbeat / IM message | `~/.commerce-os/outbox/*.json` → runtime gateway delivers to Feishu/Discord/etc. |

Full setup per runtime: `docs/08-agent-runtimes.md`. **Closed runtimes are not supported.**

## Failure modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| SQLite unwritable | init_store exits 2 | Falls back to `~/.commerce-os/store.json`; user warned |
| Adapter missing for a slot | health_check reports `missing` | Built-in fallback runs (e.g., CSV instead of API write) |
| Playwright unavailable | watch detects | User can paste competitor HTML manually |
| API token expired | sub-skill exits with `auth_required` | Skill prompts user to refresh token in `~/.commerce-os/.env` |
| Corrupted `store.db` | schema check fails | `init_store.py --reset` with explicit user confirm |

## Edge cases (top 3)

- **Multiple stores**: user is asked to pick `--store-id` or default to most-recently-updated.
- **Unknown stage**: missing `stage` → routes to `lumicc-listing` (safest default for 1→10).
- **Unsupported platform**: sub-skills check `platform` field; non-Shopify falls back to generic SOP without API writes.

## Anti-patterns

- ❌ Auto-publish products / posts without user confirmation.
- ❌ Write API tokens to SQLite or logs (env vars only).
- ❌ Invent metrics — if a number can't be sourced, write `[unknown]`.
- ❌ Scrape competitor pages that require login.

## Portability

Pure Python stdlib; no agent-SDK imports; no vendor name in core logic. Verified to load in Claude Code, Codex, Cursor, OpenClaw, Hermes, and Gemini CLI.

## Privacy

All data local; no telemetry; no remote calls beyond user-authorized adapters. GDPR/CCPA-compatible by design.

## References

`references/store-stages.md` · `references/routing-table.md` · `references/memory-schema.md` · `references/required-skills.md` · `references/api-credentials.md` · `references/io-schemas.md` · `examples/walkthrough.md` · `docs/08-agent-runtimes.md` · `docs/09-memory-boundary.md`

## Versioning & License

Semver. Current **0.2.0**. MIT. See `CHANGELOG.md`. Designed for 繁星计划·Fun Skills 全国大赛 2026.
