# Routing Table — Intent Keywords ↔ Sub-Skill

Keywords are matched case-insensitive on user intent text. Order of priority: first match wins. Both English and Chinese keywords supported.

## Table

| Sub-skill | English triggers | Chinese triggers | Weight |
|-----------|------------------|------------------|--------|
| `lumicc-launch` | "start a store", "new store", "from scratch", "launch store", "first time", "0 to 1", "haven't started" | "新店", "从零", "刚开始", "刚做", "0到1", "出海起步", "上店", "开店" | 1.0 |
| `lumicc-watch` | "competitor", "rival", "spy", "monitor", "track competition", "what are others doing" | "竞品", "对手", "监控", "盯", "巡店", "对标" | 0.95 |
| `lumicc-expand` | "next product", "expand catalog", "more SKUs", "scale products", "find another winner", "diversify" | "扩品", "下一个", "新品", "多品", "横向扩展", "找下一个爆款" | 0.95 |
| `lumicc-listing` | "listing", "product page", "conversion", "PDP", "ASIN audit", "page optimization", "low CR" | "listing 优化", "产品页", "详情页", "转化率", "PDP", "页面问题" | 0.90 |
| `lumicc-voc` | "review analysis", "VoC", "voice of customer", "negative reviews", "returns analysis", "complaints", "feedback" | "评论", "差评", "退货", "客诉", "用户反馈", "VoC", "口碑" | 0.95 |
| `lumicc-rescue` | "sales dropped", "traffic crash", "account suspended", "asin suppressed", "listing removed", "emergency", "what's wrong" | "销量降", "流量掉", "暴跌", "账号警告", "被封", "Listing 被下", "紧急" | 1.0 |

## Multi-Intent Resolution

If multiple keywords match:

1. Use highest-weight match.
2. On tie, ask user: "I detected multiple possible intents: A, B. Which fits?"
3. Log the disambiguation to events table for learning.

## Negative Keywords (de-prioritize)

| If user says... | Then skip... |
|-----------------|--------------|
| "no automation", "manual only" | Skip auto-scheduled sub-skills |
| "just curious", "research only" | Run sub-skill in read-only mode |
| "don't touch my store" | Skip any write API call sub-skills |

## Implementation Hint

`scripts/route.py` reads this file as plain markdown. Update this file → router behavior updates next run. Avoid coding the table into Python.

Recommended parsing pattern:

```python
import re
KEYWORDS = {
  "lumicc-launch": (
    ["start a store", "new store", "from scratch", "launch store"],
    ["新店", "从零", "刚开始", "开店"],
    1.0
  ),
  # ... etc.
}
```
