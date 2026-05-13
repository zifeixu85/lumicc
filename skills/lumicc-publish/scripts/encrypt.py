#!/usr/bin/env python3
"""AES-GCM 256 encryption for client-side decryption via WebCrypto.

Python side: requires `cryptography` package (only required if user encrypts;
public deploys work on stdlib alone). Key derivation via stdlib `hashlib.pbkdf2_hmac`.

Browser side: pure WebCrypto SubtleCrypto API — no JS deps.

Public API:
    encrypt(plaintext: bytes, password: str) -> dict
    wrapper_html(bundle: dict, title: str) -> str
    available() -> bool   # check cryptography is importable
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

PBKDF2_ITERATIONS = 600_000
KEY_LEN = 32  # 256-bit
SALT_LEN = 16
IV_LEN = 12  # AES-GCM standard


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                PBKDF2_ITERATIONS, dklen=KEY_LEN)


def encrypt(plaintext: bytes, password: str) -> dict[str, Any]:
    """Return ciphertext bundle. Raises ImportError if cryptography missing."""
    if not available():
        raise ImportError(
            "encryption requires the 'cryptography' package. Install via:\n"
            "    pip install cryptography\n"
            "Or use --public to deploy without encryption."
        )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(SALT_LEN)
    iv = os.urandom(IV_LEN)
    key = derive_key(password, salt)
    aes = AESGCM(key)
    ct = aes.encrypt(iv, plaintext, associated_data=None)
    return {
        "alg": "AES-GCM-256",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": _b64(salt),
        "iv": _b64(iv),
        "ct": _b64(ct),
    }


_WRAPPER_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>__TITLE__</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:#0a0a0c;color:#e7e7e7;min-height:100vh;display:grid;place-items:center;padding:24px}
.gate{max-width:420px;width:100%;background:#15151a;border:1px solid #26262d;
  border-radius:16px;padding:32px;box-shadow:0 30px 80px -20px rgba(0,0,0,0.6)}
h1{margin:0 0 8px;font-size:22px;font-weight:700;letter-spacing:-0.01em}
p.sub{margin:0 0 24px;color:#999;font-size:13px}
label{display:block;margin:0 0 8px;font-size:13px;font-weight:600}
input{width:100%;padding:14px 16px;border-radius:10px;border:1px solid #2a2a32;
  background:#0d0d10;color:#e7e7e7;font-size:15px;font-family:inherit}
input:focus{outline:2px solid #34d399;outline-offset:1px}
button{margin-top:16px;width:100%;padding:14px;border-radius:10px;border:0;
  background:#34d399;color:#0a0a0c;font-size:15px;font-weight:700;cursor:pointer}
button:disabled{opacity:0.5;cursor:wait}
.err{margin-top:14px;padding:10px 12px;border-radius:8px;background:#3a1818;
  color:#fca5a5;font-size:13px;display:none}
.err.show{display:block}
.foot{margin-top:24px;padding-top:16px;border-top:1px solid #26262d;
  color:#666;font-size:11px;text-align:center;line-height:1.6}
</style>
</head>
<body>
<main class="gate" id="gate">
  <h1>🔒 受保护的报告</h1>
  <p class="sub">这份报告已用 AES-GCM 256 加密。请输入密码解锁。
  解密在你的浏览器内完成，Cloudflare 看不到内容。</p>
  <label for="pw">密码</label>
  <input id="pw" type="password" autocomplete="off" placeholder="输入密码后按 Enter" />
  <button id="go">解锁</button>
  <div class="err" id="err"></div>
  <div class="foot">
    AES-GCM · PBKDF2-SHA256 · 600,000 iterations<br>
    Powered by Lumicc · Cross-Border Commerce OS
  </div>
</main>
<script id="bundle" type="application/json">__BUNDLE__</script>
<script>
(function(){
  const b = JSON.parse(document.getElementById('bundle').textContent);
  const $pw = document.getElementById('pw');
  const $go = document.getElementById('go');
  const $err = document.getElementById('err');
  const $gate = document.getElementById('gate');
  const b64d = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
  const showErr = m => { $err.textContent = m; $err.classList.add('show'); $go.disabled = false; };
  async function unlock(){
    $err.classList.remove('show'); $go.disabled = true;
    const pw = $pw.value || '';
    if(!pw){ showErr('请输入密码。'); return; }
    try {
      const salt = b64d(b.salt), iv = b64d(b.iv), ct = b64d(b.ct);
      const keyMat = await crypto.subtle.importKey('raw', new TextEncoder().encode(pw),
        {name:'PBKDF2'}, false, ['deriveKey']);
      const key = await crypto.subtle.deriveKey(
        {name:'PBKDF2', salt, iterations:b.iterations, hash:'SHA-256'},
        keyMat, {name:'AES-GCM', length:256}, false, ['decrypt']);
      const pt = await crypto.subtle.decrypt({name:'AES-GCM', iv}, key, ct);
      const html = new TextDecoder().decode(pt);
      // Replace document with decrypted HTML.
      document.open(); document.write(html); document.close();
    } catch(e){ showErr('密码错误或数据损坏。'); }
  }
  $go.addEventListener('click', unlock);
  $pw.addEventListener('keydown', e => { if(e.key === 'Enter') unlock(); });
  $pw.focus();
})();
</script>
</body>
</html>
"""


def wrapper_html(bundle: dict[str, Any], title: str = "受保护的报告") -> str:
    """Build a self-contained HTML wrapper around an encrypted bundle.

    Security: title is HTML-escaped before injection so a merchant-controlled
    store name like '</title><script>...' cannot break out of the title element.
    The bundle JSON is injected into a <script type="application/json"> element
    (renders as inert data, not executed) — see code-review v1.0 HIGH#4.
    """
    import html as _html
    safe_title = _html.escape(title, quote=True)
    # Replace </script and </ within the bundle JSON to prevent script-tag
    # breakout if a future template variant uses type="text/javascript".
    bundle_json = json.dumps(bundle, ensure_ascii=False).replace("</", "<\\/")
    return (_WRAPPER_TEMPLATE
            .replace("__TITLE__", safe_title)
            .replace("__BUNDLE__", bundle_json))


if __name__ == "__main__":
    import sys
    if not available():
        print("cryptography not installed", file=sys.stderr)
        sys.exit(1)
    print("cryptography OK; iterations =", PBKDF2_ITERATIONS)
