---
name: lumicc-seo
description: SEO + GEO (Generative Engine Optimization) orchestrator for cross-border independent sites. Generates llms.txt for AI crawlers, emits Schema.org JSON-LD per product, tracks keyword ranks (Google Search Console CSV import), tracks brand-citation share across ChatGPT / Perplexity / Claude / Gemini / Google AI Overviews, runs technical SEO audits (Core Web Vitals / hreflang / sitemap / robots.txt). Persists rank history + citation history to ~/.commerce-os/store.db so users see month-over-month trends. Triggers on phrases like "SEO audit", "keyword rank", "citation tracking", "llms.txt", "schema markup", "AI overviews", "GEO", "structured data", "Google ranking", "ChatGPT mentioned my brand?", "SEO 体检", "排名监控", "GEO 引用", "AI 搜索", "出现在 ChatGPT 答案里". MUST be used when user asks anything about organic search visibility (Google or AI engines).
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: attract
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, seo, geo, aeo, llms-txt, schema]
    category: marketing
    suggested_cronjobs:
      - schedule: "0 9 * * 1"
        command: "lumicc-seo --mode rank --notify-channel feishu"
        purpose: "Weekly Monday morning rank update"
      - schedule: "0 9 * * 1"
        command: "lumicc-seo --mode citation --notify-channel feishu"
        purpose: "Weekly GEO citation check"
  openclaw:
    suggested_cron:
      - cron: "0 9 * * 1"
        command: "python3 .../scripts/run.py --mode rank --notify-channel feishu --quiet-stdout"
      - cron: "0 9 * * 1"
        command: "python3 .../scripts/run.py --mode citation --notify-channel feishu --quiet-stdout"
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: []
---

# lumicc-seo

SEO + GEO orchestrator for cross-border independent sites. Not another keyword tool — there are 100+ of those. Lumicc-seo is the **glue layer** that:

1. **Owns the GEO concept** — Generative Engine Optimization. Track if your brand is cited when users ask AI engines about your category.
2. **Fills 2 of the 5 whitespaces** identified in 770 lines of ecosystem research: **llms.txt generation + validation** + **Google AI Overviews monitoring**.
3. **Persists history** — rank + citation tables in store.db so trends compound; not a one-shot tool.
4. **Composes with the rest of Lumicc** — listing changes trigger schema regen; voc clusters trigger blog briefs covering missing search queries.

## Persona

