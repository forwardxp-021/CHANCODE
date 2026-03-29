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
    min_pivot_separation: int = 2,
    min_segment_pens: int = 3,
) -> List[Segment]:
    """从笔序列识别线段（工程化简化版，接近缠论端点确认思路）。

    规则：
    1) 先在笔序列上找三笔分型确认的端点（顶/底）；
    2) 端点需顶底交替且满足最小笔间隔；
    3) 相邻端点间至少覆盖 min_segment_pens 根笔才形成线段。
    """
    if len(pens) < 5:
        return []

    pivots = _detect_pen_pivots(pens)
    pivots = _filter_alternating_pivots(pivots, min_pen_separation=min_pivot_separation)
    if len(pivots) < 2:
        return []

    min_segment_pens = max(1, int(min_segment_pens))
    segments: List[Segment] = []

    for i in range(len(pivots) - 1):
        a = pivots[i]
        b = pivots[i + 1]

        if a.ptype == b.ptype:
            continue
        if b.pen_idx <= a.pen_idx:
            continue

        covered_pens = b.pen_idx - a.pen_idx + 1
        if covered_pens < min_segment_pens:
            continue

        # 线段由奇数笔构成（起止同向）
        if covered_pens % 2 == 0:
            continue

        seg_pens = pens[a.pen_idx : b.pen_idx + 1]

        # 至少前三笔必须存在价格重叠区间
        if len(seg_pens) < 3:
            continue
        first_three = seg_pens[:3]
        if not _has_overlap([(p.low, p.high) for p in first_three]):
            continue

        direction = "up" if (a.ptype == "bottom" and b.ptype == "top") else "down"

        segment = Segment(
            start_idx=a.idx,
            end_idx=b.idx,
            start_datetime=a.datetime,
            end_datetime=b.datetime,
            start_price=a.price,
            end_price=b.price,
            direction=direction,
            high=max(p.high for p in seg_pens),
            low=min(p.low for p in seg_pens),
            pen_count=covered_pens,
        )
        segments.append(segment)

    print(
        f"[xd] 识别线段 {len(segments)} 条"
        f"（pivot_sep={min_pivot_separation}, min_segment_pens={min_segment_pens}）。"
    )
    return segments
