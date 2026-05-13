# Lumicc Architecture

> 跨境电商运营 OS · 架构与设计原则 · v0.1.0

## 设计原则

1. **本地优先** — 所有状态在 `~/.commerce-os/`，无云、无服务端、无遥测。
2. **零依赖** — 纯 Python 3 stdlib。任何 `pip install` 都是可选 adapter。
3. **HTML 优先** — 给业务方看的不是 markdown，是渲染好的 HTML 报告。
4. **agent-agnostic** — Claude / Codex / OpenClaw / Cursor / Gemini 都能用。
5. **OS 编排，不做原子工具** — 不重复造选品 / 上架 / 投放这类单点工具，把它们串成有状态的工作流。

---

## 三层架构

```
┌────────────────────────────────────────────────────────────┐
│  Layer 3 · User Interface                                  │
│  ────────────────────────                                  │
│  · Claude Code / Codex / Cursor (agent 调用)               │
│  · ./bin/lumicc (CLI launcher)                             │
│  · ~/.commerce-os/dashboard/ (静态 HTML 仪表盘)            │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  Layer 2 · Skill Orchestration                             │
│  ─────────────────────────────                             │
│  ┌──────────────┐                                          │
│  │   lumicc     │  ← 主 skill，路由器                       │
│  │  (router)    │     route.py 根据 user_intent 决策         │
│  └──────┬───────┘                                          │
│         │                                                   │
│  ┌──────┴────────┬─────────┬─────────┬─────────┐           │
│  ▼               ▼         ▼         ▼         ▼           │
│ launch  watch  expand  listing  voc  rescue  retention ... │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  Layer 1 · Data & Memory                                   │
│  ────────────────────────                                  │
│  ~/.commerce-os/store.db        (SQLite — 业务事实)          │
│  ~/.commerce-os/memory/*.md     (Layer 1 events)            │
│  ~/.commerce-os/memory/         (Layer 2 insights)           │
│  ~/.commerce-os/SOUL.md         (Layer 3 user rules)         │
│  ~/.commerce-os/runs/<id>/      (per-run artifacts)          │
└────────────────────────────────────────────────────────────┘
```

---

## 数据模型

### store.db (SQLite)

```sql
stores       (id, name, platform, url, currency, target_market, stage, niche, ...)
products     (id, store_id, sku, title, price_usd, cost_usd, status, data_json, ...)
campaigns    (id, store_id, type, status, budget_usd, results_json, ...)
events       (id, store_id, ts, category, content)             -- Layer 1
insights     (id, category, content, confidence, verified_count, ...)  -- Layer 2
runs         (run_id, skill, store_id, status, result_path, ...)
preferences  (key, value)
```

每个 skill 跑完都写入：
- `runs` 表一行（运行元数据）
- `events` 表一行（业务事件）
- `~/.commerce-os/runs/<run_id>/` 目录（report.html + report.md + result.json）

### 三层记忆

| 层 | 存储 | 写入方 | 用途 |
|---|---|---|---|
| **Layer 1 · Events** | `store.db events` + `memory/<date>.md` | 每个 skill 自动 | 完整决策流水账 |
| **Layer 2 · Insights** | `store.db insights` + `memory/insights.md` | `memory.py` 当同模式被 verify ≥ 2 次时自动沉淀 | 高置信度业务洞察 |
| **Layer 3 · SOUL** | `~/.commerce-os/SOUL.md` | **只由用户手编辑**，系统永远不写 | 运营铁律（如"目标毛利 50%"） |

设计意图：让用户手感受到 Layer 3 是不可侵犯的"操盘者意志"，其他都是系统观察。

---

## Skill 编排路由

`lumicc/scripts/route.py` 是核心决策树。基于：

1. **店铺阶段** — `0-to-1 / 1-to-10 / 10-to-100 / 100+`
2. **用户意图关键词** — 中英双语匹配
3. **最近事件** — 过去 48h 是否有 warning / decision

输出：

