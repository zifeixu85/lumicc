#!/usr/bin/env python3
"""Amazon SP-API adapter for Lumicc v0.5.

Imports a real Amazon seller account (orders, catalog items, derived customers)
into ~/.commerce-os/store.db (override via LUMICC_DATA_ROOT).

Public API:
    AmazonSPClient(marketplace_id="ATVPDKIKX0DER",
                   client_id=None, client_secret=None, refresh_token=None)
        .get_orders(since_days=30)
        .get_order_items(order_id)
        .search_catalog(keyword=None, asin=None)
    import_amazon_store(marketplace_id="ATVPDKIKX0DER", *,
                        store_id=None, days=30, asin_list=None,
                        dry_run=False, only=None, mock=False)

CLI:
    python3 adapter_amazon_sp.py --marketplace ATVPDKIKX0DER --days 30
    python3 adapter_amazon_sp.py --asins B08P4K7ZGP,B0CXYZABCD --only products
    python3 adapter_amazon_sp.py --dry-run --mock
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
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

LWA_TOKEN_ENDPOINT = "https://api.amazon.com/auth/o2/token"
USER_AGENT = "lumicc/0.5.0 (+amazon-sp-adapter)"
HTTP_TIMEOUT = 30
ORDERS_API_VERSION = "v0"
CATALOG_API_VERSION = "2022-04-01"

# marketplace_id -> (region_host, default_currency, friendly_name)
MARKETPLACES: dict[str, tuple[str, str, str]] = {
    "ATVPDKIKX0DER":  ("https://sellingpartnerapi-na.amazon.com", "USD", "Amazon US"),
    "A1F83G8C2ARO7P": ("https://sellingpartnerapi-eu.amazon.com", "GBP", "Amazon UK"),
    "A1RKKUPIHCS9HS": ("https://sellingpartnerapi-eu.amazon.com", "EUR", "Amazon ES"),
    "A13V1IB3VIYZZH": ("https://sellingpartnerapi-eu.amazon.com", "EUR", "Amazon FR"),
    "A1PA6795UKMFR9": ("https://sellingpartnerapi-eu.amazon.com", "EUR", "Amazon DE"),
    "A1VC38T7YXB528": ("https://sellingpartnerapi-fe.amazon.com", "JPY", "Amazon JP"),
}
DEFAULT_MARKETPLACE = "ATVPDKIKX0DER"


class AmazonError(RuntimeError):
    """Base for Amazon SP-API adapter errors."""

class AmazonAuthError(AmazonError):
    """Raised when LWA refresh or SP-API rejects credentials (401/403)."""

class AmazonRateLimitError(AmazonError):
    """Raised when SP-API returns 429 after retries are exhausted."""

class AmazonAPIError(AmazonError):
    """General non-2xx response from SP-API."""

class MissingSecretError(AmazonError):
    """Raised when any of the 3 LWA secrets is not configured."""


def _read_lwa_secrets(client_id, client_secret, refresh_token):
    cid = client_id or read_secret("AMAZON_LWA_CLIENT_ID")
    csec = client_secret or read_secret("AMAZON_LWA_CLIENT_SECRET")
    rtok = refresh_token or read_secret("AMAZON_LWA_REFRESH_TOKEN")
    missing = [n for n, v in (("AMAZON_LWA_CLIENT_ID", cid),
                              ("AMAZON_LWA_CLIENT_SECRET", csec),
                              ("AMAZON_LWA_REFRESH_TOKEN", rtok)) if not v]
    if missing:
        raise MissingSecretError(
            f"Missing Amazon LWA secrets: {', '.join(missing)}. "
            "Run: python3 secret_form.py --generate <KEY> --open")
    return cid, csec, rtok


class AmazonSPClient:
    """Token-managing SP-API client. Pure stdlib."""

    def __init__(self, marketplace_id: str = DEFAULT_MARKETPLACE,
                 client_id: str | None = None,
                 client_secret: str | None = None,
                 refresh_token: str | None = None) -> None:
        if marketplace_id not in MARKETPLACES:
            raise ValueError(f"unknown marketplace_id: {marketplace_id}")
        self.marketplace_id = marketplace_id
        self.host, self.currency, self.marketplace_name = MARKETPLACES[marketplace_id]
        self._client_id, self._client_secret, self._refresh_token = _read_lwa_secrets(
            client_id, client_secret, refresh_token)
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._access_token_expires_at - 60:
            return self._access_token
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": self._refresh_token,
            "client_id": self._client_id, "client_secret": self._client_secret,
        }).encode("utf-8")
        req = urllib.request.Request(
            LWA_TOKEN_ENDPOINT, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
                body, status = resp.read(), resp.status
        except urllib.error.HTTPError as e:
            body = e.read() if hasattr(e, "read") else b""
            status = e.code
        except urllib.error.URLError as e:
            raise AmazonError(f"LWA network error: {e}") from e
        if status in (400, 401, 403):
            raise AmazonAuthError(
                f"LWA refresh failed ({status}): {body[:200]!r}. "
                "Re-run: python3 secret_form.py --generate AMAZON_LWA_REFRESH_TOKEN")
        if status != 200:
            raise AmazonAPIError(f"LWA unexpected status {status}: {body[:200]!r}")
        try:
            obj = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise AmazonAPIError(f"LWA bad JSON: {e}") from e
        tok = obj.get("access_token")
        if not isinstance(tok, str) or not tok:
            raise AmazonAuthError("LWA response missing access_token")
        self._access_token = tok
        self._access_token_expires_at = time.time() + int(obj.get("expires_in", 3600))
        return tok

    def _headers(self) -> dict[str, str]:
        return {"x-amz-access-token": self._get_access_token(),
                "Accept": "application/json", "User-Agent": USER_AGENT}

    def _http_get(self, path: str, params: dict | None = None,
                  *, retries: int = 3) -> dict:
        qs = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                qs = "?" + urllib.parse.urlencode(clean, doseq=True)
        url = f"{self.host}{path}{qs}"
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
                    raise AmazonError(f"network error after {retries} retries: {e}") from e
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            if status == 429:
                attempt += 1
                if attempt > retries:
                    raise AmazonRateLimitError("rate limited (429) after retries")
                ra = headers.get("Retry-After") or headers.get("retry-after")
                try:
                    delay = float(ra) if ra else 60.0
                except ValueError:
                    delay = 60.0
                time.sleep(delay)
                req = urllib.request.Request(url, headers=self._headers(), method="GET")
                continue
            if status in (401, 403):
                raise AmazonAuthError(
                    f"SP-API rejected token ({status}) on {path}: {body[:200]!r}")
            if status == 404:
                raise AmazonAPIError(f"404 from {url}")
            if status >= 500:
                attempt += 1
                if attempt > retries:
                    raise AmazonAPIError(f"server error {status} after retries")
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue
            if status != 200:
                raise AmazonAPIError(f"unexpected HTTP {status} from {url}: {body[:200]!r}")
            try:
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise AmazonAPIError(f"bad JSON from {url}: {e}") from e
        raise AmazonError("exhausted retries")

    def get_orders(self, since_days: int = 30) -> list[dict]:
        since = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max(0, since_days))
        params: dict[str, Any] = {"MarketplaceIds": self.marketplace_id,
                                  "CreatedAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ")}
        out: list[dict] = []
        while True:
            data = self._http_get(f"/orders/{ORDERS_API_VERSION}/orders", params)
            payload = data.get("payload") or {}
            out.extend(payload.get("Orders") or [])
            nxt = payload.get("NextToken")
            if not nxt:
                break
            params = {"MarketplaceIds": self.marketplace_id, "NextToken": nxt}
            time.sleep(0.5)
        return out

    def get_order_items(self, order_id: str) -> list[dict]:
        params: dict[str, Any] = {}
        out: list[dict] = []
        path = f"/orders/{ORDERS_API_VERSION}/orders/{order_id}/orderItems"
        while True:
            data = self._http_get(path, params or None)
            payload = data.get("payload") or {}
            out.extend(payload.get("OrderItems") or [])
            nxt = payload.get("NextToken")
            if not nxt:
                break
            params = {"NextToken": nxt}
        return out

    def search_catalog(self, keyword: str | None = None,
                       asin: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"marketplaceIds": self.marketplace_id,
                                  "includedData": "summaries,attributes,identifiers"}
        if asin:
            params["identifiers"] = asin
            params["identifiersType"] = "ASIN"
        elif keyword:
            params["keywords"] = keyword
        else:
            raise ValueError("search_catalog requires keyword or asin")
        out: list[dict] = []
        while True:
            data = self._http_get(f"/catalog/{CATALOG_API_VERSION}/items", params)
            out.extend(data.get("items") or [])
            nxt = (data.get("pagination") or {}).get("nextToken")
            if not nxt:
                break
            params = {"marketplaceIds": self.marketplace_id, "pageToken": nxt}
        return out


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
    Defense in depth — see adapter_shopify._sanitize_for_event."""
    s = str(v or "")
    for c in "<>&\"'":
        s = s.replace(c, "")
    return s[:200]