**Team**: 🔭 市场情报员 · see [`personas.md` § 4](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的市场情报员。这次扫了你内容在 Google / Bing / Perplexity / ChatGPT / Claude 的引用情况。

**Tone**: 冷静、像侦察兵，先报观察+严重度，再给建议。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 引用低 → 品牌内容师重写
- keyword 抢不过 → CMO 看转型 long-tail

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

Trigger whenever the user asks about:
- Google organic rank / SERP position / Search Console
- "Why am I not showing up?" / "How do I rank?"
- Schema.org / structured data / JSON-LD
- llms.txt / AI crawler readability
- ChatGPT / Perplexity / Claude / Gemini citing the brand
- AI Overviews / SGE / featured snippets
- Technical SEO / Core Web Vitals / hreflang / sitemap

**Do not** trigger for: deep blog writing (→ `article-writing` skill) / paid ad bidding (→ platform-native tools) / brand voice (→ `brand-voice` skill).

## Modes

`run.py --mode X` dispatches to one of:

| Mode | Purpose | Frequency | Input |
|------|---------|-----------|-------|
| `llms-txt` ⭐ | Generate `llms.txt` for AI crawlers + validate format | one-time per site | store + products |
| `schema` ⭐ | Per-product Schema.org JSON-LD (Product / Offer / AggregateRating / FAQPage) | each listing change | product row |
| `rank` | Track keyword rank trends | weekly | Google Search Console CSV / Ahrefs export |
| `citation` ⭐ | Track brand citation share across ChatGPT / Perplexity / Claude / Gemini / AI Overviews | weekly | engine query results (paste mode or API) |
| `audit` | Technical SEO checklist | monthly | store URL |
| `all` | Run llms-txt + schema (per active product) + audit; skip rank/citation (need input) | one-time setup | — |

## Workflow

1. **Pick mode** by user intent or default to `all` for setup.
2. **Run** the mode's script; each writes a Markdown report to `~/.commerce-os/runs/<id>/`.
3. **Persist** results to `seo_keywords` / `seo_citations` tables (auto-created).
4. **Render HTML** in `report.html` for browsing.
5. **Notify** (agent mode): outbox alert if rank dropped ≥ 10 positions or citation share fell.
6. **Recommend next** — e.g., "3 keywords lost > 5 positions → trigger `lumicc-content blog_brief` to write coverage articles".

## Inputs

```json
{
  "store_id": "string?",
  "mode": "llms-txt | schema | rank | citation | audit | all",
  "product_id": "string?      // for --mode schema",
  "queries_file": "string?    // for --mode citation: JSON list of {query, engine, raw_answer}",
  "gsc_csv": "string?         // for --mode rank: Google Search Console CSV path",
  "min_position_drop": "int?  // notify threshold; default 10",
  "target_brand_keyword": "string?  // for citation matching; default = store.name"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-seo",
  "mode": "string",
  "status": "success | partial | failed",
  "deliverables": [
    {"type": "llms_txt", "path": "~/.commerce-os/seo/llms.txt"},
    {"type": "schema_json_ld", "path": "~/.commerce-os/runs/<id>/schema-MKR-16.json"},
    {"type": "rank_delta_md", "path": "~/.commerce-os/runs/<id>/rank-report.md"},
    {"type": "citation_share", "path": "~/.commerce-os/runs/<id>/citation-report.md"},
    {"type": "audit_checklist", "path": "~/.commerce-os/runs/<id>/audit.md"}
  ],
  "warnings": ["string"],
  "next_recommended_skill": "lumicc-content"
}
```

## Tools & Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `scripts/llms_txt.py` | Generate + validate `llms.txt` per llmstxt.org spec | ✅ |
| `scripts/schema_gen.py` | Generate Schema.org JSON-LD per product | ✅ |
| `scripts/rank.py` | Import GSC CSV → seo_keywords table | ✅ |
| `scripts/citation.py` | Parse pasted AI engine answers → seo_citations table | ✅ |
| `scripts/audit.py` | Technical SEO checklist | ✅ |
| `scripts/run.py` | Mode dispatcher + report rendering | ✅ |
| `scripts/test_seo.py` | End-to-end smoke test (mocks GSC + paste mode) | ✅ |
| `scripts/notify.py` | Shared notification dispatcher | ✅ |

## Capability slots & adapters

| Slot | Required? | Provider examples | When missing |
|------|-----------|-------------------|--------------|
| `google_search_console` | optional | GSC CSV export / GSC API (future v0.2.0) | rank tracking works via manual CSV import |
| `ai_engine_query` | optional | ChatGPT API / Perplexity API / direct paste | citation tracking falls back to paste mode |
| `core_web_vitals` | optional | PageSpeed Insights API | audit prints checklist for manual run |
| `ahrefs_semrush` | optional | their APIs | rank works via CSV; gap analysis defers |
| `article-writing` skill | optional | local | blog brief stays as prompt for user |
| `deep-research` skill | optional | local | competitive content gap is sketchier |
| `exa-search` skill | optional | local | SERP discovery uses Google direct |

## Citation tracking (the GEO core differentiation)

Two ways to collect citations:

**Mode A — Paste mode (default, no API needed)**:
1. User opens ChatGPT and asks: `"What are the best magnetic knife racks?"`
2. User saves the answer as `~/.commerce-os/seo/queries-2026-05-12.json`:
   ```json
   [{"engine": "chatgpt", "query": "best magnetic knife racks",
     "raw_answer": "<paste the full ChatGPT answer here>"}]
   ```
3. Run `python3 run.py --mode citation --queries-file <path> --target-brand-keyword "Acme"`
4. We parse the answer text for brand keyword occurrences, compute citation share per engine, append to `seo_citations` table.

**Mode B — API mode (v0.2.0)**: configure provider API keys → we auto-query.

Per-engine differences are real: ChatGPT cites Wikipedia 48%, Perplexity cites Reddit 47%, citation overlap between ChatGPT and Perplexity is only 11%. Track each engine separately.

## Memory & state

New tables (auto-migrated on first run):

```sql
CREATE TABLE IF NOT EXISTS seo_keywords (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id TEXT,
  keyword TEXT NOT NULL,
  target_market TEXT,
  search_volume INTEGER,
  cpc REAL,
  current_rank INTEGER,
  prev_rank INTEGER,
  url TEXT,
  ts INTEGER NOT NULL,
  source TEXT
);

CREATE TABLE IF NOT EXISTS seo_citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id TEXT,
  engine TEXT NOT NULL,
  query TEXT NOT NULL,
  brand_mentioned INTEGER,
  position INTEGER,
  citation_url TEXT,
  raw_answer_excerpt TEXT,
  ts INTEGER NOT NULL
);
```

## Runtime modes

| Mode | Coder runtime | Agent runtime |
|------|---------------|---------------|
| llms-txt / schema / audit | runs once; opens report | runs once; outbox notifies path |
| rank | one-shot CSV import | weekly cron `0 9 * * 1`, outbox if drop ≥ 10 positions |
| citation | one-shot per query batch | weekly cron `0 9 * * 1`, outbox if share dropped |

## Anti-patterns

- ❌ Do not invent rank positions or citation shares without input data.
- ❌ Do not auto-submit anything to Google Search Console (read-only by design).
- ❌ Do not call paid SERP APIs without explicit configuration.
- ❌ Do not crawl competitor sites in this skill — that's `lumicc-watch`.
- ❌ Do not store raw AI engine answers verbatim if > 1000 chars (only excerpt).

## Privacy

- All data local under `~/.commerce-os/seo/` and `~/.commerce-os/runs/`.
- Citation raw text is excerpted (≤ 500 chars) to avoid copying proprietary AI engine output verbatim.
- No telemetry; no remote calls except optional adapter APIs the user configured.

## References

- `references/llmstxt-spec.md` — how llms.txt format works
- `references/schema-org-types.md` — which JSON-LD types we emit
- `references/citation-tracking.md` — paste mode + API mode workflow
- `references/audit-checklist.md` — technical SEO audit items
- `references/whitespaces.md` — the 5 SEO/GEO whitespaces and which we tackle
- `examples/walkthrough.md` — end-to-end setup

## Versioning & License

Semver. Current 0.1.0. MIT. Designed for 繁星计划·Fun Skills 全国大赛 2026.
