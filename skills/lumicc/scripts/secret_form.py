"""Lumicc secret form system. Credentials never enter the LLM conversation:
agent generates a local HTML form, browser writes the value to a 0600 file via
showSaveFilePicker (or downloads + manual move). Public API: SECRETS_DIR,
read_secret, has_secret, secret_fingerprint, list_secrets, render_form,
delete_secret."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

try:
    import html_lib as H  # type: ignore
except ImportError:  # pragma: no cover - flexible import
    sys.path.insert(0, str(Path(__file__).parent))
    import html_lib as H  # type: ignore

esc = H.esc


# Provider catalog. Each row: (key, provider, prefix_hint, label, where_to_get, docs)
_PROVIDER_ROWS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("SHOPIFY_ADMIN_TOKEN", "shopify", "shpat_",
     "Shopify Admin API Token",
     "Shopify Admin → Apps → Develop apps → Create app → Admin API access token",
     "https://shopify.dev/docs/apps/auth/admin-app-access-tokens"),
    ("AMAZON_SP_API_REFRESH", "amazon", "Atzr|",
     "Amazon SP-API Refresh Token",
     "Seller Central → Apps and Services → Develop Apps → Authorize",
     "https://developer-docs.amazon.com/sp-api/docs/authorizing-selling-partner-api-applications"),
    ("TIKTOK_SHOP_API", "tiktok", "",
     "TikTok Shop API Key",
     "TikTok Shop Partner Center → My Apps → App Detail → App Key/Secret",
     "https://partner.tiktokshop.com/docv2/page/64f199709b69b302be5cb52f"),
    ("ETSY_API_KEY", "etsy", "",
     "Etsy API Key",
     "Etsy Developers → Your Apps → Keystring",
     "https://developers.etsy.com/documentation/essentials/authentication"),
    ("KLAVIYO_API_KEY", "klaviyo", "pk_",
     "Klaviyo Private API Key",
     "Klaviyo → Account → Settings → API Keys → Create Private API Key",
     "https://developers.klaviyo.com/en/docs/retrieve_api_credentials"),
    ("ANTHROPIC_API_KEY", "anthropic", "sk-ant-",
     "Anthropic API Key",
     "console.anthropic.com → Settings → API Keys",
     "https://docs.anthropic.com"),
    ("OPENAI_API_KEY", "openai", "sk-",
     "OpenAI API Key",
     "platform.openai.com → API keys → Create new secret key",
     "https://platform.openai.com/docs/api-reference/authentication"),
    ("NANO_BANANA_API_KEY", "nano-banana", "",
     "Nano Banana (image gen) API Key",
     "Nano Banana 控制台 → API → Create Key", ""),
    ("GPT_IMAGE_2_API_KEY", "gpt-image-2", "",
     "GPT Image 2 API Key",
     "GPT Image 2 控制台 → Tokens", ""),
)
PROVIDERS: dict[str, dict[str, str]] = {
    k: {"provider": p, "prefix_hint": ph, "label": lbl, "where_to_get": w, "docs": d}
    for (k, p, ph, lbl, w, d) in _PROVIDER_ROWS
}


def _data_root() -> Path:
    override = os.environ.get("LUMICC_DATA_ROOT")
    if override:
        return Path(override)
    return Path.home() / ".commerce-os"


def _secrets_dir() -> Path:
    d = _data_root() / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


SECRETS_DIR: Path = _secrets_dir()


def _secret_path(key: str) -> Path:
    return _secrets_dir() / f"{key}.json"


def _fingerprint(value: str) -> str:
    v = value.strip()
    if len(v) <= 6:
        return "***"
    return f"{v[:2]}***{v[-4:]}"


def has_secret(key: str) -> bool:
    return _secret_path(key).exists()


def read_secret(key: str) -> str | None:
    p = _secret_path(key)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    val = data.get("value")
    return val if isinstance(val, str) else None


def secret_fingerprint(key: str) -> str | None:
    val = read_secret(key)
    if val is None:
        return None
    return _fingerprint(val)


def list_secrets() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, meta in PROVIDERS.items():
        p = _secret_path(key)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            out[key] = {
                "provider": meta["provider"],
                "label": meta["label"],
                "stored_at": data.get("stored_at"),
                "fingerprint": data.get("fingerprint")
                or (_fingerprint(data["value"]) if isinstance(data.get("value"), str) else None),
                "missing": False,
            }
        else:
            out[key] = {
                "provider": meta["provider"],
                "label": meta["label"],
                "stored_at": None,
                "fingerprint": None,
                "missing": True,
            }
    return out


def delete_secret(key: str) -> bool:
    p = _secret_path(key)
    if p.exists():
        p.unlink()
        return True
    return False


def _form_body(key: str, meta: dict[str, str]) -> str:
    label = meta.get("label", key)
    where = meta.get("where_to_get", "")
    docs = meta.get("docs", "")
    prefix_hint = meta.get("prefix_hint", "")
    provider = meta.get("provider", "unknown")
    secrets_dir = str(_secrets_dir())

    banner = H.card(
        title="🔒 凭据安全说明",
        tag="SECURITY",
        tag_color="rose",
        body=(
            "<p><strong>凭据从不进入 LLM 对话历史。</strong></p>"
            f"<p>提交后只写到本机文件 <code>{esc(secrets_dir)}/{esc(key)}.json</code>，"
            "权限 <code>0600</code>。所有处理都在你的浏览器里完成，"
            "页面没有任何网络请求 (CSP <code>connect-src 'none'</code>)。</p>"
        ),
    )

    where_html = ""
    if where or docs:
        body_parts = []
        if where:
            body_parts.append(f"<p>{esc(where)}</p>")
        if docs:
            body_parts.append(
                f'<p><a href="{esc(docs)}" target="_blank" rel="noopener">{esc(docs)}</a></p>'
            )
        where_html = H.collapsible("📖 在哪里拿到这个 Key？", "".join(body_parts), open_=False)

    hint_html = (
        f'<p class="form-hint">预期前缀：<code>{esc(prefix_hint)}</code></p>'
        if prefix_hint else ""
    )

    form_card = H.card(
        title=f"{label}",
        tag=key,
        tag_color="emerald",
        body=f"""
