#!/usr/bin/env python3
"""Lumicc 控制台 — 跨店聚合的「今日焦点」首屏。

`lumicc`（裸命令）的默认入口。一屏看清所有店铺的所有火情，不用记子命令。

设计原则（见 docs/ROADMAP_TO_GA.md §2.5）：
  - 聚合单位是「行动项」不是「店铺」—— 多店运营者先想"今天什么最该管"
  - Portfolio 条（所有店）+ 跨店 focus feed（按紧急度排）
  - 每个行动项可点 → 一键运行对应 skill
  - 新用户友好：没店时引导接入 / 从零开始

Usage:
    python3 home.py                 # coder 模式，渲染 + 打开浏览器
    python3 home.py --no-open       # 渲染，不开浏览器
    python3 home.py --quiet-stdout  # agent 模式，JSON 一行
    python3 home.py --store-id ID   # 只看一家店
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import html_lib as H  # noqa: E402


def _root() -> Path:
    return Path(os.environ.get("LUMICC_DATA_ROOT", str(Path.home() / ".commerce-os")))


def db_path() -> Path:
    return _root() / "store.db"


# =============================================================================
# Data loading
# =============================================================================
def _open_db() -> sqlite3.Connection | None:
    p = db_path()
    if not p.exists():
        return None
    db = sqlite3.connect(p)
    db.row_factory = sqlite3.Row
    return db


def load_state(store_filter: str | None = None) -> dict:
    """Load all stores + their recent events / campaigns / runs."""
    state: dict = {"stores": [], "events_by_store": {}, "campaigns_by_store": {},
                   "runs_by_store": {}, "recent_runs": []}
    db = _open_db()
    if db is None:
        return state
    try:
        q = "SELECT * FROM stores"
        params: tuple = ()
        if store_filter:
            q += " WHERE id = ?"
            params = (store_filter,)
        state["stores"] = [dict(r) for r in db.execute(q + " ORDER BY updated_at DESC", params)]

        now = int(time.time())
        for s in state["stores"]:
            sid = s["id"]
            state["events_by_store"][sid] = [
                dict(r) for r in db.execute(
                    "SELECT * FROM events WHERE store_id = ? AND ts >= ? ORDER BY ts DESC LIMIT 20",
                    (sid, now - 7 * 86400))
            ]
            state["campaigns_by_store"][sid] = [
                dict(r) for r in db.execute(
                    "SELECT * FROM campaigns WHERE store_id = ? ORDER BY started_at DESC", (sid,))
            ]
            state["runs_by_store"][sid] = [
                dict(r) for r in db.execute(
                    "SELECT * FROM runs WHERE store_id = ? ORDER BY started_at DESC LIMIT 10", (sid,))
            ]
        state["recent_runs"] = [
            dict(r) for r in db.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT 12")
        ]
    except sqlite3.OperationalError:
        pass
    finally:
        db.close()
    return state


# =============================================================================
# Action-item generation + urgency scoring
# =============================================================================
STAGE_LABEL = {
    "0-to-1": "0→1 新店", "1-to-10": "1→10 成长",
    "10-to-100": "10→100 规模", "100+": "100+ 成熟",
}

# urgency score → (band name, health dot color, urgency label)
_URGENCY_BANDS = [
    (90, "crisis", "rose", "立即"),
    (60, "high", "amber", "本周"),
    (30, "medium", "sky", "可安排"),
    (0, "low", "emerald", "可选"),
]
_CRISIS_WORDS = ("警告", "暴跌", "被封", "拒绝", "下架", "suppress", "warning",
                 "crash", "dropped", "disapprov", "violation")


def _report_href(run: dict) -> str | None:
    """Relative href (from home.html) to a run's report.html if it exists, else None."""
    rp = run.get("result_path")
    if not rp:
        return None
    report = Path(rp).expanduser().parent / "report.html"
    if report.exists():
        return f"runs/{run.get('run_id', '')}/report.html"
    return None


def _band(score: int) -> tuple[str, str, str]:
    for threshold, name, color, label in _URGENCY_BANDS:
        if score >= threshold:
            return name, color, label
    return "low", "emerald", "可选"


