# Lumicc — 跨境电商运营 OS

> **一个 Skill bundle，把跨境独立站从「选品 → 上架 → 引流 → 转化 → 留存 → 救火」串成完整工作流。**

面向 **跨境独立站卖家 / 一人公司 / 出海小品牌团队** 的「数字运营团队」。把 ChatGPT / Claude 上零散的"帮我写文案"、"分析评论"、"看竞品"、"做选品"工作，串成一个有状态、可复盘、跨会话记忆的本地化 OS。

[![Version](https://img.shields.io/badge/version-1.0.0-brightgreen)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Skills](https://img.shields.io/badge/skills-12-green)](skills/)
[![Tests](https://img.shields.io/badge/tests-25%2F25_passing-brightgreen)](#运行测试)
[![Security](https://img.shields.io/badge/credentials-never_in_LLM-red)](#凭据安全)

---

## 为什么是 Lumicc

**跨境运营者每天都在多工具间来回切换。**

- 早上看竞品价格 → 打开 SimilarWeb / Shopify 后台 / 小红书 ❌ 切换 5 个 tab
- 下午调商详 → 复制贴到 GPT，问"我这个 SEO 怎么样？" ❌ 上下文丢失
- 晚上看销量降了 → 不知道是平台问题还是自己改坏了 ❌ 没有事件回溯
- 周末复盘 → 上周哪天做了什么决定？回忆不起来 ❌ 没有记忆沉淀

**Lumicc 把跨境运营者的协作能力，封装成一个 Skill bundle**。

- ✅ **有状态** — `~/.commerce-os/` 本地数据库 + 三层记忆（Events / Insights / SOUL），跨会话保留。
- ✅ **可视化** — 每个 skill 跑完都产出 HTML 报告，业务向、可下载、可分享，支持 4 种视觉主题。
- ✅ **零依赖** — 纯 Python 3 stdlib。无 `pip install`、无 Docker、无服务端。
- ✅ **离线可读** — 所有报告内联 CSS + 系统字体，断网也能看。
- ✅ **多 Agent 兼容** — Claude Code / Codex / OpenClaw / Hermes / Cursor / Gemini CLI 都可调用。

---

## 6 大差异化壁垒

| # | 壁垒 | 说明 |
|---|---|---|
| 1 | **OS 编排，不做原子工具** | 不重复造选品 / 上架 / 投放等原子工具，做的是**串起来的工作流**，按店铺阶段（0→1 / 1→10 / 10→100）路由。 |
| 2 | **6 个专家团队人设系统** | CMO 总指挥 + 建站团队 + 数据分析师 + 市场情报员 + 品牌内容师 + 危机响应官。跨 skill 切换时显式 announce 团队交棒，给"换了一支专家接手"的真实感。详见 [personas.md](skills/lumicc/references/personas.md)。 |
| 3 | **凭据零暴露给 LLM** 🔒 | API key / token 通过本地 HTML 表单收集（CSP 锁死外联），永远不进入对话历史。其他 skill 厂商基本没人做这层。详见下文「凭据安全」。 |
| 4 | **持久化业务记忆** | 三层 memory（事件 / 洞察 / 用户铁律）+ 跨 skill 会话状态，跨会话不丢。和 LLM 原生 memory **完全独立**。 |
| 5 | **HTML 优先的可视化 + 视觉选择器** | 4 主题实时切换。设计风格 / 配色 / 排版需要"用眼睛看"的决策走本地 HTML 选择器，不靠对话猜。 |
| 6 | **本地优先 · 零依赖** | 数据全部在 `~/.commerce-os/`，纯 Python stdlib 无 `pip install`。无遥测、无云、无 vendor lock-in。 |

---

## 11 个 Skill · 按 4 支柱叙事

```
                   ┌──────────────────────────────┐
                   │  lumicc (OS · 路由 · 记忆)    │
                   └───────────────┬──────────────┘
                                   │
        ┌──────────────┬──────────┴──────────┬──────────────────┐
        ▼              ▼                     ▼                  ▼
    🚀 LAUNCH      📢 ATTRACT             💰 CONVERT          ❤️ RETAIN
        │              │                     │                  │
  lumicc-launch   lumicc-seo            lumicc-listing    lumicc-retention
   (30 天 SOP)    lumicc-content        lumicc-expand     lumicc-voc
                  lumicc-watch
                                                         🚨 RESCUE
                                                         lumicc-rescue
                                                ┌────────────────┐
                                                │ lumicc-dashboard│
                                                │  (统一仪表盘)    │
                                                └────────────────┘
```

| Skill | 何时调用 | 典型产出 |
|---|---|---|
| **`lumicc`** | 任何模糊意图 → 自动路由 | 决策 + 下一步建议 |
| **`lumicc-launch`** | 新店 0→1 | 30 天 Gantt 时间表 + 每日任务清单 |
| **`lumicc-watch`** | 日常监控 | 竞品 diff timeline + 严重度排序 |
| **`lumicc-seo`** | 内容曝光低 | SEO/GEO 引用热力图 + 关键词覆盖 |
| **`lumicc-content`** | 缺图片/视频 | 多模型 prompt 卡片（Nano Banana / GPT Image 2） |
| **`lumicc-listing`** | 销量低 / 体检 | 8 项评分 + Top-3 修复 + 严重度 tabs |
| **`lumicc-expand`** | "找下一个爆品" | 拖拽决策板 (KEEP/WATCH/DROP) |
| **`lumicc-retention`** | 客户分群 / 复购 | RFM 5×5 矩阵 + VIP 名单 + winback 邮件 |
| **`lumicc-voc`** | 评论 / 工单分析 | 10 主题聚类 + 与上次对比 |
| **`lumicc-rescue`** | 销量骤降 / 账号警告 | 3 问诊断树 + playbook + 24h watchdog |
| **`lumicc-dashboard`** | 看整体状况 | 5 页静态站点（概览/店铺/活动/跑次/记忆） |

---

## 快速开始

### 前置依赖

```bash
# Python 3.10+ (macOS / Linux 自带)
python3 --version    # 应输出 Python 3.10.x 或更高

# 可选 — sqlite3 (macOS / Linux 自带)
sqlite3 --version
```

> Lumicc 是 **纯 Python stdlib**，不需要 `pip install` 任何包。

### 5 种安装方式

Lumicc 是 agent-agnostic 的 skill bundle — 任意支持 SKILL.md 标准的 runtime 都可安装。

**1. Claude Code 用户** — 一键 git clone + 本地安装：

```bash
git clone https://github.com/<your-user>/lumicc.git ~/lumicc
cd ~/lumicc && ./install.sh
```

安装脚本会自动检测当前 agent runtime（默认 `~/.claude/skills/`），跑完后让 Claude Code 自动发现 11 个 skill 的 SKILL.md。

**2. OpenClaw 用户** — 一行命令直接装：

```bash
openclaw skills install github:<your-user>/lumicc
```

OpenClaw 读 `install.json`，把 11 个 skill 装到 `~/.openclaw/skills/` 或 workspace。

**3. Hermes 用户** — 同样一行：

```bash
hermes skills install github:<your-user>/lumicc
```

Hermes 把 skill 装到 `~/.hermes/skills/`，cron 调度自动接管 `lumicc-watch / lumicc-retention / lumicc-seo` 的定时任务。

**4. 飞书 / 微信 / Discord 机器人用户** — 任何接了 Hermes/OpenClaw 的机器人都能装：

```text
@bot install https://github.com/<your-user>/lumicc          # 飞书
!install lumicc https://github.com/<your-user>/lumicc       # Discord
```

机器人在后端跑 `hermes skills install` 或 `openclaw skills install`，然后把后续 Lumicc 通知（销量警报、竞品 diff、RFM 月报）推到这个 IM 频道。

**5. 手动 / 任意目标** — 直接拷贝：

```bash
cp -r skills/* ~/<你的-agent>/skills/
# 或用 launcher 指定 target：
./bin/lumicc install --target manual --dest ~/my-agent/skills
```

把 11 个 skill 目录原样拷过去即可；只要 runtime 读 `SKILL.md` frontmatter，Lumicc 就能跑。

> 安装完成后跑 `./bin/lumicc test` 验证（15+ 测试应该通过）。

### 初始化

第一次使用：

```bash
python3 ~/.claude/skills/lumicc/scripts/init_store.py
```

会引导你回答几个问题，创建 `~/.commerce-os/store.db` 和店铺档案。

或者用 launcher：

```bash
./bin/lumicc init
```

---

## 使用方式

### 方式 1 · 通过 Agent (推荐)

让 Claude Code / Codex / 任何兼容 agent 自动调用：

```
你：我新开一家独立站做宠物用品，US 市场，预算 $500，每周能投 10 小时，
    给我一个 30 天上店计划。

agent → lumicc (主 skill) → 路由到 lumicc-launch → 生成 30 天 Gantt + report.html
```

```
你：销量从昨天开始降了 60%，没改过任何东西。

agent → lumicc → 路由到 lumicc-rescue → 3 问诊断 → playbook
```

### 方式 2 · 直接调用 launcher

```bash
./bin/lumicc launch --budget 500 --hours 10
./bin/lumicc watch --store-id <id>
./bin/lumicc retention --csv orders.csv --mode all
./bin/lumicc voc --input reviews.json
./bin/lumicc dashboard            # 渲染整站仪表盘
```

### 方式 3 · 直接调用 Python 脚本

```bash
python3 ~/.claude/skills/lumicc-launch/scripts/run.py --store-id my-store --budget 500
python3 ~/.claude/skills/lumicc-retention/scripts/run.py --csv orders.csv --mode all
```

每次跑完会输出：

```
~/.commerce-os/runs/<run_id>/
  ├─ report.html      ← 浏览器打开看
  ├─ report.md        ← 给 LLM 看
  └─ result.json      ← agent 间结构化交换
```

---

## 对话引导 · 团队切换

每个 skill 属于一个**专家团队**（CMO 总指挥 / 建站团队 / 数据分析师 / 市场情报员 / 品牌内容师 / 危机响应官）。当 agent 从一个团队任务切到另一个，会主动 announce 团队交棒——给用户"换了一支专家接手"的真实感，而不是同一个 AI 在不同 prompt 下漂移。

举例对话：

```
👤 用户：销量从昨天开始降了 60%，没改过任何东西。

🚨 危机响应官：我是你的危机响应官。先稳住，我们一步步来。
   我需要快速搞清楚 3 件事：
   1. 平台有没有给你正式通知？
   2. 你最近 48 小时内改过什么？
   3. 影响范围是单 SKU 还是全店？

👤 用户：[回答 3 个问题]

🚨 危机响应官：[诊断 + playbook，生成 report.html]
   给完 playbook 后，24h 后会自动复查 ——
   到时候如果还没恢复，我把你转给 **市场情报员**，看是不是行业大盘问题。

[24 小时后]

🔭 市场情报员：我是你的市场情报员。接手之前危机响应官的 case。
   我刚扫了 5 个竞品，发现 ......
```

人设完整定义见 [`personas.md`](skills/lumicc/references/personas.md)。

## 视觉选择器

涉及**眼睛要看才能决定**的场景（landing 风格 / 配色 / 商品卡布局 / 首屏构图 / 字体搭配），agent 会开本地 HTML 选择器：

```bash
# 品牌内容师团队:
"你的 landing 想走什么调性？我开个本地选择器给你看 6 个方向。"

→ python3 .../picker.py --kind landing_style --session <id> --open

→ 浏览器打开：
  ┌─────────────────────────────────────┐
  │ Landing 风格选择 (单选)              │
  │ ┌─────┐ ┌─────┐ ┌─────┐             │
  │ │Aesop│ │Kinfk│ │Apple│             │
  │ └─────┘ └─────┘ └─────┘             │
  │ ┌─────┐ ┌─────┐ ┌─────┐             │
  │ │Bruta│ │Y2K  │ │Rolex│             │
  │ └─────┘ └─────┘ └─────┘             │
  │           [ 确认选择 ]                │
  └─────────────────────────────────────┘

→ 选择写到 ~/.commerce-os/sessions/<id>/choice-landing_style.json
→ agent 下一轮读，继续问下一个问题
```

5 类选择器内置：

| Kind | 选项 | 用途 |
|---|---|---|
| `landing_style` | Aesop / Kinfolk / Apple / Brutalist / Y2K / Rolex（6） | 落地页整体调性 |
| `color_palette` | 赤陶+鼠尾草 / 深夜翡翠 / 香槟金深蓝 / 亚麻森林 / 柔和粉彩 / 纯灰阶（6） | 品牌主色 |
| `product_card_layout` | 极简 / 角标 / 左图右文 / 杂志大图（4） | 商品卡布局 |
| `hero_composition` | 居中 / 左字右图 / 通屏图叠加 / 视频背景 / 杂志非对称（5） | 首屏构图 |
| `typography_pairing` | 衬线×衬线 / 衬线×无衬线 / 无衬线×无衬线 / 展示×无衬线（4） | 字体搭配 |

---

## 视觉主题

每个 HTML 报告右上角有 4 个色块按钮，点击即时切换主题；选择持久化到 `localStorage`。

| 主题 | 风格定位 | 场景 |
|---|---|---|
| **midnight-emerald** | Bloomberg Terminal × Apothecary | 深色 · 默认 · 编辑器友好 |
| **linen-warm** | Kinfolk Editorial | 暖白 · 给业务方看 |
| **slate-premium** | Rolex Boutique × Manhattan Penthouse | 深蓝 + 香槟金 · 高端品牌 |
| **dawn-coral** | Aesop Storefront | 暖珊瑚 · 成熟温暖（不幼稚） |

全部使用系统字体（SF Pro / Segoe UI / Helvetica Neue / Songti / PingFang），不加载任何网络字体，断网可读。

**永久设置某主题：**

编辑 `~/.commerce-os/design.md`：

```markdown
## Theme: linen-warm
```

或者用环境变量：

```bash
export LUMICC_THEME=slate-premium
```

---

## 凭据安全

> **设计原则：API key 永远不经过 LLM 对话。**

跨境运营涉及大量第三方 API（Shopify Admin Token / Amazon SP-API / TikTok Shop / Klaviyo / OpenAI / Anthropic / 图像生成模型……）。这些凭据如果发到对话里，会进入 LLM 的对话日志、可能被训练、可能被记录到 cloud。

Lumicc 的解法：

```
1. agent (品牌内容师团队人设):
   "我需要你的 Anthropic API Key。
    出于安全考虑不要发到对话里——我给你开个本地表单，凭据只留在本机。"
   ↓ 执行 python3 .../secret_form.py --generate ANTHROPIC_API_KEY --open

2. 浏览器自动打开本地 HTML 表单：
   ┌──────────────────────────────────────────┐
   │ 🔒 Anthropic API Key                     │
   │ ⚠ 凭据从不进入 LLM 对话历史              │
   │ ┌──────────────────────────────────────┐ │
   │ │ sk-ant-xxxxxxxxxx               (隐藏)│ │
   │ └──────────────────────────────────────┘ │
   │ ☑️ 我确认凭据仅保存到本机                 │
   │ [ 保存到本地 ]                            │
   └──────────────────────────────────────────┘
   (HTML <meta CSP> 锁死外联，浏览器层禁止 fetch 出去)

3. 点保存后：
   - Chromium: showSaveFilePicker 直接写到 ~/.commerce-os/secrets/ANTHROPIC_API_KEY.json
   - Safari/Firefox: Blob 下载 + 一键复制 mv 命令

4. 文件权限：~/.commerce-os/secrets/ = 0700，单文件 = 0600
   只有当前 OS 用户能读

5. skill 调用 API 时，子进程 read_secret() 读 → 直接传给 HTTPS 请求
   →  主对话进程从不接触 cleartext value
```

**3 个安全特性：**
- ✅ **网络隔离** — `<meta CSP="connect-src 'none'; form-action 'none'">` 浏览器层禁止任何外联
- ✅ **文件权限** — `secrets/` 0700 + 单文件 0600，仅当前用户可读
- ✅ **LLM 隔离** — `read_secret()` 是唯一返回 cleartext 的函数，所有其他公开 API 只返回 `fingerprint`（前 2 后 4 字符遮罩）

**支持的凭据类型**（`secret_form.py --list` 查看）：

| Key | 用途 |
|---|---|
| `SHOPIFY_ADMIN_TOKEN` | Shopify Admin API |
| `AMAZON_SP_API_REFRESH` | Amazon SP-API refresh token |
| `TIKTOK_SHOP_API` | TikTok Shop API |
| `ETSY_API_KEY` | Etsy API |
| `KLAVIYO_API_KEY` | Klaviyo private API |
| `ANTHROPIC_API_KEY` | Anthropic（写文案 / RAG） |
| `OPENAI_API_KEY` | OpenAI |
| `NANO_BANANA_API_KEY` | Nano Banana 图像生成（推荐） |
| `GPT_IMAGE_2_API_KEY` | GPT Image 2（中文图建议） |

健康检查命令：

```bash
python3 ~/.claude/skills/lumicc/scripts/secret_form.py --list
# 输出：每个 key 的状态 + fingerprint（如 'sk***bcde'），永不打印 value 全文
```

---

## 数据 · 隐私 · 离线

```
~/.commerce-os/
├── store.db              # SQLite — stores / products / campaigns / events / insights / runs
├── runs/<run_id>/        # 每次 skill 跑完的产出（HTML + MD + JSON）
├── memory/<date>.md      # Layer 1 — 每日决策事件流
├── memory/insights.md    # Layer 2 — 自动沉淀的高置信度模式
├── SOUL.md               # Layer 3 — 用户手编辑的运营铁律
├── outbox/               # agent 模式下待发送的飞书/Discord 通知队列
└── design.md             # 主题 + token 覆盖（可选）
```

- **全部本地** — 无云、无服务端、无遥测。
- **无 LLM 依赖** — 每个 skill 是纯 Python，可单独跑。LLM 只用作触发器和写文案。
- **可携带** — 整个目录拷走就是完整运营状态。

---

## Agent 兼容

| Agent | 兼容方式 |
|---|---|
| **Claude Code** | `~/.claude/skills/` 自动发现 SKILL.md |
| **OpenClaw / Hermes** | SKILL.md frontmatter 的 `metadata.openclaw` / `metadata.hermes` |
| **Codex / OpenAI Agents** | 调用 `python3 run.py` + 读取 `result.json` |
| **Cursor / Continue** | 把 SKILL.md 作为系统 prompt 注入 |
| **Gemini CLI** | 当 shell tool 调用，传 `--quiet-stdout` 拿 JSON |

每个 skill 的 SKILL.md 顶部 frontmatter 都遵循 agentskills.io 标准。

---

## 项目结构

```
lumicc/
├── README.md              # 本文件
├── CHANGELOG.md           # 版本变更记录
├── LICENSE                # MIT
├── VERSION                # 0.1.0
├── install.sh             # 一键安装脚本
├── bin/
│   └── lumicc             # CLI launcher
├── docs/
│   ├── ARCHITECTURE.md    # 架构说明
│   └── SKILLS.md          # 每个 skill 详解
└── skills/
    ├── lumicc/            # 主 OS 编排器 + html_lib
    ├── lumicc-dashboard/  # 统一仪表盘
    ├── lumicc-launch/     # LAUNCH 支柱
    ├── lumicc-seo/        # ATTRACT
    ├── lumicc-content/    # ATTRACT
    ├── lumicc-watch/      # ATTRACT
    ├── lumicc-listing/    # CONVERT
    ├── lumicc-expand/     # CONVERT
    ├── lumicc-retention/  # RETAIN
    ├── lumicc-voc/        # RETAIN
    └── lumicc-rescue/     # RESCUE
```

---

## 运行测试

```bash
# 在仓库根目录
for d in skills/lumicc skills/lumicc-*; do
  test_file=$(ls "$d/scripts"/test_*.py 2>/dev/null | head -1)
  [ -n "$test_file" ] && python3 "$test_file" >/dev/null 2>&1 \
    && echo "✓ $(basename $d)" \
    || echo "✗ $(basename $d)"
done
```

预期输出全部 11/11 通过。

---

## 卸载

```bash
# 移除 skill 文件
rm -rf ~/.claude/skills/lumicc ~/.claude/skills/lumicc-*

# (可选) 删除业务数据 — 这会删掉所有店铺记忆
rm -rf ~/.commerce-os
```

---

## 贡献 / 反馈

- **Issues** — 报 bug、提需求
- **Discussions** — 想法 / 用法 / 案例
- **PRs** — 欢迎，请先开 issue 对齐

---

## License

MIT — see [LICENSE](LICENSE).

---

**v1.0.0** · 2026-05-14 · 12 skills · 25/25 tests passing · 4 themes · 6 personas · 9 secret keys · 6 picker kinds · 4 platform adapters (CSV / Plausible / Shopify / Amazon SP) · 真实图像生成 (evolink Nano Banana / GPT Image 2 / Sora 2) · Cloudflare 加密分享 · Anti-Slop 6 gate · 5 install channels (Claude Code / OpenClaw / Hermes / IM bot / manual) · 0 network dependencies
