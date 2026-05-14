#!/usr/bin/env python3
"""Lumicc 配置中心 + 首次安装引导。

解决两个痛点：(1) 首次安装没有上手指引，(2) 之后没有快捷方式查看/修改配置。

行为自适应：
  - 还没有店铺 → 渲染 Landing 引导页（介绍 6 个专家团队 + 典型工作流 + 下一步）
  - 已有店铺   → 渲染配置中心（店铺列表 + API 凭据 + SOUL.md + 主题 + 快速链接）

Usage:
    python3 config.py                      # 渲染配置中心 / 引导页，打开浏览器
    python3 config.py --no-open            # 渲染，不开浏览器
    python3 config.py --quiet-stdout       # agent 模式，JSON 一行
    python3 config.py --create-store --platform shopify --market us \\
        --niche "宠物用品" --stage 0-to-1 [--name "店名"] [--url "..."]
    python3 config.py --create-store --from-json store.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import html_lib as H  # noqa: E402
import secret_form  # noqa: E402


def _root() -> Path:
    return Path(os.environ.get("LUMICC_DATA_ROOT", str(Path.home() / ".commerce-os")))


def db_path() -> Path:
    return _root() / "store.db"


def _soul_path() -> Path:
    return _root() / "SOUL.md"


def _design_path() -> Path:
    return _root() / "design.md"


THEME_NAMES = ["midnight-emerald", "linen-warm", "slate-premium", "dawn-coral"]
DEFAULT_THEME = "midnight-emerald"

STAGE_LABEL = {
    "0-to-1": "0→1 新店", "1-to-10": "1→10 成长",
    "10-to-100": "10→100 规模", "100+": "100+ 成熟",
}

SOUL_TEMPLATE = """# 运营铁律 · SOUL.md

> 这些是你手编辑的铁律，Lumicc 永远不会自动改这里。

- 目标毛利：50%
- 每周最多做 3 个重大决策
- 任何 > $500 的支出我要手动确认
"""

# 6 个专家团队 —— 取自 references/personas.md
TEAMS = [
    ("🎯 CMO 总指挥", "统筹判断局势、派单给专业团队。不亲自动手，只做诊断和决策路由。",
     "lumicc · lumicc-dashboard"),
    ("🏪 建站团队", "Shopify 主题工程 + Amazon Listing + 跨境合规。开店 0→1、商详质检与改写。",
     "lumicc-launch · lumicc-listing"),
    ("📊 数据分析师", "客户数据 + BI。看复购、RFM 分群、评论隐藏信号、选品决策。",
     "lumicc-retention · lumicc-voc · lumicc-expand"),
    ("🔭 市场情报员", "竞品监控 + SEO/GEO。每天巡店看竞品动态、做搜索与 LLM 引用优化。",
     "lumicc-watch · lumicc-seo"),
    ("🎨 品牌内容师", "视觉总监 + 文案 + AI 图视频提示工程。出图、视频、文案、品牌 tone。",
     "lumicc-content"),
    ("🚨 危机响应官", "前平台政策审查员。销量崩、账号警告、广告被拒、Listing 被压制时接手。",
     "lumicc-rescue"),
]

# 选品 → 上架 → 引流 → 转化 → 留存 → 救火
WORKFLOW = [
    ("选品", "LAUNCH", "数据分析师选品 + 建站团队开店"),
    ("上架", "LAUNCH", "建站团队做商详、合规检查"),
    ("引流", "ATTRACT", "市场情报员竞品/SEO + 品牌内容师出图文"),
    ("转化", "CONVERT", "建站团队商详质检、漏斗优化"),
    ("留存", "RETAIN", "数据分析师 RFM 分群 + winback"),
    ("救火", "RESCUE", "危机响应官处理账号/销量危机"),
]

# 额外（非 PROVIDERS 内）的 Cloudflare 凭据，用于部署独立站
CLOUDFLARE_KEYS = ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]


# =============================================================================
# Data loading
# =============================================================================
def load_stores() -> list[dict]:
    p = db_path()
    if not p.exists():
        return []
    db = sqlite3.connect(p)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute("SELECT * FROM stores ORDER BY created_at DESC")]
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()


def _read_soul() -> str | None:
    p = _soul_path()
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _current_theme() -> str:
    """env LUMICC_THEME > design.md `## Theme:` > default."""
    env = os.environ.get("LUMICC_THEME")
    if env and env in THEME_NAMES:
        return env
    p = _design_path()
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.lower().startswith("## theme:"):
                    name = s.split(":", 1)[1].strip()
                    if name in THEME_NAMES:
                        return name
        except OSError:
            pass
    return DEFAULT_THEME


# =============================================================================
# Config-center-specific CSS
# =============================================================================
_CONFIG_CSS = """
<style>
.cfg-hero { margin: 6px 0 26px; }
.cfg-hero h1 { font-size: 30px; }
.cfg-pitch { color: var(--ink-muted); font-size: 15px; margin-top: 8px; line-height: 1.6; }
.team-card { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 16px 18px; transition: border-color .15s, transform .15s; }
.team-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.team-name { font-weight: 600; color: var(--ink-strong); font-size: 14px; }
.team-what { color: var(--ink-muted); font-size: 12.5px; margin-top: 6px; line-height: 1.55; }
.team-skills { color: var(--ink-dim); font-size: 11px; margin-top: 9px; font-family: var(--mono); }
.flow { display: flex; gap: 8px; flex-wrap: wrap; align-items: stretch; }
.flow-step { flex: 1; min-width: 130px; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 13px 14px; position: relative; }
.flow-step::after { content: "→"; position: absolute; right: -13px; top: 50%;
  transform: translateY(-50%); color: var(--ink-dim); font-size: 14px; z-index: 1; }
