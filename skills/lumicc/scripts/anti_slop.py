#!/usr/bin/env python3
"""Anti-Slop quality gate for Lumicc.

Detects 6 categories of AI-generated low-quality text patterns:

    G1: no_llm_filler       — LLM 套话 (Let me help, 总结来说, ...)
    G2: no_word_stack       — 形容词堆栈 (innovative cutting-edge revolutionary)
    G3: be_specific         — 模糊词无数字 (recently, many, 近期, 大量)
    G4: data_has_source     — 数据无来源 (87% lift 没出处)
    G5: no_fake_authority   — 假权威 (experts say, 据研究)
    G6: chinese_not_machine — 中文机翻味 (利用我们的, 中文里夹英文逗号)

Public API:
    check_slop(text, *, lang="auto", gates=None, severity_threshold="warn") -> SlopReport
    render_banner(report) -> str           # short HTML snippet
    render_report_html(report) -> str      # full HTML page

CLI:
    python3 anti_slop.py --file report.md
    cat draft.txt | python3 anti_slop.py --stdin
    python3 anti_slop.py --file report.md --gates G1,G2,G6
    python3 anti_slop.py --file report.md --quiet-stdout       # JSON
    python3 anti_slop.py --file report.md --html-report > out.html

Exit codes: 0 = passed, 1 = violations, 2 = error.

Optional banner integration in another skill's render_html.py:

    from anti_slop import check_slop, render_banner
    body = build_body(...)
    report = check_slop(body, lang="zh")
    return H.page(body=render_banner(report) + body, title="...")

Pure stdlib. Conservative on purpose: false negatives preferred over false positives.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

VERSION = "0.1.0"
ALL_GATES = ("G1", "G2", "G3", "G4", "G5", "G6")
SEVERITY_RANK = {"info": 0, "warn": 1, "block": 2}
SNIPPET_MAX = 120


# =============================================================================
# Types
# =============================================================================

class Violation(NamedTuple):
    gate: str
    line: int
    snippet: str
    match: str
    suggestion: str


class SlopReport(NamedTuple):
    passed: bool
    gate_counts: dict
    violations: list
    total_chars: int


# =============================================================================
# Patterns
# =============================================================================

# Severity (info/warn/block) — used by severity_threshold filter
_GATE_SEVERITY = {
    "G1": "warn",
    "G2": "warn",
    "G3": "warn",
    "G4": "block",
    "G5": "block",
    "G6": "warn",
}

# G1: LLM filler
G1_PATTERNS = [
    (r"\blet me (help|assist|walk you|guide|show)\b", "去掉套话, 直接给结论"),
    (r"\bi'?d be happy to\b", "去掉套话, 直接给结论"),
    (r"\bi hope this helps\b", "去掉收尾套话"),
    (r"\bhere'?s a comprehensive\b", "改成 '以下是...' 或直接列表"),
    (r"\b(sure|of course|absolutely|certainly)!?[,.\s]", "回声式问候, 删掉"),
    (r"\bas an ai (language )?model\b", "去掉自我介绍"),
    (r"\bi'?ll (now |go ahead and )?(help|create|generate|provide)\b", "改成主动语态"),
    (r"\bgreat question\b", "去掉奉承"),
    (r"(总结来说|综上所述|总而言之)", "去掉套话, 直接给结论"),
    (r"让我.{0,4}(帮|为你|来)", "去掉套话, 直接给行动"),
    (r"希望.{0,6}(能帮|对你|有所帮助)", "去掉收尾套话"),
    (r"作为一个?(AI|人工智能|语言模型)", "去掉自我介绍"),
    (r"很高兴(为你|能够|帮助)", "去掉奉承"),
    (r"以下是.{0,4}全面的?", "改成 '以下是...' 或直接列表"),
    (r"接下来,?\s*让我", "去掉套话"),
]

# G2: word stack — adjective stacking
# EN: 3+ consecutive adjectives matching common suffixes
G2_EN_ADJ_RE = re.compile(
    r"\b((?:\w+(?:ing|ive|ful|ous|al|able|ible|ent|ant))\s+){2}\w+(?:ing|ive|ful|ous|al|able|ible|ent|ant)\b",
    re.IGNORECASE,
)
# ZH: 3+ adjectives joined (e.g. 高效优质卓越的) — heuristic
# Detect 3+ 2-char adjective-like runs before "的"
G2_ZH_ADJ_RE = re.compile(
    r"([一-鿿]{2}){3,}的"
)

# G3: vague terms (require nearby number to NOT match)
G3_EN_TERMS = [
    "recently", "many", "various", "several", "numerous", "a lot of",
    "short-term", "long-term", "near future", "soon", "some",
    "significant", "substantial", "considerable",
]
G3_ZH_TERMS = [
    "近期", "若干", "大量", "短期内", "中长期", "一定程度",
    "众多", "诸多", "许多", "不少", "近日", "最近",
    "显著(的)?(提升|增长|改善)", "大幅(度)?",
]

# G4: numbers/percentages without source
# Trigger: a digit followed by % or money/multiplier
G4_NUMBER_RE = re.compile(
    r"(?:[\$￥€£]\s?\d[\d,]*(?:\.\d+)?|\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*[xX×]\b|\d{3,}(?:,\d{3})+)"
)
# Source markers — if present within +/-80 chars of number, accepted
G4_SOURCE_MARKERS = [
    "store.db", "shopify", "gsc", "ga4", "google search console",
    "google analytics", "amazon", "tiktok", "meta",
    "per ", "from ", "source:", "源自", "来自", "据", "出自",
    "see ", "ref:", "ref.", "参考", "数据来自", "数据源", ".csv", ".db",
    "export", "report", "/data/",
]

# G5: fake authority
G5_PATTERNS = [
    (r"\baccording to (research|studies|experts|some)\b", "改成具体来源 (e.g. 'per Shopify 2024 report')"),
    (r"\b(experts|researchers|studies|scientists) (say|believe|show|suggest|agree)\b",
     "改成具体来源"),
    (r"\bit is (widely |generally )?(known|believed|accepted)\b", "去掉权威套话"),
    (r"\bresearch (shows|suggests|indicates)\b", "改成具体研究 / DOI / 数据集"),
    (r"\bstudies have shown\b", "改成具体研究"),
    (r"据(研究|专家|权威|调查|统计)", "改成具体来源 (店内数据 / 公开报告)"),
    (r"(专家|权威机构|学者)(表示|认为|指出|建议)", "改成具体来源"),
    (r"(众所周知|大家都知道|公认)", "去掉权威套话"),
    (r"调查显示", "改成具体调查 (谁做的, 何时)"),
]

# G6: Chinese machine-translation tells
G6_PATTERNS = [
    (r"利用我们的", "改成 '用我们的'"),
    (r"接下来的几(个|步|项)", "改成 '接下来几$1'"),
    (r"将会有.{0,6}(提升|改善|增长|改进)", "改成 '会$1'"),
    (r"进行(一个|一次)([一-鿿]{1,4})", "改成 '$2一下' 或直接动词"),
    (r"做出([一-鿿]{2,4})", "改成动词 (e.g. '决定', 不要 '做出决定' 之类堆叠)"),
    (r"这是一个非常.{1,4}的", "去掉 '非常', 形容词单用"),
    (r"在.{1,8}的方面", "改成 '在...上' 或删掉"),
    (r"为了.{1,8}的目的", "改成 '为了...'"),
    (r"通过使用", "改成 '用' / '靠'"),
    (r"上述(所提到的|所述)", "改成 '上面' / '前面'"),
    (r",\s*[一-鿿]", "中文上下文里, 用全角逗号 '，'"),
    (r"[一-鿿]\s+[一-鿿]", "中文词之间不要加英文空格"),
    (r"基于.{1,8}的基础上", "'基于...' 或 '在...的基础上', 不要叠"),
    (r"对.{1,8}进行.{1,8}", "改成主动语态 (e.g. '处理 X' 而非 '对 X 进行处理')"),
]


# =============================================================================
# Language detection
# =============================================================================

_CJK_RE = re.compile(r"[一-鿿]")


def _detect_lang(text: str) -> str:
    if not text:
        return "en"
    cjk = len(_CJK_RE.findall(text))
    ratio = cjk / max(len(text), 1)
    if ratio > 0.3:
        return "zh"
    if ratio > 0.05:
        return "mixed"
    return "en"


def _is_zh_active(lang: str) -> bool:
    return lang in ("zh", "mixed", "auto")


def _is_en_active(lang: str) -> bool:
    return lang in ("en", "mixed", "auto")


# =============================================================================
# Helpers
# =============================================================================

def _line_of(text: str, pos: int) -> int:
    """1-indexed line number for character offset."""
    return text.count("\n", 0, pos) + 1


def _snippet(text: str, start: int, end: int, pad: int = 30) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    out = text[s:e].replace("\n", " ").strip()
    if len(out) > SNIPPET_MAX:
        out = out[: SNIPPET_MAX - 1] + "…"
    return out


def _has_source_nearby(text: str, pos: int, window: int = 80) -> bool:
    s = max(0, pos - window)
    e = min(len(text), pos + window)
    chunk = text[s:e].lower()
    return any(m in chunk for m in G4_SOURCE_MARKERS)


# =============================================================================
# Gate runners
# =============================================================================

def _run_pattern_list(
    text: str,
    patterns: Iterable,
    gate: str,
    flags: int = re.IGNORECASE,
) -> list:
    out = []
    for pat, sugg in patterns:
        try:
            rx = re.compile(pat, flags)
        except re.error:
            continue
        for m in rx.finditer(text):
            out.append(Violation(
                gate=gate,
                line=_line_of(text, m.start()),
                snippet=_snippet(text, m.start(), m.end()),
                match=m.group(0)[:80],
                suggestion=sugg,
            ))
    return out


def _gate_g1(text: str, lang: str) -> list:
    return _run_pattern_list(text, G1_PATTERNS, "G1")


def _gate_g2(text: str, lang: str) -> list:
    out = []
    if _is_en_active(lang):
        for m in G2_EN_ADJ_RE.finditer(text):
            out.append(Violation(
                "G2", _line_of(text, m.start()),
                _snippet(text, m.start(), m.end()),
                m.group(0)[:80],
                "形容词堆叠, 挑一个最准的",
            ))
    if _is_zh_active(lang):
        for m in G2_ZH_ADJ_RE.finditer(text):
            # heuristic: only flag if the adjective run is >= 6 chars (3+ 2-char adjs)
            if len(m.group(0)) >= 7:  # 6 chars + 的
                out.append(Violation(
                    "G2", _line_of(text, m.start()),
                    _snippet(text, m.start(), m.end()),
                    m.group(0)[:80],
                    "中文形容词堆叠, 挑一个最准的",
                ))
    return out


def _gate_g3(text: str, lang: str) -> list:
    out = []
    terms = []
    if _is_en_active(lang):
        terms += [(t, "改成具体数字/时间 (e.g. 'in Q1 2026', '17 stores')") for t in G3_EN_TERMS]
    if _is_zh_active(lang):
        terms += [(t, "改成具体数字/时间 (e.g. '2026年Q1', '17 家店')") for t in G3_ZH_TERMS]
    for term, sugg in terms:
        rx = re.compile(r"\b" + term + r"\b" if re.match(r"[a-z\-\s]+$", term) else term,
                        re.IGNORECASE)
        for m in rx.finditer(text):
            # Skip if a number appears within +/- 40 chars
            s = max(0, m.start() - 40)
            e = min(len(text), m.end() + 40)
            if re.search(r"\d", text[s:e]):
                continue
            out.append(Violation(
                "G3", _line_of(text, m.start()),
                _snippet(text, m.start(), m.end()),
                m.group(0)[:80], sugg,
            ))
    return out


def _gate_g4(text: str, lang: str) -> list:
    out = []
    for m in G4_NUMBER_RE.finditer(text):
        if _has_source_nearby(text, m.start()):
            continue
        out.append(Violation(
            "G4", _line_of(text, m.start()),
            _snippet(text, m.start(), m.end()),
            m.group(0)[:80],
            "数字要带出处 (e.g. 'per store.db', '来自 Shopify 导出')",
        ))
    return out


def _gate_g5(text: str, lang: str) -> list:
    return _run_pattern_list(text, G5_PATTERNS, "G5")


def _gate_g6(text: str, lang: str) -> list:
    # Only meaningful when ZH is present
    if not _is_zh_active(lang):
        return []
    # Skip pure-English text
    if not _CJK_RE.search(text):
        return []
    return _run_pattern_list(text, G6_PATTERNS, "G6", flags=0)


_GATE_RUNNERS = {
    "G1": _gate_g1,
    "G2": _gate_g2,
    "G3": _gate_g3,
    "G4": _gate_g4,
    "G5": _gate_g5,
    "G6": _gate_g6,
}


# =============================================================================
# Public API
# =============================================================================

def check_slop(
    text: str,
    *,
    lang: str = "auto",
    gates: list | None = None,
    severity_threshold: str = "warn",
) -> SlopReport:
    """Lint text against the 6 Anti-Slop gates. Never raises."""
    try:
        text = text or ""
        if lang == "auto":
            lang = _detect_lang(text)
        active_gates = list(gates) if gates else list(ALL_GATES)
        active_gates = [g for g in active_gates if g in _GATE_RUNNERS]

        threshold_rank = SEVERITY_RANK.get(severity_threshold, 1)
        active_gates = [
            g for g in active_gates
            if SEVERITY_RANK.get(_GATE_SEVERITY.get(g, "warn"), 1) >= threshold_rank
        ]

        violations: list = []
        gate_counts = {g: 0 for g in ALL_GATES}
        for g in active_gates:
            try:
                vs = _GATE_RUNNERS[g](text, lang)
            except Exception:
                vs = []
            violations.extend(vs)
            gate_counts[g] = len(vs)

        # Sort by line, then gate
        violations.sort(key=lambda v: (v.line, v.gate))

        return SlopReport(
            passed=(len(violations) == 0),
            gate_counts=gate_counts,
            violations=violations,
            total_chars=len(text),
        )
    except Exception as e:  # noqa: BLE001 — top-level guard, must not crash callers
        # SECURITY: failing to run the slop check should NOT silently report "clean".
        # Log to stderr (debug) and surface as a single G0 violation so callers see
        # the gate didn't run. See code-review v1.0 MEDIUM#3.
        import sys as _sys
        print(f"anti_slop: check_slop crashed ({type(e).__name__}: {e})", file=_sys.stderr)
        viol = [Violation(gate="G0", line=0, snippet="(slop check errored)",
                          match=str(e)[:120],
                          suggestion="Anti-slop gate failed to run; treat as not-checked.")]
        return SlopReport(False, {g: 0 for g in ALL_GATES}, viol, len(text or ""))


# =============================================================================
# HTML rendering (optional — only used when html_lib available)
# =============================================================================

def _try_import_html_lib():
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import html_lib as H  # type: ignore
        return H
    except Exception:
        return None


_GATE_TITLES = {
    "G1": "G1 · LLM 套话",
    "G2": "G2 · 堆栈词",
    "G3": "G3 · 模糊词无数字",
    "G4": "G4 · 数据无源",
    "G5": "G5 · 假权威",
    "G6": "G6 · 中文机翻味",
}


def _esc(s: str) -> str:
    H = _try_import_html_lib()
    if H is not None:
        return H.esc(s)
    import html as _h
    return _h.escape(str(s or ""), quote=True)


def render_banner(report: SlopReport) -> str:
    """Short HTML snippet shown at top of a report when slop is detected."""
    if report.passed:
        return ""
    top = report.violations[:3]
    items = "".join(
        f"<li><b>{_esc(v.gate)}</b> (L{v.line}): "
        f"<code>{_esc(v.match)}</code> — {_esc(v.suggestion)}</li>"
        for v in top
    )
    total = len(report.violations)
    more = f" (+{total - 3} more)" if total > 3 else ""
    return (
        '<div style="margin:12px 0;padding:12px 16px;border:1px solid #f59e0b;'
        'background:#fef3c7;color:#78350f;border-radius:8px;font-size:13px;">'
        f'<b>⚠ Anti-Slop: {total} violation(s){more}</b>'
        f'<ul style="margin:6px 0 0 16px;padding:0;">{items}</ul>'
        '</div>'
    )


def render_report_html(report: SlopReport) -> str:
    """Full HTML page grouping violations by gate."""
    H = _try_import_html_lib()
    by_gate: dict = {g: [] for g in ALL_GATES}
    for v in report.violations:
        by_gate.setdefault(v.gate, []).append(v)

    if H is None:
        # Fallback minimal HTML
        rows = ""
        for g in ALL_GATES:
            vs = by_gate.get(g, [])
            rows += f"<h2>{_esc(_GATE_TITLES[g])} — {len(vs)}</h2>"
            if not vs:
                rows += "<p>✓ clean</p>"
                continue
            rows += "<ul>"
            for v in vs:
                rows += (
                    f"<li>L{v.line}: <code>{_esc(v.match)}</code><br>"
                    f"<small>{_esc(v.snippet)}</small><br>"
                    f"<i>→ {_esc(v.suggestion)}</i></li>"
                )
            rows += "</ul>"
        status = "PASSED" if report.passed else f"FAILED ({len(report.violations)} violations)"
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Anti-Slop Report</title></head><body>"
            f"<h1>Anti-Slop: {status}</h1>"
            f"<p>Total chars: {report.total_chars}</p>"
            f"{rows}</body></html>"
        )

    # Rich HTML via html_lib
    cards = []
    for g in ALL_GATES:
        vs = by_gate.get(g, [])
        if not vs:
            body = H.empty_state("✓ 通过", hint=f"{_GATE_TITLES[g]} 无违规")
        else:
            rows = [[
                f"L{v.line}",
                f"<code>{H.esc(v.match)}</code>",
                H.esc(v.snippet),
                H.esc(v.suggestion),
            ] for v in vs]
            body = H.table(["行", "命中", "上下文", "建议"], rows)
        tag = "ok" if not vs else "warn"
        color = "green" if not vs else "amber"
        cards.append(H.card(
            title=_GATE_TITLES[g],
            tag=f"{len(vs)}", tag_color=color,
            body=body,
        ))

    status_badge = (H.badge("PASSED", color="green") if report.passed
                    else H.badge(f"{len(report.violations)} VIOLATIONS", color="red"))
    header = H.section("Anti-Slop 质检", H.kpi_strip([
        ("Status", status_badge, ""),
        ("Total chars", report.total_chars, ""),
        ("Violations", len(report.violations), ""),
    ]))
    body = header + H.card_grid(cards, min_width=420)
    return H.page(title="Anti-Slop Report", body=body, active=None)


# =============================================================================
# CLI
# =============================================================================

def _parse_gates(spec: str | None) -> list | None:
    if not spec:
        return None
    gs = [g.strip().upper() for g in spec.split(",") if g.strip()]
    return [g for g in gs if g in ALL_GATES] or None


def _report_to_dict(r: SlopReport) -> dict:
    return {
        "passed": r.passed,
        "gate_counts": r.gate_counts,
        "total_chars": r.total_chars,
        "violations": [
            {"gate": v.gate, "line": v.line, "snippet": v.snippet,
             "match": v.match, "suggestion": v.suggestion}
            for v in r.violations
        ],
    }


def _print_text(r: SlopReport, out=sys.stdout) -> None:
    if r.passed:
        print("✓ Anti-Slop PASSED (0 violations)", file=out)
        return
    print(f"✗ Anti-Slop FAILED — {len(r.violations)} violation(s) "
          f"across {r.total_chars} chars", file=out)
    for g in ALL_GATES:
        c = r.gate_counts.get(g, 0)
        if c:
            print(f"  {_GATE_TITLES[g]}: {c}", file=out)
    print("", file=out)
    for v in r.violations[:50]:
        print(f"  [{v.gate}] L{v.line}: {v.match}", file=out)
        print(f"          ↳ {v.suggestion}", file=out)
    if len(r.violations) > 50:
        print(f"  ... (+{len(r.violations) - 50} more)", file=out)


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(prog="anti_slop", description="Lumicc Anti-Slop quality gate")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--file", help="path to text/markdown file")
    src.add_argument("--stdin", action="store_true", help="read text from stdin")
    p.add_argument("--lang", choices=["auto", "en", "zh", "mixed"], default="auto")
    p.add_argument("--gates", help="comma-separated subset, e.g. G1,G2")
    p.add_argument("--severity", choices=["info", "warn", "block"], default="warn")
    p.add_argument("--quiet-stdout", action="store_true", help="emit JSON instead of text")
    p.add_argument("--html-report", action="store_true", help="emit full HTML page")
    args = p.parse_args(argv)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"error: file not found: {args.file}", file=sys.stderr)
            return 2
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"error: cannot read {args.file}: {e}", file=sys.stderr)
            return 2
    elif args.stdin:
        text = sys.stdin.read()
    else:
        # No source — read stdin if piped, otherwise error
        if not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            p.print_help(sys.stderr)
            return 2

    report = check_slop(
        text,
        lang=args.lang,
        gates=_parse_gates(args.gates),
        severity_threshold=args.severity,
    )

    if args.html_report:
        sys.stdout.write(render_report_html(report))
    elif args.quiet_stdout:
        json.dump(_report_to_dict(report), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_text(report)

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
