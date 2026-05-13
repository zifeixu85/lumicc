#!/usr/bin/env python3
"""Schema.org JSON-LD generator per product.

Emits Product + Offer + AggregateRating (when reviews exist) + optional FAQPage.
Output is a ready-to-paste <script type="application/ld+json"> block plus the raw
JSON for downstream tooling.

Why we need this: AI engines (ChatGPT, Perplexity, Claude, Gemini) parse
Schema.org structured data far better than they parse free-form HTML. Schema
markup increases your citation share — it's one of the highest-ROI GEO moves.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


AVAILABILITY_MAP = {
    "active": "https://schema.org/InStock",
    "in_stock": "https://schema.org/InStock",
    "draft": "https://schema.org/PreOrder",
    "out_of_stock": "https://schema.org/OutOfStock",
    "discontinued": "https://schema.org/Discontinued",
}


def build_product(product: dict, store: dict) -> dict:
    """Build a Product JSON-LD object from product + store rows."""
    sku = product.get("sku") or product.get("id")
    title = product.get("title") or sku
    description = product.get("description") or product.get("short_desc") or ""
    images = product.get("images") or []
    if isinstance(images, list):
        image_urls = [img.get("url") if isinstance(img, dict) else img for img in images if img]
    else:
        image_urls = []

    product_url = product.get("url") or (
        (store.get("url") or "").rstrip("/") + f"/products/{product.get('handle', sku)}"
    )
    currency = store.get("currency") or "USD"
    price = product.get("price_usd") if currency == "USD" else product.get("price")
    compare = product.get("compare_at_price")
    availability = AVAILABILITY_MAP.get((product.get("status") or "active").lower(),
                                         "https://schema.org/InStock")

    offer: dict = {
        "@type": "Offer",
        "url": product_url,
        "priceCurrency": currency,
        "price": f"{price:.2f}" if price else "0.00",
        "availability": availability,
        "itemCondition": "https://schema.org/NewCondition",
    }
    if compare and price and compare > price:
        offer["priceSpecification"] = {
            "@type": "PriceSpecification",
            "price": f"{price:.2f}",
            "priceCurrency": currency,
            "valueAddedTaxIncluded": False,
        }

    schema: dict = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": title,
        "description": description[:500] if description else f"{title} - high-quality cross-border product",
        "sku": sku,
        "offers": offer,
    }
    if image_urls:
        schema["image"] = image_urls
    brand_name = store.get("brand_name") or store.get("name")
    if brand_name:
        schema["brand"] = {"@type": "Brand", "name": brand_name}

    # AggregateRating only when reviews exist
    reviews = product.get("reviews") or {}
    if isinstance(reviews, dict) and reviews.get("count", 0) > 0:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(reviews.get("avg") or 4.5),
            "reviewCount": str(reviews.get("count") or 1),
        }

    return schema


def build_faq(faqs: list[dict]) -> dict | None:
    """Build a FAQPage JSON-LD from a list of {question, answer} dicts."""
    if not faqs:
        return None
    return {
        "@context": "https://schema.org/",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q.get("question", ""),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": q.get("answer", "")[:500],
                },
            }
            for q in faqs if q.get("question") and q.get("answer")
        ],
    }


def to_script_block(schema: dict) -> str:
    """Wrap a JSON-LD object in a <script> tag ready to paste into a theme."""
    return (
        '<script type="application/ld+json">\n'
        + json.dumps(schema, ensure_ascii=False, indent=2)
        + "\n</script>"
    )


def generate(*, product: dict, store: dict, faqs: list[dict] | None = None) -> dict:
    """Generate all JSON-LD objects for a product page. Returns a dict with the
    raw schemas + ready-to-paste HTML blocks."""
    prod_schema = build_product(product, store)
    blocks: list[dict] = [{"type": "Product", "schema": prod_schema,
                            "html_block": to_script_block(prod_schema)}]
    faq_schema = build_faq(faqs or [])
    if faq_schema:
        blocks.append({"type": "FAQPage", "schema": faq_schema,
                       "html_block": to_script_block(faq_schema)})
    return {
        "sku": product.get("sku"),
        "product_url": prod_schema.get("offers", {}).get("url"),
        "schemas": blocks,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--product-json", required=True, help="JSON file: product dict")
    p.add_argument("--store-json", required=True, help="JSON file: store dict")
    p.add_argument("--faqs-json", default=None, help="JSON file: list of {question, answer}")
    p.add_argument("--out", default=None)
    args = p.parse_args()
    product = json.loads(Path(args.product_json).read_text(encoding="utf-8"))
    store = json.loads(Path(args.store_json).read_text(encoding="utf-8"))
    faqs = json.loads(Path(args.faqs_json).read_text(encoding="utf-8")) if args.faqs_json else []
    result = generate(product=product, store=store, faqs=faqs)
    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(json.dumps({"saved": args.out, "blocks": len(result["schemas"])}))
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
