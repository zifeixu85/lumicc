# Changelog

所有显著变化都记录在这里。版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

格式：`Added` / `Changed` / `Fixed` / `Removed` / `Deprecated` / `Security`

---

## [1.3.0] · 2026-05-14 · 真实表单向导 · 零命令暴露

### Changed

- **`config.py` 重建为真实本地 HTTP 服务器向导** — 从「静态 HTML + 可复制命令」改为 lumi-lab 式的活表单。用户在浏览器里**填表、点按钮、即生效**，全程不出现 shell 命令：
  - 纯 stdlib `ThreadingHTTPServer`，绑 `127.0.0.1`（仅本地），端口 7777→7780 自动探测
  - **4 步向导**：欢迎（Lumicc 是什么 + 6 团队 + 工作流）→ 你的店铺（有店/从零真实表单 → POST 直接建店 + 写 SOUL.md）→ 工具集成（API key 表单）→ 完成
  - **工具集成步是重点**：每个 API key 一个字段 = 名称 + 一句话说明（这 key 解锁什么功能）+ 折叠的「怎么拿到」3-4 步引导 + `<input type="password">` + 验证并保存按钮。按用途分 5 组（电商数据 / 图像生成 / 邮件 / LLM / 部署），**全部可选**
  - 密钥写到 `~/.commerce-os/secrets/<KEY>.json` 0600（沿用 secret_form 格式），验证 best-effort（失败也存 + 给警告）
  - 完成步后服务器自动优雅关闭
- CLI 保留 `--create-store`（agent 对话收集后 headless 调用）/ `--quiet-stdout` / `--status` / `--port` / `--no-open`

### Why

用户反馈：onboard 页里给用户看 shell 命令是错的——用户只用自然语言说话，命令是给 agent 的。API key 配置应该是真实表单，告诉用户每个工具是干嘛的，引导用户按需填写。参考 lumi-lab 的 onboarding 表单（"非常完整"）。现在表单真正能用了。

---

## [1.2.0] · 2026-05-14 · 配置中心 + onboarding + 全链路可导航

### Added

- **`lumicc/scripts/config.py`** — 统一配置中心 + onboarding 入口（`lumicc config` / `lumicc onboard`），两种模式自适应：
  - **首次（无店铺）= Landing 引导** — 介绍 Lumicc 是什么、6 个专家团队各能干嘛、典型工作流（选品→上架→引流→转化→留存→救火），两个行动卡（接入已有店 / 从零开始）
  - **后期（有店铺）= 配置中心** — 店铺列表、API 凭据状态表（X/N 已配置 · fingerprint · 每个 key 的 `secret_form --generate` 命令可一键复制）、SOUL.md 预览、当前主题 + 4 主题切换说明
  - `--create-store --platform X --market Y --niche Z --stage S` 直接建店 + 写 SOUL.md 初稿
  - `--create-store --from-json <path>` 供 HTML 向导回调
- **`bin/lumicc config` / `bin/lumicc onboard`** 命令 — 解决两个痛点：初始化时有了配置引导，后期有了快速改配置入口

### Changed

- **Dashboard + 控制台全链路可导航** — 之前 runs/campaigns 只是死文本，现在：
  - dashboard runs 页 + index 最近跑次 → 每行链到 `../runs/<id>/report.html`，新增"报告"列
  - cold-start campaign 卡片 → 链到对应 `lumicc-launch` 报告
  - `home.py` 控制台 focus-feed + 最近产出 chips → 可点进 `runs/<id>/report.html`
  - 只链磁盘上真实存在的文件，绝不产生断链
- `bin/lumicc` 测试列表加入 `test_config.py` — **27/27 测试通过**

### Why

用户反馈：初始化时没有配置引导，后期也没有快速改配置的方案；dashboard 看到活动却点不进去详情。v1.2 把"装完 → 第一家店 → 看到活动点进详情"这条路打通——产品从一堆断链 HTML 变成可点可导航的整体。

---

## [1.1.0] · 2026-05-14 · 控制台首屏 · 一个命令看清所有店

### Added

