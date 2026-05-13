#!/usr/bin/env python3
"""Smoke tests for picker.py. Pure stdlib, exit 0 on success."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def _setup_env() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="lumicc-picker-test-"))
    os.environ["LUMICC_DATA_ROOT"] = str(tmp)
    return tmp


def main() -> int:
    root = _setup_env()
    sys.path.insert(0, str(Path(__file__).parent))

    import session as S  # noqa: E402
    import picker as P  # noqa: E402

    # --- list_kinds returns the 5 expected kinds
    kinds = P.list_kinds()
    expected = {
        "landing_style", "color_palette", "product_card_layout",
        "hero_composition", "typography_pairing", "brand_direction",
    }
    assert set(kinds) == expected, f"kinds mismatch: {kinds}"
    assert "brand_direction" in kinds, "brand_direction missing from list_kinds"
    assert len(kinds) == 6, f"expected 6 kinds, got {len(kinds)}"
    print(f"  [ok] list_kinds: {kinds}")

    # --- create a session and render landing_style picker
    sid = S.new_session("test")
    out = P.render_picker("landing_style", sid)
    assert out.exists(), f"picker HTML not written: {out}"
    html = out.read_text(encoding="utf-8")

    # every landing_style option id must appear in the HTML
    for opt in P.KINDS["landing_style"]["options"]:
        assert opt["id"] in html, f"missing option id in HTML: {opt['id']}"
    print(f"  [ok] render_picker(landing_style) → {out}  ({len(html)} bytes)")

    # --- theme switcher inherited from page shell
    assert "data-set-theme" in html, "page shell theme switcher missing"
    assert html.count("data-set-theme") >= 4, "expected 4 theme buttons"
    print("  [ok] HTML inherits page shell (4 theme switcher buttons)")

    # --- both save paths present
    assert "showSaveFilePicker" in html, "primary save path missing"
    assert "Blob" in html, "fallback Blob path missing"
    print("  [ok] HTML contains both showSaveFilePicker + Blob fallback")

    # --- read_choice returns None initially
    assert P.read_choice(sid, "landing_style") is None
    assert P.has_choice(sid, "landing_style") is False
    print("  [ok] read_choice returns None before user picks")

    # --- hand-write a choice JSON and read it back
    fake = {
        "kind": "landing_style",
        "selected_id": "aesop_apothecary",
        "label": "Aesop · 药剂铺",
        "picked_at": 1700000000,
    }
    choice_path = S.session_dir(sid) / "choice-landing_style.json"
    choice_path.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
    got = P.read_choice(sid, "landing_style")
    assert got is not None
    assert got["selected_id"] == "aesop_apothecary"
    assert P.has_choice(sid, "landing_style") is True
    print(f"  [ok] read_choice returns saved JSON: {got['selected_id']}")

    # --- render every kind to make sure none blow up
    for k in kinds:
        p = P.render_picker(k, sid)
        text = p.read_text(encoding="utf-8")
        for opt in P.KINDS[k]["options"]:
            assert opt["id"] in text, f"{k}: missing {opt['id']}"
    print(f"  [ok] all {len(kinds)} kinds render without error")

    # --- custom_options path works for ad-hoc kinds
    custom = [{"id": "alpha", "label": "Alpha"}, {"id": "beta", "label": "Beta"}]
    p = P.render_picker("ad_hoc_kind", sid, custom_options=custom)
    text = p.read_text(encoding="utf-8")
    assert "alpha" in text and "beta" in text
    print("  [ok] custom_options accepted for unknown kind")

    # --- picker history persistence (Task 1)
    import sqlite3 as _sqlite3
    # Bootstrap a minimal store.db so record_picker_choice has somewhere to write.
    db_path = root / "store.db"
    db = _sqlite3.connect(str(db_path))
    db.execute(
        "CREATE TABLE IF NOT EXISTS preferences ("
        "  key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER)"
    )
    db.commit(); db.close()

    sample = {"selected_id": "aesop_apothecary", "label": "Aesop · 药剂铺", "kind": "landing_style"}
    S.record_picker_choice("test-store", "landing_style", sample)
    got = S.get_picker_history("test-store", "landing_style")
    assert got is not None and got["selected_id"] == "aesop_apothecary", f"history roundtrip failed: {got}"
    print(f"  [ok] record_picker_choice → get_picker_history: {got['selected_id']}")

    assert S.get_picker_history("other-store", "landing_style") is None, "different store should be None"
    assert S.get_picker_history("test-store", "color_palette") is None, "different kind should be None"
    print("  [ok] history scoped by (store_id, kind)")

    # Banner appears when history exists
    sid2 = S.new_session("test", store_id="test-store")
    out2 = P.render_picker("landing_style", sid2)
    html2 = out2.read_text(encoding="utf-8")
    assert "上次你选了" in html2, "history banner text missing"
    assert "picker-history-continue" in html2, "history continue button missing"
    print("  [ok] picker renders history banner for known (store_id, kind)")

    # No banner for a fresh kind on the same session
    out3 = P.render_picker("hero_composition", sid2)
    html3 = out3.read_text(encoding="utf-8")
    assert "上次你选了" not in html3, "history banner should not show for unknown kind"
    print("  [ok] no banner without history")

    # No-op when store.db missing (different LUMICC_DATA_ROOT)
    import tempfile as _tf, os as _os
    saved = _os.environ["LUMICC_DATA_ROOT"]
    with _tf.TemporaryDirectory() as t2:
        _os.environ["LUMICC_DATA_ROOT"] = t2
        # Should not raise even though store.db doesn't exist
        S.record_picker_choice("x", "y", {"a": 1})
        assert S.get_picker_history("x", "y") is None
    _os.environ["LUMICC_DATA_ROOT"] = saved
    print("  [ok] picker history no-op when store.db missing")

    print(f"\nAll picker tests passed. (data root: {root})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
