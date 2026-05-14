#!/usr/bin/env python3
"""Lumicc 配置向导 —— 本地 HTTP 服务器，浏览器即 UI。

不再生成静态 HTML 让用户复制命令。这是一个真正的本地服务器：用户在浏览器
里填表单、点提交，立即生效。镜像 lumi-lab 的 onboarding wizard，纯 Python
stdlib 实现。

4 步向导：
  1/4 · 欢迎       —— Lumicc 是什么 · 6 个专家团队 · 典型工作流
  2/4 · 你的店铺   —— 表单创建店铺（有店 / 从零）
  3/4 · 工具集成   —— API keys，按用途分组，逐个验证并保存
  4/4 · 完成       —— 总览 + 入口链接

服务器只绑 127.0.0.1，端口 7777→7780。完成第 4 步后自动关闭。

Usage:
    python3 config.py                    # 启动向导服务器 + 开浏览器（默认）
    python3 config.py --no-open          # 启动服务器，不开浏览器
    python3 config.py --port 7780        # 指定端口
    python3 config.py --quiet-stdout     # 不启动服务器，打印 JSON 状态
    python3 config.py --status           # 打印人类可读状态，不启动服务器
    python3 config.py --create-store --platform shopify --market us \\
        --niche "宠物用品" --stage 0-to-1 [--name "店名"]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import html_lib as H  # noqa: E402
import secret_form  # noqa: E402

VERSION = "0.2.0"
PORTS = [7777, 7778, 7779, 7780]
HTTP_TIMEOUT = 8


# =============================================================================
# Paths
# =============================================================================
def _root() -> Path:
    return Path(os.environ.get("LUMICC_DATA_ROOT", str(Path.home() / ".commerce-os")))


def db_path() -> Path:
    return _root() / "store.db"


def _soul_path() -> Path:
    return _root() / "SOUL.md"


SOUL_TEMPLATE = """# 运营铁律 · SOUL.md

> 这些是你手编辑的铁律，Lumicc 永远不会自动改这里。

