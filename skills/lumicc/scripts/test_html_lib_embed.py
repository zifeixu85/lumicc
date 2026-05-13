#!/usr/bin/env python3
"""Tests for html_lib.embed_image. Pure stdlib, exit 0 on success."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).parent))
    import html_lib as H  # noqa: E402

    tmp = Path(tempfile.mkdtemp(prefix="lumicc-embed-test-"))

    # --- 1. Real PNG (fake content with valid PNG magic) embeds as data URI
    png = tmp / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"junk-content-for-test")
    result = H.embed_image(png)
    assert result.startswith("data:image/png;base64,"), f"png mime wrong: {result[:40]}"
    print(f"  [ok] embed_image(png) → {result[:48]}...")

    # --- 2. JPEG ext maps to image/jpeg
    jpg = tmp / "y.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0junk")
    result = H.embed_image(jpg)
    assert result.startswith("data:image/jpeg;base64,")
    print("  [ok] embed_image(jpg) → image/jpeg mime")

    # --- 3. Missing file returns SVG placeholder (never raises)
    missing = tmp / "nope.png"
    result = H.embed_image(missing)
    assert result.startswith("data:image/svg+xml"), f"missing → not placeholder: {result[:60]}"
    print("  [ok] embed_image(missing) → SVG placeholder")

    # --- 4. Oversize file returns placeholder
    big = tmp / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"x" * (1024 * 1024)))  # ~1MB
    result = H.embed_image(big, max_kb=10)
    assert result.startswith("data:image/svg+xml"), f"oversize not placeholder: {result[:60]}"
    print("  [ok] embed_image(oversize, max_kb=10) → SVG placeholder")

    # --- 5. Same oversize file fits when max_kb large enough
    result = H.embed_image(big, max_kb=2048)
    assert result.startswith("data:image/png;base64,")
    print("  [ok] embed_image(oversize, max_kb=2048) → embeds successfully")

    print(f"\nAll embed_image tests passed. (tmp: {tmp})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
