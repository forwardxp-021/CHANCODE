"""tests/test_bi.py – 测试笔识别。"""
from __future__ import annotations

import pandas as pd
import pytest

from chancode.fractal import FractalPoint
from chancode.bi import Pen, build_pens


def _make_fractals(types_and_prices):
    """快速构建分型列表：types_and_prices = [('top', 20), ('bottom', 5), ...]"""
    dates = pd.date_range("2024-01-01", periods=len(types_and_prices), freq="D")
    result = []
    for i, (ftype, price) in enumerate(types_and_prices):
        if ftype == "top":
            result.append(FractalPoint(i, dates[i], "top", price, price - 2))
        else:
            result.append(FractalPoint(i, dates[i], "bottom", price + 2, price))
    return result


class TestBuildPens:
    def test_empty_input(self):
        assert build_pens([]) == []

    def test_single_fractal(self):
        fractals = _make_fractals([("top", 20)])
        assert build_pens(fractals) == []

    def test_two_fractals_one_pen(self):
        fractals = _make_fractals([("top", 20), ("bottom", 5)])
        pens = build_pens(fractals)
        assert len(pens) == 1
        assert pens[0].direction == "down"

    def test_three_fractals_two_pens(self):
        fractals = _make_fractals([("bottom", 5), ("top", 20), ("bottom", 8)])
        pens = build_pens(fractals)
        assert len(pens) == 2
        assert pens[0].direction == "up"
        assert pens[1].direction == "down"

    def test_pen_direction_property(self):
        fractals = _make_fractals([("bottom", 5), ("top", 20)])
        pen = build_pens(fractals)[0]
        assert pen.is_up is True

    def test_pen_high_low(self):
        fractals = _make_fractals([("bottom", 5), ("top", 20)])
        pen = build_pens(fractals)[0]
        assert pen.high >= pen.low