- 目标毛利：50%
- 每周最多做 3 个重大决策
- 任何 > $500 的支出我要手动确认
"""

STAGE_LABEL = {
    "0-to-1": "0→1 新店", "1-to-10": "1→10 成长",
    "10-to-100": "10→100 规模", "100+": "100+ 成熟",
}

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

WORKFLOW = [
    ("选品", "LAUNCH", "数据分析师选品 + 建站团队开店"),
    ("上架", "LAUNCH", "建站团队做商详、合规检查"),
    ("引流", "ATTRACT", "市场情报员竞品/SEO + 品牌内容师出图文"),
    ("转化", "CONVERT", "建站团队商详质检、漏斗优化"),
    ("留存", "RETAIN", "数据分析师 RFM 分群 + winback"),
    ("救火", "RESCUE", "危机响应官处理账号/销量危机"),
]

# 部署用的 Cloudflare 凭据（不在标准 PROVIDERS 列表里）
CLOUDFLARE_KEYS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")

# Step 3 分组：(legend, [keys], collapsed?)
KEY_GROUPS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("电商平台数据",
     ("SHOPIFY_ADMIN_TOKEN", "AMAZON_SP_API_REFRESH", "TIKTOK_SHOP_API", "ETSY_API_KEY"),
     False),
    ("图像生成", ("NANO_BANANA_API_KEY", "GPT_IMAGE_2_API_KEY"), False),
    ("邮件营销", ("KLAVIYO_API_KEY",), False),
    ("LLM（可选 · 通常宿主已自带）", ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"), True),
    ("部署（lumicc-publish 用）", CLOUDFLARE_KEYS, True),
)

# 每个 key 的一句话用途（hint）+ 快速上手步骤（quickstart，| 分隔）
_KEY_META: dict[str, tuple[str, str]] = {
    "SHOPIFY_ADMIN_TOKEN": (
        "用来直接拉取你 Shopify 店的产品/订单/客户数据；没有它就用 CSV 导入。",
        "打开 Shopify Admin → Settings → Apps and sales channels|"
        "Develop apps → Create an app|"
        "Configure Admin API scopes（products / orders / customers 读取）|"
        "Install app → 复制 Admin API access token（shpat_ 开头）"),
    "AMAZON_SP_API_REFRESH": (
        "解锁 Amazon 卖家数据同步（订单、库存、Listing）；没有则手动导出。",
        "Seller Central → Apps & Services → Develop Apps|"
        "创建/授权一个 SP-API 应用|走 OAuth 授权流程，拿到 refresh token|"
        "粘贴到这里（Atzr| 开头）"),
    "TIKTOK_SHOP_API": (
        "接入 TikTok Shop 的商品与订单数据；缺失时走 CSV / 手动。",
        "TikTok Shop Partner Center → My Apps|"
        "打开 App Detail，复制 App Key / App Secret|粘贴 App Key 到这里"),
    "ETSY_API_KEY": (
        "拉取 Etsy 店铺的 listing 与订单；没有就手动维护。",
        "登录 https://www.etsy.com/developers/your-apps|"
        "Create a New App|复制 Keystring"),
    "NANO_BANANA_API_KEY": (
        "品牌内容师出图用；没有则只给出图提示词，你自己跑。",
        "登录 Nano Banana 控制台|API → Create Key|复制并粘贴到这里"),
    "GPT_IMAGE_2_API_KEY": (
        "另一个出图后端，和 Nano Banana 二选一即可。",
        "登录 GPT Image 2 控制台|Tokens → 新建|复制并粘贴"),
    "KLAVIYO_API_KEY": (
        "用来发 winback / 营销邮件；没有则只生成邮件草稿。",
        "Klaviyo → Account → Settings → API Keys|"
        "Create Private API Key|复制（pk_ 开头）"),
    "ANTHROPIC_API_KEY": (
        "可选——你的 AI 宿主通常已自带 LLM，一般不用填。",
        "console.anthropic.com → Settings → API Keys|"
        "Create Key → 复制（sk-ant- 开头）"),
    "OPENAI_API_KEY": (
        "可选——同上，宿主自带 LLM 时无需填。",
        "platform.openai.com → API keys|Create new secret key → 复制（sk- 开头）"),
    "CLOUDFLARE_API_TOKEN": (
        "lumicc-publish 把独立站部署到 Cloudflare Pages 时用。",
        "打开 dash.cloudflare.com/profile/api-tokens|"
        "Create Token → Custom Token|权限：Account · Cloudflare Pages · Edit|"
        "Create → 复制 token"),
    "CLOUDFLARE_ACCOUNT_ID": (
        "配合上面的 token 指定部署到哪个 Cloudflare 账号。",
        "打开 dash.cloudflare.com|右侧栏可见 Account ID，直接复制"),
}
KEY_HINTS: dict[str, str] = {k: v[0] for k, v in _KEY_META.items()}
KEY_QUICKSTART: dict[str, list[str]] = {
    k: v[1].split("|") for k, v in _KEY_META.items()
}

# key → human label。优先用 secret_form 的 PROVIDERS。
EXTRA_LABELS = {
    "CLOUDFLARE_API_TOKEN": "Cloudflare API Token",
    "CLOUDFLARE_ACCOUNT_ID": "Cloudflare Account ID",
}


def _key_label(key: str) -> str:
    if key in secret_form.PROVIDERS:
        return secret_form.PROVIDERS[key]["label"]
    return EXTRA_LABELS.get(key, key)


# =============================================================================
# Store data
# =============================================================================
def load_stores() -> list[dict]:
    p = db_path()
    if not p.exists():
        return []
    db = sqlite3.connect(p)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(
            "SELECT * FROM stores ORDER BY created_at DESC")]
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()


def create_store(*, platform: str, market: str, niche: str, stage: str,
                  name: str | None = None, url: str | None = None) -> dict:
    """Insert a store row + write a SOUL.md starter if missing."""
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    p = db_path()
    if not p.exists():
        raise SystemExit(f"store.db 不存在 — 先运行 python3 {HERE}/init_store.py")

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

    soul = _soul_path()
    soul_written = False
    if not soul.exists():
        soul.write_text(SOUL_TEMPLATE, encoding="utf-8")
        soul_written = True

    return {"store_id": sid, "name": store_name, "created": True,
            "soul_written": soul_written}


# =============================================================================
# Secret storage — same format as secret_form.py
# =============================================================================
def _save_key(key: str, value: str, provider: str) -> dict:
    """Write a secret file in secret_form.py's exact JSON format, mode 0600.

    Returns {ok, fingerprint, stored_at}.
    """
    value = (value or "").strip()
    if not value:
        return {"ok": False, "error": "凭据值为空"}
    secrets_dir = secret_form.SECRETS_DIR
    secrets_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(secrets_dir, 0o700)
    except OSError:
        pass
    fingerprint = secret_form._fingerprint(value)
    stored_at = int(time.time())
    payload = {
        "key": key,
        "provider": provider,
        "value": value,
        "stored_at": stored_at,
        "fingerprint": fingerprint,
    }
    path = secrets_dir / f"{key}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"ok": True, "fingerprint": fingerprint, "stored_at": stored_at}


# =============================================================================
# Token verification — best-effort. Failed verify still saves the key.
# =============================================================================
def _http_json(url: str, headers: dict[str, str]) -> tuple[int, dict | None]:
    """GET url, return (status, parsed_json_or_none). Raises on network error."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        return e.code, None


