"""chancode.settings - core strategy configuration.

Only two user-facing constraints are exposed here:
1) MIN_PEN_KLINES: minimum merged K-bar gap to form a pen.
2) ZHONGSHU_BASIS: build centers from "pen" or "segment".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ChanCoreConfig:
    """Core tunable parameters for Chan structure extraction."""

    min_pen_klines: int = 7
    zhongshu_basis: Literal["pen", "segment"] = "pen"


DEFAULT_CONFIG = ChanCoreConfig()


def validate_basis(value: str) -> str:
    """Normalize and validate zhongshu basis string."""
    normalized = (value or "").strip().lower()
    if normalized not in {"pen", "segment"}:
        return DEFAULT_CONFIG.zhongshu_basis
    return normalized
