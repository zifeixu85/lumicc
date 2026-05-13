#!/usr/bin/env python3
"""Status / list reports for lumicc-publish. Uses lumicc html_lib (H.page)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(LUMICC_SCRIPTS))

try:
    import html_lib as H  # type: ignore
except ImportError:  # pragma: no cover
    H = None  # type: ignore


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def render_share_status(share: dict) -> str:
    """Render a single share row as a status HTML page."""
    if H is None:
        return _fallback_status(share)
    rows = [
        ["share_id", H.esc(share.get("share_id", ""))],
        ["URL", f'<a href="{H.esc(share.get("cloudflare_url", ""))}" target="_blank">'
                f'{H.esc(share.get("cloudflare_url", ""))}</a>'],
        ["加密", "✅ AES-GCM 256" if share.get("encrypted") else "🌐 公开"],
        ["password fingerprint", H.esc(share.get("password_fingerprint") or "—")],
        ["created", _fmt_ts(share.get("created_at"))],
        ["expires", _fmt_ts(share.get("expires_at"))],
        ["revoked", "✓" if share.get("revoked") else "—"],
        ["view count", str(share.get("view_count", 0))],
    ]
    table = H.table(["字段", "值"], rows, align=["left", "left"])
    body = H.page_head("Share 状态", subtitle=share.get("share_id", "")) + \
        H.section(title="详情", body=table)
    return H.page(title="Share 状态", body=body, back_link=None, right_meta="lumicc-publish")


def render_list(shares: list[dict]) -> str:
    if H is None:
        return _fallback_list(shares)
    if not shares:
        body = H.page_head("Shares", subtitle="0 条记录") + \
            H.section(title="", body="<p class='muted'>暂无 share 记录。</p>")
        return H.page(title="Shares", body=body, back_link=None, right_meta="lumicc-publish")
    rows = []
    for s in shares:
        rows.append([
            H.esc(s.get("share_id", "")[:8] + "…"),
            f'<a href="{H.esc(s.get("cloudflare_url", ""))}" target="_blank">URL</a>',
            "🔒" if s.get("encrypted") else "🌐",
            _fmt_ts(s.get("created_at")),
            _fmt_ts(s.get("expires_at")),
            "✓" if s.get("revoked") else "—",
        ])
    table = H.table(
        ["share", "url", "enc", "created", "expires", "revoked"],
        rows,
        align=["left", "left", "center", "left", "left", "center"],
    )
    body = H.page_head("Shares", subtitle=f"{len(shares)} 条记录") + \
        H.section(title="所有 share", body=table)
    return H.page(title="Shares", body=body, back_link=None, right_meta="lumicc-publish")


def _fallback_status(share: dict) -> str:
    return f"<html><body><pre>{share}</pre></body></html>"


def _fallback_list(shares: list[dict]) -> str:
    return f"<html><body><pre>{shares}</pre></body></html>"
