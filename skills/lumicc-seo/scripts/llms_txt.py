#!/usr/bin/env python3
"""llms.txt generator + validator — pure stdlib.

llms.txt is a proposed standard (llmstxt.org) that gives AI crawlers a curated
map of your site, similar to how robots.txt + sitemap.xml work for search
engines. Format is minimal Markdown:

  # Site Name
  > One-line description.

  ## Section
  - [Link text](url): optional description

We generate it from store info + active products + recommended collections,
and we validate the format against the spec.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Sections we emit (in this order)
DEFAULT_SECTIONS = ["products", "collections", "policies", "about", "blog"]

# Validation rules (subset of llmstxt.org spec we enforce)
H1_RE = re.compile(r"^# .+", re.MULTILINE)
H2_RE = re.compile(r"^## .+", re.MULTILINE)
LINK_LINE_RE = re.compile(r"^- \[([^\]]+)\]\((https?://[^)]+)\)(?::\s*.+)?$", re.MULTILINE)
BLOCKQUOTE_RE = re.compile(r"^>\s+.+", re.MULTILINE)


def generate(*, store_name: str, store_url: str, description: str,
             products: list[dict], collections: list[dict] | None = None,
             policies: list[dict] | None = None,
             about_url: str | None = None,
             blog_url: str | None = None) -> str:
    """Build an llms.txt string.

    `products` is a list of {"title", "url", "description"?} dicts.
    """
    lines: list[str] = []
    lines.append(f"# {store_name}")
    lines.append("")
    lines.append(f"> {description}")
    lines.append("")

    if products:
        lines.append("## Products")
        lines.append("")
        for p in products:
            title = p.get("title", "—")
            url = p.get("url") or (store_url.rstrip("/") + f"/products/{p.get('handle','')}")
            desc = p.get("description") or p.get("short_desc") or ""
            line = f"- [{title}]({url})"
            if desc:
                line += f": {desc[:140]}"
            lines.append(line)
        lines.append("")

    if collections:
        lines.append("## Collections")
        lines.append("")
        for c in collections:
            title = c.get("title", "—")
            url = c.get("url") or (store_url.rstrip("/") + f"/collections/{c.get('handle','')}")
            desc = c.get("description") or ""
            line = f"- [{title}]({url})"
            if desc:
                line += f": {desc[:140]}"
            lines.append(line)
        lines.append("")

    if policies:
        lines.append("## Policies")
        lines.append("")
        for pol in policies:
            title = pol.get("title", "—")
            url = pol.get("url", "")
            lines.append(f"- [{title}]({url})")
        lines.append("")

    if about_url:
        lines.append("## About")
        lines.append("")
        lines.append(f"- [About {store_name}]({about_url}): brand story, mission, contact")
        lines.append("")

    if blog_url:
        lines.append("## Blog")
        lines.append("")
        lines.append(f"- [Blog]({blog_url}): articles and guides")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def validate(content: str) -> dict:
    """Validate an llms.txt against our subset of llmstxt.org spec.

    Returns {"ok": bool, "errors": [...], "warnings": [...]}.
    """
    errors: list[str] = []
    warnings: list[str] = []

    h1s = H1_RE.findall(content)
    if not h1s:
        errors.append("Missing top-level # heading (site name)")
    elif len(h1s) > 1:
        errors.append(f"Multiple # headings ({len(h1s)}); spec allows only one site name")

    if not BLOCKQUOTE_RE.search(content):
        warnings.append("No '> blockquote' description — recommended right after the title")

    if not H2_RE.findall(content):
        warnings.append("No ## sections — content has no structure beyond the title")

    if "## Products" not in content and "## products" not in content.lower():
        warnings.append("No Products section — e-commerce sites should list products here")

    # Verify links are well-formed
    bad_links: list[str] = []
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("- [") and "](" in s:
            m = LINK_LINE_RE.match(line)
            if not m:
                bad_links.append(line[:120])
    if bad_links:
        warnings.append(f"{len(bad_links)} link lines do not match `- [text](url): desc` shape")

    char_count = len(content)
    if char_count > 50000:
        warnings.append(f"File is {char_count} chars (>50KB) — consider trimming to keep crawler-friendly")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "char_count": char_count,
        "section_count": len(H2_RE.findall(content)),
        "link_count": len(LINK_LINE_RE.findall(content)),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("generate")
    p_gen.add_argument("--input", required=True, help="JSON file with {store_name, store_url, description, products, ...}")
    p_gen.add_argument("--out", default=None)

    p_val = sub.add_parser("validate")
    p_val.add_argument("--input", required=True, help="llms.txt path")

    args = p.parse_args()

    if args.cmd == "generate":
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        content = generate(**data)
        if args.out:
            Path(args.out).write_text(content, encoding="utf-8")
            print(json.dumps({"saved": args.out, "char_count": len(content)}, ensure_ascii=False))
        else:
            sys.stdout.write(content)
    elif args.cmd == "validate":
        content = Path(args.input).read_text(encoding="utf-8")
        result = validate(content)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
