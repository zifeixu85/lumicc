#!/usr/bin/env python3
"""Render lumicc-watch report.html — visual companion to the markdown report.

Visual differentiators:
  - Per-target tab UI (one tab per host) with snapshot timestamps
  - Severity badges (high=rose / medium=amber / low=sky) on every change
  - Change-cards with before/after snippets for banner/hero/SEO/social
  - Flat audit log table across all targets
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H  # noqa: E402


CATEGORY_LABEL: dict[str, str] = {
    "new_product": "🆕 新品上架",
    "removed_product": "❌ 下架",
    "promo_banner_change": "🎯 促销变化",
    "homepage_hero_change": "🖼️ 首屏改版",
    "meta_seo_change": "🔎 SEO 调整",
    "social_handle_change": "📱 社交账号",
    "sitemap_size_swing": "📊 站内规模变化",
}

SEVERITY_COLOR: dict[str, str] = {
    "high": "rose",
    "medium": "amber",
    "low": "sky",
}


def _label(category: str) -> str:
    return CATEGORY_LABEL.get(category, category)


def _short(text: str | None, n: int = 60) -> str:
    if not text:
        return "—"
    t = str(text).strip().replace("\n", " ")
    return t if len(t) <= n else t[: n - 1] + "…"


def _diff_block(prev: str | None, curr: str | None) -> str:
    """before → after rendered with <code> blocks."""
    p = H.esc(prev) if prev else "<i>（空）</i>"
    c = H.esc(curr) if curr else "<i>（空）</i>"
    return (
        '<div style="display:flex;flex-direction:column;gap:6px;'
        'font-size:12px;font-family:var(--mono);">'
        f'<div><span style="color:var(--ink-muted);">before:</span> '
        f'<code style="color:var(--ink-dim);">{p}</code></div>'
        f'<div><span style="color:var(--ink-muted);">after:</span> '
        f'<code style="color:var(--ink);">{c}</code></div>'
        "</div>"
    )


def _list_block(items: list[str], cap: int = 8) -> str:
    if not items:
        return '<div style="color:var(--ink-muted);font-size:12px;">—</div>'
    lis = []
    for it in items[:cap]:
        lis.append(
            f'<li style="font-size:12px;font-family:var(--mono);'
            f'color:var(--ink-dim);">{H.esc(it)}</li>'
        )
    extra = ""
    if len(items) > cap:
        extra = (
            f'<li style="font-size:11px;color:var(--ink-muted);list-style:none;">'
            f"… +{len(items) - cap} more</li>"
        )
    return f'<ul style="margin:4px 0 0 16px;padding:0;">{"".join(lis)}{extra}</ul>'


def _change_body(ch: dict) -> str:
    cat = ch.get("category", "")
    detail = ch.get("detail") or {}
    if cat == "new_product":
        return _list_block([detail.get("url", "")])
    if cat == "removed_product":
        return _list_block([detail.get("url", "")])
    if cat == "promo_banner_change":
        return _list_block(detail.get("new_lines") or [])
    if cat == "homepage_hero_change":
        prev = " / ".join(detail.get("prev") or [])
        curr = " / ".join(detail.get("curr") or [])
        return _diff_block(_short(prev, 120), _short(curr, 120))
    if cat == "meta_seo_change":
        field = detail.get("field", "")
        head = (
            f'<div style="font-size:11px;color:var(--ink-muted);'
            f'margin-bottom:4px;">字段：<code>{H.esc(field)}</code></div>'
        )
        return head + _diff_block(
            _short(detail.get("prev"), 120),
            _short(detail.get("curr"), 120),
        )
    if cat == "social_handle_change":
        plat = detail.get("platform", "")
        head = (
            f'<div style="font-size:11px;color:var(--ink-muted);'
            f'margin-bottom:4px;">平台：<code>{H.esc(plat)}</code></div>'
        )
        return head + _diff_block(detail.get("prev"), detail.get("curr"))
    if cat == "sitemap_size_swing":
        prev = detail.get("prev", 0)
        curr = detail.get("curr", 0)
        delta = detail.get("delta_pct", 0)
        delta_color = "rose" if abs(delta) >= 15 else "amber"
        return (
            f'<div style="font-size:13px;color:var(--ink);">'
            f'<code>{prev}</code> → <code>{curr}</code> '
            f'{H.badge(f"{delta:+.1f}%", delta_color)}</div>'
        )
    # fallback: render dict
    import json as _json
    return (
        f'<pre style="font-size:11px;max-height:120px;">'
        f'{H.esc(_json.dumps(detail, ensure_ascii=False, indent=2))}</pre>'
    )


def _change_summary(ch: dict) -> str:
    cat = ch.get("category", "")
    detail = ch.get("detail") or {}
    if cat in ("new_product", "removed_product"):
        return _short(detail.get("url", ""))
    if cat == "promo_banner_change":
        lines = detail.get("new_lines") or []
        return _short(lines[0] if lines else "")
    if cat == "homepage_hero_change":
        curr = detail.get("curr") or []
        return _short(" / ".join(curr))
    if cat == "meta_seo_change":
        return f"{detail.get('field', '')}: {_short(detail.get('curr'))}"
    if cat == "social_handle_change":
        return f"{detail.get('platform', '')}: {detail.get('prev')} → {detail.get('curr')}"
    if cat == "sitemap_size_swing":
        return f"{detail.get('prev')} → {detail.get('curr')} ({detail.get('delta_pct', 0):+.1f}%)"
    return ""


# =============================================================================
# Category distribution
# =============================================================================
def render_category_distribution(all_changes: list[dict]) -> str:
    if not all_changes:
        return H.empty_state("本次没有任何变化。")
    by_cat: dict[str, list[dict]] = {}
    for ch in all_changes:
        by_cat.setdefault(ch.get("category", ""), []).append(ch)

    rows = []
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        avg_w = sum(c.get("weight", 0) for c in items) / len(items)
        sev = "high" if avg_w >= 2.0 else "medium" if avg_w >= 1.0 else "low"
        last_ts = max((c.get("ts") or 0) for c in items) or None
        rows.append([
            _label(cat),
            len(items),
            H.badge(f"{sev} ({avg_w:.1f})", SEVERITY_COLOR.get(sev, "zinc")),
            H.fmt_rel(last_ts) if last_ts else "—",
        ])
    return H.table(
        ["类别", "数量", "平均严重度", "最近一次"],
        rows,
        align=["left", "right", "center", "right"],
    )


# =============================================================================
# Per-target tab body
# =============================================================================
def render_target_body(t: dict) -> str:
    url = t.get("url", "")
    snap_ts = t.get("snapshot_ts")
    prior_ts = t.get("prior_ts")
    changes = t.get("changes") or []
    is_first = t.get("is_first_run", False)
    error = t.get("error")

    head_bits = [
        H.external_link(url, label=t.get("host") or url),
        f'<span style="color:var(--ink-muted);font-size:12px;">本次快照：'
        f'{H.esc(H.fmt_rel(snap_ts))}</span>',
    ]
    if prior_ts:
        head_bits.append(
            f'<span style="color:var(--ink-muted);font-size:12px;">上次快照：'
            f'{H.esc(H.fmt_rel(prior_ts))}</span>'
        )
    head = (
        '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;'
        f'margin-bottom:12px;">{"".join(head_bits)}</div>'
    )

    if error:
        return head + H.empty_state(f"抓取失败：{H.esc(error)}")
    if is_first:
        return head + H.empty_state(
            "首次快照，下次运行后会有 diff。",
            "保持目标 URL 不变即可累计基线。",
        )
    if not changes:
        return head + H.empty_state("本次无显著变化。", "站点没有动")

    cards = []
    for ch in changes:
        sev = ch.get("severity", "low")
        cat = ch.get("category", "")
        weight = ch.get("weight", 0)
        meta = (
            f'<span style="color:var(--ink-muted);font-size:11px;">'
            f'权重 <code>{weight:.1f}</code></span>'
        )
        cards.append(H.card(
            title=_label(cat),
            tag=sev, tag_color=SEVERITY_COLOR.get(sev, "zinc"),
            meta=meta,
            body=_change_body(ch),
        ))
    return head + H.card_grid(cards, min_width=320)


# =============================================================================
# Flat audit log
# =============================================================================
def render_audit_log(targets_results: list[dict]) -> str:
    sev_order = {"high": 0, "medium": 1, "low": 2}
    keyed: list[tuple[int, int, list]] = []
    for t in targets_results:
        host = t.get("host") or t.get("url", "")
        snap_ts = t.get("snapshot_ts") or 0
        for ch in t.get("changes") or []:
            sev = ch.get("severity", "low")
            row = [
                H.esc(host),
                _label(ch.get("category", "")),
                H.badge(sev, SEVERITY_COLOR.get(sev, "zinc")),
                H.fmt_rel(snap_ts) if snap_ts else "—",
                H.esc(_short(_change_summary(ch), 60)),
            ]
            keyed.append((sev_order.get(sev, 9), -snap_ts, row))
    if not keyed:
        return H.empty_state("无变化记录。")
    keyed.sort(key=lambda x: (x[0], x[1]))
    rows = [r for _, _, r in keyed]
    return H.table(
        ["目标", "类别", "严重度", "时间", "摘要"],
        rows,
        align=["left", "left", "center", "right", "left"],
    )


# =============================================================================
# Master render
# =============================================================================
def render_page(*, run_id: str, store_name: str,
                targets_results: list[dict], html_path: Path) -> str:
    """Render unified watch report.html."""
    n_targets = len(targets_results)
    all_changes: list[dict] = []
    for t in targets_results:
        for ch in t.get("changes") or []:
            enriched = dict(ch)
            enriched.setdefault("ts", t.get("snapshot_ts"))
            all_changes.append(enriched)
    total = len(all_changes)
    n_high = sum(1 for c in all_changes if c.get("severity") == "high")
    n_med = sum(1 for c in all_changes if c.get("severity") == "medium")

    head = H.page_head(
        f"竞品监控 · {store_name or '—'}",
        f"{n_targets} 个目标 · 共 {total} 个变化 · "
        f"Run <code>{H.esc(run_id[:8])}</code>",
    )

    kpis = H.kpi_strip([
        (n_targets, "监控目标数", "本轮扫描", "sky"),
        (total, "总变化数", "全部严重度", "indigo"),
        (n_high, "🚨 high", "需即时关注", "rose"),
        (n_med, "⚠️ medium", "近期跟进", "amber"),
    ])

    dist_section = H.section("📈 变化类别分布",
                             render_category_distribution(all_changes))

    # Tabs per target
    tab_defs: list[tuple[str, str, str]] = []
    for i, t in enumerate(targets_results):
        host = t.get("host") or f"target-{i}"
        key = f"t{i}-{host}".replace(".", "-").replace(":", "-")[:48]
        n_ch = len(t.get("changes") or [])
        label = f"{host} ({n_ch})" if n_ch else host
        tab_defs.append((key, label, render_target_body(t)))

    target_section = H.section(
        "🎯 每个目标的发现",
        H.tabs(tab_defs) if tab_defs else H.empty_state("没有配置目标。"),
    )

    audit_section = H.section("📋 完整变化清单",
                              render_audit_log(targets_results))

    body = head + kpis + dist_section + target_section + audit_section

    return H.page(
        title=f"竞品监控 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"watch · {n_targets} targets",
    )


# =============================================================================
# Smoke test entrypoint
# =============================================================================
if __name__ == "__main__":
    import argparse
    import json as _json

    p = argparse.ArgumentParser(description="Smoke render of synthetic data")
    p.add_argument("--out", default="/tmp/lumicc-watch-smoke.html")
    args = p.parse_args()

    now = int(time.time())
    synthetic = [
        {
            "url": "https://acme.example.com",
            "host": "acme.example.com",
            "snapshot_ts": now,
            "prior_ts": now - 86400,
            "is_first_run": False,
            "changes": [
                {"category": "new_product", "weight": 3.0, "severity": "high",
                 "detail": {"url": "https://acme.example.com/products/widget-x"}},
                {"category": "promo_banner_change", "weight": 1.8, "severity": "medium",
                 "detail": {"new_lines": ["Mega sale: 30% off!"]}},
                {"category": "social_handle_change", "weight": 0.7, "severity": "low",
                 "detail": {"platform": "instagram", "prev": "old", "curr": "new"}},
            ],
        },
        {
            "url": "https://newshop.example.com",
            "host": "newshop.example.com",
            "snapshot_ts": now,
            "prior_ts": None,
            "is_first_run": True,
            "changes": [],
        },
    ]
    html = render_page(
        run_id="smoke-test-1234",
        store_name="demo-store",
        targets_results=synthetic,
        html_path=Path(args.out),
    )
    Path(args.out).write_text(html, encoding="utf-8")
    print(_json.dumps({"saved": args.out, "bytes": len(html)}))
