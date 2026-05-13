#!/usr/bin/env python3
"""Tests for adapter_amazon_sp.py — pure stdlib, urllib mocked."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import adapter_amazon_sp as A  # noqa: E402
from adapter_amazon_sp import (  # noqa: E402
    AmazonAPIError,
    AmazonAuthError,
    AmazonRateLimitError,
    AmazonSPClient,
    MissingSecretError,
    import_amazon_store,
)


class _FakeResp:
    def __init__(self, body: bytes, status: int = 200,
                 headers: dict | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _json_resp(obj: dict, status: int = 200, headers: dict | None = None) -> _FakeResp:
    return _FakeResp(json.dumps(obj).encode("utf-8"), status, headers or {})


def _http_error(url: str, status: int, body: bytes = b"",
                headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, status, "err", headers or {}, io.BytesIO(body))


def _lwa_ok() -> _FakeResp:
    return _json_resp({"access_token": "Atza|FAKE", "expires_in": 3600})


def _make_client(**kw) -> AmazonSPClient:
    return AmazonSPClient(
        client_id="ci", client_secret="cs", refresh_token="Atzr|FAKE", **kw)


class TestSecrets(unittest.TestCase):
    def test_each_secret_missing(self) -> None:
        # All read_secret returns -> only specific one missing triggers error
        cases = [
            (None, "cs", "rt", "AMAZON_LWA_CLIENT_ID"),
            ("ci", None, "rt", "AMAZON_LWA_CLIENT_SECRET"),
            ("ci", "cs", None, "AMAZON_LWA_REFRESH_TOKEN"),
        ]
        for cid, csec, rtok, expected in cases:
            with patch.object(A, "read_secret", return_value=None):
                with self.assertRaises(MissingSecretError) as ctx:
                    AmazonSPClient(client_id=cid, client_secret=csec,
                                   refresh_token=rtok)
                self.assertIn(expected, str(ctx.exception))

    def test_all_present(self) -> None:
        c = _make_client()
        self.assertEqual(c.marketplace_id, "ATVPDKIKX0DER")
        self.assertEqual(c.currency, "USD")


class TestTokenExchange(unittest.TestCase):
    def test_caches_access_token(self) -> None:
        c = _make_client()
        with patch("urllib.request.urlopen", return_value=_lwa_ok()) as m:
            self.assertEqual(c._get_access_token(), "Atza|FAKE")
            self.assertEqual(c._get_access_token(), "Atza|FAKE")
            self.assertEqual(m.call_count, 1)  # cached

    def test_auth_error_on_401(self) -> None:
        c = _make_client()

        def raise401(*_a, **_k):
            raise _http_error("https://api.amazon.com/auth/o2/token", 401,
                              b'{"error":"invalid_grant"}')

        with patch("urllib.request.urlopen", side_effect=raise401):
            with self.assertRaises(AmazonAuthError):
                c._get_access_token()

    def test_missing_access_token_field(self) -> None:
        c = _make_client()
        with patch("urllib.request.urlopen",
                   return_value=_json_resp({"expires_in": 3600})):
            with self.assertRaises(AmazonAuthError):
                c._get_access_token()


class TestPaginatedOrders(unittest.TestCase):
    def test_orders_paginate_two_pages(self) -> None:
        c = _make_client()
        page1 = _json_resp({"payload": {
            "Orders": [{"AmazonOrderId": "A-1",
                        "PurchaseDate": "2026-05-01T00:00:00Z",
                        "OrderTotal": {"Amount": "10.00", "CurrencyCode": "USD"}}],
            "NextToken": "TOKEN-2",
        }})
        page2 = _json_resp({"payload": {
            "Orders": [{"AmazonOrderId": "A-2",
                        "PurchaseDate": "2026-05-02T00:00:00Z",
                        "OrderTotal": {"Amount": "20.00", "CurrencyCode": "USD"}}],
        }})

        responses = [_lwa_ok(), page1, page2]

        def fake(*_a, **_k):
            return responses.pop(0)

        with patch("urllib.request.urlopen", side_effect=fake), \
             patch("time.sleep"):
            orders = c.get_orders(since_days=30)
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0]["AmazonOrderId"], "A-1")
        self.assertEqual(orders[1]["AmazonOrderId"], "A-2")


class TestRateLimit(unittest.TestCase):
    def test_429_retries_with_backoff(self) -> None:
        c = _make_client()
        # token already cached
        c._access_token = "Atza|FAKE"
        c._access_token_expires_at = 9_999_999_999

        counter = {"calls": 0}

        def fake(*_a, **_k):
            counter["calls"] += 1
            if counter["calls"] == 1:
                raise _http_error("https://x", 429, b"", {"Retry-After": "1"})
            return _json_resp({"payload": {"Orders": []}})

        sleeps: list[float] = []
        with patch("urllib.request.urlopen", side_effect=fake), \
             patch("time.sleep", side_effect=lambda s: sleeps.append(s)):
            orders = c.get_orders(since_days=1)
        self.assertEqual(orders, [])
        self.assertGreaterEqual(counter["calls"], 2)
        self.assertIn(1.0, sleeps)

    def test_429_exhausts_retries(self) -> None:
        c = _make_client()
        c._access_token = "Atza|FAKE"
        c._access_token_expires_at = 9_999_999_999

        def fake(*_a, **_k):
            raise _http_error("https://x", 429, b"", {"Retry-After": "0"})

        with patch("urllib.request.urlopen", side_effect=fake), \
             patch("time.sleep"):
            with self.assertRaises(AmazonRateLimitError):
                c.get_orders(since_days=1)


class TestCatalog(unittest.TestCase):
    def test_search_by_asin(self) -> None:
        c = _make_client()
        catalog = _json_resp({"items": [
            {"asin": "B08P4K7ZGP",
             "summaries": [{"itemName": "Echo Dot (4th Gen)"}],
             "attributes": {"partNumber": [{"value": "ED-4G-001"}]}},
        ]})
        with patch("urllib.request.urlopen", side_effect=[_lwa_ok(), catalog]):
            items = c.search_catalog(asin="B08P4K7ZGP")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["asin"], "B08P4K7ZGP")

    def test_search_requires_keyword_or_asin(self) -> None:
        c = _make_client()
        with self.assertRaises(ValueError):
            c.search_catalog()


class TestImportFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        os.environ["LUMICC_DATA_ROOT"] = self.tmp

    def tearDown(self) -> None:
        os.environ.pop("LUMICC_DATA_ROOT", None)

    def test_mock_mode_no_http(self) -> None:
        # Patch urlopen so any real call would fail loudly
        with patch("urllib.request.urlopen",
                   side_effect=AssertionError("no HTTP in mock mode")):
            result = import_amazon_store(
                "ATVPDKIKX0DER", days=30, asin_list=["B08MOCK001"],
                mock=True)
        self.assertEqual(result["marketplace_id"], "ATVPDKIKX0DER")
        self.assertEqual(result["marketplace_name"], "Amazon US")
        self.assertGreaterEqual(result["orders_imported"], 1)
        self.assertGreaterEqual(result["products_imported"], 1)

    def test_catalog_import_emits_null_price_warning(self) -> None:
        c = _make_client()
        c._access_token = "Atza|FAKE"
        c._access_token_expires_at = 9_999_999_999
        catalog = _json_resp({"items": [
            {"asin": "B08P4K7ZGP",
             "summaries": [{"itemName": "Echo Dot"}],
             "attributes": {"partNumber": [{"value": "ED-001"}]}},
        ]})
        orders_empty = _json_resp({"payload": {"Orders": []}})
        with patch("urllib.request.urlopen", side_effect=[catalog, orders_empty]), \
             patch("time.sleep"):
            result = import_amazon_store(
                "ATVPDKIKX0DER", asin_list=["B08P4K7ZGP"], days=1,
                _client=c)
        self.assertEqual(result["products_imported"], 1)
        joined = " ".join(result["warnings"])
        self.assertIn("NULL price", joined)
        # Verify DB row has NULL price
        import sqlite3
        db = sqlite3.connect(Path(self.tmp) / "store.db")
        row = db.execute(
            "SELECT price_usd, title FROM products WHERE id=?",
            ("B08P4K7ZGP",)).fetchone()
        db.close()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])
        self.assertEqual(row[1], "Echo Dot")

    def test_auth_error_propagates(self) -> None:
        # MissingSecretError should propagate, not be wrapped into warnings
        with patch.object(A, "read_secret", return_value=None):
            with self.assertRaises(MissingSecretError):
                import_amazon_store("ATVPDKIKX0DER", days=1)

    def test_orders_imported_with_buyer(self) -> None:
        c = _make_client()
        c._access_token = "Atza|FAKE"
        c._access_token_expires_at = 9_999_999_999
        orders = _json_resp({"payload": {"Orders": [
            {"AmazonOrderId": "111-1",
             "PurchaseDate": "2026-05-01T00:00:00Z",
             "OrderTotal": {"Amount": "49.99", "CurrencyCode": "USD"},
             "NumberOfItemsShipped": 1, "NumberOfItemsUnshipped": 0,
             "BuyerInfo": {"BuyerEmail": "buyer@x.com", "BuyerName": "B"}}
        ]}})
        with patch("urllib.request.urlopen", side_effect=[orders]), \
             patch("time.sleep"):
            result = import_amazon_store(
                "ATVPDKIKX0DER", days=1, _client=c, only="orders")
        self.assertEqual(result["orders_imported"], 1)
        self.assertEqual(result["customers_imported"], 1)


class TestUnknownMarketplace(unittest.TestCase):
    def test_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            AmazonSPClient(marketplace_id="ZZZZ",
                           client_id="ci", client_secret="cs",
                           refresh_token="rt")


if __name__ == "__main__":
    unittest.main()
