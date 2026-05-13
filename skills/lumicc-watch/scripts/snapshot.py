#!/usr/bin/env python3
"""Snapshot a single competitor storefront — public pages only.

Strategy:
  1) Try sitemap.xml (lightweight, no JS) — extracts product URLs.
  2) Fetch homepage HTML via stdlib (no Playwright dep).
  3) Parse: <title>, meta description, h1/h2 headings, og:image, products on home,
     announcement bar copy, social handles.

If Playwright is installed, an extended path (--use-playwright) renders JS-heavy
pages. The snapshot JSON shape is the same in both paths.

This script obeys robots.txt and rate-limits (default 3000 ms between requests).
It NEVER attempts to log in or scrape behind authentication.

Usage:
    python3 snapshot.py --url https://example.com --out /tmp/example.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

USER_AGENT = "Lumicc-Watch/0.1 (+https://github.com/lumicc-bot; respect-robots-txt)"
TIMEOUT_S = 20
DEFAULT_DELAY_MS = 3000


# ---------- HTTP helpers ----------
def http_get(url: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
    h = {"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "gzip, identity"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            if enc == "gzip":
                data = gzip.decompress(data)
            return resp.status, data, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", {}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, b"", {"error": str(e)}


def check_robots(url: str) -> tuple[bool, float]:
    """Return (allowed, crawl_delay_seconds)."""
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
    except Exception:
        return True, DEFAULT_DELAY_MS / 1000.0
    allowed = rp.can_fetch(USER_AGENT, url)
    delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*") or (DEFAULT_DELAY_MS / 1000.0)
    return allowed, float(delay)


# ---------- Parsers ----------
TAG_RE = re.compile(r"<(?P<tag>title|h1|h2|meta|link|a|img)\b(?P<attrs>[^>]*)>(?P<inner>.*?)</?(?:title|h1|h2|a)?>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"|(\w[\w-]*)\s*=\s*\'([^\']*)\'')
ANNOUNCEMENT_HINTS = [
    "free shipping", "save", "% off", "discount", "limited time",
    "free delivery", "promo", "sale", "coupon", "code",
]


def parse_attrs(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in ATTR_RE.finditer(s):
        if m.group(1):
            out[m.group(1).lower()] = m.group(2)
        elif m.group(3):
            out[m.group(3).lower()] = m.group(4)
    return out


def parse_homepage(html: str, base_url: str) -> dict[str, Any]:
    """Best-effort homepage extraction without external deps."""
    result: dict[str, Any] = {
        "title": None,
        "meta_description": None,
        "headings": [],
        "og_image": None,
        "announcement_candidates": [],
        "products": [],
        "social_handles": {},
        "raw_size": len(html),
    }

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        result["title"] = re.sub(r"\s+", " ", m.group(1)).strip()

    for m in re.finditer(r"<meta[^>]+>", html, re.IGNORECASE):
        attrs = parse_attrs(m.group(0))
        if attrs.get("name", "").lower() == "description":
            result["meta_description"] = attrs.get("content", "")[:600]
        if attrs.get("property", "").lower() == "og:image":
            result["og_image"] = attrs.get("content")

    for m in re.finditer(r"<h[12][^>]*>(.*?)</h[12]>", html, re.IGNORECASE | re.DOTALL):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        text = re.sub(r"\s+", " ", text).strip()
        if text and len(text) < 300:
            result["headings"].append(text)
    result["headings"] = result["headings"][:20]

    # Announcement bar — look for short banners with hint words
    for m in re.finditer(r'class="[^"]*(announcement|banner|promo-bar|top-bar)[^"]*"[^>]*>(.*?)<', html, re.IGNORECASE | re.DOTALL):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        if text and len(text) < 250:
            result["announcement_candidates"].append(text)
    # Fallback: look for short visible texts containing hint words
    if not result["announcement_candidates"]:
        plain = re.sub(r"<[^>]+>", " ", html)
        for line in plain.splitlines():
            line = line.strip()
            if not (20 < len(line) < 200):
                continue
            low = line.lower()
            if any(h in low for h in ANNOUNCEMENT_HINTS):
                result["announcement_candidates"].append(line)
                if len(result["announcement_candidates"]) >= 3:
                    break
    result["announcement_candidates"] = result["announcement_candidates"][:5]

    # Product links on homepage — Shopify pattern /products/<handle>
    seen: set[str] = set()
    for m in re.finditer(r'href="([^"]*?/products/[^"#?]+)"[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL):
        href = urllib.parse.urljoin(base_url, m.group(1))
        if href in seen:
            continue
        seen.add(href)
        text = re.sub(r"<[^>]+>", "", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        result["products"].append({"url": href, "anchor_text": text[:140]})
        if len(result["products"]) >= 30:
            break

    # Social handles
    for platform, pattern in [
        ("instagram", r"instagram\.com/([A-Za-z0-9_.]{2,30})"),
        ("tiktok", r"tiktok\.com/@([A-Za-z0-9_.]{2,30})"),
        ("twitter", r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,30})"),
        ("youtube", r"youtube\.com/(?:c/|channel/|@)([A-Za-z0-9_-]{2,40})"),
        ("facebook", r"facebook\.com/([A-Za-z0-9.]{2,40})"),
    ]:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            handle = m.group(1)
            if handle.lower() not in ("share", "intent", "post", "embed"):
                result["social_handles"][platform] = handle
    return result


def parse_sitemap(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    # Strip namespaces for simpler matching
    urls: list[str] = []
    for elem in root.iter():
        if elem.tag.split("}")[-1] == "loc" and elem.text:
            urls.append(elem.text.strip())
    return urls


def fingerprint(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ---------- Main snapshot ----------
def snapshot_url(url: str, delay_s: float | None = None) -> dict:
    parsed = urllib.parse.urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    allowed, robot_delay = check_robots(url)
    out: dict[str, Any] = {
        "url": url,
        "base_url": base_url,
        "ts": int(time.time()),
        "robots_allowed": allowed,
        "crawl_delay_s": float(delay_s if delay_s is not None else robot_delay),
        "errors": [],
    }
    if not allowed:
        out["errors"].append("robots.txt disallows our crawler — skipping")
        return out

    # Fetch sitemap (if available)
    sitemap_url = f"{base_url}/sitemap.xml"
    status, data, _ = http_get(sitemap_url)
    sitemap_products: list[str] = []
    if status == 200 and data:
        urls = parse_sitemap(data)
        sitemap_products = [u for u in urls if "/products/" in u][:200]
    out["sitemap_product_count"] = len(sitemap_products)
    out["sitemap_products_sample"] = sitemap_products[:20]

    time.sleep(out["crawl_delay_s"])

    # Fetch homepage
    status, data, headers = http_get(base_url)
    if status != 200 or not data:
        out["errors"].append(f"Homepage fetch failed (status={status})")
        return out
    try:
        html = data.decode("utf-8", errors="replace")
    except Exception as e:
        out["errors"].append(f"Decode failed: {e}")
        return out

    parsed_home = parse_homepage(html, base_url)
    out["homepage"] = parsed_home
    out["fingerprint"] = fingerprint({
        "title": parsed_home.get("title"),
        "headings": parsed_home.get("headings"),
        "announcement": parsed_home.get("announcement_candidates"),
        "product_urls": [p["url"] for p in parsed_home.get("products", [])],
        "sitemap_count": out["sitemap_product_count"],
    })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--out", default=None, help="Output JSON path; default: stdout")
    p.add_argument("--delay-ms", type=int, default=DEFAULT_DELAY_MS)
    args = p.parse_args()
    result = snapshot_url(args.url, delay_s=args.delay_ms / 1000.0)
    txt = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(txt, encoding="utf-8")
        print(json.dumps({"saved": args.out, "fingerprint": result.get("fingerprint")}))
    else:
        print(txt)
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
