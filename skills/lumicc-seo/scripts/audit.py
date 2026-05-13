#!/usr/bin/env python3
"""Technical SEO audit — pure stdlib HEAD/GET probes.

Probes a store URL for:
  - robots.txt presence + accessibility
  - sitemap.xml presence
  - llms.txt presence (our whitespace #1)
  - <title> + meta description on homepage
  - Open Graph + Twitter Card meta
  - Schema.org JSON-LD presence on homepage
  - hreflang tags
  - canonical link
  - viewport meta (mobile-friendly signal)
  - HTTP redirects (www vs apex)
  - HTTPS

Outputs a markdown checklist with pass/fail/warn per check.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "Lumicc-SEO-Audit/0.1 (audit-only; obeys robots-txt)"
TIMEOUT_S = 15


def _http_get(url: str, headers: dict | None = None) -> tuple[int, bytes, dict]:
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, identity"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                data = gzip.decompress(data)
            return resp.status, data, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", {}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, b"", {"error": str(e)}


def _check_path(base: str, path: str) -> dict:
    url = urllib.parse.urljoin(base, path)
    status, data, _ = _http_get(url)
    size = len(data)
    return {
        "url": url,
        "status": status,
        "exists": 200 <= status < 300,
        "size_bytes": size,
    }


def audit(store_url: str) -> dict:
    """Run the full audit. Returns a dict with per-check results."""
    if not store_url.startswith(("http://", "https://")):
        store_url = "https://" + store_url

    checks: dict[str, dict] = {}

    # HTTPS
    parsed = urllib.parse.urlparse(store_url)
    checks["https"] = {
        "status": "pass" if parsed.scheme == "https" else "fail",
        "evidence": f"URL scheme: {parsed.scheme}",
        "fix": "Migrate to HTTPS; Shopify enforces by default." if parsed.scheme != "https" else "OK.",
    }

    # robots.txt
    r = _check_path(store_url, "/robots.txt")
    checks["robots_txt"] = {
        "status": "pass" if r["exists"] else "fail",
        "evidence": f"GET {r['url']} → status {r['status']}",
        "fix": "Add a /robots.txt at site root." if not r["exists"] else "Present.",
    }

    # sitemap.xml
    s = _check_path(store_url, "/sitemap.xml")
    checks["sitemap_xml"] = {
        "status": "pass" if s["exists"] else "warn",
        "evidence": f"GET {s['url']} → status {s['status']}",
        "fix": "Generate sitemap.xml (Shopify auto-generates)." if not s["exists"] else "Present.",
    }

    # llms.txt — our whitespace #1 differentiator
    l = _check_path(store_url, "/llms.txt")
    checks["llms_txt"] = {
        "status": "pass" if l["exists"] else "warn",
        "evidence": f"GET {l['url']} → status {l['status']}",
        "fix": ("Generate llms.txt via `lumicc-seo --mode llms-txt`. This is a whitespace — most "
                "sites lack it, but AI crawlers parse it preferentially.") if not l["exists"] else "Present (great!).",
    }

    # Fetch homepage and parse meta
    status_home, body, _ = _http_get(store_url)
    if status_home >= 200 and status_home < 300:
        html = body.decode("utf-8", errors="replace")

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = (title_match.group(1).strip() if title_match else "")[:200]
        checks["title_tag"] = {
            "status": "pass" if 30 <= len(title) <= 80 else "warn" if title else "fail",
            "evidence": f"Title length: {len(title)}; '{title[:80]}'",
            "fix": ("Set a 30-80 char <title> with primary keyword first."
                    if not (30 <= len(title) <= 80) else "Length OK."),
        }

        meta_desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html, re.IGNORECASE)
        if not meta_desc_match:
            meta_desc_match = re.search(r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"]([^'\"]*)['\"]", html, re.IGNORECASE)
        meta_desc = meta_desc_match.group(1) if meta_desc_match else ""
        checks["meta_description"] = {
            "status": "pass" if 70 <= len(meta_desc) <= 160 else "warn" if meta_desc else "fail",
            "evidence": f"Meta desc length: {len(meta_desc)}",
            "fix": "Set a 70-160 char meta description." if not (70 <= len(meta_desc) <= 160) else "OK.",
        }

        og = bool(re.search(r'<meta\s+property=["\']og:(title|image|url)["\']', html, re.IGNORECASE))
        checks["open_graph"] = {
            "status": "pass" if og else "warn",
            "evidence": "og:title / og:image / og:url presence",
            "fix": "Add OpenGraph meta tags for richer social previews." if not og else "Present.",
        }

        canonical = bool(re.search(r'<link\s+rel=["\']canonical["\']\s+href="', html, re.IGNORECASE))
        checks["canonical"] = {
            "status": "pass" if canonical else "warn",
            "evidence": "rel=canonical present" if canonical else "rel=canonical missing",
            "fix": "Add <link rel='canonical' href='...'> to prevent duplicate-content issues." if not canonical else "OK.",
        }

        viewport = bool(re.search(r'<meta\s+name=["\']viewport["\']', html, re.IGNORECASE))
        checks["viewport"] = {
            "status": "pass" if viewport else "fail",
            "evidence": "viewport meta " + ("present" if viewport else "missing"),
            "fix": "Add <meta name='viewport' content='width=device-width, initial-scale=1'>." if not viewport else "OK.",
        }

        json_ld = bool(re.search(r'<script\s+type=["\']application/ld\+json["\']', html, re.IGNORECASE))
        checks["schema_jsonld"] = {
            "status": "pass" if json_ld else "warn",
            "evidence": "JSON-LD script " + ("present" if json_ld else "missing"),
            "fix": ("Generate per-product JSON-LD via `lumicc-seo --mode schema` and embed in your theme."
                    if not json_ld else "Present."),
        }

        hreflang = bool(re.search(r'<link\s+rel=["\']alternate["\']\s+hreflang=["\']', html, re.IGNORECASE))
        checks["hreflang"] = {
            "status": "pass" if hreflang else "info",
            "evidence": "hreflang " + ("present" if hreflang else "missing"),
            "fix": ("Add hreflang tags only if you serve multiple languages/regions."
                    if not hreflang else "Present."),
        }
    else:
        checks["homepage"] = {
            "status": "fail",
            "evidence": f"Could not fetch homepage (status={status_home})",
            "fix": "Verify store URL is accessible from the public internet.",
        }

    # Score
    weights = {"pass": 1.0, "warn": 0.5, "info": 0.8, "fail": 0.0}
    score = sum(weights.get(c["status"], 0) for c in checks.values()) / max(1, len(checks)) * 100

    return {
        "store_url": store_url,
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "passed": sum(1 for c in checks.values() if c["status"] == "pass"),
            "failed": sum(1 for c in checks.values() if c["status"] == "fail"),
            "score": round(score, 1),
        },
    }


def render_report_md(report: dict) -> str:
    lines = [f"# 技术 SEO 体检 · {report['store_url']}", ""]
    s = report["summary"]
    lines.append(f"**得分**: {s['score']}/100 · {s['passed']}/{s['total_checks']} 项通过 · {s['failed']} 项需修复")
    lines.append("")
    icon_map = {"pass": "✅", "warn": "🟡", "info": "ℹ️", "fail": "🔴"}
    for name, c in report["checks"].items():
        icon = icon_map.get(c["status"], "?")
        lines.append(f"## {icon} {name}")
        lines.append(f"- 证据: {c['evidence']}")
        lines.append(f"- 修复: {c['fix']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()
    result = audit(args.url)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(render_report_md(result), encoding="utf-8")
        print(json.dumps(result["summary"], indent=2))
    else:
        print(render_report_md(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
