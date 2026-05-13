#!/usr/bin/env python3
"""Deploy a Lumicc HTML report to Cloudflare Pages with optional AES-GCM gate.

Usage:
    python3 run.py --html report.html --password 8888
    python3 run.py --html report.html --public --subdomain my-store
    python3 run.py --html report.html --password 8888 --expires-days 30
    python3 run.py --list
    python3 run.py --status <share_id>
    python3 run.py --revoke <share_id>
    python3 run.py --html report.html --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUMICC_SCRIPTS = HERE.parent.parent / "lumicc" / "scripts"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(LUMICC_SCRIPTS))

import encrypt as enc_mod  # noqa: E402
import notify as notify_mod  # noqa: E402

try:
    import secret_form as sf  # type: ignore
except ImportError:  # pragma: no cover
    sf = None  # type: ignore


CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"


class MissingSecretError(RuntimeError):
    pass


def data_root() -> Path:
    return Path(os.environ.get("LUMICC_DATA_ROOT") or (Path.home() / ".commerce-os"))


def db_path() -> Path:
    return data_root() / "store.db"


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(p)
    db.row_factory = sqlite3.Row
    return db


def _ensure_table(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            share_id TEXT PRIMARY KEY,
            store_id TEXT,
            source_path TEXT,
            cloudflare_url TEXT,
            encrypted INTEGER NOT NULL DEFAULT 0,
            password_fingerprint TEXT,
            expires_at INTEGER,
            created_at INTEGER NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0,
            view_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT
        )
    """)
    db.commit()


def _password_fingerprint(pw: str) -> str:
    """Non-reversible fingerprint of the password (for display only)."""
    digest = hashlib.sha256(pw.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:8]}"


def _read_secret(key: str) -> str:
    if sf is None:
        raise MissingSecretError(f"secret_form not importable; cannot read {key}.")
    val = sf.read_secret(key) if hasattr(sf, "read_secret") else None
    if not val:
        raise MissingSecretError(
            f"missing {key}. Set via:\n  python3 {LUMICC_SCRIPTS}/secret_form.py "
            f"--generate {key} --open")
    return val


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", s.lower()).strip("-")
    return s[:50] or "lumicc-share"


def _random_project_name() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"lumicc-{suffix}"


def build_bundle(html_bytes: bytes, password: str | None, title: str) -> bytes:
    """Return final HTML bytes to deploy (encrypted wrapper or raw)."""
    if password is None:
        return html_bytes
    bundle = enc_mod.encrypt(html_bytes, password)
    wrapper = enc_mod.wrapper_html(bundle, title=title)
    return wrapper.encode("utf-8")


