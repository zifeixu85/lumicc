#!/usr/bin/env python3
"""Independent-site ingestion adapter for Lumicc v0.3.

Pulls products + Plausible traffic data from a self-hosted commerce site
(e.g. lumiclaw-commerce-store.vercel.app) into ~/.commerce-os/store.db.

Public API:
    fetch_plausible_stats(api_key, site_id, days=90) -> dict
    fetch_products_from_url(store_url) -> list[dict]
    initialize_store_from_indep_site(store_url, site_name=None, ...) -> dict

CLI:
    python3 adapter_indep.py --url https://example.com --name "MyStore"
    python3 adapter_indep.py --url ... --no-plausible
    python3 adapter_indep.py --url ... --quiet-stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Local helpers — make import resilient when run from anywhere.
try:
    from secret_form import read_secret  # type: ignore
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).parent))
    from secret_form import read_secret  # type: ignore

USER_AGENT = "lumicc/0.3.0"
PLAUSIBLE_BASE = "https://plausible.io/api/v1"
HTTP_TIMEOUT = 15


# --- HTTP helpers ---------------------------------------------------------

def _http_get(url: str, headers: dict[str, str] | None = None,
              timeout: int = HTTP_TIMEOUT) -> tuple[int, bytes, dict[str, str]]:
    """GET a URL. Returns (status, body, headers). Never raises for HTTP errors;
    re-raises only for URLError (network failure)."""
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read()
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b"", dict(e.headers or {})


def _json_get(url: str, headers: dict[str, str] | None = None) -> Any:
    status, body, _ = _http_get(url, headers=headers)
    if status != 200:
        raise RuntimeError(f"HTTP {status} from {url}")
    return json.loads(body.decode("utf-8"))


# --- Plausible ------------------------------------------------------------

def fetch_plausible_stats(api_key: str, site_id: str, days: int = 90) -> dict:
    """Fetch aggregate stats + source breakdown from Plausible v1 API.

    Returns:
        {
          "pageviews": int, "visitors": int, "bounce_rate": float,
          "sources": [{"source": str, "visitors": int}, ...],
          "site_id": str, "period_days": int,
        }
    Raises RuntimeError on transport/parse errors.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    period = f"{days}d"

    agg_url = (
        f"{PLAUSIBLE_BASE}/stats/aggregate?"
        + urllib.parse.urlencode({
            "site_id": site_id,
            "period": period,
            "metrics": "visitors,pageviews,bounce_rate",
        })
    )
    breakdown_url = (
        f"{PLAUSIBLE_BASE}/stats/breakdown?"
        + urllib.parse.urlencode({
            "site_id": site_id,
            "period": period,
            "property": "visit:source",
        })
    )
    agg = _json_get(agg_url, headers=headers)
    breakdown = _json_get(breakdown_url, headers=headers)

    res = (agg or {}).get("results", {}) if isinstance(agg, dict) else {}
    sources_raw = (breakdown or {}).get("results", []) if isinstance(breakdown, dict) else []

    def _val(node: Any) -> Any:
        if isinstance(node, dict):
            return node.get("value", node)
        return node

    return {
        "pageviews": int(_val(res.get("pageviews", 0)) or 0),
        "visitors": int(_val(res.get("visitors", 0)) or 0),
        "bounce_rate": float(_val(res.get("bounce_rate", 0)) or 0),
        "sources": [
            {"source": s.get("source", "unknown"), "visitors": int(s.get("visitors", 0) or 0)}
            for s in sources_raw
            if isinstance(s, dict)
        ],
        "site_id": site_id,
        "period_days": days,
    }


# --- Product fetch (3-tier graceful degradation) --------------------------

_JSON_ENDPOINTS = ("/data/products.json", "/api/products", "/products.json")
_SLUG_RE = re.compile(r"<loc>(.*?)</loc>", re.IGNORECASE)