.flow-step:last-child::after { content: ""; }
.flow-name { font-weight: 600; color: var(--ink-strong); font-size: 14px; }
.flow-pillar { font-family: var(--mono); font-size: 10px; letter-spacing: .1em;
  color: var(--accent); margin-top: 3px; }
.flow-desc { color: var(--ink-muted); font-size: 11.5px; margin-top: 6px; line-height: 1.5; }
.action-card { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 20px 22px; }
.action-card h3 { font-size: 16px; color: var(--ink-strong); margin: 0 0 4px; }
.action-card p { color: var(--ink-muted); font-size: 13px; margin: 0 0 12px; }
.cmd-line { display: block; margin: 6px 0; }
.cfg-cmd { display: inline-block; font-family: var(--mono); font-size: 12px;
  padding: 6px 11px; background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; color: var(--ink-muted); cursor: pointer;
  transition: border-color .15s, color .15s; word-break: break-all; }
.cfg-cmd:hover { border-color: var(--accent); color: var(--ink-strong); }
.cfg-cmd::before { content: "$ "; color: var(--ink-dim); }
.soul-pre { background: var(--surface-2); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 16px 18px; font-family: var(--mono);
  font-size: 12px; color: var(--ink-muted); white-space: pre-wrap; overflow-x: auto;
  line-height: 1.6; margin: 0 0 12px; }
.theme-list { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.theme-chip { font-family: var(--mono); font-size: 11px; padding: 4px 10px;
  border: 1px solid var(--line); border-radius: 999px; color: var(--ink-muted); }
.theme-chip.current { border-color: var(--accent); color: var(--ink-strong);
  background: color-mix(in srgb, var(--accent) 10%, var(--surface)); }
.cfg-links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }
.cfg-links a { padding: 9px 18px; border: 1px solid var(--line); border-radius: var(--radius);
  color: var(--ink-muted); text-decoration: none; font-size: 13px;
  transition: border-color .15s, color .15s; }
