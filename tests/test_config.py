"""tests/test_config.py - YAML config loading and validation."""
from __future__ import annotations

from pathlib import Path

import pytest

from chancode.config import load_config


def test_load_default_config_when_project_override_missing():
    root = Path(__file__).resolve().parents[1]
    override = root / "chancode_config.yaml"
    backup = root / "chancode_config.yaml.bak_test"

    if backup.exists():
        backup.unlink()

    had_override = override.exists()
    if had_override:
        override.rename(backup)

    try:
        cfg = load_config()
        assert cfg.min_bi_separation == 3
        assert cfg.min_pen_separation == 3
        assert cfg.fractal_allow_equal is True
        assert cfg.display_near_gap == 1
        assert cfg.fractal_min_separation == 2
        assert cfg.fractal_assess_lookahead_bars == 8
        assert cfg.fractal_assess_lower_level_gap_bars == 10
        assert cfg.zhongshu_level == "bi"
    finally:
        if had_override:
            backup.rename(override)


def test_project_root_config_overrides_default():
    root = Path(__file__).resolve().parents[1]
    override = root / "chancode_config.yaml"
    backup = root / "chancode_config.yaml.bak_test"

    if backup.exists():
        backup.unlink()

    had_override = override.exists()
    if had_override:
        override.rename(backup)

    try:
        override.write_text(
            (
                "chan:\n"
                "  min_bi_separation: 9\n"
                "  min_pen_separation: 5\n"
                "  fractal_allow_equal: false\n"
                "  display_near_gap: 2\n"
                "  fractal_min_separation: 4\n"
                "  fractal_assess_lookahead_bars: 6\n"
                "  fractal_assess_lower_level_gap_bars: 7\n"
                "  zhongshu_level: \"segment\"\n"
            ),
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.min_bi_separation == 9
        assert cfg.min_pen_separation == 5
        assert cfg.fractal_allow_equal is False
        assert cfg.display_near_gap == 2
        assert cfg.fractal_min_separation == 4
        assert cfg.fractal_assess_lookahead_bars == 6
        assert cfg.fractal_assess_lower_level_gap_bars == 7
        assert cfg.zhongshu_level == "segment"
    finally:
        if override.exists():
            override.unlink()
        if had_override:
            backup.rename(override)


def test_invalid_min_bi_separation_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 0\n  zhongshu_level: bi\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_min_pen_separation_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_pen_separation: 0\n  zhongshu_level: bi\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_zhongshu_level_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 5\n  zhongshu_level: foo\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_display_near_gap_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 5\n  display_near_gap: 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_fractal_min_separation_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 5\n  fractal_min_separation: 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_assess_lookahead_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 5\n  fractal_assess_lookahead_bars: 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_invalid_assess_lower_gap_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 5\n  fractal_assess_lower_level_gap_bars: 0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))
