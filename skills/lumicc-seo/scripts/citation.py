#!/usr/bin/env python3
"""GEO citation tracker — find your brand mentions in AI engine answers.

Paste mode (default): user manually queries ChatGPT / Perplexity / etc.
and pastes the answers as JSON. We parse for brand keyword occurrences,
compute citation share, and persist to seo_citations table for trend analysis.

Per-engine citation behavior differs sharply: ChatGPT cites Wikipedia 48%,
Perplexity cites Reddit 47%, overlap between them is only 11%. Track each
engine independently.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

VALID_ENGINES = {
    "chatgpt", "openai", "claude", "anthropic",
    "perplexity", "gemini", "google", "ai_overviews",
    "bing", "copilot", "doubao", "kimi",
}


def normalize_engine(name: str) -> str:
    s = (name or "").lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "openai": "chatgpt", "gpt": "chatgpt", "gpt4": "chatgpt", "gpt_4": "chatgpt",
        "gpt_4o": "chatgpt", "gpt_5": "chatgpt", "chat_gpt": "chatgpt",
        "anthropic": "claude", "claude_3": "claude", "claude_4": "claude",
        "google": "gemini", "gemini_pro": "gemini",
        "sge": "ai_overviews", "ai_overview": "ai_overviews", "google_sge": "ai_overviews",
        "copilot": "bing", "microsoft": "bing", "bing_chat": "bing",
        "doubao_pro": "doubao", "kimi_chat": "kimi",
    }
    return aliases.get(s, s)


def find_brand_mentions(text: str, brand_keywords: list[str],
                         competitor_keywords: list[str] | None = None) -> dict:
    """Find brand mentions in an answer text.

    Returns counts + positions + competitor counts for comparison.
    """
    text_l = text or ""
    mentions: list[dict] = []
    for kw in brand_keywords:
        kw_l = kw.lower()
        # find all positions (case-insensitive)
        for m in re.finditer(re.escape(kw_l), text_l.lower()):
            mentions.append({"keyword": kw, "char_pos": m.start()})
    mentions.sort(key=lambda x: x["char_pos"])

    competitor_count = 0
    competitor_hits: list[dict] = []
    for kw in (competitor_keywords or []):
        for m in re.finditer(re.escape(kw.lower()), text_l.lower()):
            competitor_count += 1
            competitor_hits.append({"competitor": kw, "char_pos": m.start()})

    # "Position" = rank of first brand mention among (brand + competitor) mentions
    all_hits = []
    for m in mentions:
        all_hits.append({"is_brand": True, "char_pos": m["char_pos"]})
    for c in competitor_hits:
        all_hits.append({"is_brand": False, "char_pos": c["char_pos"]})
    all_hits.sort(key=lambda x: x["char_pos"])
    position = None
    for rank, hit in enumerate(all_hits, 1):
        if hit["is_brand"]:
            position = rank
            break

    return {
        "brand_mentions": len(mentions),
        "competitor_mentions": competitor_count,
        "share": (len(mentions) / max(1, len(mentions) + competitor_count)),
        "position": position,
        "first_mention_excerpt": _excerpt_around(text_l, mentions[0]["char_pos"]) if mentions else None,
    }


def _excerpt_around(text: str, pos: int, radius: int = 80) -> str:
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    return text[start:end].strip()


def process_batch(queries: list[dict], brand_keywords: list[str],
                  competitor_keywords: list[str] | None = None) -> list[dict]:
    """Process a batch of {engine, query, raw_answer} dicts.

    Returns a list of analyzed results ready for DB insertion.
    """
    out: list[dict] = []
    for q in queries:
        engine = normalize_engine(q.get("engine", ""))
        if engine not in VALID_ENGINES:
            continue
        analysis = find_brand_mentions(
            q.get("raw_answer", ""), brand_keywords, competitor_keywords,
        )
        out.append({
            "engine": engine,
            "query": q.get("query", ""),
            "brand_mentioned": analysis["brand_mentions"] > 0,
            "brand_mentions": analysis["brand_mentions"],
            "competitor_mentions": analysis["competitor_mentions"],
            "share": round(analysis["share"], 3),
            "position": analysis["position"],
            "raw_answer_excerpt": (q.get("raw_answer") or "")[:500],
            "first_mention_excerpt": analysis["first_mention_excerpt"],
        })
    return out


def render_report_md(results: list[dict], brand_keyword: str) -> str:
    if not results:
        return "_未检测到匹配的引擎查询数据。_"
    by_engine: dict[str, list[dict]] = {}
    for r in results:
        by_engine.setdefault(r["engine"], []).append(r)
    lines = [f"# GEO 引用追踪 · {brand_keyword}", ""]
    overall_share = sum(r["share"] for r in results) / len(results)
    n_mentioned = sum(1 for r in results if r["brand_mentioned"])
    lines.append(f"**整体表现**: 在 {len(results)} 个查询中被引用 {n_mentioned} 次（平均引用份额 {overall_share:.1%}）")
    lines.append("")
    for engine, rs in sorted(by_engine.items()):
        mentioned = sum(1 for r in rs if r["brand_mentioned"])
        share = sum(r["share"] for r in rs) / len(rs)
        icon = "🟢" if mentioned == len(rs) else "🟡" if mentioned > 0 else "🔴"
        lines.append(f"\n## {icon} {engine} ({mentioned}/{len(rs)} · 平均份额 {share:.1%})")
        for r in rs:
            badge = "✓" if r["brand_mentioned"] else "✗"
            pos = f" · 位置 #{r['position']}" if r["position"] else ""
            lines.append(f"- {badge} `{r['query'][:80]}`{pos}")
            if r["first_mention_excerpt"]:
                lines.append(f"  > {r['first_mention_excerpt'][:140]}...")
    return "\n".join(lines)


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queries-file", required=True,
                   help="JSON list of {engine, query, raw_answer} dicts")
    p.add_argument("--brand-keyword", action="append", required=True,
                   help="Brand keyword to look for. Repeatable.")
    p.add_argument("--competitor-keyword", action="append", default=[],
                   help="Competitor keyword for share comparison. Repeatable.")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    queries = json.loads(open(args.queries_file, encoding="utf-8").read())
    if not isinstance(queries, list):
        queries = [queries]
    results = process_batch(queries, args.brand_keyword, args.competitor_keyword)
    out = json.dumps({
        "brand_keywords": args.brand_keyword,
        "competitor_keywords": args.competitor_keyword,
        "results": results,
        "report_md": render_report_md(results, args.brand_keyword[0] if args.brand_keyword else "—"),
    }, ensure_ascii=False, indent=2)
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(out, encoding="utf-8")
        print(json.dumps({"saved": args.out, "results": len(results)}))
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
