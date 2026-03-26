"""tests/test_xd.py - segment detection from pens."""
from __future__ import annotations

import pandas as pd

from chancode.bi import Pen
from chancode.xd import build_segments


_BASE = pd.date_range("2024-01-01", periods=200, freq="D")


def _pen(i: int, start_idx: int, end_idx: int, start_price: float, end_price: float) -> Pen:
    return Pen(
        start_idx=start_idx,
        end_idx=end_idx,
        start_datetime=_BASE[start_idx],
        end_datetime=_BASE[end_idx],
        start_price=start_price,
        end_price=end_price,
        high=max(start_price, end_price),
        low=min(start_price, end_price),
        start_ftype="bottom" if end_price > start_price else "top",
        end_ftype="top" if end_price > start_price else "bottom",
    )


def test_build_segments_empty_or_short():
    assert build_segments([]) == []
    short = [_pen(0, 0, 8, 10, 20), _pen(1, 8, 16, 20, 12), _pen(2, 16, 24, 12, 24), _pen(3, 24, 32, 24, 14)]
    assert build_segments(short) == []


def test_build_segments_direction_and_sparsity():
    # 构造交替笔，包含明显高低点，线段数量应显著少于笔数量。
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 14),
        _pen(2, 16, 24, 14, 26),
        _pen(3, 24, 32, 26, 13),
        _pen(4, 32, 40, 13, 24),
        _pen(5, 40, 48, 24, 12),
        _pen(6, 48, 56, 12, 28),
        _pen(7, 56, 64, 28, 11),
    ]
    segments = build_segments(pens, min_pivot_separation=1, min_segment_pens=3)

    assert len(segments) < len(pens)
    for seg in segments:
        assert seg.direction in {"up", "down"}
        assert seg.end_idx > seg.start_idx


def test_segment_endpoints_monotonic():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 24),
        _pen(3, 24, 32, 24, 14),
        _pen(4, 32, 40, 14, 26),
        _pen(5, 40, 48, 26, 13),
        _pen(6, 48, 56, 13, 29),
    ]
    segments = build_segments(pens)

    for i in range(1, len(segments)):
        assert segments[i].start_idx > segments[i - 1].start_idx
        assert segments[i].end_idx > segments[i - 1].end_idx
