---
name: lumicc-publish
description: Package any Lumicc HTML report and deploy to Cloudflare Pages with optional AES-GCM client-side encryption + password gate. The encrypted bundle is unreadable even to Cloudflare — only the password holder can view. Generates a public URL the user can send to stakeholders. Triggers on phrases like "share my report", "deploy dashboard", "send to client", "give my boss access", "分享报告", "发给客户", "上线给老板看", "导出 URL", "客户那边看", "把报告发出去".
license: MIT
version: 1.0.0
platforms: [macos, linux]
required_environment_variables: []
metadata:
  lumicc:
    pillar: ops
    runtime_modes: [coder, agent]
    notification_channels: [feishu, discord, telegram, slack, email]
    data_root: "~/.commerce-os"
    parent_skill: lumicc
  hermes:
    tags: [ecommerce, publish, deploy, encryption, cloudflare]
    category: ops
  openclaw:
    workspace_scope: optional
  compatibility:
    agents: [claude-code, codex, cursor, openclaw, hermes, gemini-cli]
    channels: [feishu, discord, telegram, slack, wechat, line, imessage, email]
    scripts: [python3]
---

# lumicc-publish

Package any Lumicc HTML report (or arbitrary HTML file) and ship it to Cloudflare
Pages. Optional client-side AES-GCM password gate makes the payload unreadable
even to Cloudflare — only the password holder can view.

## Persona

**Team**: 🎯 CMO 总指挥 · see [`personas.md`](../lumicc/references/personas.md)

> 没有专门的 "deploy 团队"，所以分享报告这件事 CMO 自己来：选个加密策略、
> 给个公开 URL，然后告诉你密码。

**Opening (agent 调用本 skill 时说的第一句话)**:

> 我是 CMO。你这份报告我马上发到 Cloudflare Pages，给你一个公开 URL。
> 要不要加密？要的话告诉我密码，浏览器端解密，Cloudflare 也看不到内容。

**Tone**: 简短、决策导向，先决定加密/不加密，再选过期时间。

**Handoff triggers**:

- 报告含财务数字 / 客户名单 → 默认建议加密 + 30 天过期
- 给 SEO / PR 用 → 公开链接 + 长期保留

**Security pattern**: Cloudflare token 必须走本地表单：
`python3 ../lumicc/scripts/secret_form.py --generate CLOUDFLARE_API_TOKEN --open`
和 `--generate CLOUDFLARE_ACCOUNT_ID --open`。**绝不让用户把 token 贴进对话。**

## When to Use

- 任何 Lumicc skill 跑完产出 `report.html`，需要发给非技术干系人（客户、老板、合伙人）。
- 想给报告加"密码门"，但不想搭服务器。
- 一次性 dashboard 演示，链接 30 天后自动失效。

## Workflow

1. 读 source HTML（任意 Lumicc skill 的 `report.html`）。
2. 可选加密：PBKDF2-SHA256 (600k 迭代) 派生 256-bit key，AES-GCM 加密 payload。
   浏览器用内置 WebCrypto 解密 —— 无外部依赖。
3. 包装到 `index.html`（包含密码输入 + 解密脚本，或裸 HTML）。
4. 调用 Cloudflare Pages API（或 `wrangler` CLI 若可用）创建 deployment。
5. 写一行到 `shares` 表，返回 share_id + URL。
6. 通过 notify 渠道发 URL + 密码（密码可走单独消息，建议另一通道）。

## Inputs

```json
{
  "html": "path/to/report.html",
  "password": "optional",
  "public": false,
  "subdomain": "optional-pretty-name",
  "expires_days": 30
}
```

## Outputs

```json
{
  "share_id": "uuid",
  "url": "https://lumicc-<random>.pages.dev",
  "password": "8888",
  "encrypted": true,
  "expires_at": null,
  "duration_sec": 12.3
}
```

## CLI

```bash
# Deploy with password gate
python3 run.py --html ~/.commerce-os/runs/abc/report.html --password 8888

# Public (no encryption)
python3 run.py --html report.html --public

# Custom subdomain + 30-day expiry
python3 run.py --html report.html --password 8888 \
    --subdomain my-store-q3 --expires-days 30

# Lifecycle ops
python3 run.py --list
python3 run.py --status <share_id>
python3 run.py --revoke <share_id>

# Local dry-run (no Cloudflare HTTP call)
python3 run.py --html report.html --password 8888 --dry-run
```

## Encryption (honest disclosure)

- Algorithm: **AES-GCM 256** with **PBKDF2-SHA256 (600,000 iterations)** key
  derivation — matches OWASP 2023 recommendation.
- Python side requires `cryptography` package. If missing, the script prints
  install instructions and exits. This is the **only** Lumicc skill that breaks
  the stdlib-only rule; public deployment (`--public`) works on pure stdlib.
- Browser side uses **WebCrypto SubtleCrypto** — built into all evergreen
  browsers, zero JS dependencies.
- Cloudflare Pages serves the encrypted bundle as opaque bytes. Even with full
  Cloudflare access, an attacker cannot read the report without the password.

See `references/cloudflare-setup.md` for token setup.

## Tools & Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run.py` | CLI entrypoint (deploy/list/status/revoke) |
| `scripts/encrypt.py` | AES-GCM + browser decrypt JS template |
| `scripts/render_html.py` | Wrapper page (password gate UI) + status reports |
| `scripts/notify.py` | Push share URL to notification channel |

## Anti-Patterns

- ❌ 不要把密码和 URL 发到同一个 IM 消息里 — 分两个通道发。
- ❌ 不要给"加密"的报告设置弱密码（< 8 字符） — PBKDF2 也救不了。
- ❌ 不要 revoke 后假设 CDN cache 立即失效 — Cloudflare edge 有 TTL。
- ❌ 不要把 CLOUDFLARE_API_TOKEN 当 CLI 参数 — 永远走 secret_form。

## References

- `references/cloudflare-setup.md` — token & account_id 获取步骤

## Status

v0.5.0 — encrypted deploy + revoke + list + dry-run + tests with mocked HTTP.
