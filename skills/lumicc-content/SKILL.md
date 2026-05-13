---
name: lumicc-content
description: Cross-border content production studio — generates all marketing content needs (product detail pages, promotional posters, 5-angle product images, image-to-video prompts, TikTok scripts, blog briefs, ad creatives, email sequences, 小红书 posters) for cross-border e-commerce stores. Output is a single self-contained HTML "studio page" with copy-prompt buttons and image download links. Triggers on phrases like "generate poster", "product images", "video prompt", "PDP copy", "TikTok script", "ad creative", "email sequence", "海报", "商品图", "详情页文案", "视频脚本", "邮件序列", "广告创意", "出图". MUST be used whenever the user wants new marketing content for any SKU — even when only one specific asset type is requested.
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []           # all optional; with EVOLINK_API_KEY we generate real images
metadata:
  lumicc:
    pillar: attract
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    image_provider_default: evolink
    image_model_default: gemini-3-pro-image-preview     # Nano Banana Pro
    image_model_for_chinese: gpt-image-2                # auto-switch
    video_generation: opt_in                            # default OFF
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, content, image-gen, poster, pdp]
    category: marketing
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
    optional_tools: []
---

# lumicc-content

A content production studio for cross-border e-commerce. Generates **all content types** a store needs (PDP copy / posters / product images / video prompts / TikTok scripts / blog briefs / ad creatives / emails / 小红书 posters) and outputs a single beautiful HTML page where each item has a copy-prompt button or a download-image button.

**Images are real**: with an evolink.ai API key configured, Lumicc generates actual PNGs via Nano Banana Pro or GPT Image 2 and saves them to `~/.commerce-os/generated/<run_id>/`.

**Videos are opt-in**: default to prompt-only (Seedance 2.0 / HappyHorse 1.0 prompts); user explicitly enables with `--enable-video-gen` after seeing the cost.

## Persona

**Team**: 🎨 品牌内容师 · see [`personas.md` § 5](../lumicc/references/personas.md)

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是你的品牌内容师。先确认一下——你的 landing / 商详 / 海报想走什么调性？我开个本地选择器给你看 6 个方向。

**Tone**: 审美在线、说人话不堆术语。

**Handoff triggers** — 何时主动 announce 团队交棒：

- 选完风格 → 建站团队接手上架

**Security pattern**: 涉及 API key / token / 凭据收集时，引导用户去本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate <KEY>`。**绝不让用户把凭据贴进对话**。

## When to Use

Trigger whenever the user wants new marketing content for a store, including but not limited to:
- "为新 SKU 出一套内容" / "generate content for this product"
- "做个母亲节海报" / "create a Mother's Day promo poster"
- "5 个角度商品图" / "five product angles"
- "TikTok 视频脚本" / "TikTok video script"
- "邮件序列文案" / "email sequence copy"
- "广告创意变体" / "ad creative variations"
- "出图" / "out 图"

Do **not** trigger for: deep blog writing (let `article-writing` skill handle it) / brand voice design (let `brand-voice` skill handle it).

## Content Types (v0.1.0)

| Type | What you get | Mode |
|------|--------------|------|
| `pdp` | SEO title / 5 bullets / long description / meta / Schema.org JSON-LD as brief prompts | prompt-only (paste to ChatGPT/Claude) |
| `poster` | Real PNG images via Nano Banana Pro / GPT Image 2, 1-N variants | **real image generation** if EVOLINK_API_KEY |
| `product_image` | 5 angles (hero / lifestyle / scale / feature / packaging) as real PNGs | same |
| `product_enhance` | Photoroom-style cleanup prompts + recommendations | prompt-only |
| `video` | Seedance / HappyHorse prompts ready to paste | prompt-only by default; `--enable-video-gen` triggers real API |
| `tiktok_script` | 3-act script + 5 hooks + captions + hashtags | prompt-only |
| `blog_brief` | Brief that `article-writing` skill can pick up | prompt-only |
| `ad_creative` | 5 hook + 5 visual prompts + copy variants | prompt-only |
| `email_sequence` | Welcome / abandoned-cart / winback / post-purchase | prompt-only |

## Workflow

1. **Decide language**: skill auto-detects from store target_market or `--language` flag.
2. **Pick model**: defaults to Nano Banana Pro (`gemini-3-pro-image-preview`); auto-switches to GPT Image 2 (`gpt-image-2`) when `language == "zh"` (best for Chinese characters in image). Override via `--model`.
3. **Estimate cost** before any real API call: print expected credits; user confirms (unless `--auto-confirm`).
4. **Generate**: for each requested item, build the right prompt via `templates/<type>.py`, then either:
   - **Image types** (poster / product_image) → submit async task to `https://api.evolink.ai/v1/images/generations`, poll until done, download to `~/.commerce-os/generated/<run_id>/`.
   - **Video types** → default prompt-only; on `--enable-video-gen` submit async to `/v1/videos/generations`.
   - **Text types** (pdp / brief / ad / email) → render brief as Markdown.
5. **Render HTML**: build `content.html` with one card per item, copy-prompt buttons, image previews, download links.
6. **Persist**: write `generated_assets` rows to store.db.
7. **Optional notify**: agent mode → outbox JSON pointing to the HTML file.

