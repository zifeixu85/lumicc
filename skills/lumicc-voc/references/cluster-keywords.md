# Fallback Keyword Clusters

When embeddings are unavailable, group complaints into these buckets via keyword match. EN + CN.

| Cluster | English keywords | Chinese keywords | Typical fix |
|---------|------------------|------------------|-------------|
| `packaging_damage` | broken, damaged, crushed, dented, leaked, smashed, torn | 破损, 压坏, 漏, 撞坏, 凹陷 | Add packaging upgrade, supplier outreach |
| `size_mismatch` | too small, too big, wrong size, doesn't fit, smaller than expected | 太小, 太大, 尺寸不对, 偏小, 偏大 | Add scale/size reference image, fix size chart |
| `quality_issue` | cheap, flimsy, fell apart, low quality, poor build | 质量差, 易坏, 做工差, 廉价感 | Listing transparency, supplier upgrade |
| `delivery_late` | late, slow, took weeks, never arrived, lost | 慢, 迟到, 没收到, 物流 | Faster shipping option, ETA clarity |
| `not_as_described` | misleading, photos lie, different color, fake | 与图不符, 货不对板, 颜色不同 | Image accuracy, description rewrite |
| `instructions_missing` | confusing, no manual, hard to use, instructions | 说明书没有, 不会用, 复杂 | Add instruction PDF, video, FAQ |
| `compatibility` | doesn't work with, incompatible, not suitable | 不兼容, 不适配 | Compatibility table on listing |
| `smell_taste` | smell, odor, plastic smell, chemical | 味道, 异味, 化学味 | Supplier check, material upgrade |
| `customer_service` | rude, no response, refund refused | 客服, 退款, 售后 | Service SOP, response time SLA |
| `value_for_money` | overpriced, not worth, too expensive | 贵, 不值, 性价比低 | Price test, value-add bundle |

## Scoring rules

- Cluster size = unique customer mentions (1 customer = 1 vote even if multi-mention)
- Cross-product clusters get +1 weight per product affected
- Recency boost: events in last 14 days weighted 1.5×
