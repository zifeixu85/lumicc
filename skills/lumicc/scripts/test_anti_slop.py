#!/usr/bin/env python3
"""Tests for anti_slop.py — 24 cases covering all 6 gates + CLI + rendering."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import anti_slop as A  # noqa: E402

SCRIPT = Path(__file__).parent / "anti_slop.py"


# ---------------------------------------------------------------------------
# 1. Clean text
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_01_clean_text_passes():
    r = A.check_slop("This is a normal paragraph about Q1 2026 results from store.db.")
    assert r.passed
    assert r.violations == []
    assert all(c == 0 for c in r.gate_counts.values())


# ---------------------------------------------------------------------------
# 2-3. G1 LLM filler
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_02_g1_english_filler():
    r = A.check_slop("Let me help you with that. Here's a comprehensive analysis.")
    assert not r.passed
    assert r.gate_counts["G1"] >= 1
    assert any(v.gate == "G1" for v in r.violations)


@pytest.mark.unit
def test_03_g1_chinese_filler():
    r = A.check_slop("总结来说我们的产品很好。希望这能帮到你。", lang="zh")
    assert not r.passed
    assert r.gate_counts["G1"] >= 1


# ---------------------------------------------------------------------------
# 4-5. G2 word stack
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_04_g2_english_adjective_stack():
    r = A.check_slop("Our innovative cutting-edge revolutionary solution wins.",
                     lang="en")
    # "innovative" (-ive), "revolutionary" (-ary not in list, but innovative+...)
    # Let's use a clearer one:
    r = A.check_slop("This is an amazing inspiring engaging beautiful product.",
                     lang="en")
    assert r.gate_counts["G2"] >= 1


@pytest.mark.unit
def test_05_g2_chinese_adjective_stack():
    r = A.check_slop("我们提供高效卓越优质创新的服务给客户。", lang="zh")
    assert r.gate_counts["G2"] >= 1


# ---------------------------------------------------------------------------
# 6-7. G3 vague terms
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_06_g3_english_vague():
    r = A.check_slop("Recently, we observed many improvements across the board.",
                     lang="en")
    assert r.gate_counts["G3"] >= 2


@pytest.mark.unit
def test_07_g3_chinese_vague():
    r = A.check_slop("近期销量有大量提升, 团队反馈很好。", lang="zh")
    assert r.gate_counts["G3"] >= 2


@pytest.mark.unit
def test_07b_g3_skipped_when_number_nearby():
    # Number nearby should disable G3
    r = A.check_slop("Recently in Q1 2026 we shipped 47 features.", lang="en")
    # "recently" near "2026" / "47" → should NOT fire
    assert r.gate_counts["G3"] == 0


# ---------------------------------------------------------------------------
# 8-9. G4 data has source
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_08_g4_unsourced_number():
    r = A.check_slop("We saw an 87% conversion lift after the redesign.")
    assert r.gate_counts["G4"] >= 1


@pytest.mark.unit
def test_09_g4_sourced_number_passes():
    r = A.check_slop("We saw an 87% lift per store.db RFM analysis.")
    assert r.gate_counts["G4"] == 0


# ---------------------------------------------------------------------------
# 10. G5 fake authority
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_10_g5_english_authority():
    r = A.check_slop("According to research, customers prefer faster checkout.")
    assert r.gate_counts["G5"] >= 1


@pytest.mark.unit
def test_10b_g5_chinese_authority():
    r = A.check_slop("据研究, 客户更喜欢简洁的页面。专家认为这是趋势。", lang="zh")
    assert r.gate_counts["G5"] >= 1


# ---------------------------------------------------------------------------
# 11-12. G6 machine-translation tells
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_11_g6_machine_translation():
    r = A.check_slop("利用我们的服务提升您的销量。", lang="zh")
    assert r.gate_counts["G6"] >= 1


@pytest.mark.unit
def test_12_g6_english_comma_in_chinese():
    r = A.check_slop("我们做了测试, 结果不错。", lang="zh")
    assert r.gate_counts["G6"] >= 1


# ---------------------------------------------------------------------------
# 13. lang auto-detect
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_13_lang_autodetect_zh():
    # Pure Chinese text — auto should choose zh and fire G6 patterns
    r = A.check_slop("利用我们的服务接下来的几个步骤会有显著的提升。", lang="auto")
    assert r.gate_counts["G6"] >= 1


@pytest.mark.unit
def test_13b_lang_autodetect_en():
    r = A.check_slop("Let me help you analyze this data.", lang="auto")
    assert r.gate_counts["G1"] >= 1


# ---------------------------------------------------------------------------
# 14. gates subset
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_14_gates_subset():
    text = ("Let me help you. Recently we saw 87% lift. According to research, "
            "many things improved.")
    r = A.check_slop(text, gates=["G1", "G2"])
    # G1 fires, others should be 0 because not run
    assert r.gate_counts["G1"] >= 1
    assert r.gate_counts["G3"] == 0
    assert r.gate_counts["G4"] == 0
    assert r.gate_counts["G5"] == 0


# ---------------------------------------------------------------------------
# 15. severity threshold
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_15_severity_threshold_block_only():
    text = ("Let me help you. Recently we saw 87% lift. According to research, "
            "many things improved.")
    # block-only excludes G1 (warn), G2 (warn), G3 (info), G6 (warn)
    r = A.check_slop(text, severity_threshold="block")
    # Only G4 and G5 should run
    assert r.gate_counts["G1"] == 0
    assert r.gate_counts["G3"] == 0
    # G4 should fire (unsourced 87%)
    assert r.gate_counts["G4"] >= 1


# ---------------------------------------------------------------------------
# 16-17. render_banner
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_16_render_banner_empty_when_passed():
    r = A.check_slop("Clean text from store.db in Q1 2026.")
    assert A.render_banner(r) == ""


@pytest.mark.unit
def test_17_render_banner_lists_top_three():
    r = A.check_slop(
        "Let me help. Of course! According to research, many recently."
    )
    banner = A.render_banner(r)
    assert banner != ""
    assert "Anti-Slop" in banner
    assert banner.count("<li>") <= 3


# ---------------------------------------------------------------------------
# 18. render_report_html
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_18_render_report_html_is_valid():
    r = A.check_slop("Let me help you with 87% lift.")
    html = A.render_report_html(r)
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


# ---------------------------------------------------------------------------
# 19. CLI exit code on slop
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_19_cli_exits_1_on_slop(tmp_path: Path):
    f = tmp_path / "dirty.md"
    f.write_text("Let me help you analyze this.", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(f)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1


@pytest.mark.unit
def test_19b_cli_exits_0_on_clean(tmp_path: Path):
    f = tmp_path / "clean.md"
    f.write_text("Q1 2026 data from store.db shows 17 stores active.",
                 encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(f)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# 20. CLI JSON output
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_20_cli_quiet_stdout_emits_json(tmp_path: Path):
    f = tmp_path / "x.md"
    f.write_text("Let me help you.", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--file", str(f), "--quiet-stdout"],
        capture_output=True, text=True,
    )
    data = json.loads(proc.stdout)
    assert "passed" in data
    assert "gate_counts" in data
    assert "violations" in data
    assert data["passed"] is False


# ---------------------------------------------------------------------------
# 21. Long text doesn't crash
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_21_long_text():
    big = "This is a paragraph about products. " * 300  # ~10k chars
    r = A.check_slop(big)
    assert isinstance(r, A.SlopReport)


# ---------------------------------------------------------------------------
# 22. Empty input
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_22_empty_input_passes():
    r = A.check_slop("")
    assert r.passed
    assert r.total_chars == 0


# ---------------------------------------------------------------------------
# 23. Mixed EN+ZH
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_23_mixed_en_zh():
    text = "Let me help you. 利用我们的服务."
    r = A.check_slop(text, lang="mixed")
    # G1 (EN) and G6 (ZH) should both fire
    assert r.gate_counts["G1"] >= 1
    assert r.gate_counts["G6"] >= 1


# ---------------------------------------------------------------------------
# 24. Snippet truncation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_24_snippet_max_length():
    text = "x" * 500 + " Let me help you " + "y" * 500
    r = A.check_slop(text)
    for v in r.violations:
        assert len(v.snippet) <= A.SNIPPET_MAX


# ---------------------------------------------------------------------------
# Extras: ensure helpers don't crash
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_25_check_slop_never_raises_on_garbage():
    # Surrogates / odd chars should not crash
    r = A.check_slop("\x00\x01 some text 利用我们的 \n\n\n")
    assert isinstance(r, A.SlopReport)


@pytest.mark.unit
def test_26_violations_sorted_by_line():
    text = "利用我们的产品\n\nLet me help you\n\n87% lift here"
    r = A.check_slop(text)
    lines = [v.line for v in r.violations]
    assert lines == sorted(lines)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