- **`lumicc/scripts/home.py`** — 跨店聚合控制台。`lumicc`（裸命令）的默认入口：
  - **Portfolio 条** — 所有店铺一行排开，每个带健康度圆点（按该店最高紧急度着色）
  - **跨店「今日焦点」feed** — 所有店的所有待办按紧急度排成一列，聚合单位是「行动项」不是「店铺」
  - **紧急度打分器** — 危机事件 100 / 指标低于阈值 60-85 / 冷启动日常 55 / 闲置店 35 / 一切正常 15
  - **6 个专家团队卡片** + 最近产出（跨店）
  - 空状态引导（没店时显示"接入我的店 / 从零开始"）
  - `--store-id` 过滤到单店；`--quiet-stdout` agent 模式
- **`bin/lumicc` 裸命令** 现在直接打开控制台（不再是文本 usage dump）；新增 `lumicc home` 子命令
- `init_store.py` 现在也认 `LUMICC_DATA_ROOT` 环境变量（与 session/secret_form/adapters/home 一致）

### Changed

- `bin/lumicc` 测试列表加入 `test_home.py` — **26/26 测试通过**

### Why

12 个强力 skill 但之前「前门」是一串子命令名 + 对话。多店运营者第一个念头是"今天什么最该管"，不是"挨个看店"。控制台把这一层补上：一个命令、一屏、所有火情按紧急度排好。

---

## [1.0.0] · 2026-05-14 · 🎉 GA · 完整跨境运营 OS

### Highlights

- **12 个 skill**（v0.2 的 11 + 新增 `lumicc-publish`）
- **真实数据接入**（不再有 demo seed） — 3 个 platform adapter：CSV / Plausible / Shopify Admin / Amazon SP-API
- **真实图像生成** — `lumicc-content` 通过 evolink.ai 调用 Nano Banana Pro / GPT Image 2，自动中文切 GPT Image 2
- **报告分享部署** — `lumicc-publish` 上传到 Cloudflare Pages，AES-GCM 加密 + 密码门（密码不进 LLM 不进 stdout）
- **6 团队 dialogue scripts**（912 行）让 agent 不出戏，跨 skill 显式 announce 团队交棒
- **5 种安装方式**：Claude Code / OpenClaw / Hermes / 飞书 Discord 机器人 / 手动
- **Anti-Slop 6 gate** 检测 LLM 套话 / 堆栈词 / 不具体 / 数据无源 / 假权威 / 中文机翻
- **25/25 测试通过**，已修 v1.0 code-review 的 4 HIGH 问题（XSS 防御 + 密码不外泄 + 加密 wrapper 防 script-tag breakout）

### Added — 真实数据 Adapters

- `lumicc/scripts/adapter_csv.py` (445 行)：通用 CSV 导入，中英 30+ 列别名自动识别，支持 Shopify export / 自定义 products/customers 表
- `lumicc/scripts/adapter_indep.py` (385 行)：独立站接入，Plausible API + sitemap + 产品页 fetch
- `lumicc/scripts/adapter_shopify.py` (548 行)：Shopify Admin API v2024-10，支持分页 + 限流 + Retry-After
- `lumicc/scripts/adapter_amazon_sp.py` (556 行)：Amazon SP-API，LWA token 交换 + 6 marketplace + 6 个 SP-API 坑位详细记录

### Added — 真实图像生成

- `lumicc-content/scripts/image_client.py` (430 行)：evolink.ai API · Nano Banana Pro · GPT Image 2 · Sora 2 视频（opt-in）
- `lumicc/scripts/assets.py` (276 行)：assets 表 CRUD（schema v2 migration）
- `lumicc-dashboard` 新增「过去 30 天素材」卡片，含累计成本统计
- `lumicc-content` 新增 `--generate-images` / `--video` / `--enable-video` / `--estimate-only` flags
- HTML 报告内联 base64 嵌入生成图（< 500KB），超过则显示本地路径

### Added — 发布与分享 (lumicc-publish, 新 skill)

- AES-GCM 256-bit 加密 + PBKDF2-SHA256 600k 迭代（OWASP 2023）
- WebCrypto API 浏览器侧解密（无依赖）
- Cloudflare Pages REST API 部署 + wrangler CLI 自动探测
- shares 表持久化（含 password_fingerprint，从不存明文）
- 可选 `--expires-days` / `--public` / `--revoke` / `--list`

### Added — 对话引导深化

- `lumicc/references/dialogue-scripts/` 6 个团队 × 3-5 个对话路径（cmo/builder/analyst/intel/content/rescue.md）
- `lumicc/scripts/route.py` 加 `--review` mode：跨 skill 复盘 + 自动派单下一步
- `lumicc-dashboard` 新增「API 凭据」卡片（仅 fingerprint，零 cleartext）
- `picker.py` 新增 `brand_direction` kind（5 个品牌方向选项）
- `picker` 历史持久化到 `store.db preferences`，下次自动推荐
- `lumicc-listing` 在 hero 评分 < 6 时自动推荐 `landing_style` picker

