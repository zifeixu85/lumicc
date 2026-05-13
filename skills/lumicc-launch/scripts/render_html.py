#!/usr/bin/env python3
"""Render lumicc-launch plan.html — 30-day Gantt-style timeline.

Visual differentiators (per thariq HTML-effectiveness):
  - 4-week × 7-day grid (not a markdown calendar)
  - Today's cell HIGHLIGHTED (live position marker)
  - Past days dimmed; future days normal
  - Per-day click → show task details
  - Feasibility KPIs prominent at top
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))
import html_lib as H


def render_gantt(plan: dict, started_at: int | None = None) -> str:
    """30-day Gantt grid: 4 weeks × 7 cols (Days 1-7, 8-14, 15-21, 22-28+).

    Marks today if started_at is set.
    """
    schedule = plan.get("schedule", [])
    if not schedule:
        return H.empty_state("还没有 schedule。")

    # Compute today's day_offset
    today_day = None
    if started_at:
        today_day = max(1, (int(time.time()) - int(started_at)) // 86400 + 1)

    # Group into weeks
    weeks: dict[int, list[dict]] = {}
    for d in schedule:
        wk = (d["day"] - 1) // 7 + 1
        weeks.setdefault(wk, []).append(d)

    rows_html = ""
    # Header row
    rows_html += '<div class="gantt-row-label" style="color:var(--ink-muted);font-family:var(--mono);font-size:11px;">阶段</div>'
    for i in range(1, 8):
        rows_html += f'<div class="gantt-header">第 {i} 天</div>'

    for wk in sorted(weeks.keys()):
        days = sorted(weeks[wk], key=lambda d: d["day"])
        # Week phase from first day
        phase = days[0].get("phase", f"Week {wk}")
        # Trim phase label
        phase_short = phase.split("—")[-1].strip() if "—" in phase else phase
        rows_html += f'<div class="gantt-row-label">{H.esc(phase_short)}</div>'

        # 7 day cells per week
        days_by_pos: dict[int, dict] = {d["day"]: d for d in days}
        week_start = (wk - 1) * 7 + 1
        for i in range(7):
            day_num = week_start + i
            day = days_by_pos.get(day_num)
            if not day:
                rows_html += '<div class="gantt-day" style="opacity:0.4;"><div class="day-num">·</div></div>'
                continue

            classes = ["gantt-day"]
            if today_day:
                if day_num < today_day:
                    classes.append("past")
                elif day_num == today_day:
                    classes.append("today")
                else:
                    classes.append("future")

            tasks_html = "".join(
                f'<div class="task">• {H.esc(t)}</div>' for t in day.get("tasks", [])
            )
            slots_html = ""
            if day.get("capability_slots"):
                slots_html = (
                    f'<div style="margin-top:6px;font-size:9px;color:var(--ink-dim);'
                    f'font-family:var(--mono);">'
                    f'{H.esc(", ".join(day["capability_slots"]))}</div>'
                )
            today_label = (
                ' · <span style="color:var(--accent-soft);font-weight:600;">今日</span>'
                if today_day and day_num == today_day else ""
            )
            rows_html += (
                f'<div class="{" ".join(classes)}" title="Day {day_num}">'
                f'<div class="day-num">Day {day_num}{today_label}</div>'
                f'{tasks_html}{slots_html}</div>'
            )

    return f'<div class="gantt-grid">{rows_html}</div>'


def render_feasibility_kpis(plan: dict) -> str:
    fz = plan.get("feasibility", {})
    inputs = plan.get("inputs", {})
    tier = fz.get("tier", "—")
    tier_color = (
        "rose" if tier == "Lean" else "amber" if tier == "Standard" else "emerald"
    )

    return H.kpi_strip([
        (tier, "Tier", "投入档位", tier_color),
        (fz.get("first_sale_in_30d_probability", "?"), "首单概率", "30 天内"),
        (H.fmt_currency(inputs.get("budget_usd")), "预算"),
        (f'{inputs.get("hours_per_week", "?")} h/wk', "时间投入"),
    ])


def render_milestones(plan: dict) -> str:
    ms = plan.get("milestones") or {}
    if not ms:
        return ""
    cards = []
    for k, v in ms.items():
        cards.append(H.card(title=k, tag="里程碑", tag_color="indigo", body=H.esc(v)))
    return H.section("4 周里程碑", H.card_grid(cards, min_width=240))


def render_feasibility_warnings(plan: dict) -> str:
    fz = plan.get("feasibility", {})
    issues = fz.get("issues") or []
    actions = fz.get("recommended_actions") or []
    if not issues and not actions:
        return ""

    body = ""
    if issues:
        body += "<b style='color:#fda4af'>⚠️ 风险</b><ul style='margin:6px 0 12px 24px;'>" + \
                "".join(f"<li>{H.esc(i)}</li>" for i in issues) + "</ul>"
    if actions:
        body += "<b style='color:#6ee7b7'>✅ 建议调整</b><ul style='margin:6px 0 12px 24px;'>" + \
                "".join(f"<li>{H.esc(a)}</li>" for a in actions) + "</ul>"
    return H.section("可行性评估", f'<div class="card" style="padding:18px 20px;">{body}</div>')


def render_page(*, run_id: str, store_name: str, plan: dict,
                started_at: int | None = None,
                today_day_offset: int | None = None,
                html_path: Path) -> str:
    """Build plan.html with full Gantt + KPIs + milestones."""
    head = H.page_head(
        f"30 天上店计划 · {store_name or 'Lumicc'}",
        f"campaign <code>{H.esc((plan.get('campaign_id','—'))[:8])}</code> · "
        f"Run <code>{H.esc(run_id[:8])}</code>",
    )

    body = (
        head
        + render_feasibility_kpis(plan)
        + render_feasibility_warnings(plan)
        + render_milestones(plan)
        + H.section(
            "30 天日程（实时位置）" if started_at else "30 天日程",
            (
                "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
                "今天高亮显示。已过去的日子半透明。每格内是当日任务清单。</p>"
                if started_at else
                "<p class='muted' style='font-size:13px;margin:6px 0 12px;'>"
                "活动尚未启动 — 跑 <code>plan.py</code> 时会自动 starts。</p>"
            )
            + render_gantt(plan, started_at=started_at),
        )
    )

    return H.page(
        title=f"30 天计划 · {store_name or 'Lumicc'}",
        body=body,
        right_meta=f"day {today_day_offset}/30" if today_day_offset else "",
    )
