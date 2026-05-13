#!/usr/bin/env python3
"""Tests for adapter_shopify.py. Mocks urllib.request.urlopen."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200,
                 headers: dict | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _resp(payload: dict, status: int = 200,
          headers: dict | None = None) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"), status, headers or {})


def _make_router(routes: list):
    """routes: list of (predicate, response_or_exception_or_list).

    A list value pops left on each call (allows simulating retries / pagination).
    """
    def _fake(req, timeout=20):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for pred, resp in routes:
            if pred(url):
                if isinstance(resp, list):
                    item = resp.pop(0)
                else:
                    item = resp
                if isinstance(item, Exception):
                    raise item
                return item
        raise urllib.error.URLError(f"no fake route for {url}")
    return _fake


class ShopifyAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["LUMICC_DATA_ROOT"] = self._tmp.name
        # Force reimport so module picks up env var.
        for m in ("adapter_shopify",):
            if m in sys.modules:
                del sys.modules[m]
        import adapter_shopify
        self.adapter = adapter_shopify

    def tearDown(self) -> None:
        os.environ.pop("LUMICC_DATA_ROOT", None)
        self._tmp.cleanup()

    # -- helpers -------------------------------------------------------
    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(Path(self._tmp.name) / "store.db")

    def _client(self):
        return self.adapter.ShopifyClient("mystore.myshopify.com",
                                          access_token="tok-123")

    # -- tests ---------------------------------------------------------
    def test_get_shop_creates_store_row(self) -> None:
        routes = [
            (lambda u: "/shop.json" in u,
             _resp({"shop": {"name": "Aurora Co", "currency": "EUR",
                             "myshopify_domain": "aurora.myshopify.com",
                             "domain": "aurora.com"}})),
            (lambda u: "/products.json" in u, _resp({"products": []})),
            (lambda u: "/orders.json" in u, _resp({"orders": []})),
            (lambda u: "/customers.json" in u, _resp({"customers": []})),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=_make_router(routes)):
            client = self._client()
            result = self.adapter.import_shopify_store(
                "mystore.myshopify.com", days=30, _client=client,
            )
        self.assertEqual(result["shop_name"], "Aurora Co")
        self.assertEqual(result["currency"], "EUR")
        row = self._db().execute(
            "SELECT name, currency, platform FROM stores"
        ).fetchone()
        self.assertEqual(row, ("Aurora Co", "EUR", "shopify"))

    def test_pagination_follows_link_header(self) -> None:
        p1 = _resp(
            {"products": [
                {"id": 1, "title": "A", "status": "active",
                 "variants": [{"sku": "A-1", "price": "10.00"}]},
                {"id": 2, "title": "B", "status": "draft",
                 "variants": [{"sku": "B-1", "price": "20.00"}]},
            ]},
            headers={"Link": '<https://mystore.myshopify.com/admin/api/'
                             '2024-10/products.json?page_info=NEXT>; rel="next"'},
        )
        p2 = _resp(
            {"products": [
                {"id": 3, "title": "C", "status": "archived",
                 "variants": [{"sku": "C-1", "price": "30.00"}]},
            ]},
        )
        routes = [
            (lambda u: "/shop.json" in u,
             _resp({"shop": {"name": "Shop", "currency": "USD"}})),
            (lambda u: "page_info=NEXT" in u, p2),
            (lambda u: "/products.json" in u, p1),
            (lambda u: "/orders.json" in u, _resp({"orders": []})),
            (lambda u: "/customers.json" in u, _resp({"customers": []})),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=_make_router(routes)):
            result = self.adapter.import_shopify_store(
                "mystore.myshopify.com", _client=self._client(),
            )
        self.assertEqual(result["products_imported"], 3)
        rows = self._db().execute(
            "SELECT title, status FROM products ORDER BY title"
        ).fetchall()
        titles = [r[0] for r in rows]
        statuses = {r[0]: r[1] for r in rows}
        self.assertEqual(titles, ["A", "B", "C"])
        # archived → removed mapping
        self.assertEqual(statuses["C"], "removed")
        self.assertEqual(statuses["A"], "active")
        self.assertEqual(statuses["B"], "draft")

    def test_orders_create_events_and_customers(self) -> None:
        orders = [
            {"id": 100, "name": "#1001", "total_price": "49.00",
             "currency": "USD", "created_at": "2026-04-01T10:00:00Z",
             "line_items": [{"id": 1}, {"id": 2}],
             "customer": {"id": 9001, "first_name": "Ada",
                          "last_name": "Lin", "email": "ada@example.com"}},
            {"id": 101, "name": "#1002", "total_price": "99.00",
             "currency": "USD", "created_at": "2026-04-05T10:00:00Z",
             "line_items": [{"id": 3}],
             "customer": {"id": 9001, "email": "ada@example.com"}},
            {"id": 102, "name": "#1003", "total_price": "25.00",
             "currency": "USD", "created_at": "2026-04-10T10:00:00Z",
             "line_items": [{"id": 4}],
             "customer": {"id": 9002, "email": "bo@example.com"}},
        ]
        routes = [
            (lambda u: "/shop.json" in u,
             _resp({"shop": {"name": "S", "currency": "USD"}})),
            (lambda u: "/products.json" in u, _resp({"products": []})),
            (lambda u: "/orders.json" in u, _resp({"orders": orders})),
            (lambda u: "/customers.json" in u, _resp({"customers": []})),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=_make_router(routes)):
            result = self.adapter.import_shopify_store(
                "mystore.myshopify.com", _client=self._client(),
            )
        self.assertEqual(result["orders_imported"], 3)
        db = self._db()
        n_events = db.execute(
            "SELECT COUNT(*) FROM events WHERE category='order'"
        ).fetchone()[0]
        self.assertEqual(n_events, 3)
        cust = db.execute(
            "SELECT id, total_spent, order_count FROM customers ORDER BY id"
        ).fetchall()
        self.assertEqual(len(cust), 2)
        ada = [c for c in cust if c[0] == "9001"][0]
        self.assertAlmostEqual(ada[1], 148.0)
        self.assertEqual(ada[2], 2)

    def test_customers_updated(self) -> None:
        customers = [
            {"id": 9001, "first_name": "Ada", "last_name": "Lin",
             "email": "ada@example.com", "total_spent": "199.00",
             "orders_count": 3,
             "addresses": [{"country": "US"}]},
            {"id": 9002, "email": "bo@example.com",
             "total_spent": "25.00", "orders_count": 1,
             "addresses": []},
        ]
        routes = [
            (lambda u: "/shop.json" in u,
             _resp({"shop": {"name": "S", "currency": "USD"}})),
            (lambda u: "/products.json" in u, _resp({"products": []})),
            (lambda u: "/orders.json" in u, _resp({"orders": []})),
            (lambda u: "/customers.json" in u, _resp({"customers": customers})),
        ]
        with mock.patch("urllib.request.urlopen", side_effect=_make_router(routes)):
            result = self.adapter.import_shopify_store(
                "mystore.myshopify.com", _client=self._client(),
            )
        self.assertEqual(result["customers_imported"], 2)
        row = self._db().execute(
            "SELECT email, total_spent, order_count, data_json "
            "FROM customers WHERE id='9001'"
        ).fetchone()
        self.assertEqual(row[0], "ada@example.com")
        self.assertAlmostEqual(row[1], 199.0)
        self.assertEqual(row[2], 3)
        self.assertIn("US", row[3])

    def test_401_raises_auth_error(self) -> None:
        def _raise(req, timeout=20):  # noqa: ARG001
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized",
                hdrs={}, fp=None,  # type: ignore[arg-type]
            )
        with mock.patch("urllib.request.urlopen", side_effect=_raise):
            with self.assertRaises(self.adapter.ShopifyAuthError):
                self.adapter.import_shopify_store(
                    "mystore.myshopify.com", _client=self._client(),
                )

    def test_429_retries_then_succeeds(self) -> None:
        counter = {"n": 0}

        def _fake(req, timeout=20):  # noqa: ARG001
            url = req.full_url
            if "/shop.json" in url:
                counter["n"] += 1
                if counter["n"] == 1:
                    raise urllib.error.HTTPError(
                        url, 429, "Too Many", hdrs={"Retry-After": "0"},  # type: ignore[arg-type]
                        fp=None,
                    )
                return _resp({"shop": {"name": "OK", "currency": "USD"}})
            if "/products.json" in url:
                return _resp({"products": []})
            if "/orders.json" in url:
                return _resp({"orders": []})
            if "/customers.json" in url:
                return _resp({"customers": []})
            raise urllib.error.URLError("?")

        with mock.patch("urllib.request.urlopen", side_effect=_fake):
            with mock.patch("time.sleep"):  # don't actually sleep
                result = self.adapter.import_shopify_store(
                    "mystore.myshopify.com", _client=self._client(),
                )
        self.assertEqual(counter["n"], 2)
        self.assertEqual(result["shop_name"], "OK")

    def test_missing_secret_raises(self) -> None:
        # Force no token via env + secret_form returning None.
        with mock.patch.object(self.adapter, "read_secret", return_value=None):
            with self.assertRaises(self.adapter.MissingSecretError):
                self.adapter.ShopifyClient("mystore.myshopify.com")

    def test_mock_mode_no_http(self) -> None:
        # Patch urlopen to blow up if called; mock mode must not touch HTTP.
        def _boom(*a, **k):  # noqa: ARG001
            raise AssertionError("HTTP should not be called in --mock mode")
        with mock.patch("urllib.request.urlopen", side_effect=_boom):
            result = self.adapter.import_shopify_store(
                "irrelevant.myshopify.com", mock=True,
            )
        self.assertEqual(result["shop_name"], "Mock Store")
        self.assertEqual(result["currency"], "USD")
        self.assertGreaterEqual(result["products_imported"], 4)
        self.assertGreaterEqual(result["orders_imported"], 1)
        self.assertGreaterEqual(result["customers_imported"], 1)

    def test_link_header_parsing(self) -> None:
        link = ('<https://x/admin/api/2024-10/products.json?page_info=A>; rel="previous", '
                '<https://x/admin/api/2024-10/products.json?page_info=B>; rel="next"')
        self.assertEqual(
            self.adapter._parse_link_next(link),
            "https://x/admin/api/2024-10/products.json?page_info=B",
        )
        self.assertIsNone(self.adapter._parse_link_next(None))
        self.assertIsNone(self.adapter._parse_link_next(""))


if __name__ == "__main__":
    unittest.main()
