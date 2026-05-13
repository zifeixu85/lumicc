#!/usr/bin/env python3
"""Tests for adapter_csv.py.

Uses LUMICC_DATA_ROOT override to redirect store.db to a temp dir.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


class CSVAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["LUMICC_DATA_ROOT"] = self._tmp.name
        # Reload module so any cached _data_root sees the new env.
        for m in ("adapter_csv",):
            if m in sys.modules:
                del sys.modules[m]
        import adapter_csv  # noqa: F401
        self.adapter = adapter_csv

    def tearDown(self) -> None:
        os.environ.pop("LUMICC_DATA_ROOT", None)
        self._tmp.cleanup()

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(Path(self._tmp.name) / "store.db")
        db.row_factory = sqlite3.Row
        return db

    # 1. Orders CSV → orders + derived customers in store.db
    def test_import_orders_basic(self) -> None:
        csv_path = Path(self._tmp.name) / "orders.csv"
        csv_path.write_text(
            "Name,Email,Created at,Total\n"
            "#1001,alice@example.com,2026-01-15 10:00:00,49.99\n"
            "#1002,alice@example.com,2026-02-01 11:00:00,29.50\n"
            "#1003,bob@example.com,2026-02-10 12:00:00,99.00\n"
            "#1004,carol@example.com,2026-03-05 09:00:00,15.00\n"
            "#1005,bob@example.com,2026-03-12 14:00:00,42.00\n",
            encoding="utf-8",
        )
        result = self.adapter.import_orders(csv_path, store_id="s_test")
        self.assertEqual(result["orders_count"], 5)
        self.assertEqual(result["customers_count"], 3)

        db = self._db()
        n_events = db.execute("SELECT COUNT(*) AS n FROM events WHERE store_id='s_test'").fetchone()["n"]
        self.assertEqual(n_events, 5)
        n_cust = db.execute("SELECT COUNT(*) AS n FROM customers WHERE store_id='s_test'").fetchone()["n"]
        self.assertEqual(n_cust, 3)
        alice = db.execute(
            "SELECT total_spent, order_count FROM customers WHERE email=? AND store_id='s_test'",
            ("alice@example.com",),
        ).fetchone()
        self.assertEqual(alice["order_count"], 2)
        self.assertAlmostEqual(alice["total_spent"], 79.49, places=2)
        db.close()

    # 2. Chinese-headers products CSV
    def test_import_products_chinese_headers(self) -> None:
        csv_path = Path(self._tmp.name) / "products.csv"
        csv_path.write_text(
            "商品编码,商品名,价格,成本\n"
            "SKU001,魔力清洁海绵,8.99,1.50\n"
            "SKU002,折叠衣架,12.50,3.20\n",
            encoding="utf-8",
        )
        result = self.adapter.import_products(csv_path, store_id="s_zh")
        self.assertEqual(result["products_count"], 2)
        db = self._db()
        row = db.execute(
            "SELECT title, price_usd, cost_usd FROM products WHERE id='SKU001'"
        ).fetchone()
        self.assertEqual(row["title"], "魔力清洁海绵")
        self.assertAlmostEqual(row["price_usd"], 8.99, places=2)
        self.assertAlmostEqual(row["cost_usd"], 1.50, places=2)
        db.close()

    # 3. Bad CSV → warnings, no crash
    def test_import_products_missing_title_column(self) -> None:
        csv_path = Path(self._tmp.name) / "bad.csv"
        csv_path.write_text("foo,bar\n1,2\n", encoding="utf-8")
        result = self.adapter.import_products(csv_path, store_id="s_bad")
        self.assertEqual(result["products_count"], 0)
        self.assertTrue(any("Missing required column: title" in w for w in result["warnings"]))

    def test_import_orders_missing_customer_column(self) -> None:
        csv_path = Path(self._tmp.name) / "bad_orders.csv"
        csv_path.write_text("Total,Date\n10.00,2026-01-01\n", encoding="utf-8")
        result = self.adapter.import_orders(csv_path, store_id="s_bad")
        self.assertEqual(result["orders_count"], 0)
        self.assertTrue(any("customer_id or email" in w for w in result["warnings"]))

    # 4. Email aliases all map to email
    def test_detect_columns_email_aliases(self) -> None:
        for header in ("Email", "email", "邮箱", "customer email", "Customer Email"):
            cols = self.adapter.detect_columns([header])
            self.assertEqual(cols.get("email"), header,
                             f"header {header!r} did not map to canonical 'email'")

    def test_detect_columns_title_aliases(self) -> None:
        for header in ("Title", "Product Name", "Lineitem name", "商品名", "产品名称"):
            cols = self.adapter.detect_columns([header])
            self.assertEqual(cols.get("title"), header,
                             f"header {header!r} did not map to 'title'")

    def test_unrecognized_columns_warned(self) -> None:
        csv_path = Path(self._tmp.name) / "extra.csv"
        csv_path.write_text(
            "sku,title,price,WeirdField\nA1,Thing,9.99,xyz\n",
            encoding="utf-8",
        )
        result = self.adapter.import_products(csv_path, store_id="s_warn")
        self.assertEqual(result["products_count"], 1)
        self.assertTrue(any("WeirdField" in w for w in result["warnings"]))

    # Customers CSV
    def test_import_customers(self) -> None:
        csv_path = Path(self._tmp.name) / "cust.csv"
        csv_path.write_text(
            "Customer ID,Email,Total Spent,Orders\n"
            "C1,alice@example.com,250.00,5\n"
            "C2,bob@example.com,120.00,3\n",
            encoding="utf-8",
        )
        result = self.adapter.import_customers(csv_path, store_id="s_c")
        self.assertEqual(result["customers_count"], 2)
        db = self._db()
        row = db.execute(
            "SELECT total_spent, order_count FROM customers WHERE id='C1' AND store_id='s_c'"
        ).fetchone()
        self.assertAlmostEqual(row["total_spent"], 250.00, places=2)
        self.assertEqual(row["order_count"], 5)
        db.close()


if __name__ == "__main__":
    unittest.main()
