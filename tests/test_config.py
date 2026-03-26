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
        assert cfg.min_bi_separation == 7
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
            "chan:\n  min_bi_separation: 9\n  zhongshu_level: \"segment\"\n",
            encoding="utf-8",
        )
        cfg = load_config()
        assert cfg.min_bi_separation == 9
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


def test_invalid_zhongshu_level_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("chan:\n  min_bi_separation: 7\n  zhongshu_level: foo\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))
