#!/usr/bin/env python3
"""Render lumicc-rescue report.html — visual companion for the crisis playbook.

Layout:
  - Page head: hypothesis + branch + confidence + run id
  - KPI strip: severity / confidence / resolution_time / # alternatives
  - Section: 🎯 行动方案 (playbook) — numbered step cards (vertical stack)
  - Section: 🔍 备选诊断 — small card grid (if any)
  - Section: 📋 近 48h 事件回顾 — timeline (or empty state)
  - Bottom: 24h watchdog callout card
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


# Branch severity → KPI color + label
SEVERITY = {
    "A": ("rose", "CRITICAL", "🚨"),
    "B": ("rose", "HIGH", "⚠️"),
    "C": ("rose", "HIGH", "⚠️"),
    "D": ("amber", "MEDIUM", "🟡"),
    "E": ("amber", "MEDIUM", "🟡"),
    "F": ("sky", "INFO", "🔵"),
    "G": ("amber", "MEDIUM", "🟡"),
    "H": ("amber", "MEDIUM", "🟡"),
}

CATEGORY_COLOR = {
    "decision": "indigo",
    "warning": "amber",
    "observation": "sky",
    "task": "indigo",
}

CATEGORY_SEVERITY = {
    "decision": "decision",
    "warning": "warn",
    "observation": "info",
    "error": "error",
}


def render_playbook(steps: list[str]) -> str:
    """Vertical card list, big step number on left."""
    if not steps:
        return H.empty_state("无 playbook 步骤。")
    cards: list[str] = []
    for i, step in enumerate(steps, 1):
        body = (
            '<div style="display:flex;align-items:flex-start;gap:18px;">'
            f'<div style="flex:0 0 56px;font-size:32px;font-weight:800;'
            'line-height:1;color:var(--accent);font-family:var(--mono);">'
            f'{i:02d}</div>'
            '<div style="flex:1;font-size:15px;line-height:1.55;color:var(--ink);">'
            f'{H.esc(step)}</div></div>'
        )
        cards.append(f'<div class="card">{body}</div>')
    return '<div style="display:flex;flex-direction:column;gap:10px;">' + "".join(cards) + "</div>"


def render_alternatives(alts: list[dict]) -> str:
    if not alts:
        return ""
    cards = []
    for a in alts:
        body = (
            f'<div style="font-size:14px;color:var(--ink);margin-bottom:6px;">'
            f'{H.esc(a.get("hypothesis", ""))}</div>'
            f'<div style="font-size:12px;color:var(--ink-muted);line-height:1.5;">'
            f'{H.esc(a.get("reason", ""))}</div>'
        )
        cards.append(H.card(
            title=f'分支 {a.get("branch_id", "?")}',
            tag="备选", tag_color="zinc",
            body=body,
        ))
    return H.card_grid(cards, min_width=280)


def render_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return H.empty_state("近 48h 无相关事件。", "events 表里没有 decision/warning 记录")
    entries = []
    for e in evidence[:20]:
        cat = (e.get("category") or "observation").lower()
        sev = CATEGORY_SEVERITY.get(cat, "info")
        entries.append({
            "ts": e.get("ts"),
            "title": cat.upper(),
            "body": e.get("content", ""),
            "severity": sev,
        })
    return H.timeline(entries)


def render_watchdog_callout() -> str:
    body = (
        '<div style="font-size:14px;line-height:1.6;color:var(--ink);">'
        '24 小时后将自动跑一次 <code>lumicc-watch</code> 验证恢复进度。'
        '若关键指标仍未回升，Lumicc 会升级到下一个最可能的分支并重新生成 playbook。'
        '<br><br>'
        '<span style="color:var(--ink-muted);font-size:13px;">'
        '建议：完成 playbook 步骤后手动在 events 表写入一条 <code>decision</code> 记录，'
        '便于 watchdog 对比前后状态。</span>'
        '</div>'
    )
    return H.card(
        title="⚠️ 24h Watchdog",
        tag="自动复查", tag_color="sky",
        body=body,
    )


def render_page(*, run_id: str, store_name: str, diag: dict,
                evidence: list[dict], html_path: Path) -> str:
    branch_id = diag.get("branch_id", "?")
    branch_key = diag.get("branch_key", "—")
    hypothesis = diag.get("hypothesis", "未确定")
    confidence = float(diag.get("confidence", 0.0))
    resolution_time = diag.get("resolution_time", "—")
    alternatives = diag.get("alternatives") or []
    steps = diag.get("playbook_steps") or diag.get("playbook") or []

    sev_color, sev_label, sev_icon = SEVERITY.get(branch_id, ("zinc", "—", "⚠️"))

    head = H.page_head(
        f"🚨 危机响应 · {hypothesis}",
        f"branch {branch_id}:{branch_key} · 置信度 {confidence:.0%} · Run {run_id[:8]}",
    )

    kpis = H.kpi_strip([
        (f"{sev_icon} {sev_label}", "严重级别", f"分支 {branch_id}", sev_color),
        (f"{confidence:.0%}", "置信度",
         "≥80% 可执行" if confidence >= 0.8 else "< 80% 建议人工复核",
         "emerald" if confidence >= 0.8 else "amber"),
        (resolution_time, "预估解决", "典型恢复时间"),
        (len(alternatives), "备选诊断", "若主分支无效则尝试"),
    ])

    body_parts = [
        head,
        kpis,
        H.section("🎯 行动方案 (playbook)", render_playbook(steps)),
    ]

    if alternatives:
        body_parts.append(H.section("🔍 备选诊断", render_alternatives(alternatives)))

    body_parts.append(H.section(
        f"📋 近 48h 事件回顾 ({len(evidence)})",
        render_evidence(evidence),
    ))

    body_parts.append(H.section("", render_watchdog_callout()))

    return H.page(
        title=f"危机响应 · {store_name or 'Lumicc'}",
        body="".join(body_parts),
        right_meta=f"branch {branch_id}",
    )


if __name__ == "__main__":
    # Smoke test
    fake_diag = {
        "branch_id": "A", "branch_key": "account_warning",
        "hypothesis": "Account health drop / suspension imminent",
        "confidence": 0.92, "resolution_time": "2-7 days",
        "playbook_steps": [
            "Open the platform's Account Health page; screenshot every flagged metric.",
            "Identify the specific policy violation. Do NOT submit a generic appeal.",
            "Pause any related listings or ads while you investigate.",
        ],
        "alternatives": [
            {"branch_id": "B", "hypothesis": "Ad creative or policy rejection",
             "reason": "ad change may have hit disapproval pending"},
        ],
    }
    fake_evidence = [
        {"ts": 1715000000, "category": "decision",
         "content": "Lowered price on hero SKU by 12%", "store_id": "s1"},
        {"ts": 1715050000, "category": "warning",
         "content": "Amazon Account Health dropped to 180", "store_id": "s1"},
    ]
    out = Path("/tmp/rescue_smoke.html")
    html = render_page(run_id="test1234", store_name="DemoStore",
                       diag=fake_diag, evidence=fake_evidence, html_path=out)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} bytes)")