```json
{
  "decision": { "matched_subskill": "lumicc-launch", "confidence": 0.86, "reason": "..." },
  "store_memory_snapshot": { "stage": "0-to-1", "active_campaigns": [] },
  "next_action": { "type": "execute_subskill", "payload": {...} }
}
```

如果 confidence < 0.5，要求用户澄清而非乱猜。

---

## HTML 渲染体系

所有 skill 报告共用 `skills/lumicc/scripts/html_lib.py`：

### Helpers

- `H.page(title, body, theme=None, brand_subtitle, right_meta)` — 整页 shell（含主题切换器）
- `H.page_head(title, subtitle)` — h1 + 副标
- `H.section(title, body, action_link?)` — 二级 section
- `H.kpi_strip([(value, label, hint?, color?), ...])` — 4 卡 KPI
- `H.card(title, tag, tag_color, meta, body, actions)` — 单卡
- `H.card_grid(cards, min_width)` — 响应式卡片网格
- `H.table(headers, rows, align?)` — 数据表
- `H.tabs([(key, label, content), ...])` — 选项卡（含切换 JS）
- `H.badge(text, color)` / `H.empty_state(text, hint)` / `H.progress_bar(pct)` / 等

### 4 主题系统

所有 4 主题都内嵌到每个页面，通过 `[data-theme="..."]` CSS 作用域隔离：

```css
[data-theme="midnight-emerald"] { --bg: #0a0d12; --accent: #34d399; ... }
[data-theme="linen-warm"]       { --bg: #f6f1e7; --accent: #2d5a3d; ... }
[data-theme="slate-premium"]    { --bg: #0b1220; --accent: #d4af37; ... }
[data-theme="dawn-coral"]       { --bg: #f9efe6; --accent: #b85c38; ... }
```

切换器 JS（`<10 行`）切换 `<html data-theme>` 属性并存 `localStorage`。

### 主题来源优先级

1. 报告 URL hash / 内嵌切换器（最高 — 用户即时选择）
2. `LUMICC_THEME` 环境变量
3. `~/.commerce-os/design.md` 中 `## Theme: <name>`
4. 默认 `midnight-emerald`

---

## 双模运行

每个 skill 的 `run.py` 支持：

### `coder` 模式（默认）

```bash
python3 run.py --store-id <id> --whatever
```

- 打印人类可读的进度
- 跑完用 `webbrowser.open()` 自动打开 `report.html`
- 适合手动调试

### `agent` 模式

```bash
python3 run.py --store-id <id> --quiet-stdout --notify-channel feishu --notify-target user:cheche
```

- stdout 只输出一行 JSON（agent 间结构化交换）
- 跑完往 `~/.commerce-os/outbox/<uuid>.json` 写一份通知（飞书/Discord/Telegram/Slack/Email）
- 适合 OpenClaw / Hermes 这类 agent runner 调用

---

## 测试策略

每个 skill 都有一个 `test_*.py` smoke test：

- 用 `tempfile` 建临时 `~/.commerce-os/`
- 跑完整 run.py 一次
- 断言：HTML 文件存在 + 包含关键字段 + JSON schema 合法 + 数据库行写入

不追求 80% line coverage（这是 stdlib + I/O，coverage 工具帮助有限），追求 **"跑完一次完整闭环不崩"**。

```bash
./bin/lumicc test                  # 跑全部 11 skill 的 smoke test
```

---

## 已知设计取舍

1. **没有 ORM** — 直接 `sqlite3` + `db.row_factory = sqlite3.Row`。轻、可调试、零依赖。
2. **没有模板引擎** — html_lib 用 f-string 拼接。可读、可单步调试、无 build step。
3. **没有 async** — 大多数操作是文件读 / 一次 HTTP fetch / SQLite，同步够用。
4. **没有 i18n 框架** — 中文 hardcode 在 UI 字符串里。需要英文版时手动 fork。
5. **没有用户系统** — 单用户 / 单机器假设。多店铺通过 `store_id` 区分，同一用户操盘。
