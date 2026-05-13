#!/usr/bin/env python3
"""Tests for adapter_indep.py. Mocks urllib.request.urlopen."""
from __future__ import annotations

import io
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
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_urlopen(routes: dict[str, _FakeResponse | Exception]):
    """Return a callable that picks a fake response by URL substring."""
    def _fake(req, timeout=15):  # noqa: ARG001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for needle, resp in routes.items():
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise urllib.error.URLError(f"no fake route for {url}")
    return _fake


class IndepAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["LUMICC_DATA_ROOT"] = self._tmp.name
        for m in ("adapter_indep",):
            if m in sys.modules:
                del sys.modules[m]
        import adapter_indep
        self.adapter = adapter_indep

    def tearDown(self) -> None:
        os.environ.pop("LUMICC_DATA_ROOT", None)
        self._tmp.cleanup()

    def _write_secret(self, key: str, value: str) -> None:
        sec_dir = Path(self._tmp.name) / "secrets"
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / f"{key}.json").write_text(
            json.dumps({"key": key, "value": value}), encoding="utf-8"
        )

    # 1. Plausible parse from mocked JSON
    def test_fetch_plausible_stats_parses_response(self) -> None:
        agg = {"results": {"pageviews": {"value": 4321},
                           "visitors": {"value": 987},
                           "bounce_rate": {"value": 38.4}}}
        breakdown = {"results": [
            {"source": "Direct / None", "visitors": 500},
            {"source": "Google", "visitors": 300},
        ]}
        routes = {
            "/stats/aggregate": _FakeResponse(json.dumps(agg).encode()),
            "/stats/breakdown": _FakeResponse(json.dumps(breakdown).encode()),
        }
        with mock.patch("urllib.request.urlopen", _make_urlopen(routes)):
            stats = self.adapter.fetch_plausible_stats("FAKEKEY", "example.com", days=90)
        self.assertEqual(stats["pageviews"], 4321)
        self.assertEqual(stats["visitors"], 987)
        self.assertEqual(len(stats["sources"]), 2)
        self.assertEqual(stats["sources"][0]["source"], "Direct / None")

    # 2. Products from /data/products.json (lumiclaw-shaped)
    def test_fetch_products_from_url_json_endpoint(self) -> None:
        lumi = [
            {"id": "1", "slug": "magic-cleaning-sponge",
             "name": {"en": "Melamine Sponge", "zh": "魔力海绵"},
             "price": 8.99, "asin": "B08P4K7ZGP"},
            {"id": "2", "slug": "foldable-hanger",
             "name": {"en": "Foldable Hanger", "zh": "折叠衣架"},
             "price": 12.50},
        ]
        routes = {
            "/data/products.json": _FakeResponse(json.dumps(lumi).encode()),
        }
        with mock.patch("urllib.request.urlopen", _make_urlopen(routes)):
            items = self.adapter.fetch_products_from_url("https://example.com")
        self.assertEqual(len(items), 2)
        titles = [p["title"] for p in items]
        self.assertIn("Melamine Sponge", titles)
        self.assertEqual(items[0]["price"], 8.99)

    def test_fetch_products_falls_back_to_sitemap(self) -> None:
        sitemap = (
            "<?xml version='1.0'?><urlset>"
            "<url><loc>https://example.com/products/alpha</loc></url>"
            "<url><loc>https://example.com/products/beta</loc></url>"
            "<url><loc>https://example.com/about</loc></url>"
            "</urlset>"
        )

        def _fake(req, timeout=15):  # noqa: ARG001
            url = req.full_url
            if "/data/products.json" in url or "/api/products" in url or "/products.json" in url:
                raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
            if "/sitemap.xml" in url:
                return _FakeResponse(sitemap.encode())
            raise urllib.error.URLError("no route")

        with mock.patch("urllib.request.urlopen", _fake):
            items = self.adapter.fetch_products_from_url("https://example.com")
        self.assertEqual(len(items), 2)
        skus = sorted(p["sku"] for p in items)
        self.assertEqual(skus, ["alpha", "beta"])

    # 3. Missing PLAUSIBLE_API_KEY → graceful, products still tried
    def test_initialize_missing_api_key(self) -> None:
        lumi = [{"id": "1", "slug": "thing", "name": "Thing", "price": 5.0}]
        routes = {
            "/data/products.json": _FakeResponse(json.dumps(lumi).encode()),
        }
        with mock.patch("urllib.request.urlopen", _make_urlopen(routes)):
            res = self.adapter.initialize_store_from_indep_site(
                "https://example.com", site_name="Demo"
            )
        self.assertEqual(res["products_count"], 1)
        self.assertEqual(res["events_count"], 0)
        self.assertTrue(any("PLAUSIBLE_API_KEY missing" in w for w in res["warnings"]))

    def test_initialize_with_api_key_stores_event(self) -> None:
        self._write_secret("PLAUSIBLE_API_KEY", "test-key-123")
        lumi = [{"id": "1", "slug": "thing", "name": "Thing", "price": 5.0}]
        agg = {"results": {"pageviews": 100, "visitors": 50, "bounce_rate": 25}}
        breakdown = {"results": [{"source": "Direct / None", "visitors": 50}]}
        routes = {
            "/data/products.json": _FakeResponse(json.dumps(lumi).encode()),
            "/stats/aggregate": _FakeResponse(json.dumps(agg).encode()),
            "/stats/breakdown": _FakeResponse(json.dumps(breakdown).encode()),
        }
        with mock.patch("urllib.request.urlopen", _make_urlopen(routes)):
            res = self.adapter.initialize_store_from_indep_site(
                "https://example.com", site_name="Demo"
            )
        self.assertEqual(res["products_count"], 1)
        self.assertEqual(res["events_count"], 1)
        db = sqlite3.connect(Path(self._tmp.name) / "store.db")
        ev = db.execute("SELECT content FROM events WHERE category='traffic'").fetchone()
        self.assertIsNotNone(ev)
        payload = json.loads(ev[0])
        self.assertEqual(payload["pageviews"], 100)
        db.close()

    # 4. Unreachable URL → warnings, no crash
    def test_initialize_unreachable_url(self) -> None:
        def _fake(req, timeout=15):  # noqa: ARG001
            raise urllib.error.URLError("Name or service not known")

        with mock.patch("urllib.request.urlopen", _fake):
            res = self.adapter.initialize_store_from_indep_site(
                "https://nothing.invalid", site_name="Ghost"
            )
        self.assertEqual(res["products_count"], 0)
        self.assertTrue(any("No products discovered" in w for w in res["warnings"]))
        # Store still created
        db = sqlite3.connect(Path(self._tmp.name) / "store.db")
        n = db.execute("SELECT COUNT(*) AS n FROM stores").fetchone()[0]
        self.assertEqual(n, 1)
        db.close()


if __name__ == "__main__":
    unittest.main()
