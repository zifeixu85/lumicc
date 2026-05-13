#!/usr/bin/env python3
"""Shopify Admin API adapter for Lumicc v0.3.

Imports a real Shopify store (shop, products, orders, customers) into
~/.commerce-os/store.db (override via LUMICC_DATA_ROOT).

Public API:
    ShopifyClient(shop_domain, access_token=None)
        .get_shop()
        .list_products(limit_total=None)
        .list_orders(since_days=90, limit_total=None)
        .list_customers(limit_total=None)
    import_shopify_store(shop_domain, *, store_id=None, days=90,
                         dry_run=False, only=None, mock=False)

CLI:
    python3 adapter_shopify.py --domain mystore.myshopify.com --days 90
    python3 adapter_shopify.py --domain ... --only products
    python3 adapter_shopify.py --domain ... --dry-run --mock
"""
from __future__ import annotations

import argparse
import datetime as _dt
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

try:
    from secret_form import read_secret  # type: ignore
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).parent))
    from secret_form import read_secret  # type: ignore

SHOPIFY_API_VERSION = "2024-10"
USER_AGENT = "lumicc/0.3.0 (+shopify-adapter)"
HTTP_TIMEOUT = 20
DEFAULT_PAGE_SIZE = 250
_STATUS_MAP = {"active": "active", "draft": "draft", "archived": "removed"}



class ShopifyError(RuntimeError):
    """Base for Shopify adapter errors."""


class ShopifyAuthError(ShopifyError):
    """Raised when Shopify rejects credentials (401/403)."""


class MissingSecretError(ShopifyError):
    """Raised when SHOPIFY_ADMIN_TOKEN is not configured."""



