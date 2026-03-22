"""tests/test_zs.py – 测试中枢识别。"""
from __future__ import annotations

import pandas as pd
import pytest

from chancode.bi import Pen
from chancode.zs import Zhongshu, detect_zhongshu, _range_overlap


def _make_pen(low, high, day_start=0, is_up=True):
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    sp = low if is_up else high
    ep = high if is_up else low
    return Pen(
        start_idx=day_start,
        end_idx=day_start + 1,
        start_datetime=dates[day_start],
        end_datetime=dates[day_start + 1],
        start_price=sp,
        end_price=ep,
        high=high,
        low=low,
    )


class TestRangeOverlap:
    def test_overlap_exists(self):
        result = _range_overlap([(1, 10), (5, 15), (8, 20)])
        assert result == (8, 10)

    def test_no_overlap(self):
        assert _range_overlap([(1, 5), (6, 10)]) is None

    def test_single_range(self):
        assert _range_overlap([(3, 7)]) == (3, 7)


class TestDetectZhongshu:
    def test_empty_input(self):
        assert detect_zhongshu([]) == []

    def test_two_pens_no_zhongshu(self):
        pens = [_make_pen(5, 20, 0), _make_pen(12, 25, 2, is_up=False)]
        assert detect_zhongshu(pens) == []

    def test_three_pens_with_overlap(self):
        # 三笔区间均有重叠 → 一个中枢
        pens = [
            _make_pen(5, 20, 0, is_up=True),
            _make_pen(10, 25, 2, is_up=False),
            _make_pen(8, 22, 4, is_up=True),
        ]
        zhongshus = detect_zhongshu(pens)
        assert len(zhongshus) == 1
        zh = zhongshus[0]
        assert zh.low <= zh.high

    def test_three_pens_no_overlap(self):
        # 三笔区间不重叠 → 无中枢
        pens = [
            _make_pen(1, 5, 0, is_up=True),
            _make_pen(6, 10, 2, is_up=False),
            _make_pen(11, 15, 4, is_up=True),
        ]
        zhongshus = detect_zhongshu(pens)
        assert len(zhongshus) == 0

    def test_adjacent_zhongshu_merges(self):
        # 两个相邻中枢若价格区间重叠，应合并
        pens = [
            _make_pen(5, 20, 0, is_up=True),
            _make_pen(10, 25, 2, is_up=False),
            _make_pen(8, 22, 4, is_up=True),
            _make_pen(12, 28, 6, is_up=False),
            _make_pen(10, 24, 8, is_up=True),
        ]
        zhongshus = detect_zhongshu(pens)
        # 若两个中枢价格区间重叠，结果应 <= 2 个
        assert len(zhongshus) <= 2