def _verify_cloudflare(value: str) -> dict:
    """Cloudflare API token → real API call against /accounts."""
    if not value or len(value) < 20:
        return {"ok": False, "verified": False, "code": "E_FORMAT",
                "message": "token 太短，看起来不完整"}
    try:
        status, _ = _http_json(
            "https://api.cloudflare.com/client/v4/accounts",
            {"Authorization": f"Bearer {value}", "Content-Type": "application/json"},
        )
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return {"ok": True, "verified": False, "code": "E_NET",
                "message": f"网络错误，已保存但未验证：{e}"}
    if status == 200:
        return {"ok": True, "verified": True, "message": "Cloudflare token 有效"}
    if status == 401:
        return {"ok": True, "verified": False, "code": "E_401",
                "message": "Cloudflare 401：token 失效或权限不足（已保存，可稍后更换）"}
    return {"ok": True, "verified": False, "code": f"E_{status}",
            "message": f"Cloudflare 返回 {status}（已保存）"}


def _verify_format(value: str, prefix: str = "", min_len: int = 8,
                   provider: str = "") -> dict:
    """Generic format check. Always saves (ok=True)."""
    v = (value or "").strip()
    if len(v) < min_len:
        return {"ok": False, "verified": False, "code": "E_FORMAT",
                "message": f"{provider or '凭据'}太短（至少 {min_len} 字符）"}
    if prefix and not v.startswith(prefix):
        return {"ok": True, "verified": False, "code": "E_FORMAT",
                "message": f"已保存，但不以预期前缀 {prefix} 开头，请确认"}
    return {"ok": True, "verified": True, "message": "格式检查通过（首次使用时再实测）"}


def verify_token(key: str, value: str) -> dict:
    """Dispatch verification by key. Returns {ok, verified, code?, message?}."""
    if key == "CLOUDFLARE_API_TOKEN":
        return _verify_cloudflare(value)
    if key == "CLOUDFLARE_ACCOUNT_ID":
        return _verify_format(value, min_len=8, provider="Account ID")
    if key == "SHOPIFY_ADMIN_TOKEN":
        return _verify_format(value, prefix="shpat_", min_len=10,
                              provider="Shopify token")
    if key == "ANTHROPIC_API_KEY":
        return _verify_format(value, prefix="sk-ant-", min_len=10,
                              provider="Anthropic key")
    if key == "OPENAI_API_KEY":
        return _verify_format(value, prefix="sk-", min_len=10,
                              provider="OpenAI key")
    if key == "KLAVIYO_API_KEY":
        return _verify_format(value, prefix="pk_", min_len=8,
                              provider="Klaviyo key")
    # everyone else: non-empty + reasonable length
    return _verify_format(value, min_len=6, provider=_key_label(key))