### Added — 多渠道安装

- `install.json` agentskills.io v1 manifest（仓库根）
- `bin/lumicc install` 支持 `--target {claude-code,openclaw,hermes,manual}` 自动探测
- 12 个 SKILL.md frontmatter 加 `metadata.compatibility.channels: [feishu,discord,telegram,slack,wechat,line,imessage,email]`
- README "5 种安装方式" 章节

### Added — Anti-Slop

- `lumicc/scripts/anti_slop.py` (601 行)：6 个质量门（G1-G6 EN/ZH）
- `check_slop()` / `render_banner()` / `render_report_html()` 公开 API
- 30/30 测试通过，含 false-positive vibe-check 报告

### Added — base64 自包含 HTML

- `html_lib.embed_image(path, max_kb=500)` helper：本地图片 → base64 data URI，超阈值则 SVG 占位符
- 报告整体单文件，可邮件传可微信传

### Security (code-review v1.0 4 HIGH 全部修复)

- `_sanitize_for_event()` 剥离 `<>&"'` 防 events.content XSS（adapter_shopify + adapter_amazon_sp）
- `lumicc-publish` 不再返回原密码，改 `password_fingerprint`（sha256 前 8 位）
- `encrypt.py wrapper_html` 用 `html.escape()` 处理 title + 转义 `</` 防 script-tag breakout
- `anti_slop.check_slop` 异常不再静默返回 passed，改为返回 G0 violation

### Engineering

- 25 个测试文件 · 25/25 通过
- 总 LOC：~22,000 Python 行
- 0 网络依赖（系统字体 / 本地 SQLite / 本地 HTML） · `cryptography` 仅 lumicc-publish 加密功能可选

### Known limitations

- 视频生成需用户 evolink.ai API key + 显式 `--enable-video` + `--confirm-cost`
- `lumicc-publish` 加密功能需 `pip install cryptography`（仅此一个 skill 非纯 stdlib）
- `lumicc-watch` 抓不到纯 JS-SPA 内容

---

## [0.2.0] · 2026-05-13 · 对话引导 + 安全表单 + 视觉选择器

### 🎉 Highlights

- **6 个专家团队人设系统** — 不再是"一个 AI 助手"，而是 CMO 总指挥 / 建站团队 / 数据分析师 / 市场情报员 / 品牌内容师 / 危机响应官，跨 skill 切换时显式 announce 团队交棒，给用户"换了一支专家接手"的真实感。
- **凭据零暴露给 LLM 的安全表单系统** — `secret_form.py` 生成本地 HTML 表单（带 CSP 锁死外联），API key 直接写到 `~/.commerce-os/secrets/<KEY>.json`（0600 权限），永远不进入对话历史。这是产品的**核心安全设计特征**，其他 skill 厂商基本没人做这层。
- **视觉选择器** — `picker.py` 提供 5 类视觉选择（landing 风格 / 配色 / 商品卡布局 / 首屏构图 / 字体搭配），每类含 4-6 个精心策展的方向，每个方向都有真实可视化预览（不是占位符）。
- **跨 skill 会话状态机** — `session.py` 让对话上下文跨 skill / 跨 turn 保留在 `~/.commerce-os/sessions/<id>/state.json`，原子写、`LUMICC_DATA_ROOT` 可隔离，支持 GC。
- **lumicc-content 接入 picker 作为示范** — 「我开个本地选择器你看下」从口号变成可运行的工作流。

### Added — 对话引导基础设施

- `lumicc/references/personas.md` — 6 个专家团队完整定义（身份、tone、开场白、handoff 矩阵、跨团队切换时机）
- `lumicc/scripts/session.py` (220 行 + 31 测试) — `new_session` / `read_state` / `update_state` / `append_event` / `current_session` / `read_choice` / `gc_old_sessions`，跨 skill / 跨 turn 共享上下文
- 10 个 SKILL.md 注入 `## Persona` 段：每个 skill 顶部标明它属于哪个团队、开场白怎么说、何时主动交棒下一团队

### Added — 安全表单系统