def _cold_start_day(campaigns: list[dict]) -> tuple[int, int] | None:
    """Return (day, total) for a running cold-start campaign, or None."""
    for c in campaigns:
        if c.get("type") == "cold-start" and c.get("status") == "running":
            started = c.get("started_at") or int(time.time())
            day = max(1, (int(time.time()) - started) // 86400 + 1)
            total = 30
            try:
                plan = json.loads(c.get("results_json") or "{}")
                total = len(plan.get("schedule", [])) or 30
            except (json.JSONDecodeError, TypeError):
                pass
            return min(day, total), total
    return None


def action_items_for_store(store: dict, events: list[dict],
                           campaigns: list[dict], runs: list[dict]) -> list[dict]:
    """Generate urgency-scored action items for one store.

    Each item: {store_id, store_name, team, emoji, title, detail, skill,
                command, urgency, urgency_label}
    """
    items: list[dict] = []
    sid = store["id"]
    sname = store.get("name") or "（未命名店铺）"
    now = int(time.time())

    def add(team, emoji, title, detail, skill, urgency, report_href=None):
        items.append({
            "store_id": sid, "store_name": sname, "team": team, "emoji": emoji,
            "title": title, "detail": detail, "skill": skill,
            "command": f"lumicc {skill.replace('lumicc-', '')}" if skill else "",
            "urgency": urgency, "urgency_label": _band(urgency)[2],
            "report_href": report_href,
        })

    # 1. Crisis events in last 48h → highest urgency
    for e in events:
        if (e.get("ts") or 0) < now - 48 * 3600:
            continue
        content = e.get("content") or ""
        cat = (e.get("category") or "").lower()
        if cat == "warning" or any(w in content.lower() for w in _CRISIS_WORDS):
            add("🚨 危机响应官", "🚨",
                f"{sname} · 检测到危机信号",
                content[:90], "lumicc-rescue", 100)
            break  # one crisis item per store is enough for the feed

    # 2. Cold-start in progress → daily task reminder
    cs = _cold_start_day(campaigns)
    if cs:
        day, total = cs
        add("🏪 建站团队", "🏪",
            f"{sname} · 冷启动 Day {day}/{total}",
            "今天有待办任务，点开看 30 天计划的当日清单", "lumicc-launch", 55)

    # 3. New store with no products → onboarding nudge
    # (products count requires a query; cheap approximation: no runs + no campaigns)
    if not runs and not campaigns:
        add("🏪 建站团队", "🏪",
            f"{sname} · 还没开始",
            "这家店还没有任何动作。从选品开始，或先接入已有数据",
            "lumicc-launch", 65)

    # 4. Stale store → no run in 7+ days
    elif runs:
        last_run_ts = max((r.get("started_at") or 0) for r in runs)
        days_idle = (now - last_run_ts) // 86400
        if days_idle >= 7:
            add("🎯 CMO 总指挥", "🎯",
                f"{sname} · 已 {days_idle} 天没动作",
                "好久没跑过任何分析了，建议看一下全局仪表盘",
                "lumicc-dashboard", 35)

    # 5. Last run's next-step recommendation (mirror route.review_mode logic)
    if runs:
        last = runs[0]
        skill = last.get("skill") or ""
        nxt = _next_after(skill, last)
        if nxt:
            n_skill, n_team, n_emoji, n_reason, n_urg = nxt
            add(n_team, n_emoji,
                f"{sname} · {skill} 跑完了",
                n_reason, n_skill, n_urg,
                report_href=_report_href(last))

    # 6. No items at all → store is healthy / idle, low-priority "all clear"
    if not items:
        add("🎯 CMO 总指挥", "✅",
            f"{sname} · 一切正常",
            "没有需要立即处理的事。可以做例行竞品巡检或客户分析",
            "lumicc-watch", 15)

    return items


# Lightweight mirror of route._pick_next (avoids importing route.py)
def _next_after(skill: str, last_run: dict) -> tuple | None:
    """Return (next_skill, team, emoji, reason, urgency) or None."""
    result = {}
    rp = last_run.get("result_path")
    if rp:
        try:
            p = Path(rp).expanduser()
            if p.exists():
                result = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}

    if skill == "lumicc-retention":
        if metrics.get("at_risk_count", 0) > 5:
            return ("lumicc-content", "🎨 品牌内容师", "🎨",
                    f"At Risk 客户 {metrics['at_risk_count']} 人，立刻发 winback 邮件", 80)
        if metrics.get("champions_count", 0) >= 10:
            return ("lumicc-launch", "🏪 建站团队", "🏪",
                    f"Champion {metrics['champions_count']} 人，建议上 VIP 计划", 50)
    if skill == "lumicc-watch" and metrics.get("high_severity_count", 0) >= 1:
        return ("lumicc-rescue", "🚨 危机响应官", "🚨",
                "巡店发现 high severity 信号，确认是否价格战", 85)
    if skill == "lumicc-listing" and metrics.get("sick_pct", 0) >= 30:
        return ("lumicc-content", "🎨 品牌内容师", "🎨",
                f"sick listing {metrics['sick_pct']}%，重做主图 + PDP", 75)
    if skill == "lumicc-voc":
        clusters = metrics.get("clusters", {})
        pl = clusters.get("packaging", 0) + clusters.get("logistics", 0)
        if pl >= 3:
            return ("lumicc-listing", "🏪 建站团队", "🏪",
                    f"包装/物流问题 {pl} 条，要改商详", 70)
    _DEFAULTS = {
        "lumicc-launch": ("lumicc-content", "🎨 品牌内容师", "🎨", "新店首批主图 + 文案 prompt", 50),
        "lumicc-content": ("lumicc-listing", "🏪 建站团队", "🏪", "内容做好了，上架到商详", 45),
        "lumicc-rescue": ("lumicc-watch", "🔭 市场情报员", "🔭", "危机后 24h 复查行业大盘", 40),
        "lumicc-expand": ("lumicc-launch", "🏪 建站团队", "🏪", "新 SKU 上架", 45),
        "lumicc-seo": ("lumicc-content", "🎨 品牌内容师", "🎨", "SEO 发现内容空白，写 blog + FAQ", 40),
    }
    return _DEFAULTS.get(skill)


