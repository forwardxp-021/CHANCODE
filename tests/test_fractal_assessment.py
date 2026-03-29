"""tests/test_fractal_assessment.py - 分型质量评估测试。"""
from __future__ import annotations

import pandas as pd

from chancode.fractal import FractalPoint, assess_fractals


def _make_df(highs, lows, opens=None, closes=None):
    n = len(highs)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    if opens is None:
        opens = [(h + l) / 2 for h, l in zip(highs, lows)]
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1.0] * n,
        },
        index=dates,
    )


def test_assess_fractal_strength_distinguishes_strong_top():
    # i=1 为顶分型，第三根为明显阴线并收于中轴下方，应偏强。
    highs = [10, 15, 13, 12, 11]
    lows = [8, 11, 10, 9, 8]
    opens = [9, 12, 12.8, 10.5, 9.5]
    closes = [9.2, 13.5, 10.2, 9.8, 8.8]
    df = _make_df(highs, lows, opens=opens, closes=closes)

    fractals = [FractalPoint(idx=1, datetime=df.index[1], ftype="top", high=15.0, low=11.0)]
    out = assess_fractals(df, fractals, lookahead_bars=3)

    assert len(out) == 1
    assert out[0].strength_score > 45
    assert out[0].strength_level in {"medium", "strong"}


def test_assess_fractal_structure_label_continuation_and_reversal():
    # 顶分型后创新高 => continuation
    df1 = _make_df(
        highs=[10, 14, 13, 15, 16],
        lows=[8, 10, 9, 11, 12],
    )
    f1 = [FractalPoint(idx=1, datetime=df1.index[1], ftype="top", high=14.0, low=10.0)]
    a1 = assess_fractals(df1, f1, lookahead_bars=3)
    assert a1[0].structure_label == "continuation"

    # 顶分型后不创新高但跌破分型低点 => reversal
    df2 = _make_df(
        highs=[10, 14, 13, 13.5, 13.2],
        lows=[8, 10, 9, 8.5, 8.0],
    )
    f2 = [FractalPoint(idx=1, datetime=df2.index[1], ftype="top", high=14.0, low=10.0)]
    a2 = assess_fractals(df2, f2, lookahead_bars=3)
    assert a2[0].structure_label == "reversal"


def test_assess_fractal_lower_level_confirmation():
    df = _make_df(
        highs=[10, 14, 13, 12, 11, 10],
        lows=[8, 10, 9, 8, 7, 6],
    )
    parent = [FractalPoint(idx=1, datetime=df.index[1], ftype="top", high=14.0, low=10.0)]

    # 次级别在窗口内出现反向(bottom)分型 => confirmed
    lower_ok = [
        FractalPoint(idx=3, datetime=df.index[3], ftype="bottom", high=12.0, low=8.0)
    ]
    out_ok = assess_fractals(
        df,
        parent,
        lookahead_bars=4,
        lower_level_fractals=lower_ok,
        lower_level_gap_bars=4,
    )
    assert out_ok[0].lower_level_confirmed is True

    # 只有同向(top)或超窗，不确认
    lower_no = [
        FractalPoint(idx=3, datetime=df.index[3], ftype="top", high=12.0, low=8.0)
    ]
    out_no = assess_fractals(
        df,
        parent,
        lookahead_bars=4,
        lower_level_fractals=lower_no,
        lower_level_gap_bars=4,
    )
    assert out_no[0].lower_level_confirmed is False