# =============================================================================
# Wizard CSS (appended on top of html_lib themed CSS)
# =============================================================================
_WIZARD_CSS = """
<style>
.wz-steps { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; margin: 6px 0 26px; }
.wz-step { padding: 11px 13px; border-right: 1px solid var(--line); background: var(--surface); }
.wz-step:last-child { border-right: 0; }
.wz-step.current { background: color-mix(in srgb, var(--accent) 10%, var(--surface)); }
.wz-step-num { font-family: var(--mono); font-size: 11px; color: var(--ink-dim); letter-spacing: .08em; }
.wz-step.current .wz-step-num, .wz-step.done .wz-step-num { color: var(--accent); }
.wz-step-label { font-size: 12px; color: var(--ink-muted); margin-top: 2px; }
.wz-step.current .wz-step-label { color: var(--ink-strong); font-weight: 600; }
.cfg-hero h1 { font-size: 28px; }
.cfg-pitch { color: var(--ink-muted); font-size: 15px; margin-top: 8px; line-height: 1.6; max-width: 62ch; }
.team-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; transition: border-color .15s; }
.team-card:hover { border-color: var(--accent); }
.team-name { font-weight: 600; color: var(--ink-strong); font-size: 14px; }
.team-what { color: var(--ink-muted); font-size: 12.5px; margin-top: 6px; line-height: 1.55; }
.team-skills { color: var(--ink-dim); font-size: 11px; margin-top: 9px; font-family: var(--mono); }
.flow { display: flex; gap: 8px; flex-wrap: wrap; }
.flow-step { flex: 1; min-width: 130px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 13px 14px; position: relative; }
.flow-step::after { content: "\\2192"; position: absolute; right: -13px; top: 50%; transform: translateY(-50%); color: var(--ink-dim); font-size: 14px; }
.flow-step:last-child::after { content: ""; }
.flow-name { font-weight: 600; color: var(--ink-strong); font-size: 14px; }
.flow-pillar { font-family: var(--mono); font-size: 10px; letter-spacing: .1em; color: var(--accent); margin-top: 3px; }
.flow-desc { color: var(--ink-muted); font-size: 11.5px; margin-top: 6px; line-height: 1.5; }
.wz-form { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 22px 24px; margin-top: 4px; }
.wz-fieldset { border: 0; padding: 0; margin: 0 0 22px; }
.wz-fieldset:last-of-type { margin-bottom: 0; }
.wz-legend { font-family: var(--mono); font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-dim); padding-bottom: 8px; border-bottom: 1px solid var(--line); margin-bottom: 14px; width: 100%; }
.wz-row { display: grid; gap: 6px; padding: 11px 0; border-bottom: 1px solid var(--line); }
.wz-row:last-child { border-bottom: 0; }
.wz-label { font-size: 13px; font-weight: 600; color: var(--ink-strong); }
.wz-label .opt { font-family: var(--mono); font-size: 10px; color: var(--ink-dim); margin-left: 6px; font-weight: 400; }
.wz-hint { font-size: 12px; color: var(--ink-muted); line-height: 1.5; }
.wz-input, .wz-select { width: 100%; box-sizing: border-box; padding: 9px 11px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); color: var(--ink); font-size: 13px; font-family: var(--mono); }
.wz-input:focus, .wz-select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.wz-token-row { display: flex; gap: 8px; }
.wz-token-row .wz-input { flex: 1; }
.wz-btn { padding: 9px 16px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2); color: var(--ink); font-size: 13px; cursor: pointer; transition: border-color .15s, background .15s; white-space: nowrap; }
.wz-btn:hover { border-color: var(--accent); }
.wz-btn.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
.wz-btn.primary:hover { opacity: .9; }
.wz-btn:disabled { opacity: .5; cursor: not-allowed; }
.wz-radio-group { display: flex; gap: 10px; flex-wrap: wrap; }
.wz-radio { display: inline-flex; align-items: center; gap: 7px; padding: 9px 14px; border: 1px solid var(--line); border-radius: 8px; cursor: pointer; font-size: 13px; color: var(--ink-muted); background: var(--surface-2); }
.wz-radio:has(input:checked) { border-color: var(--accent); color: var(--ink-strong); background: color-mix(in srgb, var(--accent) 10%, var(--surface)); }
.wz-radio input { accent-color: var(--accent); }
.wz-status { font-size: 12px; font-family: var(--mono); min-height: 16px; line-height: 1.4; }
.wz-status.ok { color: var(--emerald, #22c55e); }
.wz-status.warn { color: var(--amber, #f59e0b); }
.wz-status.err { color: var(--rose, #f43f5e); }
.wz-qs { margin-top: 2px; }
.wz-qs summary { font-family: var(--mono); font-size: 11px; color: var(--ink-dim); cursor: pointer; padding: 3px 0; }
.wz-qs ol { margin: 4px 0 0 1.3rem; padding: 0; font-size: 12px; color: var(--ink-muted); line-height: 1.6; }
.wz-actions { display: flex; gap: 10px; align-items: center; margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--line); }
.wz-actions .spacer { flex: 1; }
.wz-note { color: var(--ink-dim); font-size: 12px; margin-top: 10px; line-height: 1.5; }
.wz-note code { font-family: var(--mono); background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
.wz-done-recap { font-size: 14px; color: var(--ink-muted); line-height: 1.7; margin: 10px 0 18px; }
.wz-links { display: flex; gap: 10px; flex-wrap: wrap; }
.wz-links a { padding: 9px 18px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--ink-muted); text-decoration: none; font-size: 13px; transition: border-color .15s, color .15s; }
.wz-links a:hover { border-color: var(--accent); color: var(--ink-strong); }
.wz-links a.primary { background: var(--accent); color: var(--bg); border-color: var(--accent); }
details.wz-collapsed { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 16px; margin-bottom: 22px; }
details.wz-collapsed > summary { font-family: var(--mono); font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-dim); cursor: pointer; }
details.wz-collapsed[open] > summary { margin-bottom: 14px; }
.hidden { display: none !important; }
</style>
<script>
async function wzPost(url, data) {
  const r = await fetch(url, { method: 'POST',
    headers: {'content-type': 'application/json'}, body: JSON.stringify(data) });
  return r.json();
}
function wzGo(path) { window.location.href = path; }
</script>
"""


def _wz_steps(current: int) -> str:
    labels = ["欢迎", "你的店铺", "工具集成", "完成"]
    cells = []
    for i, label in enumerate(labels, start=1):
        cls = "wz-step"
        if i == current:
            cls += " current"
        elif i < current:
            cls += " done"
        cells.append(
            f'<div class="{cls}"><div class="wz-step-num">{i:02d} / 04</div>'
            f'<div class="wz-step-label">{H.esc(label)}</div></div>'
        )
    return '<div class="wz-steps">' + "".join(cells) + "</div>"


def _wz_page(title: str, current: int, body: str) -> str:
    full = _wz_steps(current) + body
    return _WIZARD_CSS + H.page(
        title=title, body=full, back_link=None,
        brand_subtitle="跨境运营 OS · 配置向导",
        right_meta=f"v{VERSION} · 127.0.0.1",
    )


# =============================================================================
# Step 1 · Welcome
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