## Inputs

```json
{
  "store_id": "string?",
  "sku": "string?  // or comma-separated for multi",
  "type": "pdp | poster | product_image | product_enhance | video | tiktok_script | blog_brief | ad_creative | email_sequence",
  "occasion": "string?  // 母亲节 / Black Friday / 周年庆 / etc.",
  "style": "string?  // warm cozy / minimal / luxury / playful",
  "count": "int?  // variant count (default 1, image types max 5)",
  "model": "string?  // nano-banana | gpt-image-2 | seedance-2.0-image-to-video | etc.",
  "size": "string?  // 1:1 / 16:9 / 9:16 / 3:4 / 4:3 / etc.",
  "quality": "1K | 2K | 4K  // default 1K",
  "language": "en | zh  // default from store.target_market",
  "dry_run": "boolean  // do not call API, output prompts only",
  "enable_video_gen": "boolean  // default false",
  "max_credits": "float?  // soft cap; warns when exceeded",
  "auto_confirm": "boolean  // skip 'confirm cost' prompt"
}
```

## Outputs

```json
{
  "run_id": "uuid",
  "skill": "lumicc-content",
  "status": "success | partial | failed",
  "credits_consumed": 4.8,
  "html_path": "~/.commerce-os/runs/<run_id>/content.html",
  "items": [
    {
      "id": "uuid",
      "type": "image | prompt | brief | video",
      "category": "poster | product_image | pdp | ...",
      "subject": "string",
      "prompt_text": "string",
      "model": "string?",
      "task_id": "string?  // evolink task id",
      "image_local_path": "string?  // for real-generated images",
      "credits": 0
    }
  ]
}
```

## Tools & Scripts

| Script | Purpose | Idempotent |
|--------|---------|-----------|
| `scripts/prompts.py` | 9 prompt templates (one per content type) | ✅ |
| `scripts/image_client.py` | evolink.ai async image client (submit / poll / download) | ✅ (cached) |
| `scripts/video_client.py` | evolink.ai async video client (gated by --enable-video-gen) | ✅ |
| `scripts/render_html.py` | content.html generator (cards + copy + download) | ✅ |
| `scripts/run.py` | Orchestrator | ✅ |
| `scripts/test_content.py` | End-to-end smoke test (mocks evolink) | ✅ |
| `scripts/notify.py` | Shared notification dispatcher | ✅ |

## Capability slots & adapters

| Slot | Required? | Provider examples | When missing |
|------|-----------|-------------------|--------------|
| `image_generation` | optional | evolink.ai (`EVOLINK_API_KEY`) / OpenAI DALL-E (`OPENAI_API_KEY`) | Falls back to prompt-only mode |
| `video_generation` | optional + opt-in | evolink.ai (same key) / user-provided | Prompt-only with explicit vendor links |
| `article-writing` skill | optional | local `~/.claude/skills/article-writing/` | Brief stays in markdown; user runs LLM manually |
| `brand-voice` skill | optional | local | Prompts use generic brand tone |
| `baoyu-image-gen` skill | optional | local | Lumicc generates via evolink instead |
| `baoyu-xhs-images` skill | optional | local | For 小红书 posters, fall back to evolink |

See `references/required-skills.md`.

## Memory & State

Every generated asset writes one row to `generated_assets` (new table; auto-migrated):

```sql
generated_assets (
  id, run_id, store_id, sku, asset_type, category,
  prompt_text, model, size, local_path, remote_url,
  remote_url_expires_at, credits, created_at
)
```

This makes `lumicc-dashboard` show per-SKU asset history.

## Cost transparency

- Before any real API call, `run.py` prints **expected credit consumption** and pauses (unless `--auto-confirm`).
- A `--max-credits N` soft cap stops the run if cost would exceed N.
- A `--dry-run` flag generates prompts only, no API calls, no cost.
- The HTML page shows actual credits consumed per item.

## Anti-patterns

- ❌ Do not embed API keys in any output file (HTML / JSON / logs).
- ❌ Do not silently call paid APIs without explicit cost confirmation.
- ❌ Do not generate videos by default (quality risk; user must opt in).
- ❌ Do not retry failed tasks more than 3 times (cost explosion).
- ❌ Do not skip downloading remote URLs (24h expiry).

## Privacy

- API key only read from `~/.commerce-os/.env` or process env.
- Generated assets local under `~/.commerce-os/generated/<run_id>/`.
- No telemetry. No remote calls except evolink (or chosen provider).
- HTML viewable offline once assets are downloaded.

## References

- `references/required-skills.md` — capability-slot catalog
- `references/evolink-api.md` — API reference (image + video)
- `references/model-selection.md` — when to use Nano Banana vs GPT Image 2
- `references/prompt-design.md` — how the 9 prompt templates are built
- `references/content-types.md` — detailed guide per content type
- `examples/walkthrough.md` — Mother's Day poster + 5 product images end-to-end

## Versioning & License

Semver. Current 0.1.0. MIT. Designed for 繁星计划·Fun Skills 全国大赛 2026.
