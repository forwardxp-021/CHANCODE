"""tests/test_fractal.py – 测试分型识别。"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from chancode.fractal import FractalPoint, detect_fractals, filter_and_alternate_fractals


def _make_df(highs, lows, closes=None):
    """构造最简 DataFrame 用于分型测试。"""
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"High": highs, "Low": lows, "Close": closes}, index=dates)


class TestDetectFractals:
    def test_single_top(self):
        # 中间 K 线高于两侧 → 顶分型
        df = _make_df([10, 20, 10], [5, 15, 5])
        fractals = detect_fractals(df)
        assert len(fractals) == 1
        assert fractals[0].ftype == "top"
        assert fractals[0].high == 20

    def test_single_bottom(self):
        # 中间 K 线低于两侧 → 底分型
        df = _make_df([20, 10, 20], [15, 5, 15])
        fractals = detect_fractals(df)
        assert len(fractals) == 1
        assert fractals[0].ftype == "bottom"
        assert fractals[0].low == 5

    def test_no_fractal_monotone(self):
        # 单调上升，无分型
        df = _make_df([10, 11, 12, 13, 14], [5, 6, 7, 8, 9])
        fractals = detect_fractals(df)
        assert len(fractals) == 0

    def test_price_property(self):
        df = _make_df([10, 20, 10], [5, 15, 5])
        f = detect_fractals(df)[0]
        assert f.price == f.high  # 顶分型 price 为 high

        df2 = _make_df([20, 10, 20], [15, 5, 15])
        f2 = detect_fractals(df2)[0]
        assert f2.price == f2.low  # 底分型 price 为 low


class TestFilterAndAlternateFractals:
    def test_empty_input(self):
        assert filter_and_alternate_fractals([]) == []

    def test_removes_consecutive_tops_keeps_highest(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        fractals = [
            FractalPoint(0, dates[0], "top", 15, 10),
            FractalPoint(1, dates[1], "top", 20, 10),  # 更高
            FractalPoint(2, dates[2], "bottom", 5, 1),
        ]
        result = filter_and_alternate_fractals(fractals)
        assert len(result) == 2
        assert result[0].high == 20  # 保留高点更高的顶分型

    def test_removes_consecutive_bottoms_keeps_lowest(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        fractals = [
            FractalPoint(0, dates[0], "top", 20, 10),
            FractalPoint(1, dates[1], "bottom", 10, 5),
            FractalPoint(2, dates[2], "bottom", 10, 2),  # 更低
        ]
        result = filter_and_alternate_fractals(fractals)
        assert len(result) == 2
        assert result[1].low == 2  # 保留低点更低的底分型

    def test_alternating_unchanged(self):
        dates = pd.date_range("2024-01-01", periods=4, freq="D")
        fractals = [
            FractalPoint(0, dates[0], "top", 20, 10),
            FractalPoint(1, dates[1], "bottom", 10, 5),
            FractalPoint(2, dates[2], "top", 25, 12),
            FractalPoint(3, dates[3], "bottom", 10, 3),
        ]
        result = filter_and_alternate_fractals(fractals)
        assert len(result) == 4
