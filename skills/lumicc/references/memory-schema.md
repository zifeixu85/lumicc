# Memory Schema

## File Layout

```
~/.commerce-os/
├── store.db                            SQLite main database
├── runs/                               JSON results from each sub-skill run
│   └── <run_id>.json
├── memory/
│   ├── 2026-05-08.md                   Layer 1: daily event log (append-only)
│   ├── 2026-05-09.md
│   └── insights.md                     Layer 2: curated insights
└── SOUL.md                             Layer 3: user-edited bedrock rules
```

## Schema (SQLite)

Schema version stored in `_meta.schema_version`. `init_store.py` runs migrations idempotently.

```sql
CREATE TABLE IF NOT EXISTS _meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS stores (
  id              TEXT PRIMARY KEY,            -- UUID
  name            TEXT NOT NULL,
  platform        TEXT CHECK (platform IN ('shopify','amazon','tiktok-shop','etsy','independent')),
  url             TEXT,
  currency        TEXT DEFAULT 'USD',
  target_market   TEXT,
  stage           TEXT CHECK (stage IN ('0-to-1','1-to-10','10-to-100','100+')),
  niche           TEXT,
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  id              TEXT PRIMARY KEY,
  store_id        TEXT REFERENCES stores(id) ON DELETE CASCADE,
  sku             TEXT,
  title           TEXT,
  status          TEXT CHECK (status IN ('draft','active','paused','removed')),
  cost_usd        REAL,
  price_usd       REAL,
  supplier_url    TEXT,
  data_json       TEXT,                        -- full payload from selection skill
  created_at      INTEGER,
  updated_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_products_store ON products(store_id);

CREATE TABLE IF NOT EXISTS campaigns (
  id              TEXT PRIMARY KEY,
  store_id        TEXT REFERENCES stores(id),
  type            TEXT,                        -- cold-start | expansion | crisis | voc | watchtower
  status          TEXT CHECK (status IN ('planned','running','paused','done','cancelled')),
  budget_usd      REAL,
  started_at      INTEGER,
  ended_at        INTEGER,
  results_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_campaigns_store ON campaigns(store_id);

CREATE TABLE IF NOT EXISTS events (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id        TEXT,
  ts              INTEGER NOT NULL,
  category        TEXT,                        -- task | decision | observation | warning | external
  content         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_store_ts ON events(store_id, ts DESC);

CREATE TABLE IF NOT EXISTS insights (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  store_id        TEXT,
  ts              INTEGER NOT NULL,
  category        TEXT,
  content         TEXT NOT NULL,
  confidence      REAL DEFAULT 0.5,
  verified_count  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS preferences (
  key             TEXT PRIMARY KEY,
  value           TEXT,
  updated_at      INTEGER
);

CREATE TABLE IF NOT EXISTS runs (                -- index of skill runs
  run_id          TEXT PRIMARY KEY,
  skill           TEXT NOT NULL,
  store_id        TEXT,
  started_at      INTEGER,
  finished_at     INTEGER,
  status          TEXT CHECK (status IN ('success','partial','failed')),
  result_path     TEXT                          -- relative path to runs/<run_id>.json
);
```

## Migrations

Migrations are versioned numerically: `v1`, `v2`, … Each migration in `scripts/init_store.py` checks `_meta.schema_version` and runs only missing ones.

```python
MIGRATIONS = {
    1: ["<DDL above>"],
    # v2: future
}
```

## Daily Log Format (Layer 1)

`memory/YYYY-MM-DD.md` is append-only Markdown. Each entry:

```markdown
---
2026-05-08T14:32:11Z [decision] store=acme-pets
---

User confirmed product candidate "Magnetic Knife Rack" — added to active SKUs.
Source: lumicc-expand run abc-123.
```

A parallel `events` row is inserted for query.

## Curated Insights (Layer 2)

`memory/insights.md` is grouped by category. AI/user proposes insights when same pattern observed ≥ 2 times in events:

```markdown
## Listing — image angles

> Observed 3 times (verified_count=3, confidence=0.78)

For "home cleaning" SKUs, listings with overhead-angle hero images convert
1.8× better than eye-level. (Verified runs: abc-123, def-456, ghi-789.)
```

## SOUL (Layer 3)

`SOUL.md` is **user-edited only**. Skills may suggest additions but must not auto-write. Example:

```markdown
# My Cross-Border Commerce SOUL

- Target gross margin ≥ 40% before listing.
- Never source from suppliers with < 95% on-time rate.
- I want approval for any spend > $500.
- Primary market: US English-speaking. Secondary: UK.
```

## Idempotency Rules

- All writes use `INSERT OR REPLACE` or `INSERT … ON CONFLICT DO UPDATE`.
- `run_id` is UUID v4 — sub-skills generate via `uuid.uuid4()`.
- Migrations are guarded by schema version.
- Re-running `init_store.py` is always safe.

## Backup / Export

```bash
sqlite3 ~/.commerce-os/store.db ".dump" > ~/.commerce-os/backup-$(date +%Y%m%d).sql
tar -czf ~/.commerce-os/backup-$(date +%Y%m%d).tgz ~/.commerce-os/memory ~/.commerce-os/SOUL.md
```

Suggest user does this monthly.
