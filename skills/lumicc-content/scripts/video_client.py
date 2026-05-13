#!/usr/bin/env python3
"""evolink.ai async video-generation client.

Default: NOT used. Video generation is opt-in via --enable-video-gen because
quality varies and cost is higher than images.

API:
  POST https://api.evolink.ai/v1/videos/generations
  GET  https://api.evolink.ai/v1/tasks/<task_id>

Models:
  - seedance-2.0-text-to-video
  - seedance-2.0-image-to-video
  - seedance-2.0-reference-to-video
  - seedance-2.0-fast-text-to-video
  - seedance-2.0-fast-image-to-video
  - seedance-2.0-fast-reference-to-video
  - happyhorse-1.0-text-to-video
  - happyhorse-1.0-image-to-video
  - happyhorse-1.0-reference-to-video
  - happyhorse-1.0-video-edit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import image_client as ic  # reuse http + auth + poll + download

EVOLINK_API_BASE = "https://api.evolink.ai/v1"

VIDEO_MODELS = {
    "seedance-2.0-text-to-video": {
        "display_name": "Seedance 2.0 (text→video)",
        "inputs": ["prompt"],
        "max_duration_s": 15,
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
        "has_audio": True,
        "fast": False,
    },
    "seedance-2.0-image-to-video": {
        "display_name": "Seedance 2.0 (image→video)",
        "inputs": ["prompt", "image_urls (1-2)"],
        "max_duration_s": 15,
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
        "has_audio": True,
        "fast": False,
    },
    "seedance-2.0-reference-to-video": {
        "display_name": "Seedance 2.0 (reference→video)",
        "inputs": ["prompt", "image_urls (0-9)", "video_urls (0-3)", "audio_urls (0-3)"],
        "max_duration_s": 15,
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
        "has_audio": True,
        "fast": False,
    },
    "seedance-2.0-fast-image-to-video": {
        "display_name": "Seedance 2.0 Fast (image→video)",
        "inputs": ["prompt", "image_urls (1-2)"],
        "max_duration_s": 15,
        "resolutions": ["480p", "720p"],  # no 1080p
        "ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
        "has_audio": True,
        "fast": True,
    },
    "happyhorse-1.0-image-to-video": {
        "display_name": "HappyHorse 1.0 (image→video)",
        "inputs": ["image_urls (1)", "prompt"],
        "max_duration_s": 15,
        "resolutions": ["720p", "1080p"],
        "ratios": ["1:2.5 ~ 2.5:1 (output ratio matches input image)"],
        "has_audio": False,
        "fast": False,
    },
    "happyhorse-1.0-text-to-video": {
        "display_name": "HappyHorse 1.0 (text→video)",
        "inputs": ["prompt"],
        "max_duration_s": 15,
        "resolutions": ["720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "has_audio": False,
        "fast": False,
    },
    "happyhorse-1.0-reference-to-video": {
        "display_name": "HappyHorse 1.0 (reference→video)",
        "inputs": ["prompt", "image_urls"],
        "max_duration_s": 15,
        "resolutions": ["720p", "1080p"],
        "ratios": ["adaptive"],
        "has_audio": False,
        "fast": False,
    },
    "happyhorse-1.0-video-edit": {
        "display_name": "HappyHorse 1.0 (video edit)",
        "inputs": ["video_urls", "prompt"],
        "max_duration_s": 15,
        "resolutions": ["720p", "1080p"],
        "ratios": ["adaptive"],
        "has_audio": False,
        "fast": False,
    },
}


def model_summary(model: str) -> str:
    info = VIDEO_MODELS.get(model)
    if not info:
        return f"Unknown video model: {model}"
    parts = [info["display_name"]]
    parts.append(f"≤ {info['max_duration_s']}s")
    parts.append(", ".join(info["resolutions"]))
    if info.get("has_audio"):
        parts.append("with synced audio")
    if info.get("fast"):
        parts.append("fast tier")
    return " · ".join(parts)


def estimate_video_credits(model: str, duration_s: int = 6, resolution: str = "720p") -> float:
    """Very rough estimate; real billing is per_second on evolink."""
    base_per_s = {"480p": 0.8, "720p": 1.2, "1080p": 2.0}.get(resolution, 1.2)
    is_fast = "fast" in model
    mult = 0.6 if is_fast else 1.0
    return round(base_per_s * duration_s * mult, 2)


def submit_video_task(prompt: str, *, model: str, duration_s: int = 6,
                      resolution: str = "720p", aspect_ratio: str = "9:16",
                      image_urls: list[str] | None = None,
                      video_urls: list[str] | None = None,
                      audio_urls: list[str] | None = None,
                      api_key: str | None = None) -> dict:
    """Submit one async video task to evolink. Bypasses safety checks — caller
    must have already gated this behind --enable-video-gen + cost confirmation.
    """
    if model not in VIDEO_MODELS:
        raise ValueError(f"Unsupported video model: {model}. See VIDEO_MODELS.")
    body: dict = {
        "model": model,
        "prompt": prompt,
        "duration": duration_s,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
    }
    if image_urls:
        body["image_urls"] = image_urls
    if video_urls:
        body["video_urls"] = video_urls
    if audio_urls:
        body["audio_urls"] = audio_urls
    api_key = api_key or ic.get_api_key()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    status, payload, raw = ic._http_request(
        f"{EVOLINK_API_BASE}/videos/generations", "POST", headers, body, timeout=30,
    )
    if status >= 400 or payload is None:
        msg = (payload or {}).get("error", {}).get("message") if payload else raw[:500]
        raise RuntimeError(f"evolink video submit failed (status={status}): {msg}")
    return payload


def extract_video_urls(payload: dict) -> list[str]:
    """Find video URLs in a completed task payload."""
    urls: list[str] = []
    output = payload.get("output") or payload.get("result") or {}
    if isinstance(output, dict):
        for k in ("videos", "video_urls", "urls"):
            v = output.get(k)
            if isinstance(v, list):
                urls.extend([x if isinstance(x, str) else x.get("url", "") for x in v if x])
        if output.get("video_url"):
            urls.append(output["video_url"])
    if isinstance(payload.get("data"), list):
        for item in payload["data"]:
            if isinstance(item, dict):
                u = item.get("url") or item.get("video_url")
                if u:
                    urls.append(u)
    return [u for u in urls if u]


def generate_video(prompt: str, dest_path: Path, *, model: str,
                   duration_s: int = 6, resolution: str = "720p",
                   aspect_ratio: str = "9:16",
                   image_urls: list[str] | None = None,
                   api_key: str | None = None) -> dict:
    sub = submit_video_task(
        prompt, model=model, duration_s=duration_s, resolution=resolution,
        aspect_ratio=aspect_ratio, image_urls=image_urls, api_key=api_key,
    )
    task_id = sub.get("id") or sub.get("task_id")
    if not task_id:
        raise RuntimeError(f"No task_id returned: {sub}")
    final = ic.poll_task(task_id, api_key=api_key, timeout=600)  # videos slower
    urls = extract_video_urls(final)
    saved: list[str] = []
    if urls:
        for i, u in enumerate(urls, 1):
            p = dest_path if len(urls) == 1 else dest_path.with_name(
                f"{dest_path.stem}-{i}{dest_path.suffix or '.mp4'}"
            )
            try:
                ic.download_to_local(u, p, timeout=120)
                saved.append(str(p))
            except Exception as e:
                final.setdefault("download_errors", []).append(f"{u}: {e}")
    return {
        "task_id": task_id,
        "model": model,
        "status": final.get("status"),
        "remote_urls": urls,
        "local_paths": saved,
        "submit_response": sub,
        "final_response": final,
    }
