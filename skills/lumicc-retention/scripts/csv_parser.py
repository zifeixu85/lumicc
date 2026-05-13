#!/usr/bin/env python3
"""Flexible customer-orders CSV parser.

Auto-detects column aliases across Shopify / WooCommerce / TikTok Shop / generic
exports. Returns a normalized list of (customer_id, email, order_id, order_date,
total, sku_list) tuples.

Date parsing is forgiving: accepts ISO-8601, common locale formats, and Shopify's
"YYYY-MM-DD HH:MM:SS +0000".
"""
from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path
from typing import Iterator

# Column-name detection. Lowercased keys.
ALIASES = {
    "customer_id": {"customer_id", "customer id", "customerid", "客户id", "customer", "user_id", "userid"},
    "email": {"email", "customer email", "customer_email", "邮箱"},
    "order_id": {"order_id", "order id", "name", "id", "订单号", "order number", "orderid"},
    "order_date": {"order_date", "order date", "created at", "created_at", "date", "下单时间", "ts", "order_created_at"},
    "total": {"total", "subtotal", "amount", "order total", "金额", "total price", "lineitem price", "total_price"},
    "sku": {"sku", "lineitem sku", "lineitem_sku", "product sku", "product_sku", "skus", "product_skus"},
}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def detect_columns(fieldnames: list[str]) -> dict:
    """Map normalized-canonical → actual CSV column name."""
    out: dict[str, str] = {}
    norm_fields = {_norm(f): f for f in fieldnames}
    for canonical, candidates in ALIASES.items():
        for cand in candidates:
            if cand in norm_fields:
                out[canonical] = norm_fields[cand]
                break
    return out


def parse_date(value: str) -> datetime.date | None:
    if not value:
        return None
    v = value.strip()
    # Try common formats in order
    fmts = [
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y",
        "%Y年%m月%d日",
    ]
    for fmt in fmts:
        try:
            return datetime.datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    # Last resort: take leading 10 chars as ISO date
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", v)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def parse_total(value: str) -> float:
    if not value:
        return 0.0
    # Strip currency symbols + commas
    s = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def split_skus(value: str) -> list[str]:
    """Split SKU field by common separators: ';', ',', '|', newline."""
    if not value:
        return []
    parts = re.split(r"[;,|\n]+", str(value))
    return [p.strip() for p in parts if p and p.strip()]


def iter_orders(csv_path: Path) -> Iterator[dict]:
    """Yield normalized order dicts from a CSV file.

    Each yield: {customer_id, email, order_id, order_date (date | None), total, skus (list)}
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return
        cols = detect_columns(reader.fieldnames)
        # We need at least customer_id (or email) + order_date + total
        if not (cols.get("customer_id") or cols.get("email")):
            raise ValueError(f"CSV missing customer identifier column. Got: {reader.fieldnames}")
        if not cols.get("order_date"):
            raise ValueError(f"CSV missing order_date column. Got: {reader.fieldnames}")
        for row in reader:
            cid = row.get(cols.get("customer_id", ""), "") if cols.get("customer_id") else ""
            email = row.get(cols.get("email", ""), "") if cols.get("email") else ""
            if not cid and email:
                cid = email.strip().lower()  # use email as ID when missing
            if not cid:
                continue
            d = parse_date(row.get(cols.get("order_date", ""), ""))
            if not d:
                continue
            total = parse_total(row.get(cols.get("total", ""), ""))
            skus = split_skus(row.get(cols.get("sku", ""), "")) if cols.get("sku") else []
            yield {
                "customer_id": cid.strip(),
                "email": email.strip().lower() or None,
                "order_id": (row.get(cols.get("order_id", ""), "") or "").strip(),
                "order_date": d,
                "total": total,
                "skus": skus,
            }


def aggregate_by_customer(orders: list[dict]) -> dict[str, dict]:
    """Group orders by customer_id; return per-customer aggregate stats."""
    by_cust: dict[str, dict] = {}
    for o in orders:
        cid = o["customer_id"]
        c = by_cust.setdefault(cid, {
            "customer_id": cid,
            "email": o.get("email"),
            "order_count": 0,
            "total_spent": 0.0,
            "first_order_date": o["order_date"],
            "last_order_date": o["order_date"],
            "order_dates": [],
            "skus_purchased": [],
        })
        c["order_count"] += 1
        c["total_spent"] += o["total"]
        if o["order_date"] < c["first_order_date"]:
            c["first_order_date"] = o["order_date"]
        if o["order_date"] > c["last_order_date"]:
            c["last_order_date"] = o["order_date"]
        c["order_dates"].append(o["order_date"])
        c["skus_purchased"].extend(o["skus"])
        if o.get("email") and not c.get("email"):
            c["email"] = o["email"]
    return by_cust


def mask_email(email: str | None) -> str:
    """Mask email for display: 'user1234@domain.tld' → 'u***34@domain.tld'."""
    if not email or "@" not in email:
        return "—"
    local, _, domain = email.partition("@")
    if len(local) <= 4:
        return f"{local[:1]}***@{domain}"
    return f"{local[:1]}***{local[-2:]}@{domain}"