def _normalize_product(raw: dict) -> dict | None:
    """Coerce arbitrary product JSON into {sku, title, price, cost_usd?, data_json}."""
    if not isinstance(raw, dict):
        return None
    title = raw.get("title") or raw.get("name") or raw.get("slug")
    if isinstance(title, dict):
        title = title.get("en") or next(iter(title.values()), None)
    if not title:
        return None
    sku = (raw.get("sku") or raw.get("id") or raw.get("slug") or raw.get("asin")
           or f"p_{uuid.uuid4().hex[:10]}")
    price = raw.get("price")
    try:
        price_f = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        price_f = 0.0
    cost = raw.get("cost") or raw.get("cost_usd")
    try:
        cost_f = float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        cost_f = 0.0
    return {
        "sku": str(sku),
        "title": str(title),
        "price": price_f,
        "cost_usd": cost_f,
        "data_json": json.dumps(raw, ensure_ascii=False),
    }


def _try_json_endpoints(base: str) -> list[dict]:
    for path in _JSON_ENDPOINTS:
        url = base.rstrip("/") + path
        try:
            data = _json_get(url)
        except Exception:  # noqa: BLE001
            continue
        items: list[Any] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("products", "items", "data", "results"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        normalized = [p for p in (_normalize_product(it) for it in items if isinstance(it, dict)) if p]
        if normalized:
            return normalized
    return []


def _try_sitemap(base: str) -> list[dict]:
    url = base.rstrip("/") + "/sitemap.xml"
    try:
        status, body, _ = _http_get(url)
        if status != 200:
            return []
        text = body.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    locs = _SLUG_RE.findall(text)
    product_urls = [u for u in locs if "/product" in u.lower()]
    out: list[dict] = []
    for u in product_urls[:200]:
        slug = u.rstrip("/").split("/")[-1]
        out.append({"sku": slug, "title": slug.replace("-", " ").title(),
                    "price": 0.0, "cost_usd": 0.0,
                    "data_json": json.dumps({"source_url": u}, ensure_ascii=False)})
    return out


def _try_homepage_scrape(base: str) -> list[dict]:
    try:
        status, body, _ = _http_get(base)
        if status != 200:
            return []
        text = body.decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return []
    # Heuristic: look for <a href="/products/<slug>"> patterns.
    urls = set(re.findall(r'href=["\'](/products?/[^"\'?#]+)["\']', text))
    out = []
    for u in list(urls)[:50]:
        slug = u.rstrip("/").split("/")[-1]
        if not slug or slug in {"products", "product"}:
            continue
        out.append({"sku": slug, "title": slug.replace("-", " ").title(),
                    "price": 0.0, "cost_usd": 0.0,
                    "data_json": json.dumps({"source_url": u}, ensure_ascii=False)})
    return out


def fetch_products_from_url(store_url: str) -> list[dict]:
    """Try JSON endpoints → sitemap → homepage scrape. Empty list on total failure."""
    base = store_url.rstrip("/")
    for strategy in (_try_json_endpoints, _try_sitemap, _try_homepage_scrape):
        try:
            items = strategy(base)
        except Exception:  # noqa: BLE001
            items = []
        if items:
            return items
    return []


# --- Storage --------------------------------------------------------------

def _data_root() -> Path:
    override = os.environ.get("LUMICC_DATA_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".commerce-os"


def _open_db() -> sqlite3.Connection:
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "store.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    _ensure_tables(db)
    return db


def _ensure_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS stores (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          platform TEXT,
          url TEXT,
          currency TEXT DEFAULT 'USD',
          target_market TEXT,
          stage TEXT,
          niche TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY,
          store_id TEXT,
          sku TEXT,
          title TEXT,
          status TEXT,
          cost_usd REAL,
          price_usd REAL,
          supplier_url TEXT,
          data_json TEXT,
          created_at INTEGER,
          updated_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id TEXT,
          ts INTEGER NOT NULL,
          category TEXT,
          content TEXT NOT NULL
        );
        """
    )
    db.commit()


def _ensure_store(db: sqlite3.Connection, store_id: str, name: str, url: str) -> None:
    now = int(time.time())
    existing = db.execute("SELECT id FROM stores WHERE id=?", (store_id,)).fetchone()
    if existing:
        db.execute(
            "UPDATE stores SET name=?, url=?, updated_at=? WHERE id=?",
            (name, url, now, store_id),
        )
    else:
        db.execute(
            "INSERT INTO stores(id, name, platform, url, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (store_id, name, "independent", url, now, now),
        )


def _store_products(db: sqlite3.Connection, store_id: str, items: list[dict]) -> int:
    now = int(time.time())
    count = 0
    for p in items:
        pid = p.get("sku") or f"p_{uuid.uuid4().hex[:10]}"
        existing = db.execute(
            "SELECT id FROM products WHERE id=? AND store_id=?", (pid, store_id)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE products SET sku=?, title=?, price_usd=?, cost_usd=?, "
                "data_json=?, updated_at=? WHERE id=? AND store_id=?",
                (p.get("sku"), p.get("title"), p.get("price", 0.0), p.get("cost_usd", 0.0),
                 p.get("data_json"), now, pid, store_id),
            )
        else:
            db.execute(
                "INSERT INTO products(id, store_id, sku, title, status, cost_usd, price_usd, "
                "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, store_id, p.get("sku"), p.get("title"), "active",
                 p.get("cost_usd", 0.0), p.get("price", 0.0),
                 p.get("data_json"), now, now),
            )
        count += 1
    return count


def _store_traffic_event(db: sqlite3.Connection, store_id: str, stats: dict) -> int:
    now = int(time.time())
    db.execute(
        "INSERT INTO events(store_id, ts, category, content) VALUES (?,?,?,?)",
        (store_id, now, "traffic", json.dumps(stats, ensure_ascii=False)),
    )
    return 1


# --- Orchestrator ---------------------------------------------------------

def initialize_store_from_indep_site(
    store_url: str,
    site_name: str | None = None,
    store_id: str | None = None,
    fetch_traffic: bool = True,
    plausible_site_id: str | None = None,
) -> dict:
    """Full flow: create store, fetch products, fetch traffic.

    Returns:
        {"store_id", "products_count", "events_count", "warnings"}
    """
    warnings: list[str] = []
    parsed = urllib.parse.urlparse(store_url)
    host = parsed.netloc or parsed.path
    sid = store_id or f"s_{uuid.uuid4().hex[:10]}"
    name = site_name or host or "Independent Store"
    plausible_site = plausible_site_id or host

    db = _open_db()
    try:
        _ensure_store(db, sid, name, store_url)

        # Products
        try:
            products = fetch_products_from_url(store_url)
        except Exception as exc:  # noqa: BLE001
            products = []
            warnings.append(f"Product fetch failed: {exc}")
        if not products:
            warnings.append(
                f"No products discovered at {store_url}. "
                "Try CSV import: adapter_csv.py --kind products"
            )
        products_count = _store_products(db, sid, products)

        # Traffic
        events_count = 0
        if fetch_traffic:
            api_key = read_secret("PLAUSIBLE_API_KEY")
            if not api_key:
                warnings.append(
                    "PLAUSIBLE_API_KEY missing. "
                    "Run: python3 secret_form.py --generate PLAUSIBLE_API_KEY --open"
                )
            else:
                try:
                    stats = fetch_plausible_stats(api_key, plausible_site)
                    events_count = _store_traffic_event(db, sid, stats)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Plausible fetch failed: {exc}")

        db.commit()
    finally:
        db.close()

    return {
        "store_id": sid,
        "products_count": products_count,
        "events_count": events_count,
        "warnings": warnings,
    }


# --- CLI ------------------------------------------------------------------

def _emit(payload: dict, quiet_stdout: bool) -> None:
    if quiet_stdout:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lumicc independent-site adapter")
    p.add_argument("--url", required=True, help="Store URL")
    p.add_argument("--name", default=None, help="Friendly store name")
    p.add_argument("--store-id", default=None, dest="store_id")
    p.add_argument("--plausible-site", default=None, dest="plausible_site",
                   help="Plausible site_id (defaults to URL host)")
    p.add_argument("--no-plausible", action="store_true",
                   help="Skip traffic, just import products")
    p.add_argument("--quiet-stdout", action="store_true", dest="quiet")
    args = p.parse_args(argv)

    if not args.quiet:
        sys.stderr.write(f"[adapter_indep] connecting to {args.url}\n")

    try:
        result = initialize_store_from_indep_site(
            args.url,
            site_name=args.name,
            store_id=args.store_id,
            fetch_traffic=not args.no_plausible,
            plausible_site_id=args.plausible_site,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[adapter_indep] fatal: {exc}\n")
        _emit({"adapter": "indep", "error": str(exc), "url": args.url}, args.quiet)
        return 1

    payload = {
        "adapter": "indep",
        "url": args.url,
        **result,
    }
    _emit(payload, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