- `lumicc/scripts/secret_form.py` (376 行 + 8 测试) — 本地 HTML 表单生成器
  - 9 个已知 provider 目录：SHOPIFY / AMAZON SP-API / TIKTOK Shop / ETSY / KLAVIYO / ANTHROPIC / OPENAI / NANO BANANA / GPT IMAGE 2
  - 强制 CSP：`connect-src 'none'; form-action 'none'` 在浏览器层禁止任何外联
  - 主路径 `window.showSaveFilePicker` (Chromium 直写本地) + 兜底 Blob 下载 + 一键复制 mv 命令
  - 公开 API：`read_secret` / `has_secret` / `secret_fingerprint` / `list_secrets` / `render_form` / `delete_secret`
  - 文件权限严格：`secrets/` 0700，单文件 0600
- `health_check.py` 集成 secrets 状态显示（不泄露 cleartext value，只显示 fingerprint）

### Added — 视觉选择器

- `lumicc/scripts/picker.py` (668 行 + 8 测试) — 5 个 kind × 4-6 个精心策展选项
  - `landing_style` — Aesop / Kinfolk / Apple / Brutalist / Y2K / Rolex 6 个方向，含真实 CSS-only 预览 mock
  - `color_palette` — 6 个配色（赤陶+鼠尾草 / 深夜翡翠 / 香槟金深蓝 / 亚麻森林 / 柔和粉彩 / 纯灰阶）
  - `product_card_layout`, `hero_composition`, `typography_pairing` 各 4-5 个选项
  - 单选交互 · 选中态 accent 边框 · 确认后通过 `showSaveFilePicker` 或 Blob 下载写到 session 目录

### Changed — 已有 skill 整合

- **`lumicc-content`** 加 `--pick-style` 和 `--build --session <id>` 两步流程：先让用户选风格，再用选择产出 prompts
- **所有 10 个 active skill** 的 SKILL.md 顶部加 `## Persona` 段
- **`lumicc-content/scripts/prompts.py`** 增加 `style_modifier(choice)` helper + `STYLE_PROMPT_MOD` dict，将用户选择融入提示词

### Security

- 凭据零经过 LLM：所有 API key 通过 secret_form HTML 收集，CSP `connect-src 'none'` 在浏览器层堵死外联，写到 0600 文件
- `read_secret` 是唯一返回 cleartext 的函数，所有其他公开 API 只返回 fingerprint (`'sh***xxxx'`)
- `health_check` 默认不打印 value，只显示 fingerprint + missing 列表

### Engineering

- 11/11 skill smoke tests 通过 · 4 个新基础设施测试 (session/secret_form/picker/e2e) 全部通过
- 总测试数：15 个测试文件 · 70+ 断言

### Known limitations

- `picker.py` 在 Safari / Firefox 上走 Blob 下载兜底（用户手动 mv 文件）；Chromium 系直接 `showSaveFilePicker` 写到指定位置
- 视觉选择器目前只在 `lumicc-content` 接入；其他 skill 可按相同 pattern 引入

---

## [0.1.0] · 2026-05-13 · 首发 · 完整 11-Skill Bundle

### 🎉 Highlights

- **11 个 Skill 一次安装**：1 个 OS 编排器 (`lumicc`) + 1 个统一仪表盘 (`lumicc-dashboard`) + 9 个垂直能力（`launch / watch / expand / listing / voc / rescue / retention / seo / content`），跨 4 支柱叙事（**LAUNCH → ATTRACT → CONVERT → RETAIN**）。
- **统一 HTML 报告体系**：每个 skill 跑完都产出 `report.html`，4 个主题（midnight-emerald / linen-warm / slate-premium / dawn-coral）可在页面右上角实时切换，记忆用户偏好。
- **零依赖运行**：纯 Python 3 stdlib，无需 `pip install`。可选 `sqlite3 / playwright` 用于持久化和站点快照。
- **持久化业务记忆**：`~/.commerce-os/store.db` 三层结构（Events / Insights / SOUL），跨会话保留，与 LLM 原生 memory 完全独立。
- **离线可读**：所有报告 HTML 内联 CSS + 系统字体，没有网络字体，没有 CDN 依赖。

### Added — 核心架构

- **`lumicc`** — 主 skill / OS 编排器。`init_store.py` 创建/迁移 `~/.commerce-os/store.db`；`route.py` 根据用户意图路由到子 skill；`memory.py` 三层记忆 CRUD；`health_check.py` 依赖自检；`html_lib.py` 共享渲染库（4 主题 + 30+ 个 HTML helper）。
- **`lumicc-dashboard`** — 统一仪表盘。5 页（概览 / 店铺 / 活动 / 跑次 / 记忆）从 `store.db` 读取并渲染，与所有子 skill 共享主题。