_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _parse_link_next(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        m = _LINK_NEXT_RE.search(part.strip())
        if m:
            return m.group(1)
    return None


class ShopifyClient:
    """Thin REST client over the Shopify Admin API."""

    def __init__(self, shop_domain: str, access_token: str | None = None) -> None:
        if not shop_domain:
            raise ValueError("shop_domain required")
        d = re.sub(r"^https?://", "", shop_domain.strip()).rstrip("/")
        self.shop_domain = d
        if access_token is None:
            tok = read_secret("SHOPIFY_ADMIN_TOKEN")
            if not tok:
                raise MissingSecretError(
                    "SHOPIFY_ADMIN_TOKEN missing. Run: "
                    "python3 secret_form.py --generate SHOPIFY_ADMIN_TOKEN --open"
                )
            access_token = tok
        self.access_token = access_token
        self.base = f"https://{self.shop_domain}/admin/api/{SHOPIFY_API_VERSION}"
        self._last_call_limit: tuple[int, int] | None = None

    def _headers(self) -> dict[str, str]:
        return {"X-Shopify-Access-Token": self.access_token,
                "Accept": "application/json", "User-Agent": USER_AGENT}

    def _request(self, url: str, *, retries: int = 3) -> tuple[int, bytes, dict[str, str]]:
        """GET with auth, rate-limit awareness and exponential backoff."""
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        attempt = 0
        while attempt <= retries:
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
                    body, headers, status = resp.read(), dict(resp.headers), resp.status
            except urllib.error.HTTPError as e:
                body = e.read() if hasattr(e, "read") else b""
                headers, status = dict(e.headers or {}), e.code
            except urllib.error.URLError as e:
                attempt += 1
                if attempt > retries:
                    raise ShopifyError(f"network error after {retries} retries: {e}") from e
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            self._update_rate_limit(headers)

            if status == 429:
                attempt += 1
                if attempt > retries:
                    raise ShopifyError("rate limited (429) after retries")
                ra = headers.get("Retry-After") or headers.get("retry-after")
                try:
                    delay = float(ra) if ra else 2.0
                except ValueError:
                    delay = 2.0
                time.sleep(delay)
                continue
            if status in (401, 403):
                raise ShopifyAuthError(
                    f"Shopify rejected token ({status}). "
                    "Re-run: python3 secret_form.py --generate SHOPIFY_ADMIN_TOKEN"
                )
            if status == 404:
                raise ShopifyError(f"404 from {url} — domain wrong or store doesn't exist")
            if status >= 500:
                attempt += 1
                if attempt > retries:
                    raise ShopifyError(f"server error {status} after retries")
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            if status != 200:
                raise ShopifyError(f"unexpected HTTP {status} from {url}: {body[:200]!r}")

            self._maybe_cool_down()
            return status, body, headers
        raise ShopifyError("exhausted retries")

    def _update_rate_limit(self, headers: dict[str, str]) -> None:
        raw = (headers.get("X-Shopify-Shop-Api-Call-Limit")
               or headers.get("x-shopify-shop-api-call-limit"))
        if not raw or "/" not in raw:
            return
        try:
            used, cap = raw.split("/", 1)
            self._last_call_limit = (int(used), int(cap))
        except ValueError:
            return

    def _maybe_cool_down(self) -> None:
        if not self._last_call_limit:
            return
        used, cap = self._last_call_limit
        if cap > 0 and used / cap > 0.75:
            time.sleep(0.5)

    def get_shop(self) -> dict:
        _, body, _ = self._request(f"{self.base}/shop.json")
        return json.loads(body.decode("utf-8")).get("shop", {})

    def _paginate(self, path: str, params: dict[str, Any],
                  key: str, limit_total: int | None) -> list[dict]:
        params = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base}/{path}?{urllib.parse.urlencode(params)}"
        out: list[dict] = []
        while url:
            _, body, headers = self._request(url)
            data = json.loads(body.decode("utf-8"))
            out.extend(data.get(key, []) if isinstance(data, dict) else [])
            if limit_total is not None and len(out) >= limit_total:
                return out[:limit_total]
            url = _parse_link_next(headers.get("Link") or headers.get("link"))
        return out

    def list_products(self, limit_total: int | None = None) -> list[dict]:
        return self._paginate("products.json", {"limit": DEFAULT_PAGE_SIZE},
                              "products", limit_total)

    def list_orders(self, since_days: int = 90,
                    limit_total: int | None = None) -> list[dict]:
        since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max(0, since_days))
        return self._paginate(
            "orders.json",
            {"limit": DEFAULT_PAGE_SIZE, "status": "any",
             "created_at_min": since.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "orders", limit_total,
        )

    def list_customers(self, limit_total: int | None = None) -> list[dict]:
        return self._paginate("customers.json", {"limit": DEFAULT_PAGE_SIZE},
                              "customers", limit_total)



def _data_root() -> Path:
    override = os.environ.get("LUMICC_DATA_ROOT")
    return Path(override).expanduser() if override else Path.home() / ".commerce-os"


def _open_db() -> sqlite3.Connection:
    root = _data_root()
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "store.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS stores (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT, url TEXT,
          currency TEXT DEFAULT 'USD', target_market TEXT, stage TEXT, niche TEXT,
          created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS products (
          id TEXT PRIMARY KEY, store_id TEXT, sku TEXT, title TEXT, status TEXT,
          cost_usd REAL, price_usd REAL, supplier_url TEXT, data_json TEXT,
          created_at INTEGER, updated_at INTEGER);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, store_id TEXT, ts INTEGER NOT NULL,
          category TEXT, content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS customers (
          id TEXT PRIMARY KEY, store_id TEXT, email TEXT, name TEXT,
          total_spent REAL DEFAULT 0, order_count INTEGER DEFAULT 0,
          first_order_at INTEGER, last_order_at INTEGER, data_json TEXT,
          created_at INTEGER, updated_at INTEGER);
    """)
    db.commit()
    return db


def _to_float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _sanitize_for_event(v: Any) -> str:
    """Strip HTML control chars from API-sourced strings before storage.

    Defense in depth: events.content is later rendered into HTML reports. Renderers
    already escape via H.esc(), but stripping <>&"' here guarantees safety even if
    a future renderer forgets. Truncates to 200 chars to bound storage.
    """
    s = str(v or "")
    for c in "<>&\"'":
        s = s.replace(c, "")
    return s[:200]


def _to_int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_shopify_ts(value: str | None) -> int | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(_dt.datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    return None


def _upsert_store(db: sqlite3.Connection, store_id: str, shop: dict) -> None:
    now = int(time.time())
    name = shop.get("name") or shop.get("myshopify_domain") or "Shopify Store"
    currency = shop.get("currency") or "USD"
    url = shop.get("domain") or shop.get("myshopify_domain") or ""
    if url and not url.startswith("http"):
        url = f"https://{url}"
    if db.execute("SELECT id FROM stores WHERE id=?", (store_id,)).fetchone():
        db.execute(
            "UPDATE stores SET name=?, platform=?, url=?, currency=?, updated_at=? WHERE id=?",
            (name, "shopify", url, currency, now, store_id))
    else:
        db.execute(
            "INSERT INTO stores(id, name, platform, url, currency, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (store_id, name, "shopify", url, currency, now, now))


def _store_products(db: sqlite3.Connection, store_id: str,
                    products: list[dict]) -> int:
    now = int(time.time())
    count = 0
    for p in products:
        variants = p.get("variants") or []
        first = variants[0] if variants else {}
        sku = (first.get("sku") or "").strip() or f"p_{uuid.uuid4().hex[:10]}"
        price = _to_float(first.get("price"))
        cost = _to_float(first.get("cost"))
        status = _STATUS_MAP.get((p.get("status") or "").lower(), "active")
        pid = str(p.get("id") or sku)
        data_json = json.dumps({
            "shopify_id": p.get("id"), "handle": p.get("handle"),
            "vendor": p.get("vendor"), "product_type": p.get("product_type"),
            "tags": p.get("tags"), "images": p.get("images") or [],
            "options": p.get("options") or [], "variants": variants,
        }, ensure_ascii=False)
        if db.execute("SELECT id FROM products WHERE id=? AND store_id=?",
                      (pid, store_id)).fetchone():
            db.execute(
                "UPDATE products SET sku=?, title=?, status=?, cost_usd=?, price_usd=?, "
                "data_json=?, updated_at=? WHERE id=? AND store_id=?",
                (sku, p.get("title"), status, cost, price, data_json, now, pid, store_id))
        else:
            db.execute(
                "INSERT INTO products(id, store_id, sku, title, status, cost_usd, price_usd, "
                "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, store_id, sku, p.get("title"), status, cost, price,
                 data_json, now, now))
        count += 1
    return count


def _store_orders(db: sqlite3.Connection, store_id: str,
                  orders: list[dict]) -> tuple[int, int]:
    now = int(time.time())
    orders_count = 0
    cust_agg: dict[str, dict] = {}
    for o in orders:
        # Strip HTML/script control chars from merchant-controlled order name —
        # defense in depth so events.content is safe even if a future renderer
        # forgets H.esc(). See ROADMAP_TO_GA.md §7 (Anti-Slop) and code-review v1.0.
        order_no_raw = o.get("name") or o.get("order_number") or o.get("id") or ""
        order_no = _sanitize_for_event(order_no_raw)
        total = _to_float(o.get("total_price"))
        items = o.get("line_items") or []
        ts = _parse_shopify_ts(o.get("created_at")) or now
        currency = _sanitize_for_event(o.get("currency") or "USD")
        db.execute(
            "INSERT INTO events(store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, ts, "order",
             f"Order #{order_no} · {currency} {total:.2f} · {len(items)} items"))
        orders_count += 1
        cust = o.get("customer") or {}
        email = (o.get("email") or cust.get("email") or "").strip().lower() or None
        cid = str(cust.get("id") or email or "")
        if not cid:
            continue
        name = " ".join(x for x in [cust.get("first_name"), cust.get("last_name")] if x) or None
        agg = cust_agg.setdefault(cid, {
            "email": email, "name": name, "order_count": 0,
            "total_spent": 0.0, "first": ts, "last": ts,
        })
        agg["order_count"] += 1
        agg["total_spent"] += total
        agg["first"] = min(agg["first"], ts)
        agg["last"] = max(agg["last"], ts)

    touched = 0
    for cid, agg in cust_agg.items():
        if db.execute("SELECT id FROM customers WHERE id=? AND store_id=?",
                      (cid, store_id)).fetchone():
            db.execute(
                "UPDATE customers SET email=COALESCE(?,email), name=COALESCE(?,name), "
                "total_spent=?, order_count=?, last_order_at=?, updated_at=? "
                "WHERE id=? AND store_id=?",
                (agg["email"], agg["name"], agg["total_spent"], agg["order_count"],
                 agg["last"], now, cid, store_id))
        else:
            db.execute(
                "INSERT INTO customers(id, store_id, email, name, total_spent, order_count, "
                "first_order_at, last_order_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (cid, store_id, agg["email"], agg["name"], agg["total_spent"],
                 agg["order_count"], agg["first"], agg["last"], now, now))
        touched += 1
    return orders_count, touched


def _store_customers(db: sqlite3.Connection, store_id: str,
                     customers: list[dict]) -> int:
    now = int(time.time())
    count = 0
    for c in customers:
        cid = str(c.get("id") or c.get("email") or "")
        if not cid:
            continue
        email = (c.get("email") or "").strip().lower() or None
        name = " ".join(x for x in [c.get("first_name"), c.get("last_name")] if x) or None
        spent = _to_float(c.get("total_spent"))
        orders_n = _to_int(c.get("orders_count"))
        addresses = c.get("addresses") or []
        country = addresses[0].get("country") if addresses else None
        data_json = json.dumps({"country": country, "shopify_id": c.get("id")},
                               ensure_ascii=False)
        if db.execute("SELECT id FROM customers WHERE id=? AND store_id=?",
                      (cid, store_id)).fetchone():
            db.execute(
                "UPDATE customers SET email=COALESCE(?,email), name=COALESCE(?,name), "
                "total_spent=?, order_count=?, data_json=?, updated_at=? "
                "WHERE id=? AND store_id=?",
                (email, name, spent, orders_n, data_json, now, cid, store_id))
        else:
            db.execute(
                "INSERT INTO customers(id, store_id, email, name, total_spent, order_count, "
                "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, store_id, email, name, spent, orders_n, data_json, now, now))
        count += 1
    return count



def _mock_payload() -> dict:
    return {
        "shop": {"name": "Mock Store", "currency": "USD",
                 "myshopify_domain": "mock.myshopify.com",
                 "domain": "mock.myshopify.com"},
        "products": [
            {"id": 1, "title": "Aurora Lamp", "status": "active", "handle": "aurora-lamp",
             "variants": [{"sku": "AUR-001", "price": "49.00"}]},
            {"id": 2, "title": "Nimbus Mug", "status": "active", "handle": "nimbus-mug",
             "variants": [{"sku": "NIM-002", "price": "18.00"}]},
            {"id": 3, "title": "Loom Throw", "status": "draft", "handle": "loom-throw",
             "variants": [{"sku": "LOO-003", "price": "120.00"}]},
            {"id": 4, "title": "Halo Mirror", "status": "archived", "handle": "halo-mirror",
             "variants": [{"sku": "HAL-004", "price": "85.00"}]},
        ],
        "orders": [
            {"id": 101, "name": "#1001", "total_price": "49.00", "currency": "USD",
             "created_at": "2026-04-01T10:00:00Z", "line_items": [{"id": 1}],
             "customer": {"id": 9001, "first_name": "Ada", "last_name": "Lin",
                          "email": "ada@example.com"}},
        ],
        "customers": [
            {"id": 9001, "first_name": "Ada", "last_name": "Lin",
             "email": "ada@example.com", "total_spent": "49.00", "orders_count": 1,
             "addresses": [{"country": "US"}]},
        ],
    }



def _safe_fetch(fn, label: str, warnings: list[str]) -> list[dict]:
    try:
        return fn()
    except ShopifyAuthError:
        raise
    except ShopifyError as exc:
        warnings.append(f"{label} fetch failed: {exc}")
        return []


def import_shopify_store(
    shop_domain: str,
    *,
    store_id: str | None = None,
    days: int = 90,
    dry_run: bool = False,
    only: str | None = None,
    mock: bool = False,
    _client: ShopifyClient | None = None,
) -> dict:
    """Full import flow. See module docstring for return shape."""
    started = time.time()
    warnings: list[str] = []
    sid = store_id or f"s_{uuid.uuid4().hex[:10]}"

    if mock:
        d = _mock_payload()
        shop, products, orders, customers = (d["shop"], d["products"],
                                             d["orders"], d["customers"])
    else:
        c = _client or ShopifyClient(shop_domain)
        shop = _safe_fetch(c.get_shop, "shop", warnings) or {}  # type: ignore[assignment]
        if isinstance(shop, list):  # _safe_fetch returns [] on failure
            shop = {}
        products = _safe_fetch(c.list_products, "products", warnings) \
            if only in (None, "products") else []
        orders = _safe_fetch(lambda: c.list_orders(since_days=days),
                             "orders", warnings) if only in (None, "orders") else []
        customers = _safe_fetch(c.list_customers, "customers", warnings) \
            if only in (None, "customers") else []

    products_imported = orders_imported = customers_imported = 0
    if dry_run:
        products_imported, orders_imported, customers_imported = (
            len(products), len(orders), len(customers))
    else:
        db = _open_db()
        try:
            _upsert_store(db, sid, shop)
            if only in (None, "products"):
                products_imported = _store_products(db, sid, products)
            if only in (None, "orders"):
                orders_imported, _ = _store_orders(db, sid, orders)
            if only in (None, "customers"):
                customers_imported = _store_customers(db, sid, customers)
            db.commit()
        finally:
            db.close()

    return {
        "store_id": sid,
        "shop_name": shop.get("name", ""),
        "currency": shop.get("currency", "USD"),
        "products_imported": products_imported,
        "orders_imported": orders_imported,
        "customers_imported": customers_imported,
        "warnings": warnings,
        "duration_sec": round(time.time() - started, 3),
    }



def _emit(payload: dict, quiet_stdout: bool) -> None:
    if quiet_stdout:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lumicc Shopify adapter")
    p.add_argument("--domain", required=True, help="e.g. mystore.myshopify.com")
    p.add_argument("--store-id", dest="store_id", default=None)
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--only", choices=["products", "orders", "customers"], default=None)
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--mock", action="store_true", help="No HTTP; use fixture data")
    p.add_argument("--quiet-stdout", action="store_true", dest="quiet")
    args = p.parse_args(argv)

    if not args.quiet:
        sys.stderr.write(f"[adapter_shopify] connecting to {args.domain}\n")
    try:
        result = import_shopify_store(
            args.domain, store_id=args.store_id, days=args.days,
            dry_run=args.dry_run, only=args.only, mock=args.mock)
    except MissingSecretError as exc:
        _emit({"adapter": "shopify", "error": "missing_secret",
               "message": str(exc), "domain": args.domain}, args.quiet)
        return 2
    except ShopifyAuthError as exc:
        _emit({"adapter": "shopify", "error": "auth",
               "message": str(exc), "domain": args.domain}, args.quiet)
        return 3
    except ShopifyError as exc:
        _emit({"adapter": "shopify", "error": "shopify",
               "message": str(exc), "domain": args.domain}, args.quiet)
        return 1

    _emit({"adapter": "shopify", "domain": args.domain, **result}, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
