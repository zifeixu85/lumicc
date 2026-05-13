# Lumicc Skills · 详细使用手册

> 11 个 Skill 的输入 / 输出 / 触发方式 · v0.1.0

按 4 支柱叙事组织 · LAUNCH → ATTRACT → CONVERT → RETAIN，加横向的 RESCUE / DASHBOARD。

---

## 编排层

### `lumicc` (主 OS · 路由 · 记忆)

**何时触发**

任何跨境电商相关的模糊意图：
- "我想开独立站做 XX"
- "竞品最近什么动作"
- "评论里大家都在抱怨什么"
- "销量降了帮我看看"

`lumicc` 不直接做事，它做 **决策**：根据店铺阶段 + 用户意图 + 最近事件，路由到正确的子 skill。

**关键脚本**

| 脚本 | 用途 |
|---|---|
| `init_store.py` | 创建 / 迁移 `~/.commerce-os/store.db` |
| `route.py` | 决策树 → 选 sub-skill |
| `memory.py` | 三层记忆 CRUD |
| `health_check.py` | 依赖自检 |
| `html_lib.py` | 共享 HTML 渲染库（4 主题 + helpers） |

**输入 / 输出**

```json
// in
{ "user_intent": "我新开店做宠物用品", "store_url": null, "stage_hint": "auto" }

// out
{
  "decision": { "matched_subskill": "lumicc-launch", "confidence": 0.86 },
  "next_action": { "type": "execute_subskill", "payload": { ... } }
}
```

---

### `lumicc-dashboard` (统一仪表盘)

**何时触发**

"我现在整体什么状况？" — 看全局看板。

**输出**

`~/.commerce-os/dashboard/` 下 5 页静态 HTML：

| 页面 | 内容 |
|---|---|
| `index.html` | 第一家店概览 · 4 KPI · 运行中的活动 · 最近事件 · 最近 runs |
| `stores.html` | 所有店铺 · 每店商品表 + 事件流 |
| `campaigns.html` | 所有活动 · 含 30 天 cold-start 进度条 |
| `runs.html` | Skill 运行历史 · 含产出物 |
| `memory.html` | 三层记忆 tab · Events / Daily / Insights / SOUL |

**使用**

```bash
./bin/lumicc dashboard
# 自动打开浏览器到 ~/.commerce-os/dashboard/index.html
```

---

## 🚀 LAUNCH · 新店 0→1

### `lumicc-launch` (30 天上店 SOP)

**何时触发**

新店没开张，或第一周销量为 0。

**输入**

```bash
python3 run.py --budget 500 --hours-per-week 10 --niche "pet accessories" --target-market us
```

**输出**

`~/.commerce-os/runs/<run_id>/report.html` 包含：
- 4 卡 KPI：投入档位 (Lean/Standard/Premium) · 首单概率 · 预算 · 时间投入
- 4 周里程碑卡片
- 30 天 Gantt 网格（4 周 × 7 天）· 今日高亮 + 金色 "TODAY" 徽章 · 过去半透明
- 可行性评估（风险列表 + 建议调整）

**Plus**: `plan.json` 含完整 schedule，供其他 skill 消费。

---

## 📢 ATTRACT · 引流

### `lumicc-seo` (SEO / GEO 优化)

**何时触发**

内容写出来但没人看 · 想做 LLM 引用优化。

**输出**

- 关键词覆盖率表
- GEO 维度对比（不同地区的搜索意图差异）
- LLM 引用热力矩阵（哪些 query 上 ChatGPT/Claude 会引用你的站点）
- 改写建议

### `lumicc-content` (图片/视频提示词)

**何时触发**

"给我生成一张产品图 / 一段 TikTok 视频脚本"

**当前版本**：生成提示词（PROMPT），不直接调图像 API。

**输出**

- 多模型 prompt 卡片，默认 Nano Banana（推荐），中文产品建议 GPT Image 2
- 视频 prompt 默认关闭（用户可在 UI 里点开 + 配置 API key）
- 复制按钮、可直接拷到 ChatGPT / Sora / Runway

**未来版本**：直接调 API 生成图片 + 在 HTML 里渲染下载链接。

### `lumicc-watch` (竞品监控)

**何时触发**

每天 9:00 cron · 或随时手动 `lumicc watch`。

**做什么**

对配置的目标 URL：

1. fetch HTML + sitemap.xml
2. 解析 hero / banner / 产品列表 / SEO meta
3. 与上次快照 diff，按 weighted category 分类
4. 输出严重度排序的变化清单

**输出**

- KPI: 监控目标数 · 总变化数 · high · medium
- 类别分布表
- 每个目标的 tab（外链 · 快照时间 · 变化卡片网格 · 含 before/after diff）
- 全平台扁平审计日志（高严重度优先）

---

## 💰 CONVERT · 转化

### `lumicc-listing` (商详质检)

**何时触发**

"我这个商详评分如何？" · 销量低想体检 · 上架前最后一关。

**输入**

从 `store.db products` 读取（或 `--product-id` 指定单个）。

**做什么 — 8 项检查**

| Check | 权重 | 关注 |
|---|---|---|
| image_count | 20% | ≥ 6 张 · hero ≥ 1000px |
| title_seo | 15% | 主关键词在 80 字符内 |
| bullets | 15% | 5 条 · 每条 ≤ 150 字 |
| description | 10% | 结构化 / 不空泛 |
| price_ladder | 10% | compare_at_price 设置 |
| reviews | 10% | count + avg + 最近 |
| scarcity | 10% | 库存 / 时限信号 |
| mobile | 10% | LCP < 2.5s |

**输出**

