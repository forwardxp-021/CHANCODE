"""tests/test_zs.py - zhongshu detection and extension."""
from __future__ import annotations

import pandas as pd

from chancode.bi import Pen
from chancode.config import Config
from chancode.xd import Segment
from chancode.zs import detect_zhongshu_with_basis, _range_overlap


_BASE = pd.date_range("2024-01-01", periods=300, freq="D")


def _pen(start_idx: int, end_idx: int, low: float, high: float, up: bool) -> Pen:
    return Pen(
        start_idx=start_idx,
        end_idx=end_idx,
        start_datetime=_BASE[start_idx],
        end_datetime=_BASE[end_idx],
        start_price=low if up else high,
        end_price=high if up else low,
        high=high,
        low=low,
        start_ftype="bottom" if up else "top",
        end_ftype="top" if up else "bottom",
    )


def _segment(start_idx: int, end_idx: int, low: float, high: float, direction: str) -> Segment:
    return Segment(
        start_idx=start_idx,
        end_idx=end_idx,
        start_datetime=_BASE[start_idx],
        end_datetime=_BASE[end_idx],
        start_price=low if direction == "up" else high,
        end_price=high if direction == "up" else low,
        direction=direction,
        high=high,
        low=low,
        pen_count=3,
    )


def test_range_overlap_basic():
    assert _range_overlap([(1, 10), (5, 12), (6, 9)]) == (6, 9)
    assert _range_overlap([(1, 3), (4, 6)]) is None


def test_detect_zhongshu_confirm_and_extend_then_stop():
    # 前 3 笔形成中枢 [10, 20]，第 4 笔仍重叠（扩展），第 5 笔完全脱离（停止）。
    pens = [
        _pen(0, 7, 8, 24, up=True),
        _pen(7, 14, 10, 22, up=False),
        _pen(14, 21, 9, 20, up=True),
        _pen(21, 28, 11, 25, up=False),  # overlap with [10, 20]
        _pen(28, 35, 21, 30, up=True),   # break out, no overlap with [10, 20]
    ]
    zss = detect_zhongshu_with_basis(pens, level="bi")

    assert len(zss) >= 1
    zh = zss[0]
    assert zh.confirm_idx == pens[2].end_idx
    assert zh.end_idx == pens[3].end_idx
    assert zh.low == 10
    assert zh.high == 20


def test_detect_zhongshu_with_segment_basis():
    pens = [
        _pen(0, 7, 8, 24, up=True),
        _pen(7, 14, 10, 22, up=False),
        _pen(14, 21, 9, 20, up=True),
    ]
    segments = [
        _segment(0, 21, 10, 22, "up"),
        _segment(21, 42, 9, 20, "down"),
        _segment(42, 63, 11, 24, "up"),
    ]
    zss = detect_zhongshu_with_basis(pens, segments=segments, level="segment")

    assert len(zss) == 1
    assert zss[0].low == 11
    assert zss[0].high == 20


def test_zhongshu_level_switches_input_path():
    # pens 无三单元重叠，segments 有重叠：用于验证 level 切换是否生效。
    pens = [
        _pen(0, 7, 1, 5, up=True),
        _pen(7, 14, 6, 9, up=False),
        _pen(14, 21, 10, 13, up=True),
    ]
    segments = [
        _segment(0, 21, 10, 22, "up"),
        _segment(21, 42, 9, 20, "down"),
        _segment(42, 63, 11, 24, "up"),
    ]

    bi_cfg = Config(min_bi_separation=7, zhongshu_level="bi")
    seg_cfg = Config(min_bi_separation=7, zhongshu_level="segment")

    zss_bi = detect_zhongshu_with_basis(pens, segments=segments, config=bi_cfg)
    zss_seg = detect_zhongshu_with_basis(pens, segments=segments, config=seg_cfg)

    assert len(zss_bi) == 0
    assert len(zss_seg) == 1