.cfg-links a:hover { border-color: var(--accent); color: var(--ink-strong); }
.cfg-links a.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.cfg-note { color: var(--ink-dim); font-size: 12px; margin-top: 8px; line-height: 1.5; }
</style>
<script>
function copyCmd(el){
  var t = el.getAttribute('data-cmd') || el.textContent;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(t).then(function(){
      if (typeof showToast === 'function') showToast('✓ 已复制命令');
    });
  }
}
</script>
"""


def _cmd(text: str) -> str:
    """A copyable command chip."""
    e = H.esc(text)
    return f'<code class="cfg-cmd" data-cmd="{e}" onclick="copyCmd(this)" title="点击复制">{e}</code>'


def _scripts_dir_display() -> str:
    """Best-effort display path for the scripts dir in shown commands."""
    return str(HERE)


# =============================================================================
# Shared section: API 凭据
# =============================================================================
def _secrets_block() -> tuple[str, int, int]:
    secrets = secret_form.list_secrets()
    sd = _scripts_dir_display()
    rows: list[list[str]] = []
    configured = 0
    for key, info in secrets.items():
        if not info.get("missing"):
            configured += 1
            status = H.badge("✓ 已配置", "emerald")
            fp = H.esc(info.get("fingerprint") or "—")
            op_label = "更换"
        else:
            status = H.badge("✗ 未配置", "rose")
            fp = "—"
            op_label = "配置"
        op = _cmd(f"python3 {sd}/secret_form.py --generate {key} --open")
        rows.append([H.esc(key), status, fp,
                     f'<span class="cfg-note">{op_label}：</span>{op}'])
    table = H.table(["凭据", "状态", "Fingerprint", "操作"], rows)
    cf_missing = [k for k in CLOUDFLARE_KEYS if k not in secret_form.PROVIDERS]
    note = ""
    if cf_missing:
        note = (
            '<p class="cfg-note">部署独立站还需要 '
            + " / ".join(H.esc(k) for k in cf_missing)
            + "（不在标准 PROVIDERS 列表里），用 "
            + _cmd(f"python3 {sd}/secret_form.py --generate CLOUDFLARE_API_TOKEN --open")
            + " 同样可配置。</p>"
        )
    total = len(secrets) + len(cf_missing)
    return table + note, configured, total


# =============================================================================
# Render: Landing / onboarding mode
# =============================================================================
def _team_cards() -> str:
    cards = []
    for name, what, skills in TEAMS:
        cards.append(
            f'<div class="team-card">'
            f'<div class="team-name">{H.esc(name)}</div>'
            f'<div class="team-what">{H.esc(what)}</div>'
            f'<div class="team-skills">{H.esc(skills)}</div>'
            f'</div>'
        )
    return H.card_grid(cards, min_width=250)


def _workflow_flow() -> str:
    steps = []
    for name, pillar, desc in WORKFLOW:
        steps.append(
            f'<div class="flow-step">'
            f'<div class="flow-name">{H.esc(name)}</div>'
            f'<div class="flow-pillar">{H.esc(pillar)}</div>'
            f'<div class="flow-desc">{H.esc(desc)}</div>'
            f'</div>'
        )
    return '<div class="flow">' + "".join(steps) + "</div>"


def render_landing() -> str:
    sd = _scripts_dir_display()

    hero = (
        '<section class="cfg-hero">'
        '<h1>欢迎使用 Lumicc · 你的跨境运营 OS</h1>'
        '<p class="cfg-pitch">一个本地优先的跨境电商操作系统：6 个专家团队 + 11 个 skill，'
        '从选品到救火全程陪跑，所有数据只存你本机 ~/.commerce-os/。</p>'
        '</section>'
    )

    intro = H.section("Lumicc 能帮你做什么 · 6 个专家团队", _team_cards())

    workflow = H.section(
        "典型工作流 · 选品 → 上架 → 引流 → 转化 → 留存 → 救火",
        _workflow_flow(),
    )

    have_store = (
        '<div class="action-card">'
        '<h3>我有店 · 接入数据</h3>'
        '<p>已经在 Shopify / Amazon / 独立站上卖货？把订单和商品数据导进来。</p>'
        f'<span class="cmd-line">{_cmd(f"python3 {sd}/adapter_csv.py --help")}</span>'
        f'<span class="cmd-line">{_cmd(f"python3 {sd}/adapter_shopify.py --help")}</span>'
        f'<span class="cmd-line">{_cmd(f"python3 {sd}/adapter_indep.py --help")}</span>'
        '</div>'
    )
    new_store = (
        '<div class="action-card">'
        '<h3>从零开始 · 开新店</h3>'
        '<p>还没有店铺？直接建一家，Lumicc 会带你 0→1 冷启动。</p>'
        f'<span class="cmd-line">{_cmd(f"python3 {sd}/config.py --create-store --platform shopify --market us --niche 宠物用品 --stage 0-to-1")}</span>'
        '</div>'
    )
    next_steps = H.section(
        "下一步 · 两条路",
        H.card_grid([have_store, new_store], min_width=320),
    )

    secrets_body, configured, total = _secrets_block()
    secrets = H.section(
        f"API 凭据（{configured}/{total} 已配置）· 凭据只存本机，从不进对话",
        secrets_body,
    )

    body = hero + intro + workflow + next_steps + secrets
    return _CONFIG_CSS + H.page(
        title="Lumicc 配置中心", body=body,
        back_link=None, brand_subtitle="跨境运营 OS",
    )


# =============================================================================
# Render: Config-center mode
# =============================================================================
def _stores_block(stores: list[dict]) -> str:
    sd = _scripts_dir_display()
    rows: list[list[str]] = []
    for s in stores:
        sid = s["id"]
        name = H.esc(s.get("name") or "（未命名）")
        platform = H.esc(s.get("platform") or "—")
        stage = s.get("stage") or "—"
        stage_html = H.badge(STAGE_LABEL.get(stage, stage), "sky")
        niche = H.esc(s.get("niche") or "—")
        created = H.fmt_ts(s.get("created_at"), "%Y-%m-%d") if s.get("created_at") else "—"
        edit = _cmd(f"python3 {sd}/config.py --create-store ...  # 新建另一家店")
        rows.append([name, platform, stage_html, niche, created,
                     f'<span class="cfg-note">store_id: {H.esc(sid[:8])}…</span>'])
    return H.table(
        ["店铺", "平台", "阶段", "Niche", "创建于", ""],
        rows,
    )


def render_config(stores: list[dict] | None = None) -> str:
    """Render config center (stores exist) or landing (no stores)."""
    if stores is None:
        stores = load_stores()
    if not stores:
        return render_landing()

    sd = _scripts_dir_display()
    head = H.page_head(
        "Lumicc 配置中心",
        f"{len(stores)} 家店 · 统一查看 / 修改所有配置",
    )

    # 店铺
    stores_sec = H.section(
        f"你的店铺（{len(stores)}）",
        _stores_block(stores)
        + f'<p class="cfg-note">新建店铺：'
        + _cmd(f"python3 {sd}/config.py --create-store --platform shopify --market us --niche 类目 --stage 0-to-1")
        + "</p>",
    )

    # API 凭据
    secrets_body, configured, total = _secrets_block()
    secrets_sec = H.section(
        f"API 凭据（{configured}/{total} 已配置）",
        secrets_body,
    )

    # SOUL.md
    soul = _read_soul()
    if soul is None:
        soul_body = (
            '<p class="cfg-note">还没有 SOUL.md，建议创建 —— 这是你手编辑的运营铁律，'
            'Lumicc 永远不会自动改它。新建第一家店时会自动写一份起始模板，'
            '或手动创建：</p>'
            + _cmd(f"$EDITOR {_soul_path()}")
        )
    else:
        preview = soul[:600]
        if len(soul) > 600:
            preview += " …"
        soul_body = (
            f'<pre class="soul-pre">{H.esc(preview)}</pre>'
            '<p class="cfg-note">编辑：</p>'
            + _cmd(f"$EDITOR {_soul_path()}")
        )
    soul_sec = H.section("运营铁律 · SOUL.md", soul_body)

    # 视觉主题
    theme = _current_theme()
    chips = []
    for t in THEME_NAMES:
        cls = "theme-chip current" if t == theme else "theme-chip"
        chips.append(f'<span class="{cls}">{H.esc(t)}</span>')
    theme_body = (
        f'<p class="cfg-note">当前主题：<strong>{H.esc(theme)}</strong></p>'
        '<div class="theme-list">' + "".join(chips) + "</div>"
        '<p class="cfg-note">切换方式：在 ~/.commerce-os/design.md 写 '
        '<code>## Theme: &lt;name&gt;</code>，或临时用环境变量：</p>'
        + _cmd("export LUMICC_THEME=linen-warm")
    )
    theme_sec = H.section("视觉主题", theme_body)

    # 快速链接
    links_sec = H.section(
        "快速链接",
        '<div class="cfg-links">'
        '<a class="primary" href="home.html">控制台</a>'
        '<a href="dashboard/index.html">完整仪表盘</a>'
        '</div>',
    )

    body = head + stores_sec + secrets_sec + soul_sec + theme_sec + links_sec
    return _CONFIG_CSS + H.page(
        title="Lumicc 配置中心", body=body,
        back_link=None, brand_subtitle="跨境运营 OS",
    )


# =============================================================================
# --create-store
# =============================================================================
def create_store(*, platform: str, market: str, niche: str, stage: str,
                  name: str | None = None, url: str | None = None) -> dict:
    """Insert a store row + write a SOUL.md starter if missing."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    p = db_path()
    if not p.exists():
        raise SystemExit(
            f"store.db 不存在 — 先运行 python3 {HERE}/init_store.py")

    sid = str(uuid.uuid4())
    now = int(time.time())
    store_name = name or f"{niche} · {market}".strip()

    db = sqlite3.connect(p)
    try:
        db.execute(
            "INSERT INTO stores "
            "(id,name,platform,url,currency,target_market,stage,niche,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, store_name, platform, url, "USD", market, stage, niche, now, now),
        )
        db.commit()
    finally:
        db.close()

    # SOUL.md starter
    soul = _soul_path()
    if not soul.exists():
        soul.write_text(SOUL_TEMPLATE, encoding="utf-8")

    return {"store_id": sid, "name": store_name, "created": True}