def render_step1() -> str:
    hero = (
        '<section class="cfg-hero">'
        '<h1>欢迎使用 Lumicc · 你的跨境运营 OS</h1>'
        '<p class="cfg-pitch">一个本地优先的跨境电商操作系统：6 个专家团队 + 11 个 skill，'
        '从选品到救火全程陪跑。所有数据只存你本机 ~/.commerce-os/，凭据从不进对话。</p>'
        '</section>'
    )
    intro = H.section("Lumicc 能帮你做什么 · 6 个专家团队", _team_cards())
    workflow = H.section(
        "典型工作流 · 选品 → 上架 → 引流 → 转化 → 留存 → 救火",
        _workflow_flow(),
    )
    actions = (
        '<div class="wz-actions">'
        '<div class="spacer"></div>'
        '<button class="wz-btn primary" onclick="wzGo(\'/step/2\')">开始设置 →</button>'
        '</div>'
    )
    body = hero + intro + workflow + actions
    return _wz_page("欢迎", 1, body)


# =============================================================================
# Step 2 · Your store
# =============================================================================
def render_step2() -> str:
    platforms = ["Shopify", "独立站", "Amazon", "TikTok Shop", "Etsy"]
    markets = ["US", "EU", "UK", "SEA", "Global"]
    stages = ["0-to-1", "1-to-10", "10-to-100", "100+"]

    def _opts(items: list[str]) -> str:
        return "".join(f'<option value="{H.esc(x)}">{H.esc(x)}</option>' for x in items)

    def _stage_opts() -> str:
        return "".join(
            f'<option value="{H.esc(s)}">{H.esc(STAGE_LABEL[s])}</option>'
            for s in stages
        )

    head = H.page_head("你的店铺", "用表单建一家店 —— 立即写入 store.db。也可以跳过。")

    have_form = f"""
<fieldset class="wz-fieldset" id="fs-have">
  <div class="wz-legend">我已经有店</div>
  <div class="wz-row">
    <label class="wz-label" for="h-name">店铺名</label>
    <input class="wz-input" id="h-name" placeholder="My Pet Store">
  </div>
  <div class="wz-row">
    <label class="wz-label" for="h-platform">平台</label>
    <select class="wz-select" id="h-platform">{_opts(platforms)}</select>
  </div>
  <div class="wz-row">
    <label class="wz-label" for="h-market">目标市场</label>
    <select class="wz-select" id="h-market">{_opts(markets)}</select>
  </div>
  <div class="wz-row">
    <label class="wz-label" for="h-niche">主营品类</label>
    <input class="wz-input" id="h-niche" placeholder="宠物用品 / 户外装备 / ...">
  </div>
  <div class="wz-row">
    <label class="wz-label" for="h-stage">阶段</label>
    <select class="wz-select" id="h-stage">{_stage_opts()}</select>
  </div>
</fieldset>
"""

    new_form = f"""
<fieldset class="wz-fieldset hidden" id="fs-new">
  <div class="wz-legend">从零开始开新店</div>
  <div class="wz-row">
    <label class="wz-label" for="n-name">店铺名 <span class="opt">可选</span></label>
    <input class="wz-input" id="n-name" placeholder="还没想好可以留空">
  </div>
  <div class="wz-row">
    <label class="wz-label" for="n-niche">想做什么品类</label>
    <input class="wz-input" id="n-niche" placeholder="宠物用品 / 手工饰品 / ...">
  </div>
  <div class="wz-row">
    <label class="wz-label" for="n-market">目标市场</label>
    <select class="wz-select" id="n-market">{_opts(markets)}</select>
  </div>
  <p class="wz-note">阶段会自动设为 <code>0-to-1</code>（0→1 新店）。</p>
</fieldset>
"""

    body = head + f"""
<div class="wz-form">
  <fieldset class="wz-fieldset">
    <div class="wz-legend">你现在的状态</div>
    <div class="wz-radio-group">
      <label class="wz-radio">
        <input type="radio" name="store-mode" value="have" checked
          onchange="wzToggleMode()"> 我已经有店
      </label>
      <label class="wz-radio">
        <input type="radio" name="store-mode" value="new"
          onchange="wzToggleMode()"> 从零开始开新店
      </label>
    </div>
  </fieldset>
  {have_form}
  {new_form}
  <div class="wz-status" id="store-status"></div>
  <div class="wz-actions">
    <button class="wz-btn" onclick="wzGo('/step/1')">← 上一步</button>
    <div class="spacer"></div>
    <button class="wz-btn" onclick="wzGo('/step/3')">跳过，稍后再说</button>
    <button class="wz-btn primary" id="store-submit"
      onclick="wzCreateStore()">创建店铺 →</button>
  </div>
</div>
<script>
function wzToggleMode() {{
  const mode = document.querySelector('input[name=store-mode]:checked').value;
  document.getElementById('fs-have').classList.toggle('hidden', mode !== 'have');
  document.getElementById('fs-new').classList.toggle('hidden', mode !== 'new');
}}
async function wzCreateStore() {{
  const mode = document.querySelector('input[name=store-mode]:checked').value;
  const status = document.getElementById('store-status');
  const btn = document.getElementById('store-submit');
  let payload;
  if (mode === 'have') {{
    const niche = document.getElementById('h-niche').value.trim();
    if (!niche) {{ status.className = 'wz-status err';
      status.textContent = '请填写主营品类'; return; }}
    payload = {{
      name: document.getElementById('h-name').value.trim(),
      platform: document.getElementById('h-platform').value,
      market: document.getElementById('h-market').value,
      niche: niche,
      stage: document.getElementById('h-stage').value,
    }};
  }} else {{
    const niche = document.getElementById('n-niche').value.trim();
    if (!niche) {{ status.className = 'wz-status err';
      status.textContent = '请填写想做的品类'; return; }}
    payload = {{
      name: document.getElementById('n-name').value.trim(),
      platform: '独立站',
      market: document.getElementById('n-market').value,
      niche: niche,
      stage: '0-to-1',
    }};
  }}
  btn.disabled = true;
  status.className = 'wz-status'; status.textContent = '创建中…';
  try {{
    const res = await wzPost('/api/store', payload);
    if (res.ok) {{
      status.className = 'wz-status ok';
      status.textContent = '✓ 已创建 · ' + res.name + '，正在进入下一步…';
      setTimeout(() => wzGo('/step/3'), 700);
    }} else {{
      btn.disabled = false;
      status.className = 'wz-status err';
      status.textContent = res.error || '创建失败';
    }}
  }} catch (e) {{
    btn.disabled = false;
    status.className = 'wz-status err';
    status.textContent = '本地错误：' + e.message;
  }}
}}
</script>
"""
    return _wz_page("你的店铺", 2, body)