# =============================================================================
# HTML rendering
# =============================================================================
TEAMS = [
    ("🏪 建站团队", "开店 · 商详 · 合规", "lumicc-launch / lumicc-listing"),
    ("📊 数据分析师", "RFM · 复购 · 评论 · 选品", "lumicc-retention / voc / expand"),
    ("🔭 市场情报员", "竞品 · SEO · AI 引用", "lumicc-watch / lumicc-seo"),
    ("🎨 品牌内容师", "图片 · 视频 · 文案 · 风格", "lumicc-content"),
    ("🚨 危机响应官", "销量崩 · 账号警告 · 价格战", "lumicc-rescue"),
    ("🎯 CMO 总指挥", "全局复盘 · 派单 · 决策", "lumicc / lumicc-dashboard"),
]


def _portfolio_strip(stores: list[dict], items_by_store: dict,
                     active: str | None) -> str:
    """Horizontal store pills, each with a health dot."""
    if not stores:
        return ""
    pills = []
    # "全部" pill
    all_cls = "store-pill" + ("" if active else " active")
    pills.append(
        f'<a href="?store=all" class="{all_cls}" '
        f'style="--dot:var(--accent);">全部 · {len(stores)} 家店</a>'
    )
    for s in stores:
        sid = s["id"]
        store_items = items_by_store.get(sid, [])
        top_urg = max((it["urgency"] for it in store_items), default=0)
        _, dot_color, _ = _band(top_urg)
        stage = STAGE_LABEL.get(s.get("stage"), s.get("stage") or "—")
        cls = "store-pill" + (" active" if active == sid else "")
        pills.append(
            f'<span class="{cls}" style="--dot:var(--{dot_color});">'
            f'<span class="store-dot"></span>'
            f'{H.esc(s.get("name") or "店铺")} · {H.esc(stage)}</span>'
        )
    return (
        '<div class="portfolio-strip">'
        '<div class="portfolio-label">你的店铺</div>'
        '<div class="portfolio-pills">' + "".join(pills) + "</div>"
        "</div>"
    )


def _focus_feed(items: list[dict]) -> str:
    """Cross-store action items, sorted by urgency desc."""
    if not items:
        return H.empty_state("当前没有需要关注的事项。",
                             "接入一家店或运行任意 skill 后，这里会出现 CMO 的建议")
    items = sorted(items, key=lambda x: -x["urgency"])
    rows = []
    for it in items:
        _, color, label = _band(it["urgency"])
        cmd = H.esc(it["command"]) if it["command"] else ""
        cmd_html = (
            f'<code class="focus-cmd">{cmd}</code>' if cmd else ""
        )
        report_href = it.get("report_href")
        report_html = (
            f'<a class="focus-report" href="{H.esc(report_href)}">查看上次报告 →</a>'
            if report_href else ""
        )
        rows.append(
            f'<div class="focus-item" style="--accent-band:var(--{color});">'
            f'<div class="focus-emoji">{it["emoji"]}</div>'
            f'<div class="focus-body">'
            f'<div class="focus-title">{H.esc(it["title"])}</div>'
            f'<div class="focus-detail">{H.esc(it["detail"])}</div>'
            f'<div class="focus-meta">'
            f'<span class="focus-team">{H.esc(it["team"])}</span>'
            f'<span class="focus-urgency focus-urgency-{color}">{label}</span>'
            f'{cmd_html}'
            f'{report_html}'
            f'</div></div></div>'
        )
    return '<div class="focus-feed">' + "".join(rows) + "</div>"


