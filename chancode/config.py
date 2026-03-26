"""YAML-based runtime configuration for ChanCode."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass(frozen=True)
class Config:
    """Runtime configuration values used by core structure extraction."""

    min_bi_separation: int = 7
    zhongshu_level: str = "bi"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.default.yaml"


def _resolve_config_path(path: Optional[str]) -> Path:
    if path:
        return Path(path).expanduser().resolve()

    root_cfg = _project_root() / "chancode_config.yaml"
    if root_cfg.exists():
        return root_cfg

    return _default_config_path()


def _validate_config(cfg: Config) -> Config:
    if cfg.min_bi_separation < 1:
        raise ValueError("min_bi_separation must be >= 1")

    level = (cfg.zhongshu_level or "").strip().lower()
    if level not in {"bi", "segment"}:
        raise ValueError("zhongshu_level must be either 'bi' or 'segment'")

    return Config(min_bi_separation=int(cfg.min_bi_separation), zhongshu_level=level)


def load_config(path: str | None = None) -> Config:
    """Load config from YAML with priority:

    1) explicit `path`
    2) project-root `chancode_config.yaml`
    3) package `config.default.yaml`
    """
    cfg_path = _resolve_config_path(path)
    if not cfg_path.exists():
        raise ValueError(f"Config file not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw: Any = yaml.safe_load(f) or {}

    chan = raw.get("chan", {}) if isinstance(raw, dict) else {}
    cfg = Config(
        min_bi_separation=int(chan.get("min_bi_separation", 7)),
        zhongshu_level=str(chan.get("zhongshu_level", "bi")),
    )
    return _validate_config(cfg)
