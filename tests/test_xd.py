"""tests/test_xd.py - segment detection from pens."""
from __future__ import annotations

import pandas as pd

from chancode.bi import Pen
from chancode.xd import (
    _build_feature_sequence,
    _handle_feature_sequence_include,
    assess_segment_break_by_feature_sequence,
    build_segments,
    build_segment_records,
    SegmentIdentifier,
)


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
    short = [_pen(0, 0, 8, 10, 20), _pen(1, 8, 16, 20, 12)]
    assert build_segments(short) == []


def test_build_segments_detects_basic_alternating_triplet():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 24),
    ]
    segments = build_segments(pens)
    assert len(segments) == 1
    assert segments[0].direction == "up"
    assert segments[0].start_idx == pens[0].start_idx
    assert segments[0].end_idx == pens[2].end_idx


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
    segments = build_segments(pens, min_segment_pens=3)

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


def test_build_segment_records_exports_required_fields():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 24),
    ]
    records = build_segment_records(pens)

    assert len(records) == 1
    record = records[0]
    assert set(record) >= {"id", "type", "start", "end", "bi_count", "bi_ids", "is_complete"}
    assert record["type"] == "up"
    assert record["bi_count"] == 3
    assert record["bi_ids"] == [0, 1, 2]


def test_build_segments_can_emit_incomplete_tail():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 18),
    ]
    segments = build_segments(pens, include_incomplete_tail=True)

    assert len(segments) == 1
    assert segments[0].is_complete is False
    assert segments[0].pen_count == 3
    assert segments[0].segment_id == "SEG001"


def test_segment_identifier_wrapper_matches_function_api():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 24),
    ]
    identifier = SegmentIdentifier(min_segment_pens=3)
    segments = identifier.build_segments(pens)
    records = identifier.build_segment_records(pens)

    assert len(segments) == 1
    assert len(records) == 1
    assert records[0]["id"] == segments[0].segment_id
    assert records[0]["bi_ids"] == [0, 1, 2]


def test_feature_sequence_up_uses_down_pens():
    pens = [
        _pen(0, 0, 8, 10, 20),   # up
        _pen(1, 8, 16, 20, 12),  # down
        _pen(2, 16, 24, 12, 24), # up
        _pen(3, 24, 32, 24, 14), # down
    ]
    fs = _build_feature_sequence(pens, 0, 3, "up")
    assert len(fs) == 2
    assert [x.pen_idx for x in fs] == [1, 3]
    assert fs[0].high == pens[1].high
    assert fs[0].low == pens[1].low
    assert fs[1].high == pens[3].high
    assert fs[1].low == pens[3].low


def test_feature_sequence_down_uses_up_pens_with_reversed_high_low():
    pens = [
        _pen(0, 0, 8, 10, 20),   # up
        _pen(1, 8, 16, 20, 12),  # down
        _pen(2, 16, 24, 12, 24), # up
    ]
    fs = _build_feature_sequence(pens, 0, 2, "down")
    assert len(fs) == 2
    assert [x.pen_idx for x in fs] == [0, 2]
    # 向下线段特征序列元素高低点反向定义
    assert fs[0].high == pens[0].low
    assert fs[0].low == pens[0].high
    assert fs[1].high == pens[2].low
    assert fs[1].low == pens[2].high


def test_feature_sequence_keeps_time_order():
    pens = [
        _pen(0, 0, 8, 10, 20),
        _pen(1, 8, 16, 20, 12),
        _pen(2, 16, 24, 12, 24),
        _pen(3, 24, 32, 24, 14),
        _pen(4, 32, 40, 14, 26),
    ]
    fs = _build_feature_sequence(pens, 0, 4, "up")
    assert [x.start_datetime for x in fs] == sorted(x.start_datetime for x in fs)


def test_feature_sequence_include_merge_up_rule_max_min():
    # up 段使用向下笔作为特征序列，包含合并应 high=max, low=min
    pens = [
        _pen(0, 0, 8, 10, 20),   # up
        _pen(1, 8, 16, 20, 12),  # down -> high=20, low=12
        _pen(2, 16, 24, 12, 24), # up
        _pen(3, 24, 32, 18, 14), # down -> high=18, low=14 (被上一个包含)
    ]
    fs = _build_feature_sequence(pens, 0, 3, "up")
    merged = _handle_feature_sequence_include(fs, "up")
    assert len(merged) == 1
    assert merged[0].high == 20
    assert merged[0].low == 12


