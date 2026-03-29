"""tests/test_bi.py - pen construction rules."""
from __future__ import annotations

import pandas as pd

from chancode.fractal import FractalPoint
from chancode.bi import build_pens


def _fractal(idx: int, ftype: str, price: float) -> FractalPoint:
    dt = pd.Timestamp("2024-01-01") + pd.Timedelta(days=idx)
    if ftype == "top":
        return FractalPoint(idx, dt, "top", high=price, low=price - 2)
    return FractalPoint(idx, dt, "bottom", high=price + 2, low=price)


def test_build_pens_requires_min_kline_count():
    fractals = [
        _fractal(1, "bottom", 5),
        _fractal(4, "top", 15),   # gap=3
        _fractal(12, "bottom", 7),
    ]
    pens = build_pens(fractals, min_kline_count=5)
    assert len(pens) == 1
    assert pens[0].start_idx == 4
    assert pens[0].end_idx == 12


def test_build_pens_direction_from_fractal_type():
    fractals = [
        _fractal(1, "bottom", 5),
        _fractal(10, "top", 18),
        _fractal(20, "bottom", 8),
    ]
    pens = build_pens(fractals, min_kline_count=7)
    assert len(pens) == 2
    assert pens[0].direction == "up"
    assert pens[1].direction == "down"


def test_build_pens_have_valid_ranges():
    fractals = [
        _fractal(2, "top", 22),
        _fractal(12, "bottom", 6),
    ]
    pens = build_pens(fractals, min_kline_count=7)
    assert len(pens) == 1
    pen = pens[0]
    assert pen.high >= pen.low
    assert pen.start_datetime < pen.end_datetime


def test_build_pens_min_separation_7_threshold():
    fractals = [
        _fractal(1, "bottom", 5),
        _fractal(7, "top", 15),   # gap=6, should be rejected when threshold=7
        _fractal(15, "top", 18),  # same type replacement candidate
        _fractal(23, "bottom", 7),
    ]

    pens = build_pens(fractals, min_kline_count=7)
    assert len(pens) == 2
    assert pens[0].start_idx == 1
    assert pens[0].end_idx == 15
    assert pens[1].start_idx == 15
    assert pens[1].end_idx == 23