def _parse_amazon_ts(value: str | None) -> int | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return int(_dt.datetime.strptime(value, fmt).timestamp())
        except ValueError:
            continue
    return None


def _upsert_store(db: sqlite3.Connection, store_id: str, marketplace_id: str) -> None:
    now = int(time.time())
    _, currency, name = MARKETPLACES.get(marketplace_id,
                                         ("", "USD", f"Amazon {marketplace_id}"))
    url = f"https://sellercentral.amazon.com/?marketplace={marketplace_id}"
    if db.execute("SELECT id FROM stores WHERE id=?", (store_id,)).fetchone():
        db.execute("UPDATE stores SET name=?, platform=?, url=?, currency=?, updated_at=? WHERE id=?",
                   (name, "amazon", url, currency, now, store_id))
    else:
        db.execute("INSERT INTO stores(id, name, platform, url, currency, created_at, updated_at) "
                   "VALUES (?,?,?,?,?,?,?)",
                   (store_id, name, "amazon", url, currency, now, now))


def _extract_catalog_sku_title(item: dict) -> tuple[str, str | None]:
    attrs = item.get("attributes") or {}
    part_number = attrs.get("partNumber") or attrs.get("part_number") or []
    sku = ""
    if isinstance(part_number, list) and part_number:
        sku = str(part_number[0].get("value") or "").strip()
    summaries = item.get("summaries") or []
    title = summaries[0].get("itemName") if isinstance(summaries, list) and summaries else None
    if not sku:
        sku = str(item.get("asin") or f"p_{uuid.uuid4().hex[:10]}")
    return sku, title