# =============================================================================
# Step 3 · Tool integrations (API keys)
# =============================================================================
def _token_field(key: str) -> str:
    """Build one token input row: label, hint, quickstart, password input + button."""
    label = _key_label(key)
    provider = secret_form.PROVIDERS.get(key, {}).get("provider", "custom")
    if key in CLOUDFLARE_KEYS:
        provider = "cloudflare"
    hint = KEY_HINTS.get(key, "")
    fp = secret_form.secret_fingerprint(key)
    configured = fp is not None

    qs_steps = KEY_QUICKSTART.get(key, [])
    qs_html = ""
    if qs_steps:
        items = "".join(f"<li>{H.esc(s)}</li>" for s in qs_steps)
        qs_html = (
            f'<details class="wz-qs"><summary>在哪里拿到这个 key？</summary>'
            f'<ol>{items}</ol></details>'
        )

    state_cls = "ok" if configured else ""
    state_txt = f"已配置 ✓ · {H.esc(fp)}" if configured else ""
    placeholder = "已配置——粘贴新值可更换" if configured else f"粘贴 {H.esc(label)}…"

    return f"""
<div class="wz-row">
  <label class="wz-label" for="in-{H.esc(key)}">{H.esc(label)}
    <span class="opt">可跳过</span></label>
  {f'<div class="wz-hint">{H.esc(hint)}</div>' if hint else ''}
  <div class="wz-token-row">
    <input class="wz-input" type="password" id="in-{H.esc(key)}"
      autocomplete="off" placeholder="{placeholder}"
      data-key="{H.esc(key)}" data-provider="{H.esc(provider)}">
    <button class="wz-btn" onclick="wzSaveKey('{H.esc(key)}')">验证并保存</button>
  </div>
  <div class="wz-status {state_cls}" id="st-{H.esc(key)}">{state_txt}</div>
  {qs_html}
</div>
"""


def _key_fieldset(legend: str, keys: tuple[str, ...]) -> str:
    rows = "".join(_token_field(k) for k in keys)
    return (
        f'<fieldset class="wz-fieldset"><div class="wz-legend">{H.esc(legend)}</div>'
        f'{rows}</fieldset>'
    )


