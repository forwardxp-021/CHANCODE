"""tests/test_xd.py – 测试线段识别。"""
from __future__ import annotations

import pandas as pd
import pytest

from chancode.bi import Pen
from chancode.xd import Segment, build_segments


def _make_pen(start_price, end_price, day_start=0):
    """构造一个简单的 Pen 对象（日期从 day_start 起）。"""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    is_up = end_price > start_price
    return Pen(
        start_idx=day_start,
        end_idx=day_start + 1,
        start_datetime=dates[day_start],
        end_datetime=dates[day_start + 1],
        start_price=start_price,
        end_price=end_price,
        high=max(start_price, end_price) + 0.5,
        low=min(start_price, end_price) - 0.5,
    )


class TestBuildSegments:
    def test_empty_input(self):
        assert build_segments([]) == []

    def test_two_pens_no_segment(self):
        pens = [_make_pen(5, 20, 0), _make_pen(20, 10, 1)]
        assert build_segments(pens) == []

    def test_three_pens_up_segment(self):
        # up(5→20), down(20→12), up(12→25)  → 25 > 20 → 上升线段
        pens = [
            _make_pen(5, 20, 0),
            _make_pen(20, 12, 2),
            _make_pen(12, 25, 4),
        ]
        segs = build_segments(pens)
        assert len(segs) == 1
        assert segs[0].direction == "up"
        assert segs[0].pen_count == 3

    def test_three_pens_down_segment(self):
        # down(20→5), up(5→15), down(15→3)  → 3 < 5 → 下降线段
        pens = [
            _make_pen(20, 5, 0),
            _make_pen(5, 15, 2),
            _make_pen(15, 3, 4),
        ]
        segs = build_segments(pens)
        assert len(segs) == 1
        assert segs[0].direction == "down"

    def test_three_pens_no_break(self):
        # up(5→20), down(20→12), up(12→18)  → 18 < 20 → 不构成线段
        pens = [
            _make_pen(5, 20, 0),
            _make_pen(20, 12, 2),
            _make_pen(12, 18, 4),
        ]
        segs = build_segments(pens)
        assert len(segs) == 0

    def test_five_pen_segment(self):
        # up, down, up(breaks), down, up(further extends)
        pens = [
            _make_pen(5, 20, 0),
            _make_pen(20, 12, 2),
            _make_pen(12, 25, 4),  # 25 > 20 → valid 3-pen
            _make_pen(25, 18, 6),
            _make_pen(18, 30, 8),  # 30 > 25 → extends to 5-pen
        ]
        segs = build_segments(pens)
        assert len(segs) == 1
        assert segs[0].pen_count == 5
        assert segs[0].direction == "up"

    def test_segment_high_low(self):
        pens = [
            _make_pen(5, 20, 0),
            _make_pen(20, 12, 2),
            _make_pen(12, 25, 4),
        ]
        seg = build_segments(pens)[0]
        assert seg.high >= seg.low
        assert seg.high >= 25