def _store_catalog_items(db: sqlite3.Connection, store_id: str,
                         items: list[dict], warnings: list[str]) -> int:
    now = int(time.time())
    count = 0
    for it in items:
        asin = str(it.get("asin") or "")
        sku, title = _extract_catalog_sku_title(it)
        pid = asin or sku
        data_json = json.dumps({"asin": asin, "summaries": it.get("summaries"),
                                "attributes_keys": list((it.get("attributes") or {}).keys())},
                               ensure_ascii=False)
        if db.execute("SELECT id FROM products WHERE id=? AND store_id=?",
                      (pid, store_id)).fetchone():
            db.execute("UPDATE products SET sku=?, title=?, status=?, price_usd=NULL, "
                       "data_json=?, updated_at=? WHERE id=? AND store_id=?",
                       (sku, title, "active", data_json, now, pid, store_id))
        else:
            db.execute("INSERT INTO products(id, store_id, sku, title, status, cost_usd, "
                       "price_usd, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pid, store_id, sku, title, "active", None, None, data_json, now, now))
        count += 1
    if count:
        warnings.append(
            f"Imported {count} catalog item(s) with NULL price — SP-API Catalog "
            "does not return price. Use csv-import for accurate pricing.")
    return count


def _store_orders(db: sqlite3.Connection, store_id: str,
                  orders: list[dict]) -> tuple[int, int]:
    now = int(time.time())
    orders_count = 0
    cust_agg: dict[str, dict] = {}
    for o in orders:
        # Sanitize merchant-controlled strings — defense in depth before HTML render.
        order_no_raw = o.get("AmazonOrderId") or o.get("SellerOrderId") or "?"
        order_no = _sanitize_for_event(order_no_raw)
        total_obj = o.get("OrderTotal") or {}
        total = _to_float(total_obj.get("Amount"))
        currency = _sanitize_for_event(total_obj.get("CurrencyCode") or "USD")
        items_n = _to_float(o.get("NumberOfItemsShipped", 0)) \
            + _to_float(o.get("NumberOfItemsUnshipped", 0))
        ts = _parse_amazon_ts(o.get("PurchaseDate")) or now
        db.execute("INSERT INTO events(store_id, ts, category, content) VALUES (?,?,?,?)",
                   (store_id, ts, "order",
                    f"Order {order_no} · {currency} {total:.2f} · {int(items_n)} items"))
        orders_count += 1
        buyer = o.get("BuyerInfo") or {}
        email = (buyer.get("BuyerEmail") or "").strip().lower() or None
        name = buyer.get("BuyerName") or None
        cid = email or name or str(o.get("AmazonOrderId") or "")
        if not cid:
            continue
        agg = cust_agg.setdefault(cid, {"email": email, "name": name, "order_count": 0,
                                        "total_spent": 0.0, "first": ts, "last": ts})
        agg["order_count"] += 1
        agg["total_spent"] += total
        agg["first"] = min(agg["first"], ts)
        agg["last"] = max(agg["last"], ts)
    touched = 0
    for cid, agg in cust_agg.items():
        if db.execute("SELECT id FROM customers WHERE id=? AND store_id=?",
                      (cid, store_id)).fetchone():
            db.execute("UPDATE customers SET email=COALESCE(?,email), name=COALESCE(?,name), "
                       "total_spent=?, order_count=?, last_order_at=?, updated_at=? "
                       "WHERE id=? AND store_id=?",
                       (agg["email"], agg["name"], agg["total_spent"], agg["order_count"],
                        agg["last"], now, cid, store_id))
        else:
            db.execute("INSERT INTO customers(id, store_id, email, name, total_spent, order_count, "
                       "first_order_at, last_order_at, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (cid, store_id, agg["email"], agg["name"], agg["total_spent"],
                        agg["order_count"], agg["first"], agg["last"], now, now))
        touched += 1
    return orders_count, touched


