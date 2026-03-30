"""chancode.xd – 线段（Segment）识别。

缠论线段构成规则（简化版）：
  - 至少由 3 笔组成（奇数笔序列：同向笔/反向笔/同向笔…）
  - 最后一笔（与第一笔同向）必须突破第一笔的极值
    * 上升线段：最后一根同向上升笔的高点 > 第一根上升笔的高点
    * 下降线段：最后一根同向下降笔的低点 < 第一根下降笔的低点
  - 可逐步延伸（5 笔、7 笔…），每次延伸要求新的同向笔继续突破

线段检测采用贪心算法，从序列最左端开始，尽量向右延伸当前线段，
确认后移到下一个起始点。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from chancode.bi import Pen


@dataclass
class Segment:
    """线段：由至少 3 笔组成、方向明确的价格走势。"""

    start_idx: int          # 对应 df 行索引（笔的起点分型索引）
    end_idx: int            # 对应 df 行索引（笔的终点分型索引）
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    start_price: float
    end_price: float
    direction: str          # "up" 或 "down"
    high: float
    low: float
    pen_count: int          # 组成该线段的笔数

    @property
    def is_up(self) -> bool:
        return self.direction == "up"


@dataclass
class _PenPivot:
    """由笔序列确认出的转折点（线段端点候选）。"""

    ptype: str  # "top" or "bottom"
    pen_idx: int
    idx: int
    datetime: pd.Timestamp
    price: float


def _is_more_extreme_pivot(curr: _PenPivot, ref: _PenPivot) -> bool:
    if curr.ptype != ref.ptype:
        return False
    if curr.ptype == "top":
        return curr.price > ref.price
    return curr.price < ref.price


def _detect_pen_pivots(pens: List[Pen]) -> List[_PenPivot]:
    """使用三笔分型法确认笔级转折点。"""
    pivots: List[_PenPivot] = []
    for i in range(1, len(pens) - 1):
        prev_pen = pens[i - 1]
        cur_pen = pens[i]
        next_pen = pens[i + 1]

        is_top = (
            cur_pen.high >= prev_pen.high
            and cur_pen.high >= next_pen.high
            and (cur_pen.high > prev_pen.high or cur_pen.high > next_pen.high)
        )
        is_bottom = (
            cur_pen.low <= prev_pen.low
            and cur_pen.low <= next_pen.low
            and (cur_pen.low < prev_pen.low or cur_pen.low < next_pen.low)
        )

        if not (is_top or is_bottom):
            continue

        if is_top and not is_bottom:
            pivots.append(
                _PenPivot(
                    ptype="top",
                    pen_idx=i,
                    idx=cur_pen.end_idx,
                    datetime=cur_pen.end_datetime,
                    price=cur_pen.high,
                )
            )
        elif is_bottom and not is_top:
            pivots.append(
                _PenPivot(
                    ptype="bottom",
                    pen_idx=i,
                    idx=cur_pen.end_idx,
                    datetime=cur_pen.end_datetime,
                    price=cur_pen.low,
                )
            )

    return pivots


def _filter_alternating_pivots(
    pivots: List[_PenPivot],
    min_pen_separation: int,
) -> List[_PenPivot]:
    """去重并约束端点间最小笔间隔，减少震荡噪声。"""
    if not pivots:
        return []

    min_pen_separation = max(1, int(min_pen_separation))
    filtered: List[_PenPivot] = []

    for p in pivots:
        if not filtered:
            filtered.append(p)
            continue

        last = filtered[-1]
        if p.ptype == last.ptype:
            if _is_more_extreme_pivot(p, last):
                filtered[-1] = p
            continue

        if (p.pen_idx - last.pen_idx) < min_pen_separation:
            continue

        filtered.append(p)

    return filtered


def _has_overlap(intervals: List[tuple[float, float]]) -> bool:
    """Check whether multiple price intervals have non-empty intersection."""
    if not intervals:
        return False
    lo = max(i[0] for i in intervals)
    hi = min(i[1] for i in intervals)
    return lo <= hi


def build_segments(
    pens: List[Pen],
    min_segment_pens: int = 3,
) -> List[Segment]:
    """严格按文档核心要点划分线段。

    规则实现要点（对应文档“至少三笔且前三笔重叠、奇数笔、首尾同向且末笔突破首笔极值”）：
    1) 笔方向必须上下交替；
    2) 至少三笔，前三笔必须有价格重叠区间；
    3) 总笔数必须为奇数且首尾同向；
    4) 对于向上段，最后一根同向笔的高点必须高于第一根同向笔的高点；向下段反之；
    5) 使用贪心：从最左端起，找出满足条件的最长段，然后从该段倒数第二笔处继续尝试，确保连续划分。
    """
    if len(pens) < 3:
        return []

    min_segment_pens = max(3, int(min_segment_pens))  # 文档至少三笔
    segments: List[Segment] = []
    i = 0

    while i + 2 < len(pens):
        # 需要前三笔方向交替
        if not (
            pens[i].is_up != pens[i + 1].is_up
            and pens[i + 1].is_up != pens[i + 2].is_up
            and pens[i].is_up != pens[i + 2].is_up
        ):
            i += 1
            continue

        # 前三笔必须有价格重叠
        first_three = pens[i : i + 3]
        if not _has_overlap([(p.low, p.high) for p in first_three]):
            i += 1
            continue

        base_dir = "up" if pens[i].is_up else "down"
        base_extreme = pens[i].high if base_dir == "up" else pens[i].low

        best_end = None

        # 贪心向右扩展，要求奇数笔、首尾同向、末笔突破首笔极值
        for j in range(i + 2, len(pens)):
            seg_len = j - i + 1

            # 必须交替方向
            if pens[j].is_up == pens[j - 1].is_up:
                break

            # 必须奇数笔且首尾同向
            if seg_len % 2 == 1 and pens[j].is_up == pens[i].is_up:
                last_extreme = pens[j].high if base_dir == "up" else pens[j].low
                if (base_dir == "up" and last_extreme > base_extreme) or (
                    base_dir == "down" and last_extreme < base_extreme
                ):
                    best_end = j

        if best_end is None or (best_end - i + 1) < min_segment_pens:
            i += 1
            continue

        seg_pens = pens[i : best_end + 1]
        segment = Segment(
            start_idx=seg_pens[0].start_idx,
            end_idx=seg_pens[-1].end_idx,
            start_datetime=seg_pens[0].start_datetime,
            end_datetime=seg_pens[-1].end_datetime,
            start_price=seg_pens[0].start_price,
            end_price=seg_pens[-1].end_price,
            direction=base_dir,
            high=max(p.high for p in seg_pens),
            low=min(p.low for p in seg_pens),
            pen_count=len(seg_pens),
        )
        segments.append(segment)

        # 允许下一段从倒数第二笔开始尝试，避免错过跨界重叠
        i = best_end - 1

    print(f"[xd] 识别线段 {len(segments)} 条（min_segment_pens={min_segment_pens}）。")
    return segments