def render_step3() -> str:
    head = H.page_head(
        "工具集成 · API keys",
        "任何一项都可以跳过 · 凭据只写本机 ~/.commerce-os/secrets/（权限 600）",
    )
    intro = (
        '<p class="cfg-pitch">Lumicc 不需要 LLM 密钥——你的 AI 宿主自带。'
        '这里的 key 用来解锁数据接入、出图、部署。<strong>任何一项都可以跳过。</strong>'
        '没有 key 时对应功能会降级或用手动方式。</p>'
    )

    sections = []
    for legend, keys, collapsed in KEY_GROUPS:
        fs = _key_fieldset(legend, keys)
        if collapsed:
            sections.append(
                f'<details class="wz-collapsed"><summary>{H.esc(legend)} '
                f'· 点开配置</summary>{fs}</details>'
            )
        else:
            sections.append(fs)

    actions = (
        '<div class="wz-actions">'
        '<button class="wz-btn" onclick="wzGo(\'/step/2\')">← 上一步</button>'
        '<div class="spacer"></div>'
        '<button class="wz-btn primary" onclick="wzGo(\'/step/4\')">下一步 →</button>'
        '</div>'
    )

    body = head + intro + (
        '<div class="wz-form">' + "".join(sections) + actions + '</div>'
    )
    body += """
<script>
async function wzSaveKey(key) {
  const inp = document.getElementById('in-' + key);
  const st = document.getElementById('st-' + key);
  const value = (inp.value || '').trim();
  if (!value) {
    st.className = 'wz-status err'; st.textContent = '请先粘贴凭据值'; return;
  }
  st.className = 'wz-status'; st.textContent = '验证并保存中…';
  try {
    const res = await wzPost('/api/save-key', {
      key: key, value: value, provider: inp.dataset.provider,
    });
    if (res.ok && res.verified) {
      st.className = 'wz-status ok';
      st.textContent = '已配置 ✓ · ' + res.fingerprint +
        (res.message ? ' · ' + res.message : '');
      inp.value = '';
    } else if (res.ok) {
      st.className = 'wz-status warn';
      st.textContent = '已保存 ⚠ · ' + (res.fingerprint || '') +
        (res.message ? ' · ' + res.message : '');
      inp.value = '';
    } else {
      st.className = 'wz-status err';
      st.textContent = res.message || res.error || '保存失败';
    }
  } catch (e) {
    st.className = 'wz-status err';
    st.textContent = '本地错误：' + e.message;
  }
}
</script>
"""
    return _wz_page("工具集成", 3, body)


# =============================================================================
# Step 4 · Done
# =============================================================================
def _status_counts() -> dict:
    stores = load_stores()
    secrets = secret_form.list_secrets()
    keys_configured = sum(1 for v in secrets.values() if not v.get("missing"))
    for k in CLOUDFLARE_KEYS:
        if secret_form.has_secret(k):
            keys_configured += 1
    return {
        "stores": len(stores),
        "keys_configured": keys_configured,
        "soul_exists": _soul_path().exists(),
    }


def render_step4() -> str:
    counts = _status_counts()
    head = H.page_head("✓ 设置完成", "Lumicc 已经可以用了")

    recap = (
        '<p class="wz-done-recap">'
        f'已配置 <strong>{counts["stores"]}</strong> 家店 · '
        f'<strong>{counts["keys_configured"]}</strong> 个 API key · '
        f'SOUL.md {"已创建" if counts["soul_exists"] else "尚未创建"}。'
        '<br>所有数据都在你本机 <code>~/.commerce-os/</code>，凭据从不进对话。'
        '</p>'
    )

    home_html = _root() / "home.html"
    dashboard = _root() / "dashboard" / "index.html"
    links = (
        '<div class="wz-links">'
        f'<a class="primary" href="file://{H.esc(str(home_html))}">打开控制台</a>'
        f'<a href="file://{H.esc(str(dashboard))}">查看完整仪表盘</a>'
        '</div>'
    )

    note = (
        '<p class="wz-note">随时可以重新打开这个向导：<code>lumicc config</code>'
        '（这行可以显示，因为这是给会用 CLI 的人看的兜底）。</p>'
    )

    actions = (
        '<div class="wz-actions">'
        '<button class="wz-btn" onclick="wzGo(\'/step/3\')">← 上一步</button>'
        '<div class="spacer"></div>'
        '<button class="wz-btn primary" id="wz-finish"'
        ' onclick="wzFinish()">完成 · 关闭向导</button>'
        '</div>'
    )

    body = head + recap + H.section("下一步", links + note) + actions
    body += """
<script>
async function wzFinish() {
  const btn = document.getElementById('wz-finish');
  btn.disabled = true; btn.textContent = '正在关闭…';
  try { await wzPost('/api/shutdown', {}); } catch (e) {}
  document.body.innerHTML =
    '<div style="max-width:600px;margin:80px auto;font-family:sans-serif;' +
    'text-align:center;color:#888"><h2>✓ 配置向导已关闭</h2>' +
    '<p>可以关掉这个标签页了。回到终端继续。</p></div>';
}
// also let users finish by just closing — schedule a soft shutdown ping
window.addEventListener('beforeunload', () => {
  navigator.sendBeacon && navigator.sendBeacon('/api/shutdown');
});
</script>
"""
    return _wz_page("完成", 4, body)


