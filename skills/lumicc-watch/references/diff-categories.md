# Diff Categories & Weighting

Each detected change is classified and weighted. The report sorts by weight × confidence.

| Category | Weight | What triggers it |
|----------|--------|------------------|
| `new_product` | 3.0 | Product URL not present in prior snapshot |
| `removed_product` | 2.5 | Prior URL no longer in sitemap/homepage |
| `price_change` | 2.0 | Delta ≥ threshold_pct (default 5%) |
| `promo_banner_change` | 1.8 | Announcement bar text changed |
| `homepage_hero_change` | 1.5 | Hero image hash differs OR copy changed |
| `inventory_signal` | 1.4 | "Sold out" / "Only X left" badges appearing or disappearing |
| `review_velocity_delta` | 1.2 | Review count growth rate ↑/↓ ≥ 50% vs trailing avg |
| `social_post_burst` | 1.0 | New social posts ≥ 3 within 24h |
| `meta_seo_change` | 0.8 | `<title>` or `meta description` modified |
| `theme_change` | 0.5 | Major template / palette shift |

## Severity tiers

- **High** (weight ≥ 2.0): immediate notification, top of report
- **Medium** (1.0 – 1.9): grouped, summarized
- **Low** (< 1.0): footnote only

## Heuristic confidence boosters

```
+0.2 if same change observed at multiple targets (industry-wide signal)
+0.1 if change persisted ≥ 2 snapshots
-0.2 if first snapshot for this target (no baseline)
```

## Reporting rules

1. No more than 12 changes in the main report — group lower-weight changes into "other".
2. For price changes, show: prior → current, delta %, your equivalent SKU price (if matched).
3. For new products, always include the URL so the user can open quickly.
4. Tag each row with `target_host` for filterability.
