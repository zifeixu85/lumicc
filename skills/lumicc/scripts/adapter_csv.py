#!/usr/bin/env python3
"""CSV ingestion adapter for Lumicc v0.3.

Imports Shopify-style orders, generic product CSVs, and customer lists
into ~/.commerce-os/store.db (override via LUMICC_DATA_ROOT).

Public API:
    detect_columns(headers)
    import_orders(file_path, store_id)
    import_products(file_path, store_id)
    import_customers(file_path, store_id)

CLI:
    python3 adapter_csv.py --kind orders|products|customers \
        --file path.csv --store-id <id> [--quiet-stdout]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

# --- Column alias table (lowercased) --------------------------------------

ALIASES: dict[str, list[str]] = {
    "title": [
        "title", "product title", "name", "product name", "item name",
        "lineitem name", "line item name", "商品名", "标题", "产品名称",
        "商品名称", "品名", "产品标题",
    ],
    "sku": [
        "sku", "sku id", "skuid", "lineitem sku", "line item sku",
        "item id", "product sku", "variant sku",
        "编码", "商品编码", "sku编码", "产品编码", "货号",
    ],
    "price": [
        "price", "unit price", "lineitem price", "product price",
        "selling price", "list price",
        "单价", "价格", "售价", "零售价",
    ],
    "cost_usd": [
        "cost", "unit cost", "cogs", "product cost", "cost per item",
        "成本", "进货价", "成本价",
    ],
    "email": [
        "email", "customer email", "customer_email", "contact email",
        "邮箱", "电子邮件", "邮件地址",
    ],
    "customer_id": [
        "customer id", "customer_id", "customerid", "customer", "user_id",
        "userid", "客户id", "客户编号", "用户id",
    ],
    "customer_name": [
        "customer name", "name", "full name", "客户姓名", "姓名",
    ],
    "total_spent": [
        "total spent", "lifetime value", "ltv", "total_spent",
        "消费总额", "累计消费", "总消费",
    ],
    "order_count": [
        "orders", "order count", "orders count", "total orders",
        "订单数", "订单数量",
    ],
    "order_date": [
        "order date", "date", "created at", "created_at", "order_date",
        "ordered at", "订单日期", "下单时间", "创建时间",
    ],
    "order_id": [
        "order id", "order_id", "order number", "order #", "name",
        "id", "订单号", "订单编号",
    ],
    "total": [
        "total", "order total", "subtotal", "amount", "grand total",
        "订单金额", "金额", "总价", "总金额",
    ],
    "status": [
        "status", "product status", "published", "状态", "上架状态",
    ],
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def detect_columns(headers: list[str]) -> dict[str, str]:
    """Map canonical field name → actual header from the CSV.

    Returns {canonical: original_header}.
    Unmatched canonicals are absent from the result.
    """
    norm_map = {_norm(h): h for h in headers}
    out: dict[str, str] = {}
    for canonical, candidates in ALIASES.items():
        for cand in candidates:
            if cand in norm_map:
                out[canonical] = norm_map[cand]
                break
    return out


def unrecognized(headers: list[str], cols: dict[str, str]) -> list[str]:
    used = set(cols.values())
    return [h for h in headers if h not in used]


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
    _ensure_aux_tables(db)
    return db


def _ensure_aux_tables(db: sqlite3.Connection) -> None:
    # init_store.py owns the core schema. We additively create what we need
    # for adapters without conflicting with existing tables.
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
        CREATE TABLE IF NOT EXISTS customers (
          id TEXT PRIMARY KEY,
          store_id TEXT,
          email TEXT,
          name TEXT,
          total_spent REAL DEFAULT 0,
          order_count INTEGER DEFAULT 0,
          first_order_at INTEGER,
          last_order_at INTEGER,
          data_json TEXT,
          created_at INTEGER,
          updated_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_customers_store ON customers(store_id);
        CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);
        """
    )
    db.commit()


def _parse_money(value: str) -> float:
    if not value:
        return 0.0
    s = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _parse_int(value: str) -> int:
    if not value:
        return 0
    s = re.sub(r"[^\d\-]", "", str(value))
    try:
        return int(s) if s else 0
    except ValueError:
        return 0


def _parse_date_ts(value: str) -> int | None:
    if not value:
        return None
    v = value.strip()
    fmts = [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
    ]
    import datetime
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(v, fmt)
            return int(dt.timestamp())
        except ValueError:
            continue
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if m:
        try:
            dt = datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return int(dt.timestamp())
        except ValueError:
            pass
    return None