def _create_from_json(path: str) -> dict:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    missing = [k for k in ("platform", "market", "niche", "stage") if k not in data]
    if missing:
        raise SystemExit(f"--from-json 缺少字段: {', '.join(missing)}")
    return create_store(
        platform=data["platform"], market=data["market"],
        niche=data["niche"], stage=data["stage"],
        name=data.get("name"), url=data.get("url"),
    )


# =============================================================================
# Main
# =============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--quiet-stdout", action="store_true")
    ap.add_argument("--output", default=None, help="HTML 输出路径（默认 ~/.commerce-os/config.html）")
    ap.add_argument("--create-store", action="store_true")
    ap.add_argument("--platform", default=None)
    ap.add_argument("--market", default=None)
    ap.add_argument("--niche", default=None)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--url", default=None)
    ap.add_argument("--from-json", default=None)
    args = ap.parse_args()

    # --- create-store path ---
    if args.create_store:
        if args.from_json:
            result = _create_from_json(args.from_json)
        else:
            req = {"platform": args.platform, "market": args.market,
                   "niche": args.niche, "stage": args.stage}
            missing = [k for k, v in req.items() if not v]
            if missing:
                ap.error(f"--create-store 需要 --{' --'.join(missing)}")
            result = create_store(
                platform=args.platform, market=args.market,
                niche=args.niche, stage=args.stage,
                name=args.name, url=args.url,
            )
        if args.quiet_stdout:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"✓ 已创建店铺 · {result['name']}")
            print(f"  store_id: {result['store_id']}")
        return 0

    # --- render path ---
    stores = load_stores()
    html = render_config(stores)

    out_path = Path(args.output).expanduser() if args.output else (_root() / "config.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    _, configured, _ = _secrets_block()
    soul_exists = _soul_path().exists()
    result = {
        "skill": "lumicc-config",
        "status": "success",
        "stores": len(stores),
        "keys_configured": configured,
        "soul_exists": soul_exists,
        "config_html": str(out_path),
    }

    if args.quiet_stdout:
        print(json.dumps(result, ensure_ascii=False))
    else:
        mode = "配置中心" if stores else "首次安装引导"
        print(f"✓ {mode}已渲染 · {len(stores)} 家店 · {configured} 个凭据已配置")
        print(f"  {out_path}")
        if not args.no_open:
            try:
                webbrowser.open(f"file://{out_path}")
            except Exception:  # noqa: BLE001
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
