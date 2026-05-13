# Capability Adapters & Optional Integrations

Lumicc is a **sovereign skill bundle** — it does not require any external skill to be installed. Instead, it defines **capability slots** that any provider can fill. If a slot is empty, the corresponding workflow degrades gracefully to a manual or built-in fallback.

## Why this design

- **No vendor lock-in**: Lumicc does not embed any third-party brand's data or naming.
- **Maximum portability**: works in Claude Code / OpenClaw / Cursor / Codex / any agent that loads SKILL.md files.
- **IP clean**: we describe the capability we need, not who provides it.
- **Future-proof**: as new skill providers emerge, Lumicc gains automatically.

## Capability Slots

Each slot has: (a) the capability description, (b) example providers the user can install, (c) the built-in fallback.

### Slot 1 — Amazon revenue & ranking data

| Item | Detail |
|------|--------|
| What we need | ASIN-level monthly revenue estimate, BSR trend, sales velocity |
| Used by | `lumicc-launch` (sourcing), `lumicc-expand` (candidate scoring) |
| Example providers | Jungle Scout API, Helium 10 Black Box API, AMZScout, public BSR + heuristic |
| Built-in fallback | User pastes Amazon URL → we use public listing data only (no revenue estimate) |

### Slot 2 — B2B supplier matching

| Item | Detail |
|------|--------|
| What we need | Search by product image / keyword → supplier list with cost, MOQ, response rate |
| Used by | `lumicc-launch` (Week 1 sourcing), `lumicc-expand` (supplier check) |
| Example providers | Any Alibaba / 1688 / Global Sources adapter the user has |
| Built-in fallback | We give the user a search-query template + manual review checklist |

### Slot 3 — Shopify (or platform) write API

| Item | Detail |
|------|--------|
| What we need | Create products, update inventory, manage theme assets, read analytics |
| Used by | `lumicc-launch` (Week 2 upload), `lumicc-listing` (apply fixes) |
| Example providers | Shopify Admin GraphQL adapter, Amazon SP-API adapter, TikTok Shop Open Platform adapter |
| Built-in fallback | We output CSV / JSON that the user uploads manually via the platform UI |

### Slot 4 — Review & ticket signal

| Item | Detail |
|------|--------|
| What we need | Pull reviews, support tickets, return reasons in normalized form |
| Used by | `lumicc-voc` |
| Example providers | Shopify Reviews API, Amazon SP-API reports, Gorgias / Zendesk adapter, Klaviyo |
| Built-in fallback | User pastes recent reviews as text — we cluster via keyword groups |

### Slot 5 — Landed cost & duty calculation

| Item | Detail |
|------|--------|
| What we need | HS-code classification + duty rate by destination |
| Used by | `lumicc-launch` (margin gate), `lumicc-expand` (cost check) |
| Example providers | TurtleClassify API, Zonos, Easyship, any HS-code lookup |
| Built-in fallback | We use the user-provided percent (default 8% for US, 0% for inside-US trade) |

### Slot 6 — Social publishing

| Item | Detail |
|------|--------|
| What we need | Authenticated post to X / Instagram / TikTok / Pinterest with media + caption |
| Used by | `lumicc-launch` (Week 3 content drop) |
| Example providers | Any social publisher skill the user has, or platform-native Buffer / Later API |
| Built-in fallback | We output the post draft to a file; user copies & pastes manually |

### Slot 7 — Image & video generation

| Item | Detail |
|------|--------|
| What we need | Background removal, lifestyle composition, product video generation |
| Used by | `lumicc-launch` (listing images), `lumicc-listing` (image upgrades) |
| Example providers | Photoroom API, Remove.bg, Runway ML, Stable Diffusion local, HeyGen |
| Built-in fallback | User supplies raw supplier images — we tag which slots need new visuals |

### Slot 8 — Competitor page snapshot

| Item | Detail |
|------|--------|
| What we need | Headless browser to render JS-heavy storefronts and capture DOM |
| Used by | `lumicc-watch` |
| Example providers | Playwright (recommended), Puppeteer, browser-use, any browser MCP server |
| Built-in fallback | User pastes competitor homepage HTML — we parse it offline |

## Detection

`scripts/health_check.py` probes the user's environment and reports which slots are filled. The report drives sub-skill behavior:

```json
{
  "capability_slots": {
    "amazon_revenue_data": "available (via JUNGLE_SCOUT_API_KEY)",
    "shopify_write": "available (via SHOPIFY_ADMIN_TOKEN)",
    "social_publish": "missing — manual fallback",
    "image_gen": "missing — supplier images only"
  }
}
```

## Privacy

Lumicc never sends data to any external service automatically. Each adapter is only called when the user has explicitly configured credentials in `~/.commerce-os/.env`.

## Note on inspiration

While building Lumicc we studied many publicly-available skill catalogs (Anthropic's official examples, GitHub awesome-claude-skills, awesome-openclaw-skills, ComposioHQ collection, jezweb/claude-skills, AgriciDaniel/claude-seo, and others). We took **methodology inspiration** from those public catalogs but wrote all SKILL.md content, scripts, schema, and workflows ourselves. **Lumicc does not import or repackage any third-party skill.**
