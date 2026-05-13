#!/usr/bin/env python3
"""Generate Shopify-compatible bulk-import CSV from a candidate SKU JSON.

Used as the built-in fallback when the user has no Platform Write adapter
configured. The CSV follows Shopify's documented bulk-import format and can be
uploaded directly via Shopify Admin → Products → Import.

Input JSON shape (per SKU):
{
  "handle": "magnetic-knife-rack",          # required, lowercase-dashes
  "title": "Magnetic Knife Rack — 16in",    # required
  "body_html": "<p>...</p>",                # optional; we'll auto-wrap plaintext
  "vendor": "Acme Pets",                    # optional
  "product_type": "Kitchen",                # optional
  "tags": ["kitchen", "magnetic"],          # optional
  "published": true,                        # default true
  "variants": [
    {"sku": "MKR-16",  "price": 29.99, "compare_at": 39.99, "weight_g": 320,
     "inventory_qty": 0, "option1": "Default"}
  ],
  "images": [
    {"src": "https://...", "alt": "front view", "position": 1},
    ...
  ],
  "seo_title": "...",
  "seo_description": "..."
}

Usage:
    python3 listing_csv.py --input products.json --out listings.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Shopify bulk-import columns (canonical 2024-2026 schema; sufficient for v0.1.0)
COLUMNS = [
    "Handle", "Title", "Body (HTML)", "Vendor", "Product Category", "Type", "Tags", "Published",
    "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name", "Option3 Value",
    "Variant SKU", "Variant Grams", "Variant Inventory Tracker", "Variant Inventory Qty",
    "Variant Inventory Policy", "Variant Fulfillment Service",
    "Variant Price", "Variant Compare At Price",
    "Variant Requires Shipping", "Variant Taxable",
    "Variant Barcode",
    "Image Src", "Image Position", "Image Alt Text",
    "Gift Card",
    "SEO Title", "SEO Description",
]


def to_rows(prod: dict) -> list[dict]:
    handle = prod["handle"]
    title = prod.get("title", handle)
    body = prod.get("body_html") or ""
    if body and not body.lstrip().startswith("<"):
        body = "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    vendor = prod.get("vendor", "")
    ptype = prod.get("product_type", "")
    tags = ", ".join(prod.get("tags", []))
    published = "TRUE" if prod.get("published", True) else "FALSE"
    seo_title = prod.get("seo_title", "")
    seo_desc = prod.get("seo_description", "")
    variants = prod.get("variants") or [{"sku": handle.upper(), "price": 0, "option1": "Default"}]
    images = prod.get("images") or []

    rows: list[dict] = []
    for i, v in enumerate(variants):
        row = {c: "" for c in COLUMNS}
        # First row has full product info; subsequent variant rows only need handle + variant fields
        if i == 0:
            row.update({
                "Handle": handle, "Title": title, "Body (HTML)": body,
                "Vendor": vendor, "Type": ptype, "Tags": tags, "Published": published,
                "SEO Title": seo_title, "SEO Description": seo_desc,
                "Gift Card": "FALSE",
            })
        else:
            row["Handle"] = handle
        row.update({
            "Option1 Name": "Title" if "option1" in v else "",
            "Option1 Value": v.get("option1", "Default"),
            "Variant SKU": v.get("sku", ""),
            "Variant Grams": str(v.get("weight_g", "")),
            "Variant Inventory Tracker": "shopify",
            "Variant Inventory Qty": str(v.get("inventory_qty", 0)),
            "Variant Inventory Policy": v.get("inventory_policy", "deny"),
            "Variant Fulfillment Service": "manual",
            "Variant Price": f"{v.get('price', 0):.2f}",
            "Variant Compare At Price": f"{v.get('compare_at', 0):.2f}" if v.get("compare_at") else "",
            "Variant Requires Shipping": "TRUE",
            "Variant Taxable": "TRUE",
            "Variant Barcode": v.get("barcode", ""),
        })
        rows.append(row)

    # Append additional rows for images beyond the first (Shopify pattern)
    for img in images:
        # First image is attached to the first variant row above
        if img.get("position", 1) == 1 and rows:
            rows[0]["Image Src"] = img.get("src", "")
            rows[0]["Image Position"] = str(img.get("position", 1))
            rows[0]["Image Alt Text"] = img.get("alt", "")
        else:
            img_row = {c: "" for c in COLUMNS}
            img_row["Handle"] = handle
            img_row["Image Src"] = img.get("src", "")
            img_row["Image Position"] = str(img.get("position", 1))
            img_row["Image Alt Text"] = img.get("alt", "")
            rows.append(img_row)

    return rows


def generate(products: list[dict]) -> str:
    out = []
    out.append(",".join(COLUMNS))
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for prod in products:
        for r in to_rows(prod):
            writer.writerow(r)
    return buf.getvalue()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="JSON file: list of product dicts")
    p.add_argument("--out", default=None)
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    csv_text = generate(data)
    if args.out:
        Path(args.out).write_text(csv_text, encoding="utf-8")
        print(json.dumps({"saved": args.out, "products": len(data),
                          "rows": csv_text.count("\n") - 1}, ensure_ascii=False))
    else:
        sys.stdout.write(csv_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
