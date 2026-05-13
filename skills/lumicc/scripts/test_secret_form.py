"""Tests for secret_form.py.

Uses LUMICC_DATA_ROOT to redirect filesystem ops to a tempdir.
Run: python3 test_secret_form.py
"""

from __future__ import annotations

import importlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import traceback
from pathlib import Path


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def _fresh_module(data_root: Path):
    """Reload secret_form so module-level SECRETS_DIR picks up env override."""
    os.environ["LUMICC_DATA_ROOT"] = str(data_root)
    if "secret_form" in sys.modules:
        del sys.modules["secret_form"]
    return importlib.import_module("secret_form")


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_render_form_writes_html_with_security_properties(tmp: Path):
    sf = _fresh_module(tmp)
    path = sf.render_form("SHOPIFY_ADMIN_TOKEN", session_id="sess-abc")
    assert path.exists(), "form HTML file must exist"
    assert path.is_file()
    html = path.read_text(encoding="utf-8")

    # Security banner content
    assert "凭据" in html and "0600" in html, "must show security banner with 0600 perms text"

    # Password-type input
    assert re.search(r'<input[^>]*type="password"', html), "must use type=password input"

    # CSP meta tag with connect-src 'none'
    assert "Content-Security-Policy" in html
    assert "connect-src 'none'" in html, "CSP must block network connections"

    # No remote fetch/xhr to URLs (only allow window.showSaveFilePicker etc.)
    # The HTML should NOT contain fetch( calls to http(s) endpoints.
    # We check there are no occurrences of fetch( or XMLHttpRequest in the page.
    assert "XMLHttpRequest" not in html, "no XHR allowed"
    assert "fetch(" not in html, "no fetch() allowed"
    # Also no form action attribute pointing anywhere
    assert not re.search(r'<form[^>]*action=', html), "no form action allowed"


def test_render_form_session_path_vs_pending(tmp: Path):
    sf = _fresh_module(tmp)
    p1 = sf.render_form("ANTHROPIC_API_KEY", session_id="sess-1")
    assert "sessions/sess-1" in str(p1)
    p2 = sf.render_form("ANTHROPIC_API_KEY", session_id=None)
    assert "_pending" in str(p2)


def test_read_secret_round_trip(tmp: Path):
    sf = _fresh_module(tmp)
    # Manually write a "saved" secret file as the JS would.
    secrets_dir = tmp / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "key": "SHOPIFY_ADMIN_TOKEN",
        "provider": "shopify",
        "value": "shpat_abcdef123456",
        "stored_at": int(time.time()),
        "fingerprint": "sh***3456",
    }
    fpath = secrets_dir / "SHOPIFY_ADMIN_TOKEN.json"
    fpath.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(fpath, 0o600)

    assert sf.has_secret("SHOPIFY_ADMIN_TOKEN") is True
    assert sf.read_secret("SHOPIFY_ADMIN_TOKEN") == "shpat_abcdef123456"
    fp = sf.secret_fingerprint("SHOPIFY_ADMIN_TOKEN")
    assert fp == "sh***3456", f"expected 'sh***3456', got {fp!r}"


def test_read_secret_missing(tmp: Path):
    sf = _fresh_module(tmp)
    assert sf.has_secret("OPENAI_API_KEY") is False
    assert sf.read_secret("OPENAI_API_KEY") is None
    assert sf.secret_fingerprint("OPENAI_API_KEY") is None


def test_list_secrets_includes_all_providers(tmp: Path):
    sf = _fresh_module(tmp)
    listing = sf.list_secrets()
    # Every PROVIDERS entry shows up
    for key in sf.PROVIDERS:
        assert key in listing, f"{key} missing from list_secrets()"
        assert listing[key]["missing"] is True
        # Never reveal value field
        assert "value" not in listing[key]

    # Add one and re-check
    secrets_dir = tmp / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ETSY_API_KEY.json").write_text(json.dumps({
        "key": "ETSY_API_KEY", "provider": "etsy",
        "value": "abXXXXyzwq", "stored_at": 123, "fingerprint": "ab***zwq",
    }), encoding="utf-8")
    listing2 = sf.list_secrets()
    assert listing2["ETSY_API_KEY"]["missing"] is False
    assert listing2["ETSY_API_KEY"]["fingerprint"] == "ab***zwq"
    assert "value" not in listing2["ETSY_API_KEY"]


def test_delete_secret(tmp: Path):
    sf = _fresh_module(tmp)
    secrets_dir = tmp / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    f = secrets_dir / "KLAVIYO_API_KEY.json"
    f.write_text("{\"value\":\"pk_test\"}", encoding="utf-8")
    assert sf.delete_secret("KLAVIYO_API_KEY") is True
    assert not f.exists()
    # Second delete is False
    assert sf.delete_secret("KLAVIYO_API_KEY") is False


def test_file_permissions_after_render(tmp: Path):
    if os.name == "nt":
        return  # skip on Windows
    sf = _fresh_module(tmp)
    path = sf.render_form("OPENAI_API_KEY", session_id="perm-test")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"
    # secrets dir perms
    secrets_dir = tmp / "secrets"
    if secrets_dir.exists():
        dmode = stat.S_IMODE(secrets_dir.stat().st_mode)
        assert dmode == 0o700, f"expected 0o700 for secrets dir, got {oct(dmode)}"


def test_fingerprint_short_value(tmp: Path):
    sf = _fresh_module(tmp)
    secrets_dir = tmp / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "ANTHROPIC_API_KEY.json").write_text(
        json.dumps({"value": "abc"}), encoding="utf-8"
    )
    assert sf.secret_fingerprint("ANTHROPIC_API_KEY") == "***"


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

TESTS = [
    test_render_form_writes_html_with_security_properties,
    test_render_form_session_path_vs_pending,
    test_read_secret_round_trip,
    test_read_secret_missing,
    test_list_secrets_includes_all_providers,
    test_delete_secret,
    test_file_permissions_after_render,
    test_fingerprint_short_value,
]


def main() -> int:
    failures = 0
    for fn in TESTS:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try:
                fn(tmp)
                print(f"PASS  {fn.__name__}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {fn.__name__}: {e}")
                traceback.print_exc()
            except Exception as e:
                failures += 1
                print(f"ERROR {fn.__name__}: {e!r}")
                traceback.print_exc()
    print(f"\n{len(TESTS) - failures}/{len(TESTS)} passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
