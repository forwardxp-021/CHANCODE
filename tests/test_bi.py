"""tests/test_bi.py - pen construction rules."""
from __future__ import annotations

import pandas as pd

from chancode.fractal import FractalPoint, MergeKlineResult
from chancode.bi import Pen, build_pens, map_pens_to_original


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


def test_build_pens_rejects_invalid_price_direction():
    fractals = [
        FractalPoint(
            idx=1,
            datetime=pd.Timestamp("2024-01-02"),
            ftype="bottom",
            high=105,
            low=100,
        ),
        FractalPoint(
            idx=5,
            datetime=pd.Timestamp("2024-01-06"),
            ftype="top",
            high=90,
            low=85,
        ),
    ]

    pens = build_pens(fractals, min_kline_count=3)

    assert pens == []


def test_build_pens_standard_distance_boundary():
    fractals = [
        _fractal(1, "bottom", 5),
        _fractal(4, "top", 15),  # gap=3
        _fractal(5, "top", 16),  # gap=4
    ]

    loose = build_pens(fractals, min_kline_count=3)
    standard = build_pens(fractals, min_kline_count=4)

    assert len(loose) == 1
    assert loose[0].end_idx == 4
    assert len(standard) == 1
    assert standard[0].end_idx == 5


def test_map_pens_to_original_uses_group_extreme_endpoint():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    original_df = pd.DataFrame(
        {
            "Open": [10, 11, 9, 8],
            "High": [12, 15, 10, 9],
            "Low": [9, 10, 7, 5],
            "Close": [11, 12, 8, 6],
            "Volume": [1, 1, 1, 1],
        },
        index=dates,
    )
    merged_df = pd.DataFrame(
        {
            "Open": [10, 9],
            "High": [15, 10],
            "Low": [10, 5],
            "Close": [12, 6],
            "Volume": [2, 2],
        },
        index=[dates[0], dates[2]],
    )
    merge_result = MergeKlineResult(
        merged_df=merged_df,
        merged_indices={1, 3},
        merged_boxes=[],
        merged_to_original=[[0, 1], [2, 3]],
        orig_to_merged_index=[0, 0, 1, 1],
    )
    pen = Pen(
        start_idx=0,
        end_idx=1,
        start_datetime=merged_df.index[0],
        end_datetime=merged_df.index[1],
        start_price=15,
        end_price=5,
        high=15,
        low=5,
        start_ftype="top",
        end_ftype="bottom",
    )

    mapped = map_pens_to_original([pen], merge_result, original_df.index, original_df)

    assert len(mapped) == 1
    assert mapped[0].start_idx == 1
    assert mapped[0].start_datetime == dates[1]
    assert mapped[0].start_price == 15
    assert mapped[0].end_idx == 3
    assert mapped[0].end_datetime == dates[3]
    assert mapped[0].end_price == 5