# --- Importers ------------------------------------------------------------

def _read_csv(file_path: Path) -> tuple[list[str], list[dict]]:
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = [r for r in reader]
    return headers, rows


def import_orders(file_path: Path, store_id: str) -> dict:
    """Import Shopify-style orders CSV. Derives customer aggregates."""
    warnings: list[str] = []
    headers, rows = _read_csv(file_path)
    cols = detect_columns(headers)

    if not (cols.get("customer_id") or cols.get("email")):
        warnings.append("Missing required column: customer_id or email")
        return {"orders_count": 0, "customers_count": 0, "warnings": warnings}
    if not cols.get("order_date"):
        warnings.append("Missing required column: order_date")

    for h in unrecognized(headers, cols):
        warnings.append(f"Unrecognized column: {h} — skipped")

    db = _open_db()
    now = int(time.time())
    orders_count = 0
    cust_agg: dict[str, dict] = {}

    for row in rows:
        email = (row.get(cols.get("email", ""), "") or "").strip().lower() if cols.get("email") else ""
        cid = (row.get(cols.get("customer_id", ""), "") or "").strip() if cols.get("customer_id") else ""
        if not cid:
            cid = email
        if not cid:
            continue
        ts = _parse_date_ts(row.get(cols.get("order_date", ""), "")) if cols.get("order_date") else None
        total = _parse_money(row.get(cols.get("total", ""), "")) if cols.get("total") else 0.0
        order_id = (row.get(cols.get("order_id", ""), "") or "").strip() if cols.get("order_id") else ""

        # Log as event
        db.execute(
            "INSERT INTO events(store_id, ts, category, content) VALUES (?,?,?,?)",
            (store_id, ts or now, "order",
             json.dumps({"order_id": order_id, "customer_id": cid, "email": email or None, "total": total}, ensure_ascii=False)),
        )
        orders_count += 1

        agg = cust_agg.setdefault(cid, {
            "email": email or None,
            "order_count": 0,
            "total_spent": 0.0,
            "first": ts,
            "last": ts,
        })
        agg["order_count"] += 1
        agg["total_spent"] += total
        if ts is not None:
            if agg["first"] is None or ts < agg["first"]:
                agg["first"] = ts
            if agg["last"] is None or ts > agg["last"]:
                agg["last"] = ts
        if email and not agg["email"]:
            agg["email"] = email

    # Upsert customers
    for cid, agg in cust_agg.items():
        existing = db.execute(
            "SELECT id, total_spent, order_count FROM customers WHERE id=? AND store_id=?",
            (cid, store_id),
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE customers SET email=COALESCE(?,email), total_spent=total_spent+?, "
                "order_count=order_count+?, last_order_at=?, updated_at=? WHERE id=? AND store_id=?",
                (agg["email"], agg["total_spent"], agg["order_count"],
                 agg["last"], now, cid, store_id),
            )
        else:
            db.execute(
                "INSERT INTO customers(id, store_id, email, total_spent, order_count, "
                "first_order_at, last_order_at, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (cid, store_id, agg["email"], agg["total_spent"], agg["order_count"],
                 agg["first"], agg["last"], now, now),
            )
    db.commit()
    db.close()
    return {
        "orders_count": orders_count,
        "customers_count": len(cust_agg),
        "warnings": warnings,
    }