def test_feature_sequence_include_merge_down_rule_min_max():
    # down 段使用向上笔，且元素高低反向定义；包含合并应 high=min, low=max
    pens = [
        _pen(0, 0, 8, 10, 20),   # up -> elem high=10 low=20
        _pen(1, 8, 16, 20, 12),  # down
        _pen(2, 16, 24, 12, 18), # up -> elem high=12 low=18 (被前者包含)
    ]
    fs = _build_feature_sequence(pens, 0, 2, "down")
    merged = _handle_feature_sequence_include(fs, "down")
    assert len(merged) == 1
    assert merged[0].high == 10
    assert merged[0].low == 20


def test_feature_sequence_include_iterative_until_no_include():
    # A 包含 B，A+B 再包含 C，需要两轮收敛到一个元素。
    pens = [
        _pen(0, 0, 8, 10, 20),   # up
        _pen(1, 8, 16, 20, 12),  # down -> [12,20]
        _pen(2, 16, 24, 12, 24), # up
        _pen(3, 24, 32, 18, 14), # down -> [14,18] 被前者包含
        _pen(4, 32, 40, 14, 26), # up
        _pen(5, 40, 48, 19, 13), # down -> [13,19] 仍被合并结果包含
    ]
    fs = _build_feature_sequence(pens, 0, 5, "up")
    merged = _handle_feature_sequence_include(fs, "up")
    assert len(merged) == 1
    assert merged[0].high == 20
    assert merged[0].low == 12


def test_first_break_confirmed_without_gap_and_anchor_equals_confirm():
    pens = [
        _pen(0, 0, 8, 10, 22),
        _pen(1, 8, 16, 20, 10),  # down -> [10,20]
        _pen(2, 16, 24, 12, 24),
        _pen(3, 24, 32, 26, 12), # down -> [12,26] first fractal anchor
        _pen(4, 32, 40, 13, 25),
        _pen(5, 40, 48, 21, 11), # down -> [11,21]
    ]

    result = assess_segment_break_by_feature_sequence(pens, 0, len(pens) - 1, "up")
    assert result.confirmed is True
    assert result.break_type == "first"
    # 4.2: 第一类破坏时结束点/新起点即该分型顶点。
    assert result.anchor_pen_idx == 3
    assert result.confirm_pen_idx == result.anchor_pen_idx
    assert result.confirm_idx == result.anchor_idx


def test_second_break_with_gap_waits_for_next_reverse_fractal():
    pens = [
        _pen(0, 0, 8, 10, 22),
        _pen(1, 8, 16, 30, 20),  # down -> [20,30]
        _pen(2, 16, 24, 12, 24),
        _pen(3, 24, 32, 15, 10), # down -> [10,15] first fractal anchor (with gap)
        _pen(4, 32, 40, 13, 25),
        _pen(5, 40, 48, 16, 12), # down -> [12,16]
    ]

    result = assess_segment_break_by_feature_sequence(pens, 0, len(pens) - 1, "up")
    assert result.confirmed is False
    assert result.break_type == "none"
    assert result.anchor_pen_idx == 3
    assert result.confirm_pen_idx is None


def test_second_break_confirmed_but_endpoint_stays_on_initial_anchor():
    pens = [
        _pen(0, 0, 8, 10, 22),
        _pen(1, 8, 16, 30, 20),  # down -> [20,30]
        _pen(2, 16, 24, 12, 24),
        _pen(3, 24, 32, 15, 10), # down -> [10,15] first fractal anchor
        _pen(4, 32, 40, 13, 25),
        _pen(5, 40, 48, 16, 12), # down -> [12,16]
        _pen(6, 48, 56, 14, 27),
        _pen(7, 56, 64, 14, 8),  # down -> [8,14] second fractal confirm
        _pen(8, 64, 72, 15, 29),
        _pen(9, 72, 80, 18, 13), # down -> [13,18]
    ]

    result = assess_segment_break_by_feature_sequence(pens, 0, len(pens) - 1, "up")
    assert result.confirmed is True
    assert result.break_type == "second"
    assert result.anchor_pen_idx == 3
    assert result.confirm_pen_idx is not None
    assert result.confirm_pen_idx != result.anchor_pen_idx
    # 5.2: 第二类破坏确认后，结束点/新起点仍在最初分型顶点。
    assert result.anchor_idx is not None
    assert result.confirm_idx is not None
    assert result.anchor_idx != result.confirm_idx