def _mock_payload(marketplace_id: str) -> dict:
    return {
        "items": [
            {"asin": "B08MOCK001",
             "summaries": [{"itemName": "Mock Echo Dot"}],
             "attributes": {"partNumber": [{"value": "MOCK-ED-001"}]}},
            {"asin": "B08MOCK002",
             "summaries": [{"itemName": "Mock Fire Stick"}],
             "attributes": {"partNumber": [{"value": "MOCK-FS-002"}]}},
        ],
        "orders": [
            {"AmazonOrderId": "111-2222222-3333333",
             "PurchaseDate": "2026-04-15T10:00:00Z",
             "OrderTotal": {"Amount": "29.99",
                            "CurrencyCode": MARKETPLACES[marketplace_id][1]},
             "NumberOfItemsShipped": 1, "NumberOfItemsUnshipped": 0,
             "BuyerInfo": {"BuyerName": "Mock Buyer",
                           "BuyerEmail": "mock-buyer@marketplace.amazon.com"}},
        ],
    }


def _safe_fetch(fn, label: str, warnings: list[str]) -> list[dict]:
    try:
        return fn()
    except (AmazonAuthError, MissingSecretError):
        raise
    except AmazonError as exc:
        warnings.append(f"{label} fetch failed: {exc}")
        return []