def import_products(file_path: Path, store_id: str) -> dict:
    warnings: list[str] = []
    headers, rows = _read_csv(file_path)
    cols = detect_columns(headers)

    if not cols.get("title"):
        warnings.append("Missing required column: title")
        return {"products_count": 0, "warnings": warnings}

    for h in unrecognized(headers, cols):
        warnings.append(f"Unrecognized column: {h} — skipped")

    db = _open_db()
    now = int(time.time())
    count = 0
    for row in rows:
        title = (row.get(cols.get("title", ""), "") or "").strip()
        if not title:
            continue
        sku = (row.get(cols.get("sku", ""), "") or "").strip() if cols.get("sku") else ""
        price = _parse_money(row.get(cols.get("price", ""), "")) if cols.get("price") else 0.0
        cost = _parse_money(row.get(cols.get("cost_usd", ""), "")) if cols.get("cost_usd") else 0.0
        status = (row.get(cols.get("status", ""), "") or "").strip() if cols.get("status") else "active"
        pid = sku or f"p_{uuid.uuid4().hex[:10]}"
        existing = db.execute("SELECT id FROM products WHERE id=? AND store_id=?", (pid, store_id)).fetchone()
        if existing:
            db.execute(
                "UPDATE products SET sku=?, title=?, status=?, cost_usd=?, price_usd=?, updated_at=? "
                "WHERE id=? AND store_id=?",
                (sku, title, status, cost, price, now, pid, store_id),
            )
        else:
            db.execute(
                "INSERT INTO products(id, store_id, sku, title, status, cost_usd, price_usd, "
                "data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, store_id, sku, title, status, cost, price,
                 json.dumps(row, ensure_ascii=False), now, now),
            )
        count += 1
    db.commit()
    db.close()
    return {"products_count": count, "warnings": warnings}


def import_customers(file_path: Path, store_id: str) -> dict:
    warnings: list[str] = []
    headers, rows = _read_csv(file_path)
    cols = detect_columns(headers)

    if not (cols.get("customer_id") or cols.get("email")):
        warnings.append("Missing required column: customer_id or email")
        return {"customers_count": 0, "warnings": warnings}

    for h in unrecognized(headers, cols):
        warnings.append(f"Unrecognized column: {h} — skipped")

    db = _open_db()
    now = int(time.time())
    count = 0
    for row in rows:
        email = (row.get(cols.get("email", ""), "") or "").strip().lower() if cols.get("email") else ""
        cid = (row.get(cols.get("customer_id", ""), "") or "").strip() if cols.get("customer_id") else ""
        if not cid:
            cid = email
        if not cid:
            continue
        name = (row.get(cols.get("customer_name", ""), "") or "").strip() if cols.get("customer_name") else ""
        total_spent = _parse_money(row.get(cols.get("total_spent", ""), "")) if cols.get("total_spent") else 0.0
        order_count = _parse_int(row.get(cols.get("order_count", ""), "")) if cols.get("order_count") else 0

        existing = db.execute(
            "SELECT id FROM customers WHERE id=? AND store_id=?", (cid, store_id)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE customers SET email=COALESCE(NULLIF(?,''),email), name=COALESCE(NULLIF(?,''),name), "
                "total_spent=?, order_count=?, updated_at=? WHERE id=? AND store_id=?",
                (email, name, total_spent, order_count, now, cid, store_id),
            )
        else:
            db.execute(
                "INSERT INTO customers(id, store_id, email, name, total_spent, order_count, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (cid, store_id, email or None, name or None, total_spent, order_count, now, now),
            )
        count += 1
    db.commit()
    db.close()
    return {"customers_count": count, "warnings": warnings}


# --- CLI ------------------------------------------------------------------

def _emit(payload: dict, quiet_stdout: bool) -> None:
    if quiet_stdout:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lumicc CSV adapter")
    p.add_argument("--kind", required=True, choices=["orders", "products", "customers"])
    p.add_argument("--file", required=True, help="Path to CSV file")
    p.add_argument("--store-id", required=True, dest="store_id")
    p.add_argument("--quiet-stdout", action="store_true", dest="quiet")
    args = p.parse_args(argv)

    file_path = Path(args.file).expanduser()
    if not file_path.exists():
        sys.stderr.write(f"[adapter_csv] file not found: {file_path}\n")
        return 1

    if not args.quiet:
        sys.stderr.write(f"[adapter_csv] importing {args.kind} from {file_path}\n")

    try:
        if args.kind == "orders":
            result = import_orders(file_path, args.store_id)
            imported = result["orders_count"]
            extra = {"customers_derived": result["customers_count"]}
        elif args.kind == "products":
            result = import_products(file_path, args.store_id)
            imported = result["products_count"]
            extra = {}
        else:
            result = import_customers(file_path, args.store_id)
            imported = result["customers_count"]
            extra = {}
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[adapter_csv] error: {exc}\n")
        _emit({"adapter": "csv", "kind": args.kind, "error": str(exc),
               "store_id": args.store_id}, args.quiet)
        return 1

    payload = {
        "adapter": "csv",
        "kind": args.kind,
        "imported": imported,
        "warnings": result.get("warnings", []),
        "store_id": args.store_id,
        **extra,
    }
    _emit(payload, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