<div class="secret-form" data-key="{esc(key)}" data-provider="{esc(provider)}"
     data-prefix="{esc(prefix_hint)}" data-secrets-dir="{esc(secrets_dir)}">
  <label class="form-label" for="secret-value">凭据值</label>
  <input id="secret-value" class="form-input" type="password"
         autocomplete="off" autocapitalize="off" autocorrect="off"
         spellcheck="false" placeholder="在这里粘贴你的 {esc(label)}" />
  {hint_html}
  <div class="form-actions">
    <button type="button" id="btn-save" class="btn btn-primary">保存到本地</button>
    <button type="button" id="btn-clear" class="btn">清空</button>
  </div>
  <div id="status" class="form-status" role="status" aria-live="polite"></div>
  <div id="fallback" class="form-fallback" hidden>
    <p>浏览器不支持直接写文件。已下载到 <code>~/Downloads/</code>。请在终端运行：</p>
    <pre id="mv-cmd" class="form-cmd"></pre>
    <button type="button" id="btn-copy-cmd" class="btn">复制移动命令</button>
  </div>
</div>
"""
    )

    script = _form_script(key, prefix_hint, provider)

    return banner + (where_html or "") + form_card + script


_FORM_CSS = """<style>
.form-label{display:block;margin:0 0 6px;font-weight:600;font-size:13px}
.form-input{width:100%;box-sizing:border-box;padding:12px 14px;border-radius:10px;border:1px solid var(--border);background:var(--surface-2);color:var(--text);font-family:ui-monospace,Menlo,monospace;font-size:14px}
.form-input:focus{outline:2px solid var(--accent);outline-offset:1px}
.form-hint{margin:8px 0 0;font-size:12px;color:var(--muted)}
.form-actions{display:flex;gap:8px;margin-top:14px}
.form-status{margin-top:12px;font-size:13px}
.form-status.success{color:var(--ok,#22c55e);font-weight:600}
.form-status.error{color:var(--danger,#f43f5e)}
.form-fallback{margin-top:14px;padding:12px;border:1px dashed var(--border);border-radius:10px;background:var(--surface-2)}
.form-cmd{padding:10px;background:#0a0a0a;color:#e7e7e7;border-radius:8px;overflow-x:auto;font-size:12px;white-space:pre-wrap;word-break:break-all}
</style>"""

_FORM_JS_TEMPLATE = """<script>
(function(){
  const KEY=__KEY__, PROVIDER=__PROVIDER__, PREFIX=__PREFIX__;
  const root=document.querySelector('.secret-form');
  const dir=root.dataset.secretsDir;
  const $val=document.getElementById('secret-value');
  const $save=document.getElementById('btn-save');
  const $clear=document.getElementById('btn-clear');
  const $status=document.getElementById('status');
  const $fb=document.getElementById('fallback');
  const $cmd=document.getElementById('mv-cmd');
  const $copy=document.getElementById('btn-copy-cmd');
  const fp=v=>v.length<=6?'***':v.slice(0,2)+'***'+v.slice(-4);
  const setStatus=(m,c)=>{$status.textContent=m;$status.className='form-status '+(c||'');};
  $clear.addEventListener('click',()=>{$val.value='';setStatus('');$fb.hidden=true;$val.focus();});
  $save.addEventListener('click',async()=>{
    const v=($val.value||'').trim();
    if(!v){setStatus('请输入凭据值。','error');return;}
    if(PREFIX&&!v.startsWith(PREFIX)){if(!confirm('值不以预期前缀 "'+PREFIX+'" 开头。仍然保存？'))return;}
    const payload={key:KEY,provider:PROVIDER,value:v,stored_at:Math.floor(Date.now()/1000),fingerprint:fp(v)};
    const data=JSON.stringify(payload,null,2);
    const filename=KEY+'.json';
    if(window.showSaveFilePicker){
      try{
        const h=await window.showSaveFilePicker({suggestedName:filename,startIn:'home',
          types:[{description:'Secret JSON',accept:{'application/json':['.json']}}]});
        const w=await h.createWritable();await w.write(new Blob([data],{type:'application/json'}));await w.close();
        $val.value='';$fb.hidden=true;setStatus('✓ 已保存。可以关掉这个标签页了。','success');return;
      }catch(e){if(e&&e.name==='AbortError'){setStatus('已取消。','error');return;}}
    }
    const url=URL.createObjectURL(new Blob([data],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=filename;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $cmd.textContent='mkdir -p '+dir+' && chmod 700 '+dir+' && mv ~/Downloads/'+filename+' '+dir+'/ && chmod 600 '+dir+'/'+filename;
    $fb.hidden=false;$val.value='';
    setStatus('✓ 已下载到 Downloads。请按下面命令移动并设置权限。','success');
  });
  $copy.addEventListener('click',async()=>{
    try{await navigator.clipboard.writeText($cmd.textContent);setStatus('✓ 已复制移动命令。','success');}
    catch(e){setStatus('复制失败，请手动选择。','error');}
  });
})();
</script>"""


def _form_script(key: str, prefix_hint: str, provider: str) -> str:
    js = (_FORM_JS_TEMPLATE
          .replace("__KEY__", json.dumps(key))
          .replace("__PROVIDER__", json.dumps(provider))
          .replace("__PREFIX__", json.dumps(prefix_hint)))
    return _FORM_CSS + js


def render_form(
    key: str,
    session_id: str | None = None,
    open_browser: bool = False,
) -> Path:
    if key not in PROVIDERS:
        # Allow unknown keys but with a minimal stub.
        meta = {"label": key, "provider": "custom", "prefix_hint": "", "where_to_get": "", "docs": ""}
    else:
        meta = PROVIDERS[key]

    body = _form_body(key, meta)
    html = H.page(
        title=f"配置 {meta['label']}",
        body=H.page_head(f"配置 {meta['label']}", subtitle=f"KEY: {key}") + body,
        back_link=None,
        right_meta="安全表单",
    )
    # Add CSP meta. html_lib doesn't expose head injection, so post-process.
    csp = (
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'self' 'unsafe-inline'; "
        "connect-src 'none'; form-action 'none'; base-uri 'none';\">"
    )
    html = html.replace("<head>", "<head>\n" + csp, 1)

    if session_id:
        out_dir = _data_root() / "sessions" / session_id
    else:
        out_dir = _data_root() / "secrets" / "_pending"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"secret-form-{key}.html"
    out_path.write_text(html, encoding="utf-8")
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass

    if open_browser:
        webbrowser.open(out_path.as_uri())

    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lumicc secret form system")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--generate", metavar="KEY", help="Generate HTML form for KEY")
    g.add_argument("--list", action="store_true", help="List all known providers")
    g.add_argument("--read", metavar="KEY", help="Read fingerprint (or value with --reveal)")
    g.add_argument("--delete", metavar="KEY", help="Delete secret file")
    p.add_argument("--session", metavar="ID", help="Session id for output path")
    p.add_argument("--open", action="store_true", help="Open form in browser")
    p.add_argument("--reveal", action="store_true", help="Print raw value to stdout")
    args = p.parse_args(argv)

    if args.generate:
        print(str(render_form(args.generate, session_id=args.session, open_browser=args.open)))
        return 0
    if args.list:
        print(json.dumps(list_secrets(), indent=2, ensure_ascii=False))
        return 0
    if args.read:
        if not has_secret(args.read):
            print(json.dumps({"key": args.read, "missing": True}))
            return 1
        if args.reveal:
            v = read_secret(args.read)
            if v is None:
                return 1
            sys.stdout.write(v)
            return 0
        print(json.dumps({"key": args.read, "fingerprint": secret_fingerprint(args.read)}))
        return 0
    if args.delete:
        ok = delete_secret(args.delete)
        print(json.dumps({"key": args.delete, "deleted": ok}))
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
