#!/usr/bin/env python3
"""Route user intent → sub-skill, based on store stage + keyword match.

Reads decision rules from references/routing-table.md (canonical source).
Prints a JSON object with the routing decision.

Usage:
    python3 route.py --intent "I just dropped 50% in sales" [--store-id ID]
    echo "想找下一个爆款" | python3 route.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path.home() / ".commerce-os"

# Keyword table is duplicated from references/routing-table.md for fast standalone use.
# Update both when changing rules.
ROUTING: list[tuple[str, list[str], float]] = [
    ("lumicc-rescue",
     ["sales dropped", "traffic crash", "account suspended", "asin suppressed",
      "listing removed", "emergency", "what went wrong",
      "销量降", "流量掉", "暴跌", "账号警告", "被封", "listing 被下", "紧急"],
     1.0),
    ("lumicc-launch",
     ["start a store", "new store", "from scratch", "launch store",
      "first time", "0 to 1", "haven't started",
      "新店", "从零", "刚开始", "刚做", "0到1", "出海起步", "上店", "开店"],
     1.0),
    ("lumicc-watch",
     ["competitor", "rival", "spy", "monitor competition", "watch competitors",
      "what are others doing",
      "竞品", "对手", "巡店", "对标"],
     0.95),
    ("lumicc-expand",
     ["next product", "expand catalog", "more skus", "scale products",
      "find another winner", "diversify",
      "扩品", "下一个", "新品", "多品", "横向扩展", "找下一个爆款"],
     0.95),
    ("lumicc-voc",
     ["review analysis", "voc", "voice of customer", "negative reviews",
      "returns analysis", "complaints", "customer feedback",
      "评论", "差评", "退货", "客诉", "用户反馈", "口碑"],
     0.95),
    ("lumicc-listing",
     ["listing", "product page", "conversion", "pdp", "asin audit",
      "page optimization", "low cr", "low ctr",
      "listing 优化", "产品页", "详情页", "转化率", "页面问题"],
     0.90),
]


def db_path() -> Path:
    return ROOT / "store.db"


def get_store(store_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        if store_id:
            row = db.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM stores ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def keyword_match(intent: str) -> list[tuple[str, float, list[str]]]:
    intent_l = intent.lower()
    hits: list[tuple[str, float, list[str]]] = []
    for skill, kws, weight in ROUTING:
        matched = [k for k in kws if k.lower() in intent_l]
        if matched:
            hits.append((skill, weight + 0.05 * len(matched), matched))
    hits.sort(key=lambda x: -x[1])
    return hits


def decide(intent: str, store_id: str | None) -> dict:
    store = get_store(store_id)
    hits = keyword_match(intent)

    # Cold-start gate: no store → always cold-start
    if store is None:
        return {
            "matched_subskill": "lumicc-launch",
            "confidence": 0.95,
            "alternative_subskills": [],
            "reason": "No store record found in ~/.commerce-os — entering 0→1 cold-start flow",
            "missing_inputs": ["store_url", "platform", "target_market", "niche"],
            "next_action": "ask_user_for_inputs",
            "store_snapshot": None,
        }

    stage = store.get("stage")
    primary = hits[0] if hits else None
    secondary = hits[1] if len(hits) >= 2 else None

    # No clear keyword
    if primary is None:
        if stage == "0-to-1":
            fallback = "lumicc-listing"
            reason = "0→1 stage, no explicit intent — default to listing health check"
        else:
            fallback = "lumicc-listing"
            reason = "No intent keyword detected — defaulting to highest-leverage default"
        return {
            "matched_subskill": fallback,
            "confidence": 0.5,
            "alternative_subskills": [],
            "reason": reason,
            "missing_inputs": [],
            "next_action": "execute_subskill",
            "store_snapshot": store,
        }

    # Have keyword match
    confidence = min(0.99, primary[1])
    alt = [secondary[0]] if secondary and abs(secondary[1] - primary[1]) < 0.1 else []
    needs_disambig = bool(alt) and confidence < 0.9

    return {
        "matched_subskill": primary[0],
        "confidence": round(confidence, 2),
        "alternative_subskills": alt,
        "reason": f"Keyword match: {primary[2][:3]}",
        "missing_inputs": [],
        "next_action": "ask_user_disambiguate" if needs_disambig else "execute_subskill",
        "store_snapshot": store,
    }


# --- CMO review_mode (post-subskill recap + handoff) ---

# Hardcoded next-step mapping. Agent reads this to know who picks up.
_REVIEW_RULES: list[tuple[str, str, str, str, str]] = [
    # (skill, next_skill, team, reason, urgency)
    ("lumicc-launch", "lumicc-content", "🎨 品牌内容师",
     "新店首批 prompt（主图 + 文案 + 视频脚本）", "now"),
    ("lumicc-listing", "lumicc-content", "🎨 品牌内容师",
     "sick listing 占比高，需要重做主图 + PDP", "now"),
    ("lumicc-rescue", "lumicc-watch", "🔭 市场情报员",
     "危机后 24h 复查，看是不是行业大盘问题", "this_week"),
    ("lumicc-watch", "lumicc-rescue", "🚨 危机响应官",
     "high severity 警报，确认是否进入价格战", "now"),
    ("lumicc-voc", "lumicc-listing", "🏪 建站团队",
     "包装/物流/描述问题，需要改商详", "now"),
    ("lumicc-expand", "lumicc-launch", "🏪 建站团队",
     "新 SKU 上架", "this_week"),
    ("lumicc-seo", "lumicc-content", "🎨 品牌内容师",
     "SEO 体检发现内容空白，需要写 blog + FAQ", "this_week"),
]


def _load_run(run_id: str | None) -> dict | None:
    if not db_path().exists():
        return None
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        if run_id:
            row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        else:
            row = db.execute("SELECT * FROM runs ORDER BY finished_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def _load_result(result_path: str | None) -> dict:
    if not result_path:
        return {}
    p = Path(result_path).expanduser()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _recent_events(hours: int = 48) -> list[dict]:
    if not db_path().exists():
        return []
    db = sqlite3.connect(db_path())
    db.row_factory = sqlite3.Row
    try:
        cutoff = int(time.time()) - hours * 3600
        rows = db.execute(
            "SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT 20",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()


def _pick_next(skill: str, result: dict) -> tuple[str, str, str, str]:
    """Apply hardcoded mapping with result-aware refinements. Returns (next_skill, team, reason, urgency)."""
    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}

    if skill == "lumicc-retention":
        at_risk = metrics.get("at_risk_count", 0)
        champions = metrics.get("champions_count", 0)
        if at_risk > 5:
            return ("lumicc-content", "🎨 品牌内容师",
                    f"At Risk 客户 {at_risk} 人 > 5，立刻发 winback 邮件", "now")
        if champions >= 10:
            return ("lumicc-launch", "🏪 建站团队",
                    f"Champion {champions} 人 ≥ 10，建议上 VIP 计划", "this_week")
        return ("lumicc-dashboard", "🎯 CMO 总指挥",
                "RFM 完成，无强信号，看全局 dashboard", "optional")

    if skill == "lumicc-voc":
        clusters = metrics.get("clusters", {})
        pack_logistics = clusters.get("packaging", 0) + clusters.get("logistics", 0)
        if pack_logistics >= 3:
            return ("lumicc-listing", "🏪 建站团队",
                    f"包装/物流问题 {pack_logistics} 条 ≥ 3，要改商详 + 联系供应商", "now")

    if skill == "lumicc-watch":
        if metrics.get("high_severity_count", 0) >= 1:
            return ("lumicc-rescue", "🚨 危机响应官",
                    "巡店发现 high severity 信号，确认是否价格战", "now")

    if skill == "lumicc-listing":
        sick_pct = metrics.get("sick_pct", 0)
        if sick_pct >= 30:
            return ("lumicc-content", "🎨 品牌内容师",
                    f"sick listing 占比 {sick_pct}% ≥ 30%，重做主图 + PDP", "now")

    # Default: hardcoded table lookup
    for s, nxt, team, reason, urg in _REVIEW_RULES:
        if s == skill:
            return (nxt, team, reason, urg)

    return ("lumicc-dashboard", "🎯 CMO 总指挥", "未匹配规则，回看全局", "optional")


def review_mode(last_run_result_path: str | None = None, run_id: str | None = None) -> dict:
    """CMO 复盘模式：sub-skill 跑完后，回到顶层做总结 + 派单下一步。

    Reads the latest run from store.db (or specified run_id), pulls its result.json,
    surfaces highlights/concerns, and recommends the next skill + team handoff.
    """
    run = _load_run(run_id)
    if run is None and last_run_result_path is None:
        return {
            "team": "🎯 CMO 总指挥",
            "summary": "没有找到任何 run 记录。先跑一个 sub-skill 再回来复盘。",
            "highlights": [],
            "concerns": ["~/.commerce-os/store.db 里 runs 表为空"],
            "next_recommended": {
                "skill": "lumicc-launch",
                "team": "🏪 建站团队",
                "reason": "新店从零起步",
                "urgency": "now",
            },
            "cmo_voice_handoff": "你这里还没跑过任何东西。先从建站团队的 30 天 SOP 开始——他们带你从开店到首单。",
        }

    result_path = last_run_result_path or (run.get("result_path") if run else None)
    result = _load_result(result_path)
    skill = (run.get("skill") if run else result.get("skill")) or "unknown"
    status = (run.get("status") if run else result.get("status")) or "unknown"

    deliverables = result.get("deliverables", []) if isinstance(result, dict) else []
    metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
    warnings = result.get("warnings", []) if isinstance(result, dict) else []

    highlights = [f"产出 {len(deliverables)} 个交付物"] if deliverables else []
    for k, v in list(metrics.items())[:4]:
        highlights.append(f"{k}: {v}")

    concerns = list(warnings)[:5]
    recent = _recent_events(48)
    high_sev = [e for e in recent if e.get("severity") == "high"]
    if high_sev:
        concerns.append(f"过去 48h 有 {len(high_sev)} 个 high severity 事件")

    next_skill, next_team, reason, urgency = _pick_next(skill, result)

    summary = f"{skill} 刚跑完，状态 {status}。"
    if deliverables:
        summary += f" 交付 {len(deliverables)} 个产物。"
    if concerns:
        summary += f" 有 {len(concerns)} 个关注点需要看。"

    handoff = (
        f"{skill} 的活{('告一段落' if status == 'success' else '跑完了')}。"
        f"下一步交给 **{next_team}**——{reason}。"
        f"紧急度 {urgency}。"
    )

    return {
        "team": "🎯 CMO 总指挥",
        "summary": summary,
        "highlights": highlights,
        "concerns": concerns,
        "next_recommended": {
            "skill": next_skill,
            "team": next_team,
            "reason": reason,
            "urgency": urgency,
        },
        "cmo_voice_handoff": handoff,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", default=None, help="User intent text; if omitted, read from stdin")
    parser.add_argument("--store-id", default=None)
    parser.add_argument("--review", action="store_true", help="CMO review mode: recap last run + handoff")
    parser.add_argument("--run-id", default=None, help="Specific run_id to review")
    parser.add_argument("--result-path", default=None, help="Explicit result.json path for review")
    args = parser.parse_args()

    if args.review:
        out = review_mode(last_run_result_path=args.result_path, run_id=args.run_id)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    intent = args.intent or sys.stdin.read().strip()
    if not intent:
        print(json.dumps({"error": "no intent provided"}), file=sys.stderr)
        return 2

    decision = decide(intent, args.store_id)
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
