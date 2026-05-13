"""Evolink.ai image + video generation client for lumicc-content.

Pure Python stdlib. Reads EVOLINK_API_KEY via secret_form.read_secret only.
Downloads results locally with 0600 perms.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Import read_secret from sibling lumicc skill
_THIS_DIR = Path(__file__).resolve().parent
_LUMICC_SCRIPTS = _THIS_DIR.parent.parent / "lumicc" / "scripts"
if str(_LUMICC_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LUMICC_SCRIPTS))

try:
    from secret_form import read_secret, secret_fingerprint  # type: ignore
except ImportError:  # pragma: no cover
    def read_secret(key: str) -> str | None:  # type: ignore
        root = Path(os.environ.get("LUMICC_DATA_ROOT", str(Path.home() / ".commerce-os")))
        p = root / "secrets" / f"{key}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())["value"]
        except Exception:
            return None

    def secret_fingerprint(key: str) -> str | None:  # type: ignore
        v = read_secret(key)
        if not v:
            return None
        return f"{v[:2]}***{v[-4:]}" if len(v) > 6 else "***"


EVOLINK_BASE = "https://api.evolink.ai/v1"
USER_AGENT = "lumicc/0.4.0"
SECRET_KEY = "EVOLINK_API_KEY"

MODEL_NANO_BANANA = "gemini-3-pro-image-preview"
MODEL_GPT_IMAGE_2 = "gpt-image-2"
MODEL_SORA_2 = "sora-2"

# USD per unit (rough)
COST_TABLE = {
    MODEL_NANO_BANANA: 0.04,
    MODEL_GPT_IMAGE_2: 0.06,
    MODEL_SORA_2: 0.80,  # ~5s 720p
}

_CJK_RE = re.compile(r"[　-〿一-鿿＀-￯぀-ヿ]")


class MissingSecretError(Exception):
    """EVOLINK_API_KEY missing from ~/.commerce-os/secrets/."""


class EvolinkAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None,
                 body: str = "", model: str | None = None,
                 cost_so_far: float = 0.0) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.model = model
        self.cost_so_far = cost_so_far


class RateLimitError(EvolinkAPIError):
    pass


class QuotaExceededError(EvolinkAPIError):
    pass


# ---------- helpers ----------

def chinese_in_prompt(prompt: str) -> bool:
    return bool(_CJK_RE.search(prompt or ""))


def estimate_cost(model: str, count: int = 1, **kwargs: Any) -> float:
    if model == "auto":
        model = MODEL_NANO_BANANA
    base = COST_TABLE.get(model, 0.05)
    if model == MODEL_SORA_2:
        duration = int(kwargs.get("duration", 5))
        resolution = str(kwargs.get("resolution", "720p"))
        mult = 1.0 if "720" in resolution else 1.5
        base = base * (duration / 5.0) * mult
    return round(base * max(1, int(count)), 4)


def _data_root() -> Path:
    override = os.environ.get("LUMICC_DATA_ROOT")
    return Path(override) if override else Path.home() / ".commerce-os"


def _default_out_dir(run_id: str | None) -> Path:
    rid = run_id or uuid.uuid4().hex[:12]
    return _data_root() / "assets" / "runs" / rid


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _next_filename(out_dir: Path, prefix: str, ext: str) -> Path:
    existing = sorted(out_dir.glob(f"{prefix}-*.{ext}"))
    n = len(existing) + 1
    return out_dir / f"{prefix}-{n:03d}.{ext}"


def _require_key() -> str:
    """Resolve EVOLINK_API_KEY strictly via secret_form.read_secret.

    Env var fallback is intentionally NOT supported — credentials must live
    in ~/.commerce-os/secrets/ with 0600 perms, never in the shell env where
    `ps`/process inspection could leak them.
    """
    key = read_secret(SECRET_KEY)
    if not key:
        raise MissingSecretError(
            f"{SECRET_KEY} not configured. Run:\n"
            f"  python3 ../lumicc/scripts/secret_form.py --generate {SECRET_KEY} --open\n"
            "Submit the form in your browser; credentials never enter the LLM conversation."
        )
    return key


def _http_json(url: str, *, method: str = "GET", api_key: str,
               body: dict | None = None, timeout: int = 60) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        _raise_http(e.code, body_text)
        raise  # unreachable; for type checker
    except urllib.error.URLError as e:
        raise EvolinkAPIError(f"Network error: {e.reason}") from e


def _raise_http(status: int, body_text: str) -> None:
    snippet = body_text[:500]
    lowered = body_text.lower()
    if status == 429:
        raise RateLimitError("Rate limit (429)", status_code=status, body=snippet)
    if status in (402, 403) and ("quota" in lowered or "billing" in lowered):
        raise QuotaExceededError("Quota/billing error", status_code=status, body=snippet)
    raise EvolinkAPIError(f"HTTP {status}: {snippet}", status_code=status, body=snippet)


def _http_download(url: str, *, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise EvolinkAPIError(f"Download failed HTTP {e.code}", status_code=e.code) from e
    except urllib.error.URLError as e:
        raise EvolinkAPIError(f"Download network error: {e.reason}") from e


def _write_file(path: Path, data: bytes) -> int:
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return len(data)


def _select_image_model(prompt: str, model: str) -> str:
    if model == "auto":
        return MODEL_GPT_IMAGE_2 if chinese_in_prompt(prompt) else MODEL_NANO_BANANA
    return model


# ---------- public API ----------

def generate_image(
    prompt: str,
    *,
    model: str = "auto",
    size: str = "1024x1024",
    quality: str = "high",
    out_dir: Path | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be non-empty")

    chosen = _select_image_model(prompt, model)
    warnings: list[str] = []
    out_dir = Path(out_dir) if out_dir else _default_out_dir(run_id)
    _ensure_dir(out_dir)
    out_path = _next_filename(out_dir, "img", "png")

    if dry_run:
        fake = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        size_bytes = _write_file(out_path, fake)
        return {
            "image_path": str(out_path),
            "image_filename": out_path.name,
            "model_used": chosen,
            "prompt_used": prompt,
            "revised_prompt": None,
            "cost_estimate_usd": estimate_cost(chosen, 1),
            "size_bytes": size_bytes,
            "warnings": ["dry_run"],
        }

    api_key = _require_key()
    body: dict[str, Any] = {"model": chosen, "prompt": prompt, "n": 1, "size": size}
    if chosen == MODEL_NANO_BANANA:
        body["quality"] = quality

    try:
        resp = _http_json(f"{EVOLINK_BASE}/images/generations",
                          method="POST", api_key=api_key, body=body, timeout=180)
    except EvolinkAPIError as e:
        e.model = chosen
        raise

    # Synchronous response: {"data":[{"url":..., "b64_json":...}]}
    # Async task response: {"id":"task-xxx","status":"pending", ...} → poll /tasks/<id>
    data = (resp.get("data") or [None])[0]
    revised: str | None = None
    img_bytes: bytes | None = None
    if data:
        revised = data.get("revised_prompt")
        if data.get("b64_json"):
            img_bytes = base64.b64decode(data["b64_json"])
        elif data.get("url"):
            img_bytes = _http_download(data["url"])
    if img_bytes is None:
        # Try async task pattern
        task_id = resp.get("id") or resp.get("task_id")
        if task_id and resp.get("status") in ("pending", "processing", "queued", None):
            deadline = time.time() + 60
            url: str | None = None
            while time.time() < deadline:
                time.sleep(0.5)
                poll = _http_json(f"{EVOLINK_BASE}/tasks/{task_id}",
                                  method="GET", api_key=api_key, timeout=30)
                if poll.get("status") in ("completed", "succeeded", "success"):
                    out = poll.get("output") or {}
                    imgs = out.get("images") if isinstance(out, dict) else None
                    if imgs:
                        first = imgs[0]
                        url = first if isinstance(first, str) else first.get("url")
                    break
                if poll.get("status") in ("failed", "error", "cancelled"):
                    break
            if url:
                img_bytes = _http_download(url)
    if img_bytes is None:
        raise EvolinkAPIError("No url or b64_json in response", model=chosen,
                              body=json.dumps(resp)[:500])

    size_bytes = _write_file(out_path, img_bytes)
    return {
        "image_path": str(out_path),
        "image_filename": out_path.name,
        "model_used": chosen,
        "prompt_used": prompt,
        "revised_prompt": revised,
        "cost_estimate_usd": estimate_cost(chosen, 1),
        "size_bytes": size_bytes,
        "warnings": warnings,
    }


def generate_video(
    prompt: str,
    *,
    model: str = MODEL_SORA_2,
    duration: int = 5,
    resolution: str = "720p",
    out_dir: Path | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    poll_timeout: int = 300,
    poll_interval: int = 10,
) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be non-empty")

    out_dir = Path(out_dir) if out_dir else _default_out_dir(run_id)
    _ensure_dir(out_dir)
    out_path = _next_filename(out_dir, "vid", "mp4")
    cost = estimate_cost(model, 1, duration=duration, resolution=resolution)

    if dry_run:
        fake = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 64
        size_bytes = _write_file(out_path, fake)
        return {
            "video_path": str(out_path),
            "video_filename": out_path.name,
            "model_used": model,
            "prompt_used": prompt,
            "duration": duration,
            "resolution": resolution,
            "cost_estimate_usd": cost,
            "size_bytes": size_bytes,
            "warnings": ["dry_run"],
        }

    api_key = _require_key()
    submit = _http_json(
        f"{EVOLINK_BASE}/videos/generations",
        method="POST", api_key=api_key,
        body={"model": model, "prompt": prompt, "duration": duration, "resolution": resolution},
        timeout=60,
    )
    job_id = submit.get("id")
    if not job_id:
        raise EvolinkAPIError("No job id in submit response", model=model,
                              body=json.dumps(submit)[:500])

    deadline = time.time() + poll_timeout
    video_url: str | None = submit.get("url")
    status = submit.get("status", "processing")
    while not video_url and status not in ("failed", "error"):
        if time.time() > deadline:
            raise EvolinkAPIError(
                f"Video generation timeout after {poll_timeout}s (job {job_id})",
                model=model, cost_so_far=cost,
            )
        time.sleep(poll_interval)
        poll = _http_json(f"{EVOLINK_BASE}/videos/{job_id}",
                          method="GET", api_key=api_key, timeout=30)
        status = poll.get("status", "processing")
        video_url = poll.get("url")

    if not video_url:
        raise EvolinkAPIError(f"Video job {job_id} failed (status={status})",
                              model=model, cost_so_far=cost)

    vid_bytes = _http_download(video_url, timeout=300)
    size_bytes = _write_file(out_path, vid_bytes)
    return {
        "video_path": str(out_path),
        "video_filename": out_path.name,
        "model_used": model,
        "prompt_used": prompt,
        "duration": duration,
        "resolution": resolution,
        "cost_estimate_usd": cost,
        "size_bytes": size_bytes,
        "warnings": [],
    }


# ---------- CLI ----------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Evolink.ai image/video client")
    p.add_argument("--prompt", help="Generation prompt")
    p.add_argument("--model", default="auto",
                   help="auto | gemini-3-pro-image-preview | gpt-image-2 | sora-2")
    p.add_argument("--size", default="1024x1024")
    p.add_argument("--quality", default="high")
    p.add_argument("--run-id", default=None)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--video", action="store_true", help="Video mode (Sora 2)")
    p.add_argument("--duration", type=int, default=5)
    p.add_argument("--resolution", default="720p")
    p.add_argument("--estimate", action="store_true",
                   help="Print cost estimate and exit")
    p.add_argument("--count", type=int, default=1)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.estimate:
        model = args.model if args.model != "auto" else MODEL_NANO_BANANA
        cost = estimate_cost(model, args.count,
                             duration=args.duration, resolution=args.resolution)
        sys.stdout.write(json.dumps(
            {"model": model, "count": args.count, "cost_estimate_usd": cost}
        ) + "\n")
        return 0

    if not args.prompt:
        sys.stderr.write("--prompt is required (or use --estimate)\n")
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else None
    try:
        if args.video:
            model = args.model if args.model != "auto" else MODEL_SORA_2
            result = generate_video(
                args.prompt, model=model, duration=args.duration,
                resolution=args.resolution, out_dir=out_dir,
                run_id=args.run_id, dry_run=args.dry_run,
            )
        else:
            result = generate_image(
                args.prompt, model=args.model, size=args.size, quality=args.quality,
                out_dir=out_dir, run_id=args.run_id, dry_run=args.dry_run,
            )
    except MissingSecretError as e:
        sys.stderr.write(f"[lumicc] {e}\n")
        return 3
    except (RateLimitError, QuotaExceededError) as e:
        sys.stderr.write(f"[lumicc] {type(e).__name__}: {e} (model={e.model})\n")
        return 4
    except EvolinkAPIError as e:
        sys.stderr.write(f"[lumicc] EvolinkAPIError: {e}\n")
        return 5

    if not args.dry_run:
        fp = secret_fingerprint(SECRET_KEY)
        if fp:
            sys.stderr.write(f"[lumicc] used {SECRET_KEY}={fp}\n")
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