# =============================================================================
# HTTP server
# =============================================================================
class _WizardHandler(BaseHTTPRequestHandler):
    server_version = "LumiccWizard/" + VERSION

    def log_message(self, *args) -> None:  # silence default logging
        pass

    def _send_html(self, html: str, status: int = 200) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj: dict, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._redirect("/step/1")
            return
        renderers = {
            "/step/1": render_step1,
            "/step/2": render_step2,
            "/step/3": render_step3,
            "/step/4": render_step4,
        }
        if path in renderers:
            self._send_html(renderers[path]())
            return
        self._send_html("<h1>404</h1>", 404)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/api/store":
            self._handle_store()
        elif path == "/api/save-key":
            self._handle_save_key()
        elif path == "/api/shutdown":
            self._send_json({"ok": True})
            self.server.schedule_shutdown()
        else:
            self._send_json({"ok": False, "error": "未知接口"}, 404)

    def _handle_store(self) -> None:
        body = self._read_json()
        required = ("platform", "market", "niche", "stage")
        missing = [k for k in required if not body.get(k)]
        if missing:
            self._send_json({"ok": False,
                             "error": f"缺少字段: {', '.join(missing)}"}, 400)
            return
        try:
            result = create_store(
                platform=str(body["platform"]), market=str(body["market"]),
                niche=str(body["niche"]), stage=str(body["stage"]),
                name=(body.get("name") or None),
            )
            self._send_json({"ok": True, "store_id": result["store_id"],
                             "name": result["name"]})
        except SystemExit as e:
            self._send_json({"ok": False, "error": str(e)}, 500)
        except Exception as e:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_save_key(self) -> None:
        body = self._read_json()
        key = str(body.get("key") or "").strip()
        value = str(body.get("value") or "")
        provider = str(body.get("provider") or "custom")
        if not key:
            self._send_json({"ok": False, "error": "缺少 key"}, 400)
            return
        verdict = verify_token(key, value)
        if not verdict.get("ok"):
            # format check hard-failed → don't save
            self._send_json({"ok": False, "verified": False,
                             "code": verdict.get("code"),
                             "message": verdict.get("message")})
            return
        saved = _save_key(key, value, provider)
        if not saved.get("ok"):
            self._send_json({"ok": False, "error": saved.get("error")})
            return
        self._send_json({
            "ok": True,
            "verified": bool(verdict.get("verified")),
            "fingerprint": saved["fingerprint"],
            "code": verdict.get("code"),
            "message": verdict.get("message"),
        })


class _WizardServer(ThreadingHTTPServer):
    daemon_threads = True

    def schedule_shutdown(self, delay: float = 1.5) -> None:
        threading.Thread(target=self._delayed_shutdown, args=(delay,),
                         daemon=True).start()

    def _delayed_shutdown(self, delay: float) -> None:
        time.sleep(delay)
        self.shutdown()


def _find_port() -> tuple[int, _WizardServer]:
    """Bind 127.0.0.1 on the first free port in PORTS. Returns (port, server)."""
    last_err: OSError | None = None
    for port in PORTS:
        try:
            server = _WizardServer(("127.0.0.1", port), _WizardHandler)
            return port, server
        except OSError as e:
            last_err = e
            continue
    raise SystemExit(
        f"无法在 {PORTS[0]}–{PORTS[-1]} 任何端口启动 —— "
        f"是否已有向导在运行？({last_err})"
    )


def run_server(open_browser: bool = True,
               forced_port: int | None = None) -> int:
    if forced_port is not None:
        try:
            server = _WizardServer(("127.0.0.1", forced_port), _WizardHandler)
            port = forced_port
        except OSError as e:
            raise SystemExit(f"端口 {forced_port} 无法绑定：{e}")
    else:
        port, server = _find_port()

    url = f"http://127.0.0.1:{port}/"
    print(f"✓ Lumicc 配置向导已启动")
    print(f"  {url}")
    print(f"  完成第 4 步或 Ctrl-C 退出")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✓ 向导已中断")
    finally:
        server.server_close()
    print("✓ 向导服务器已关闭")
    return 0


# =============================================================================
# Main
# =============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-open", action="store_true",
                    help="启动服务器但不开浏览器")
    ap.add_argument("--port", type=int, default=None, help="强制使用某个端口")
    ap.add_argument("--quiet-stdout", action="store_true",
                    help="不启动服务器，打印 JSON 状态")
    ap.add_argument("--status", action="store_true",
                    help="打印人类可读状态，不启动服务器")
    ap.add_argument("--create-store", action="store_true",
                    help="headless 创建店铺")
    ap.add_argument("--platform", default=None)
    ap.add_argument("--market", default=None)
    ap.add_argument("--niche", default=None)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--url", default=None)
    args = ap.parse_args()

    # --- headless create-store ---
    if args.create_store:
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

    # --- quiet status JSON ---
    if args.quiet_stdout:
        counts = _status_counts()
        print(json.dumps({"skill": "lumicc-config", "status": "success",
                          **counts}, ensure_ascii=False))
        return 0

    # --- human-readable status ---
    if args.status:
        counts = _status_counts()
        print("Lumicc 配置状态")
        print(f"  店铺数         : {counts['stores']}")
        print(f"  已配置 API key : {counts['keys_configured']}")
        print(f"  SOUL.md        : {'已创建' if counts['soul_exists'] else '未创建'}")
        print(f"  数据目录       : {_root()}")
        return 0

    # --- default: start the wizard server ---
    return run_server(open_browser=not args.no_open, forced_port=args.port)


if __name__ == "__main__":
    sys.exit(main())