### Added — 9 个垂直 Skill

| Pillar | Skill | 核心能力 | 关键 HTML 可视化 |
|---|---|---|---|
| LAUNCH | `lumicc-launch` | 30 天上店 SOP | 4 周 × 7 天 Gantt 网格 + 实时今日高亮 + 可行性 KPI |
| ATTRACT | `lumicc-seo` | SEO / GEO 优化 | 引用热力矩阵 + 关键词覆盖率 + GEO 维度对比 |
| ATTRACT | `lumicc-content` | 图片 / 视频提示词 | 多模型 prompt 卡片 + 引导切换 (Nano Banana / GPT Image 2) |
| ATTRACT | `lumicc-watch` | 竞品监控 | 多目标 diff timeline + 严重度排序的审计表 |
| CONVERT | `lumicc-listing` | 商详质检 (8 项) | 健康度 KPI + 严重度分组 tabs + Top-3 修复块 |
| CONVERT | `lumicc-expand` | 选品决策 | 拖拽分类板 (KEEP / WATCH / DROP) + 一键导出决策 |
| RETAIN | `lumicc-retention` | RFM + VIP + winback | RFM 5×5 矩阵 + 复购漏斗 + 邮件草稿 tabs |
| RETAIN | `lumicc-voc` | 评论聚类 | 主题分布水平条 + 与上次对比 + 代表性原文 |
| RESCUE | `lumicc-rescue` | 危机响应 (3 问诊断树) | 编号 playbook 卡片 + 48h evidence timeline + 24h watchdog |

### Added — 视觉系统

- **4 主题** 全部使用系统字体（无 Google Fonts / CDN 依赖）：
  - **midnight-emerald**（默认）— Bloomberg Terminal × Apothecary 风格，深色 + 翡翠绿 + 紫罗兰 + 琥珀点缀
  - **linen-warm** — Kinfolk Editorial 风格，亚麻奶白 + 深森林绿 + 赤陶
  - **slate-premium** — Rolex Boutique 风格，深海军蓝 + 香槟金（Didot / Bodoni 衬线）
  - **dawn-coral** — Aesop Storefront 风格，暖珊瑚 + 鼠尾草绿（建筑感而非幼稚）
- **主题切换器** — 报告右上角 4 个色块按钮，点击实时切换；选择持久化到 `localStorage`（key: `lumi-theme`）。
- **大数字字体** — KPI 卡片数字统一使用 SF Pro Display / Segoe UI Variable / system-ui + `tabular-nums` + `lining-nums`，跨平台显示一致。
- **页面入场动画** — `.main > *:nth-child(N)` 错位淡入（0.05s 步进），`prefers-reduced-motion` 友好。

### Added — 工程基建

- 全部 11 skill 各自有 `test_*.py` smoke 测试，11/11 通过。
- 双模运行：`coder` 模式（直接打开浏览器）+ `agent` 模式（`--quiet-stdout` 输出 JSON one-liner，配合 `--notify-channel` 推到飞书/Discord/Telegram/Slack/Email outbox）。
- 每个 skill 输出位于 `~/.commerce-os/runs/<run_id>/`，含 `report.md` + `report.html` + `result.json`。
- `bin/lumicc` Bash launcher — 提供 `lumicc <sub> [args]` 一键路由，与原始 `python3 .../run.py` 等价。
- `install.sh` — 一键复制 skills 到 `~/.claude/skills/`，让 Claude Code / Codex / OpenClaw 等 agent 自动发现。

### Security

- 所有用户输入（产品标题、URL、评论文本、错误信息）经 `H.esc()` HTML 转义；体检过 code-reviewer 自检。
- 无网络依赖：CSS 内联、字体走系统、不加载远端资源。
- 报告 HTML 离线可读，可直接拷给业务方查看。

### Known limitations

- `lumicc-watch` 的快照基于 HTML fetch，依赖目标站点对静态请求友好；JS-only SPA 仅能抓到首屏 HTML 结构。
- `lumicc-content` 当前只生成提示词，图片/视频生成需用户配置自己的 API key（Nano Banana / GPT Image 2 / Sora 等）。
- `lumicc-retention` 的 RFM 当前用简单 quintile 切分；500+ 客户时建议做加权 LTV 预测（后续版本计划）。
