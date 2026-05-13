#!/usr/bin/env python3
"""Tests for lumicc-publish. Mocks Cloudflare HTTP + wrangler.

Run:
    python3 test_publish.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import encrypt as enc_mod  # noqa: E402
import run as run_mod  # noqa: E402


class PublishTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / ".commerce-os"
        self.root.mkdir(parents=True, exist_ok=True)
        self._env_patch = mock.patch.dict(
            os.environ, {"LUMICC_DATA_ROOT": str(self.root)}
        )
        self._env_patch.start()
        # write a sample html
        self.html = self.root / "report.html"
        self.html.write_text("<html><body><h1>hello</h1></body></html>", encoding="utf-8")

    def tearDown(self) -> None:
        self._env_patch.stop()
        self.tmp.cleanup()

    # -----------------------------------------------------------------
    def test_dry_run_public(self) -> None:
        r = run_mod.do_deploy(
            html_path=self.html, password=None, subdomain="my-test",
            expires_days=None, store_id=None, dry_run=True,
        )
        self.assertTrue(r["url"].endswith(".pages.dev"))
        self.assertFalse(r["encrypted"])
        self.assertTrue(r["dry_run"])

    def test_dry_run_writes_share_row(self) -> None:
        r = run_mod.do_deploy(
            html_path=self.html, password=None, subdomain="t1",
            expires_days=None, store_id=None, dry_run=True,
        )
        shares = run_mod.do_list()
        self.assertEqual(len(shares), 1)
        self.assertEqual(shares[0]["share_id"], r["share_id"])
        # status query
        row = run_mod.do_status(r["share_id"])
        self.assertIsNotNone(row)
        # revoke
        ok = run_mod.do_revoke(r["share_id"])
        self.assertTrue(ok)
        row2 = run_mod.do_status(r["share_id"])
        self.assertEqual(row2["revoked"], 1)

    def test_missing_secret_error(self) -> None:
        """Real (non-dry-run) deploy with no token → MissingSecretError."""
        with mock.patch.object(run_mod, "sf") as mock_sf:
            mock_sf.read_secret.return_value = None
            with self.assertRaises(run_mod.MissingSecretError) as ctx:
                run_mod.do_deploy(
                    html_path=self.html, password=None, subdomain=None,
                    expires_days=None, store_id=None, dry_run=False,
                )
            self.assertIn("CLOUDFLARE_API_TOKEN", str(ctx.exception))

    def test_mocked_api_deploy(self) -> None:
        """Mock urllib + which to simulate Cloudflare API path."""
        fake_resp_create = mock.MagicMock()
        fake_resp_create.read.return_value = json.dumps(
            {"result": {"name": "lumicc-xx", "subdomain": "lumicc-xx"}}
        ).encode()
        fake_resp_create.__enter__ = lambda s: s
        fake_resp_create.__exit__ = lambda *a: None

        fake_resp_deploy = mock.MagicMock()
        fake_resp_deploy.read.return_value = json.dumps(
            {"result": {"id": "dep-1", "url": "https://abc123.lumicc-xx.pages.dev"}}
        ).encode()
        fake_resp_deploy.__enter__ = lambda s: s
        fake_resp_deploy.__exit__ = lambda *a: None

        with mock.patch.object(run_mod.shutil, "which", return_value=None), \
             mock.patch.object(run_mod, "sf") as mock_sf, \
             mock.patch.object(
                 run_mod.urllib.request, "urlopen",
                 side_effect=[fake_resp_create, fake_resp_deploy],
             ):
            mock_sf.read_secret.side_effect = lambda k: {
                "CLOUDFLARE_API_TOKEN": "test-token",
                "CLOUDFLARE_ACCOUNT_ID": "test-account",
            }[k]
            r = run_mod.do_deploy(
                html_path=self.html, password=None,
                subdomain="my-store", expires_days=7,
                store_id="store-1", dry_run=False,
            )
        self.assertIn("pages.dev", r["url"])
        self.assertIsNotNone(r["expires_at"])

    def test_password_fingerprint_is_nonreversible(self) -> None:
        fp = run_mod._password_fingerprint("hunter2")
        self.assertTrue(fp.startswith("sha256:"))
        self.assertNotIn("hunter2", fp)

    def test_slugify(self) -> None:
        self.assertEqual(run_mod._slugify("My Store Q3 2026!"), "my-store-q3-2026")
        self.assertEqual(run_mod._slugify(""), "lumicc-share")

    def test_build_bundle_public_passthrough(self) -> None:
        html = b"<html><body>x</body></html>"
        out = run_mod.build_bundle(html, password=None, title="t")
        self.assertEqual(out, html)

    @unittest.skipUnless(enc_mod.available(), "cryptography not installed")
    def test_encrypt_roundtrip(self) -> None:
        """End-to-end: encrypt in Python, decrypt with same key derivation."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64
        plaintext = b"<html><body>secret report</body></html>"
        password = "correct-horse-battery-staple"
        bundle = enc_mod.encrypt(plaintext, password)
        # Re-derive and decrypt
        salt = base64.b64decode(bundle["salt"])
        iv = base64.b64decode(bundle["iv"])
        ct = base64.b64decode(bundle["ct"])
        key = enc_mod.derive_key(password, salt)
        aes = AESGCM(key)
        recovered = aes.decrypt(iv, ct, None)
        self.assertEqual(recovered, plaintext)

    @unittest.skipUnless(enc_mod.available(), "cryptography not installed")
    def test_encrypted_deploy_dry_run(self) -> None:
        r = run_mod.do_deploy(
            html_path=self.html, password="hunter2hunter2",
            subdomain=None, expires_days=None, store_id=None, dry_run=True,
        )
        self.assertTrue(r["encrypted"])
        # password fingerprint persisted, but raw password is NOT in db row
        row = run_mod.do_status(r["share_id"])
        self.assertTrue(row["password_fingerprint"].startswith("sha256:"))
        self.assertNotIn("hunter2hunter2", json.dumps(row))

    def test_wrapper_html_contains_subtlecrypto(self) -> None:
        if not enc_mod.available():
            self.skipTest("cryptography not installed")
        bundle = enc_mod.encrypt(b"<p>hi</p>", "pw12345678")
        wrapper = enc_mod.wrapper_html(bundle, title="Test")
        self.assertIn("crypto.subtle", wrapper)
        self.assertIn("PBKDF2", wrapper)
        self.assertIn("AES-GCM", wrapper)


if __name__ == "__main__":
    unittest.main(verbosity=2)