def import_amazon_store(
    marketplace_id: str = DEFAULT_MARKETPLACE,
    *,
    store_id: str | None = None,
    days: int = 30,
    asin_list: list[str] | None = None,
    dry_run: bool = False,
    only: str | None = None,
    mock: bool = False,
    _client: AmazonSPClient | None = None,
) -> dict:
    """Full import flow. See module docstring for return shape."""
    started = time.time()
    warnings: list[str] = []
    sid = store_id or f"s_{uuid.uuid4().hex[:10]}"
    if marketplace_id not in MARKETPLACES:
        raise AmazonError(f"unknown marketplace_id: {marketplace_id}")

    if mock:
        d = _mock_payload(marketplace_id)
        items = (d["items"][:max(1, len(asin_list))]
                 if asin_list and only in (None, "products") else [])
        orders = d["orders"] if only in (None, "orders") else []
    else:
        c = _client or AmazonSPClient(marketplace_id)
        items = []
        if only in (None, "products") and asin_list:
            for asin in asin_list:
                items.extend(_safe_fetch(
                    lambda a=asin: c.search_catalog(asin=a),
                    f"catalog[{asin}]", warnings))
        orders = _safe_fetch(lambda: c.get_orders(since_days=days),
                             "orders", warnings) if only in (None, "orders") else []

    products_imported = orders_imported = customers_imported = 0
    if dry_run:
        products_imported = len(items)
        orders_imported = len(orders)
        customers_imported = sum(1 for o in orders if o.get("BuyerInfo"))
    else:
        db = _open_db()
        try:
            _upsert_store(db, sid, marketplace_id)
            if only in (None, "products") and items:
                products_imported = _store_catalog_items(db, sid, items, warnings)
            if only in (None, "orders"):
                orders_imported, customers_imported = _store_orders(db, sid, orders)
            db.commit()
        finally:
            db.close()

    _, currency, name = MARKETPLACES[marketplace_id]
    return {
        "store_id": sid, "marketplace_id": marketplace_id,
        "marketplace_name": name, "currency": currency,
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
    p = argparse.ArgumentParser(description="Lumicc Amazon SP-API adapter")
    p.add_argument("--marketplace", default=DEFAULT_MARKETPLACE,
                   help=f"Marketplace ID (default {DEFAULT_MARKETPLACE} = US)")
    p.add_argument("--store-id", dest="store_id", default=None)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--asins", default=None,
                   help="Comma-separated ASINs to fetch from catalog")
    p.add_argument("--only", choices=["products", "orders"], default=None)
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--mock", action="store_true", help="No HTTP; use fixture data")
    p.add_argument("--quiet-stdout", action="store_true", dest="quiet")
    args = p.parse_args(argv)

    asin_list = [a.strip() for a in args.asins.split(",") if a.strip()] if args.asins else None

    if not args.quiet:
        sys.stderr.write(f"[adapter_amazon_sp] marketplace={args.marketplace}\n")
    try:
        result = import_amazon_store(
            args.marketplace, store_id=args.store_id, days=args.days,
            asin_list=asin_list, dry_run=args.dry_run, only=args.only,
            mock=args.mock)
    except MissingSecretError as exc:
        _emit({"adapter": "amazon_sp", "error": "missing_secret",
               "message": str(exc), "marketplace": args.marketplace}, args.quiet)
        return 2
    except AmazonAuthError as exc:
        _emit({"adapter": "amazon_sp", "error": "auth",
               "message": str(exc), "marketplace": args.marketplace}, args.quiet)
        return 3
    except AmazonRateLimitError as exc:
        _emit({"adapter": "amazon_sp", "error": "rate_limit",
               "message": str(exc), "marketplace": args.marketplace}, args.quiet)
        return 4
    except AmazonError as exc:
        _emit({"adapter": "amazon_sp", "error": "amazon",
               "message": str(exc), "marketplace": args.marketplace}, args.quiet)
        return 1

    _emit({"adapter": "amazon_sp", "marketplace": args.marketplace, **result}, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