- KPI: 平均健康度 · 🔴 重病数 · 🟡 待改善 · 🟢 健康
- 严重度分组 tabs · 每个商品卡片含分数 · 8 项检查表 · Top-3 修复块
- 底部 summary table（每项 check 跨产品的平均分 + 修复模板）

### `lumicc-expand` (选品决策板)

**何时触发**

"找下一个爆品" · "这批 SKU 哪些留哪些下"

**做什么**

基于过去 60 天的 ROI + 复购率 + 退货率打分。

**输出**

3 列拖拽板（KEEP / WATCH / DROP），可以：
- 鼠标拖拽调整分类
- 一键导出 `decisions.json`（喂给供应链）
- HTML 里直接看每个 SKU 的 ROI / 复购 / 退货

---

## ❤️ RETAIN · 留存

### `lumicc-retention` (RFM + VIP + winback)

**何时触发**

"分析客户" · "找出 VIP" · "发挽回邮件"

**输入**

`orders.csv` (Shopify export 格式 · 含 customer_id / order_date / total)

**Mode 选择**

| Mode | 做什么 |
|---|---|
| `--mode rfm` | RFM 5×5 矩阵 + 6 分群 |
| `--mode vip` | 找 Champions 并生成 VIP 邀请草稿 |
| `--mode winback` | At Risk + Lost 客户的 winback 邮件草稿 |
| `--mode subscription` | 找适合订阅化的 SKU |
| `--mode repeat` | 首购→复购漏斗 |
| `--mode all` | 全部跑一遍 (default) |

**输出**

- RFM 5×5 矩阵（颜色深浅 = 平均 LTV，悬停看详情）
- 6 分群 KPI 卡 (Champions / Loyal / New / At Risk / Lost / Promising)
- 复购漏斗
- Top 客户表
- 各 mode 的 markdown 草稿（winback / VIP / subscription）

### `lumicc-voc` (评论聚类)

**何时触发**

"用户都在抱怨什么" · 工单堆积 · 周/月回顾。

**输入**

`reviews.json`（含 `text` / `sku` / `ts`）或 stdin 粘贴模式。

**做什么 — 10 主题聚类**

包装破损 / 尺寸不符 / 质量 / 物流 / 货不对板 / 说明不清 / 兼容性 / 气味 / 售后 / 性价比

**输出**

- KPI: 总反馈 · 命中主题 · 未匹配 · 最大集群
- 主题分布水平条（与上次对比 · ↓ 12 绿色 / ↑ 5 红色）
- Top-6 主题 tab · 每个含原文样本 + 建议修复模板
- 与上次对比表（NEW / 改善 / 恶化 / 持平）

---

## 🚨 RESCUE · 救火

### `lumicc-rescue` (危机响应)

**何时触发**

- 销量骤降
- 账号收到警告
- 广告被拒
- Listing 被压制

**做什么 — 3 问决策树**

8 个分支：

| ID | Hypothesis | 解决时间 |
|---|---|---|
| A | Account warning / suspension | 2-7 天 |
| B | Ad disapproval | 1-3 天 |
| C | Listing suppression | 1-14 天 |
| D | Self-inflicted (近 48h 改坏了) | 数小时 |
| E | Price war | 数天 |
| F | Ecosystem event (平台问题) | 1-7 天 |
| G | Algorithm shift | 7-30 天 |
| H | Other platform event | varies |

**输出**

- KPI: 严重级别 · 置信度 · 预估解决 · 备选诊断数
- 编号 playbook 卡片（每步独立一卡，大号 accent 编号）
- 备选诊断 grid
- 48h evidence timeline
- 24h watchdog 卡片（自动安排复查）

---

## 通用约定

### Run 产出结构

```
~/.commerce-os/runs/<run_id>/
├── report.html         ← 浏览器打开 · 业务方友好
├── report.md           ← LLM 友好
├── result.json         ← agent 间结构化交换
└── (skill-specific)
    ├── plan.json       (lumicc-launch)
    ├── winback-*.md    (lumicc-retention)
    ├── decisions.json  (lumicc-expand)
    └── ...
```

### agent 模式调用

任何 skill：

```bash
python3 .../run.py \
  --store-id <id> \
  --quiet-stdout \
  --notify-channel feishu --notify-target group:ops
```

stdout 输出一行 JSON：

```json
{"run_id":"abc","skill":"lumicc-XX","status":"success","report_html":"/path/to/report.html",...}
```

通知写到 `~/.commerce-os/outbox/<uuid>.json`，由独立的 sender 进程消费。

### 错误处理

- 缺数据 → 输出 `empty_state` 而非崩溃
- 部分失败 → `status: "partial"` + `warnings: [str]`
- 数据库锁 / 文件冲突 → 重试一次 + 优雅降级

### 数据保留

- `runs/` 保留全部（用户可手动清理）
- `events` 表无 TTL（业务事件应当永久）
- `outbox/` 通知发送后由 sender 删除

---

## 调试技巧

### 看一个 skill 跑了啥

```bash
ls -lt ~/.commerce-os/runs | head
cat ~/.commerce-os/runs/<run_id>/result.json | python3 -m json.tool
open ~/.commerce-os/runs/<run_id>/report.html
```

### 看 SQLite 状态

```bash
sqlite3 ~/.commerce-os/store.db "SELECT skill, status, started_at FROM runs ORDER BY started_at DESC LIMIT 10;"
sqlite3 ~/.commerce-os/store.db "SELECT category, content FROM events ORDER BY ts DESC LIMIT 20;"
```

### 切换主题

```bash
echo "## Theme: slate-premium" > ~/.commerce-os/design.md
# 或
export LUMICC_THEME=linen-warm
```

或者直接在浏览器里点报告右上角的主题切换器（持久化到 localStorage）。
