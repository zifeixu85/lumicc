"""Tests for image_client. All HTTP is mocked. Run with: python3 -m pytest test_image_client.py"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import image_client as ic


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4_BYTES = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32


def _mock_http_response(body: dict | bytes, status: int = 200):
    """Build a context-manager mock for urlopen returning JSON or raw bytes."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = raw
    cm.__exit__.return_value = False
    cm.status = status
    return cm


def _http_error(code: int, body_text: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.evolink.ai/v1/images/generations",
        code=code, msg="err", hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body_text.encode("utf-8")),
    )


class BaseTmpDir(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Isolate data root and secrets dir
        self._prev_root = os.environ.get("LUMICC_DATA_ROOT")
        os.environ["LUMICC_DATA_ROOT"] = str(self.root)
        self.out_dir = self.root / "out"

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("LUMICC_DATA_ROOT", None)
        else:
            os.environ["LUMICC_DATA_ROOT"] = self._prev_root
        self.tmp.cleanup()

    def _write_secret(self, value: str = "ev-test-1234567890") -> None:
        secrets = self.root / "secrets"
        secrets.mkdir(parents=True, exist_ok=True)
        (secrets / "EVOLINK_API_KEY.json").write_text(
            json.dumps({"key": "EVOLINK_API_KEY", "value": value})
        )


class TestImageGeneration(BaseTmpDir):

    def test_url_response_downloads_image(self) -> None:
        self._write_secret()
        api_resp = _mock_http_response(
            {"data": [{"url": "https://cdn.example/img.png", "revised_prompt": "rev"}]}
        )
        download_resp = _mock_http_response(PNG_BYTES)
        with patch("image_client.read_secret", return_value="ev-test-key-abcdef"), \
             patch("urllib.request.urlopen", side_effect=[api_resp, download_resp]):
            result = ic.generate_image(
                "a melamine sponge on dark wood",
                model="gemini-3-pro-image-preview",
                out_dir=self.out_dir,
            )
        self.assertTrue(Path(result["image_path"]).exists())
        self.assertEqual(Path(result["image_path"]).read_bytes(), PNG_BYTES)
        self.assertEqual(result["model_used"], "gemini-3-pro-image-preview")
        self.assertEqual(result["revised_prompt"], "rev")
        self.assertIn("cost_estimate_usd", result)
        self.assertEqual(result["size_bytes"], len(PNG_BYTES))

    def test_b64_response_decodes(self) -> None:
        b64 = base64.b64encode(PNG_BYTES).decode("ascii")
        api_resp = _mock_http_response({"data": [{"b64_json": b64}]})
        with patch("image_client.read_secret", return_value="ev-key"), \
             patch("urllib.request.urlopen", side_effect=[api_resp]):
            result = ic.generate_image("test", model="gpt-image-2", out_dir=self.out_dir)
        self.assertEqual(Path(result["image_path"]).read_bytes(), PNG_BYTES)

    def test_429_raises_rate_limit(self) -> None:
        with patch("image_client.read_secret", return_value="ev-key"), \
             patch("urllib.request.urlopen", side_effect=_http_error(429, "rate limited")):
            with self.assertRaises(ic.RateLimitError) as cm:
                ic.generate_image("test", model="gpt-image-2", out_dir=self.out_dir)
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(cm.exception.model, "gpt-image-2")

    def test_401_raises_api_error(self) -> None:
        with patch("image_client.read_secret", return_value="bad"), \
             patch("urllib.request.urlopen", side_effect=_http_error(401, "unauthorized")):
            with self.assertRaises(ic.EvolinkAPIError) as cm:
                ic.generate_image("test", model="gpt-image-2", out_dir=self.out_dir)
        self.assertEqual(cm.exception.status_code, 401)
        self.assertNotIsInstance(cm.exception, ic.RateLimitError)

    def test_missing_secret_raises(self) -> None:
        with patch("image_client.read_secret", return_value=None):
            with self.assertRaises(ic.MissingSecretError) as cm:
                ic.generate_image("test", out_dir=self.out_dir)
        self.assertIn("EVOLINK_API_KEY", str(cm.exception))
        self.assertIn("secret_form.py", str(cm.exception))

    def test_auto_model_chinese(self) -> None:
        self.assertTrue(ic.chinese_in_prompt("海绵清洁产品图"))
        result = ic.generate_image("海绵清洁产品图", model="auto",
                                   out_dir=self.out_dir, dry_run=True)
        self.assertEqual(result["model_used"], "gpt-image-2")

    def test_auto_model_english(self) -> None:
        self.assertFalse(ic.chinese_in_prompt("a melamine sponge"))
        result = ic.generate_image("a melamine sponge", model="auto",
                                   out_dir=self.out_dir, dry_run=True)
        self.assertEqual(result["model_used"], "gemini-3-pro-image-preview")

    def test_dry_run_no_http(self) -> None:
        with patch("urllib.request.urlopen") as urlopen_mock:
            result = ic.generate_image("test", out_dir=self.out_dir, dry_run=True)
            urlopen_mock.assert_not_called()
        self.assertIn("dry_run", result["warnings"])
        self.assertTrue(Path(result["image_path"]).exists())
        self.assertGreater(result["size_bytes"], 0)

    def test_sequential_filenames(self) -> None:
        ic.generate_image("a", out_dir=self.out_dir, dry_run=True)
        r2 = ic.generate_image("b", out_dir=self.out_dir, dry_run=True)
        self.assertTrue(r2["image_filename"].endswith("-002.png"))


class TestVideoGeneration(BaseTmpDir):

    def test_submit_poll_download(self) -> None:
        submit = _mock_http_response({"id": "job-1", "status": "processing", "url": None})
        poll = _mock_http_response({"id": "job-1", "status": "succeeded",
                                    "url": "https://cdn.example/v.mp4"})
        dl = _mock_http_response(MP4_BYTES)
        with patch("image_client.read_secret", return_value="ev-key"), \
             patch("time.sleep"), \
             patch("urllib.request.urlopen", side_effect=[submit, poll, dl]):
            result = ic.generate_video("a fluffy cat", out_dir=self.out_dir,
                                       poll_interval=0, poll_timeout=60)
        self.assertTrue(Path(result["video_path"]).exists())
        self.assertEqual(Path(result["video_path"]).read_bytes(), MP4_BYTES)
        self.assertEqual(result["model_used"], "sora-2")

    def test_video_timeout(self) -> None:
        submit = _mock_http_response({"id": "job-2", "status": "processing", "url": None})
        # Always return processing
        def repeat_processing(*_a, **_k):
            return _mock_http_response({"id": "job-2", "status": "processing", "url": None})
        # First call is submit; subsequent are polls
        responses = [submit] + [repeat_processing() for _ in range(20)]
        with patch("image_client.read_secret", return_value="ev-key"), \
             patch("time.sleep"), \
             patch("urllib.request.urlopen", side_effect=responses), \
             patch("time.time", side_effect=[0, 0, 1000, 1001]):
            with self.assertRaises(ic.EvolinkAPIError) as cm:
                ic.generate_video("x", out_dir=self.out_dir,
                                  poll_interval=0, poll_timeout=10)
        self.assertIn("timeout", str(cm.exception).lower())


class TestCostEstimate(unittest.TestCase):

    def test_nano_banana_cost(self) -> None:
        self.assertAlmostEqual(ic.estimate_cost("gemini-3-pro-image-preview", 1), 0.04)
        self.assertAlmostEqual(ic.estimate_cost("gemini-3-pro-image-preview", 5), 0.20)

    def test_gpt_image_2_cost(self) -> None:
        self.assertAlmostEqual(ic.estimate_cost("gpt-image-2", 1), 0.06)

    def test_sora_cost_scales(self) -> None:
        c5 = ic.estimate_cost("sora-2", 1, duration=5, resolution="720p")
        c10 = ic.estimate_cost("sora-2", 1, duration=10, resolution="720p")
        self.assertGreater(c10, c5)
        c1080 = ic.estimate_cost("sora-2", 1, duration=5, resolution="1080p")
        self.assertGreater(c1080, c5)

    def test_auto_resolves(self) -> None:
        self.assertEqual(ic.estimate_cost("auto", 1), ic.estimate_cost("gemini-3-pro-image-preview", 1))


if __name__ == "__main__":
    unittest.main()