def _team_cards() -> str:
    cards = []
    for name, what, skills in TEAMS:
        cards.append(
            f'<div class="team-card">'
            f'<div class="team-name">{H.esc(name)}</div>'
            f'<div class="team-what">{H.esc(what)}</div>'
            f'<div class="team-skills mono">{H.esc(skills)}</div>'
            f'</div>'
        )
    return H.card_grid(cards, min_width=240)


def _recent_outputs(runs: list[dict]) -> str:
    if not runs:
        return H.empty_state("还没有跑过任何 skill。")
    chips = []
    for r in runs[:10]:
        skill = (r.get("skill") or "?").replace("lumicc-", "")
        status = r.get("status") or "?"
        color = {"success": "emerald", "partial": "amber",
                 "failed": "rose"}.get(status, "zinc")
        inner = (
            f'{H.badge(skill, color)}'
            f'<span class="output-when mono">{H.fmt_rel(r.get("started_at"))}</span>'
        )
        href = _report_href(r)
        if href:
            chips.append(
                f'<a class="output-chip output-chip-link" href="{H.esc(href)}">{inner}</a>'
            )
        else:
            chips.append(f'<span class="output-chip">{inner}</span>')
    return '<div class="output-chips">' + "".join(chips) + "</div>"


# Control-center-specific CSS (appended after html_lib's static CSS via a <style> in body)
_HOME_CSS = """
<style>
.portfolio-strip { margin: 8px 0 28px; }
.portfolio-label { font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--ink-dim); margin-bottom: 10px; }
.portfolio-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.store-pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 14px;
  border: 1px solid var(--line); border-radius: 999px; font-size: 13px;
  color: var(--ink-muted); background: var(--surface); text-decoration: none;
  transition: border-color .15s, color .15s, background .15s; }
.store-pill:hover { color: var(--ink); border-color: var(--line-strong); }
.store-pill.active { color: var(--ink-strong); border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, var(--surface)); }
.store-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dot);
  box-shadow: 0 0 8px var(--dot); flex-shrink: 0; }
.focus-feed { display: flex; flex-direction: column; gap: 12px; }
.focus-item { display: flex; gap: 16px; padding: 18px 20px; background: var(--surface);
  border: 1px solid var(--line); border-left: 3px solid var(--accent-band);
  border-radius: var(--radius); transition: transform .15s, box-shadow .15s; }
.focus-item:hover { transform: translateX(2px); box-shadow: var(--card-hover-shadow); }
.focus-emoji { font-size: 22px; line-height: 1.2; flex-shrink: 0; }
.focus-body { flex: 1; min-width: 0; }
.focus-title { font-weight: 600; color: var(--ink-strong); font-size: 15px; }
.focus-detail { color: var(--ink-muted); font-size: 13px; margin-top: 4px; line-height: 1.5; }
.focus-meta { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.focus-team { font-size: 12px; color: var(--ink-dim); }
.focus-urgency { font-size: 11px; font-family: var(--mono); padding: 2px 8px;
  border-radius: 999px; letter-spacing: 0.05em; }
.focus-urgency-rose { background: color-mix(in srgb, var(--rose) 16%, transparent); color: var(--rose); }
.focus-urgency-amber { background: color-mix(in srgb, var(--amber) 16%, transparent); color: var(--amber); }
.focus-urgency-sky { background: color-mix(in srgb, var(--sky) 16%, transparent); color: var(--sky); }
.focus-urgency-emerald { background: color-mix(in srgb, var(--accent) 14%, transparent); color: var(--accent); }
.focus-cmd { font-size: 11px; padding: 2px 8px; background: var(--surface-2);
  border-radius: 4px; color: var(--ink-muted); }
.focus-report { font-size: 11px; color: var(--accent); text-decoration: none; }
.focus-report:hover { text-decoration: underline; }
.output-chip-link { text-decoration: none; padding: 2px 6px; border-radius: 6px;
  transition: background .15s; }
.output-chip-link:hover { background: var(--surface-2); }
.team-card { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 16px 18px; transition: border-color .15s, transform .15s; }
.team-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.team-name { font-weight: 600; color: var(--ink-strong); font-size: 14px; }
.team-what { color: var(--ink-muted); font-size: 12.5px; margin-top: 5px; line-height: 1.5; }
.team-skills { color: var(--ink-dim); font-size: 11px; margin-top: 8px; }
.output-chips { display: flex; gap: 10px; flex-wrap: wrap; }
.output-chip { display: inline-flex; align-items: center; gap: 6px; }
.output-when { color: var(--ink-dim); font-size: 11px; }
.home-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.home-actions a { padding: 9px 18px; border: 1px solid var(--line); border-radius: var(--radius);
  color: var(--ink-muted); text-decoration: none; font-size: 13px;
  transition: border-color .15s, color .15s; }
.home-actions a:hover { border-color: var(--accent); color: var(--ink-strong); }
.home-actions a.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
</style>
"""


