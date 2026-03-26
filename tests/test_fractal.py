"""tests/test_fractal.py - fractal detection, filtering, and merge mapping."""
from __future__ import annotations

import pandas as pd

from chancode.fractal import (
    detect_fractals,
    cluster_fractals_for_display,
    build_fractals_for_bi,
    map_fractals_to_original,
    merge_klines,
)


def _make_df(highs, lows):
    n = len(highs)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1.0] * n,
        },
        index=dates,
    )


def test_detect_fractal_basic_top_and_bottom():
    df = _make_df([10, 20, 10, 22, 11], [5, 12, 3, 13, 6])
    fractals = detect_fractals(df)
    assert len(fractals) >= 2
    assert any(f.ftype == "top" for f in fractals)
    assert any(f.ftype == "bottom" for f in fractals)


def test_detect_fractals_support_equal_top_and_bottom():
    # 平顶 + 平底：严格不等号会漏标，allow_equal=True 应能识别。
    highs = [10, 12, 12, 9, 8, 8, 11]
    lows = [7, 6, 7, 5, 4, 4, 6]
    df = _make_df(highs, lows)

    fractals = detect_fractals(df, allow_equal=True)
    assert any(f.ftype == "top" for f in fractals)
    assert any(f.ftype == "bottom" for f in fractals)


def test_detect_fractals_requires_range_shape_not_only_single_side():
    # 中间K线只有 high 更高但 low 更低，不应被判为顶分型。
    df = _make_df(
        highs=[10, 12, 11],
        lows=[9, 7, 8],
    )
    fractals = detect_fractals(df, allow_equal=True)
    assert len(fractals) == 0


def test_fractals_all_vs_for_bi_density_and_constraints():
    highs = [10, 13, 11, 14, 12, 15, 13, 16, 12, 17, 11, 18, 10]
    lows = [7, 8, 6, 9, 5, 10, 6, 11, 5, 12, 4, 13, 3]
    df = _make_df(highs, lows)

    raw = detect_fractals(df, allow_equal=True)
    fractals_all = cluster_fractals_for_display(raw, near_gap=1)
    fractals_for_bi = build_fractals_for_bi(
        fractals_all,
        min_separation=2,
        min_pen_separation=4,
    )

    assert len(fractals_all) >= len(fractals_for_bi)
    for i in range(1, len(fractals_for_bi)):
        assert fractals_for_bi[i].ftype != fractals_for_bi[i - 1].ftype
        assert fractals_for_bi[i].idx - fractals_for_bi[i - 1].idx >= 4


def test_merge_mapping_maps_fractal_to_original_axis():
    # 第 2 根与第 3 根构成包含关系，合并后分型应能映射到原始时间轴上的组内位置。
    highs = [10, 12, 11, 13, 9, 14, 8]
    lows = [7, 8, 8.2, 9, 6, 10, 5]
    df = _make_df(highs, lows)

    merge_result = merge_klines(df)
    merged_df = merge_result.merged_df

    raw = detect_fractals(merged_df, allow_equal=True)
    fractals_all = cluster_fractals_for_display(raw, near_gap=1)
    mapped = map_fractals_to_original(fractals_all, merge_result, anchor="right", original_index=df.index)

    assert len(mapped) == len(fractals_all)
    for m in mapped:
        assert 0 <= m.idx < len(df)
        assert m.datetime == df.index[m.idx]
        merged_idx = merge_result.orig_to_merged_index[m.idx]
        assert merged_idx >= 0
        assert m.idx in merge_result.merged_to_original[merged_idx]


def test_map_fractals_to_original_anchor_extreme_uses_group_extrema():
    highs = [10, 12, 11, 13, 9]
    lows = [8, 7.5, 8.5, 9, 7]
    df = _make_df(highs, lows)
    merge_result = merge_klines(df)

    from chancode.fractal import FractalPoint
    # 人工构造一个映射到 merged[0] 的顶分型，期望落到原始组内最高点位置。
    fake = [
        FractalPoint(
            idx=0,
            datetime=merge_result.merged_df.index[0],
            ftype="top",
            high=float(merge_result.merged_df["High"].iloc[0]),
            low=float(merge_result.merged_df["Low"].iloc[0]),
        )
    ]

    mapped = map_fractals_to_original(
        fake,
        merge_result,
        anchor="extreme",
        original_index=df.index,
        original_df=df,
    )
    assert len(mapped) == 1
    group = merge_result.merged_to_original[0]
    expected_idx = max(group, key=lambda i: float(df["High"].iloc[i]))
    assert mapped[0].idx == expected_idx