def _cf_create_project(account_id: str, token: str, project_name: str) -> dict:
    url = f"{CLOUDFLARE_API}/accounts/{account_id}/pages/projects"
    body = json.dumps({
        "name": project_name,
        "production_branch": "main",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _cf_deploy(account_id: str, token: str, project_name: str,
               html_bytes: bytes) -> dict:
    """Deploy via multipart upload to Cloudflare Pages.

    Uses a hand-rolled multipart body (stdlib only).
    """
    url = f"{CLOUDFLARE_API}/accounts/{account_id}/pages/projects/{project_name}/deployments"
    boundary = f"----lumicc{uuid.uuid4().hex}"
    parts: list[bytes] = []
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        b'Content-Disposition: form-data; name="file"; filename="index.html"\r\n'
    )
    parts.append(b"Content-Type: text/html\r\n\r\n")
    parts.append(html_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _deploy_via_wrangler(project_name: str, html_bytes: bytes,
                         workdir: Path) -> dict:
    """If wrangler CLI exists, prefer it (handles edge cases better)."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "index.html").write_bytes(html_bytes)
    cmd = ["wrangler", "pages", "deploy", str(workdir),
           "--project-name", project_name, "--commit-dirty=true"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    url_match = re.search(r"https?://[^\s]+\.pages\.dev", proc.stdout + proc.stderr)
    return {
        "ok": proc.returncode == 0,
        "url": url_match.group(0) if url_match else None,
        "stdout": proc.stdout[-1000:],
        "stderr": proc.stderr[-1000:],
    }


def do_deploy(html_path: Path, password: str | None, subdomain: str | None,
              expires_days: int | None, store_id: str | None,
              dry_run: bool) -> dict:
    started = time.time()
    if not html_path.exists():
        raise FileNotFoundError(f"HTML not found: {html_path}")
    html_bytes = html_path.read_bytes()
    bundle_bytes = build_bundle(html_bytes, password, title=f"Lumicc · {html_path.stem}")

    share_id = str(uuid.uuid4())
    project_name = _slugify(subdomain) if subdomain else _random_project_name()

    if dry_run:
        cloudflare_url = f"https://{project_name}.pages.dev"
        deploy_meta = {"dry_run": True, "size_bytes": len(bundle_bytes)}
    else:
        token = _read_secret("CLOUDFLARE_API_TOKEN")
        account_id = _read_secret("CLOUDFLARE_ACCOUNT_ID")
        if shutil.which("wrangler"):
            tmp = data_root() / "tmp" / share_id
            r = _deploy_via_wrangler(project_name, bundle_bytes, tmp)
            if not r["ok"]:
                raise RuntimeError(f"wrangler deploy failed: {r['stderr']}")
            cloudflare_url = r["url"] or f"https://{project_name}.pages.dev"
            deploy_meta = {"via": "wrangler"}
        else:
            try:
                _cf_create_project(account_id, token, project_name)
            except urllib.error.HTTPError as e:
                # project may already exist — that's fine
                if e.code not in (409,):
                    raise
            dep = _cf_deploy(account_id, token, project_name, bundle_bytes)
            cloudflare_url = (
                dep.get("result", {}).get("url")
                or f"https://{project_name}.pages.dev"
            )
            deploy_meta = {"via": "api", "raw": dep.get("result", {}).get("id")}

    expires_at = (
        int(time.time() + expires_days * 86400) if expires_days else None
    )
    fp = _password_fingerprint(password) if password else None
    encrypted = 1 if password else 0

    db = _connect()
    try:
        _ensure_table(db)
        db.execute(
            "INSERT INTO shares (share_id, store_id, source_path, cloudflare_url, "
            "encrypted, password_fingerprint, expires_at, created_at, revoked, "
            "view_count, metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (share_id, store_id, str(html_path), cloudflare_url, encrypted, fp,
             expires_at, int(time.time()), 0, 0,
             json.dumps({"project_name": project_name, **deploy_meta}, ensure_ascii=False)),
        )
        db.commit()
    finally:
        db.close()

    # SECURITY: never return / log the raw password — caller already knows it
    # (they passed --password). We echo only a fingerprint so logs/agent stdout
    # don't leak the gate credential. See code-review v1.0 HIGH#3.
    pw_fp = None
    if password:
        import hashlib as _hl
        pw_fp = _hl.sha256(password.encode()).hexdigest()[:8]
    return {
        "share_id": share_id,
        "url": cloudflare_url,
        "password_fingerprint": pw_fp,
        "encrypted": bool(encrypted),
        "expires_at": expires_at,
        "duration_sec": round(time.time() - started, 2),
        "dry_run": dry_run,
    }


def do_list() -> list[dict]:
    if not db_path().exists():
        return []
    db = _connect()
    try:
        _ensure_table(db)
        rows = db.execute(
            "SELECT * FROM shares ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def do_status(share_id: str) -> dict | None:
    if not db_path().exists():
        return None
    db = _connect()
    try:
        _ensure_table(db)
        row = db.execute(
            "SELECT * FROM shares WHERE share_id=?", (share_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def do_revoke(share_id: str) -> bool:
    if not db_path().exists():
        return False
    db = _connect()
    try:
        _ensure_table(db)
        cur = db.execute(
            "UPDATE shares SET revoked=1 WHERE share_id=?", (share_id,)
        )
        db.commit()
        return cur.rowcount > 0
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--html", help="Path to source HTML file")
    g.add_argument("--list", action="store_true")
    g.add_argument("--status", metavar="SHARE_ID")
    g.add_argument("--revoke", metavar="SHARE_ID")

    p.add_argument("--password", default=None)
    p.add_argument("--public", action="store_true", help="Deploy without encryption")
    p.add_argument("--subdomain", default=None)
    p.add_argument("--expires-days", type=int, default=None)
    p.add_argument("--store-id", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--notify-channel", default=None)
    p.add_argument("--notify-target", default="")
    p.add_argument("--quiet-stdout", action="store_true")
    args = p.parse_args()

    try:
        if args.list:
            shares = do_list()
            print(json.dumps(shares, ensure_ascii=False, indent=2))
            return 0
        if args.status:
            row = do_status(args.status)
            if row is None:
                print(json.dumps({"share_id": args.status, "missing": True}))
                return 1
            print(json.dumps(row, ensure_ascii=False, indent=2))
            return 0
        if args.revoke:
            ok = do_revoke(args.revoke)
            print(json.dumps({"share_id": args.revoke, "revoked": ok}))
            return 0 if ok else 1
        if not args.html:
            p.print_help()
            return 2

        if args.password and args.public:
            print("error: --password and --public are mutually exclusive", file=sys.stderr)
            return 2
        password = None if args.public else args.password
        if password and not enc_mod.available():
            print(
                "error: encryption requested but 'cryptography' is not installed.\n"
                "  pip install cryptography\n"
                "Or use --public to deploy without encryption.",
                file=sys.stderr,
            )
            return 3

        result = do_deploy(
            html_path=Path(args.html).expanduser(),
            password=password,
            subdomain=args.subdomain,
            expires_days=args.expires_days,
            store_id=args.store_id,
            dry_run=args.dry_run,
        )

        if args.notify_channel:
            body = (f"- URL: {result['url']}\n- 加密: "
                    f"{'✅' if result['encrypted'] else '🌐 公开'}\n"
                    f"- 过期: {result['expires_at'] or '永久'}\n"
                    f"- share_id: {result['share_id']}")
            notify_mod.notify(
                channel=args.notify_channel, target=args.notify_target,
                title=f"📤 报告已上线 · {result['url']}", body_md=body,
                severity="info", skill="lumicc-publish",
            )
        if args.quiet_stdout:
            print(json.dumps({"share_id": result["share_id"], "url": result["url"]},
                             ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except MissingSecretError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