def render_home(state: dict, active: str | None = None) -> str:
    stores = state["stores"]

    # Build action items per store
    items_by_store: dict[str, list[dict]] = {}
    all_items: list[dict] = []
    for s in stores:
        sid = s["id"]
        its = action_items_for_store(
            s, state["events_by_store"].get(sid, []),
            state["campaigns_by_store"].get(sid, []),
            state["runs_by_store"].get(sid, []))
        items_by_store[sid] = its
        all_items.extend(its)

    # Filter to active store if set
    feed_items = (
        [it for it in all_items if it["store_id"] == active] if active
        else all_items
    )

    # --- empty state: no stores ---
    if not stores:
        body = H.page_head("欢迎使用 Lumicc 控制台", "你的跨境运营 OS · 还没有店铺")
        body += H.empty_state(
            "还没有接入任何店铺",
            "两个选择：接入一家已有的店，或从零开始开新店")
        body += (
            '<div class="home-actions">'
            '<a class="primary" href="#">接入我的店 · lumicc init</a>'
            '<a href="#">从零开始 · lumicc launch</a>'
            '<a href="#">快速开始指南</a>'
            '</div>'
        )
        return _HOME_CSS + H.page(title="Lumicc 控制台", body=body,
                                  back_link=None, brand_subtitle="跨境运营 OS")

    # --- normal state ---
    crisis_n = sum(1 for it in feed_items if it["urgency"] >= 90)
    high_n = sum(1 for it in feed_items if 60 <= it["urgency"] < 90)

    head = H.page_head(
        "Lumicc 控制台",
        f"{len(stores)} 家店 · {len(feed_items)} 个待办 · "
        f"{crisis_n} 立即 · {high_n} 本周",
    )

    portfolio = _portfolio_strip(stores, items_by_store, active)

    focus = H.section(
        "🎯 CMO · 今天需要你关注的"
        + (f"（{stores_name(stores, active)}）" if active else "（跨所有店 · 按紧急度排）"),
        _focus_feed(feed_items),
    )

    teams = H.section("6 个专家团队 · 点开看能做什么", _team_cards())

    outputs = H.section(
        "最近产出（跨店）",
        _recent_outputs(state["recent_runs"]),
        action_link=("../../dashboard/index.html", "完整仪表盘 →"),
    )

    actions = (
        '<div class="home-actions">'
        '<a class="primary" href="#">快速开始指南</a>'
        '<a href="../../dashboard/index.html">完整仪表盘</a>'
        '<a href="#">接入新店</a>'
        '</div>'
    )

    body = head + portfolio + focus + teams + outputs + actions
    return _HOME_CSS + H.page(title="Lumicc 控制台", body=body,
                              back_link=None, brand_subtitle="跨境运营 OS")


def stores_name(stores: list[dict], sid: str | None) -> str:
    for s in stores:
        if s["id"] == sid:
            return s.get("name") or "店铺"
    return "未知店铺"


# =============================================================================
# Main
# =============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--quiet-stdout", action="store_true")
    ap.add_argument("--store-id", default=None)
    ap.add_argument("--output", default=None, help="HTML 输出路径（默认 ~/.commerce-os/home.html）")
    args = ap.parse_args()

    state = load_state(args.store_id)
    html = render_home(state, active=args.store_id)

    out_path = Path(args.output).expanduser() if args.output else (_root() / "home.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    n_stores = len(state["stores"])
    n_items = sum(len(action_items_for_store(
        s, state["events_by_store"].get(s["id"], []),
        state["campaigns_by_store"].get(s["id"], []),
        state["runs_by_store"].get(s["id"], []))) for s in state["stores"])

    result = {
        "skill": "lumicc-home",
        "status": "success",
        "stores": n_stores,
        "action_items": n_items,
        "home_html": str(out_path),
    }

    if args.quiet_stdout:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"✓ 控制台已渲染 · {n_stores} 家店 · {n_items} 个待办")
        print(f"  {out_path}")
        if not args.no_open:
            try:
                webbrowser.open(f"file://{out_path}")
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
