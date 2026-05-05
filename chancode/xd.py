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

from dataclasses import dataclass, field
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
    is_complete: bool = True
    segment_id: str = ""
    bi_ids: List[int] = field(default_factory=list)

    @property
    def is_up(self) -> bool:
        return self.direction == "up"

    def to_record(self) -> dict[str, object]:
        """输出符合计划表要求的结构化线段记录。"""
        return {
            "id": self.segment_id,
            "type": self.direction,
            "start": self.start_idx,
            "end": self.end_idx,
            "bi_count": self.pen_count,
            "bi_ids": list(self.bi_ids),
            "is_complete": self.is_complete,
        }


@dataclass
class FeatureSequenceElement:
    """特征序列元素（对应缠论第67课线段划分工具）。

    说明：
    1) 向上线段：特征序列取该线段中的向下笔，元素高低点与笔本身一致。
    2) 向下线段：特征序列取该线段中的向上笔，元素高低点反向定义
       （high <- pen.low, low <- pen.high）。
    """

    pen_idx: int
    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    high: float
    low: float
    source_pen_direction: str


@dataclass
class SegmentBreakResult:
    """线段破坏确认结果（对应第77/78课中的两类破坏）。"""

    confirmed: bool
    break_type: str  # "none" | "first" | "second"
    anchor_pen_idx: Optional[int] = None
    anchor_idx: Optional[int] = None
    anchor_datetime: Optional[pd.Timestamp] = None
    anchor_price: Optional[float] = None
    confirm_pen_idx: Optional[int] = None
    confirm_idx: Optional[int] = None
    confirm_datetime: Optional[pd.Timestamp] = None
    confirm_price: Optional[float] = None


def _build_feature_sequence(
    pens: List[Pen],
    start_idx: int,
    end_idx: int,
    segment_type: str,
) -> List[FeatureSequenceElement]:
    """构建线段特征序列 S（第67课）。

    参数：
    - segment_type='up'：提取向下笔，元素高低点与笔一致。
    - segment_type='down'：提取向上笔，元素高低点按原著反向定义。

    返回值按时间顺序排列。
    """
    if not pens:
        return []

    seg_type = (segment_type or "").strip().lower()
    if seg_type not in {"up", "down"}:
        raise ValueError("segment_type must be 'up' or 'down'")

    s = max(0, int(start_idx))
    e = min(len(pens) - 1, int(end_idx))
    if s > e:
        return []

    elements: List[FeatureSequenceElement] = []
    for i in range(s, e + 1):
        p = pens[i]

        # 向上线段特征序列取向下笔；向下线段特征序列取向上笔。
        if seg_type == "up" and p.is_up:
            continue
        if seg_type == "down" and (not p.is_up):
            continue

        if seg_type == "up":
            elem_high, elem_low = p.high, p.low
        else:
            # 第67课：向下线段特征序列元素高低点反向定义。
            elem_high, elem_low = p.low, p.high

        elements.append(
            FeatureSequenceElement(
                pen_idx=i,
                start_idx=p.start_idx,
                end_idx=p.end_idx,
                start_datetime=p.start_datetime,
                end_datetime=p.end_datetime,
                high=elem_high,
                low=elem_low,
                source_pen_direction=("up" if p.is_up else "down"),
            )
        )

    return elements


def _is_alternating_pens(pens: List[Pen]) -> bool:
    if len(pens) < 2:
        return True
    return all(pens[i].is_up != pens[i + 1].is_up for i in range(len(pens) - 1))


def _has_include(a: FeatureSequenceElement, b: FeatureSequenceElement) -> bool:
    """判断两个特征序列元素是否存在包含关系。"""
    return (a.high >= b.high and a.low <= b.low) or (b.high >= a.high and b.low <= a.low)


def _merge_feature_elements(
    left: FeatureSequenceElement,
    right: FeatureSequenceElement,
    segment_type: str,
) -> FeatureSequenceElement:
    """按线段方向合并包含关系元素。

    - 向上线段：合并后 high=max, low=min
    - 向下线段：合并后 high=min, low=max（第67课反向合并）
    """
    seg_type = (segment_type or "").strip().lower()
    if seg_type not in {"up", "down"}:
        raise ValueError("segment_type must be 'up' or 'down'")

    if seg_type == "up":
        merged_high = max(left.high, right.high)
        merged_low = min(left.low, right.low)
    else:
        merged_high = min(left.high, right.high)
        merged_low = max(left.low, right.low)

    # 以时间更左的元素作为合并锚点，保持左到右处理与顺序稳定。
    base = left if left.start_datetime <= right.start_datetime else right
    tail = right if base is left else left
    return FeatureSequenceElement(
        pen_idx=min(left.pen_idx, right.pen_idx),
        start_idx=min(left.start_idx, right.start_idx),
        end_idx=max(left.end_idx, right.end_idx),
        start_datetime=min(left.start_datetime, right.start_datetime),
        end_datetime=max(left.end_datetime, right.end_datetime),
        high=merged_high,
        low=merged_low,
        source_pen_direction=base.source_pen_direction or tail.source_pen_direction,
    )


def _handle_feature_sequence_include(
    feature_seq: List[FeatureSequenceElement],
    segment_type: str,
) -> List[FeatureSequenceElement]:
    """处理特征序列包含关系（第67课）。

    规则：
    1) 从左到右处理相邻元素；
    2) 若相邻元素存在包含关系，则按线段方向进行合并；
    3) 合并后继续检查新的相邻关系，直至无包含关系为止。
    """
    if len(feature_seq) <= 1:
        return list(feature_seq)

    seq = sorted(feature_seq, key=lambda x: (x.start_datetime, x.end_datetime, x.pen_idx))

    changed = True
    while changed:
        changed = False
        out: List[FeatureSequenceElement] = []
        i = 0
        while i < len(seq):
            if i == len(seq) - 1:
                out.append(seq[i])
                i += 1
                continue

            a, b = seq[i], seq[i + 1]
            if _has_include(a, b):
                out.append(_merge_feature_elements(a, b, segment_type))
                changed = True
                i += 2
            else:
                out.append(a)
                i += 1

        seq = out

    return seq


def _make_segment_from_pens(
    seg_pens: List[Pen],
    segment_type: str,
    segment_id: str,
    bi_ids: List[int],
    is_complete: bool,
) -> Segment:
    return Segment(
        start_idx=seg_pens[0].start_idx,
        end_idx=seg_pens[-1].end_idx,
        start_datetime=seg_pens[0].start_datetime,
        end_datetime=seg_pens[-1].end_datetime,
        start_price=seg_pens[0].start_price,
        end_price=seg_pens[-1].end_price,
        direction=segment_type,
        high=max(p.high for p in seg_pens),
        low=min(p.low for p in seg_pens),
        pen_count=len(seg_pens),
        is_complete=is_complete,
        segment_id=segment_id,
        bi_ids=list(bi_ids),
    )


def _feature_element_price_range(elem: FeatureSequenceElement) -> tuple[float, float]:
    """返回元素的标准化价格区间 [low, high]。"""
    lo = min(elem.high, elem.low)
    hi = max(elem.high, elem.low)
    return lo, hi


def _has_gap_between_feature_elements(
    left: FeatureSequenceElement,
    right: FeatureSequenceElement,
) -> bool:
    """判断两个特征序列元素间是否存在缺口（无价格重叠）。"""
    l_lo, l_hi = _feature_element_price_range(left)
    r_lo, r_hi = _feature_element_price_range(right)
    return l_hi < r_lo or r_hi < l_lo


def _detect_feature_sequence_fractals(
    feature_seq: List[FeatureSequenceElement],
) -> List[tuple[int, str]]:
    """在特征序列中识别分型，返回 (元素下标, 分型类型)。"""
    out: List[tuple[int, str]] = []
    if len(feature_seq) < 3:
        return out

    highs = [max(x.high, x.low) for x in feature_seq]
    lows = [min(x.high, x.low) for x in feature_seq]

    for i in range(1, len(feature_seq) - 1):
        prev_hi, cur_hi, next_hi = highs[i - 1], highs[i], highs[i + 1]
        prev_lo, cur_lo, next_lo = lows[i - 1], lows[i], lows[i + 1]

        is_top = cur_hi >= prev_hi and cur_hi >= next_hi and (cur_hi > prev_hi or cur_hi > next_hi)
        is_bottom = cur_lo <= prev_lo and cur_lo <= next_lo and (cur_lo < prev_lo or cur_lo < next_lo)

        if is_top and not is_bottom:
            out.append((i, "top"))
        elif is_bottom and not is_top:
            out.append((i, "bottom"))

    return out


def assess_segment_break_by_feature_sequence(
    pens: List[Pen],
    start_idx: int,
    end_idx: int,
    segment_type: str,
) -> SegmentBreakResult:
    """按特征序列规则评估线段破坏类型。

    规则实现：
    1) 先构建并处理包含关系后的特征序列；
    2) 反向特征序列出现首个分型时，检查前两元素是否有缺口；
       - 无缺口：第一类破坏，立即确认；
       - 有缺口：标记候选，需等待后续反向分型确认；
    3) 第二类破坏确认后，结束点和新起点均回到“最初分型顶点”（即首个分型顶点）。
    """
    raw_seq = _build_feature_sequence(pens, start_idx, end_idx, segment_type)
    seq = _handle_feature_sequence_include(raw_seq, segment_type)
    if len(seq) < 3:
        return SegmentBreakResult(confirmed=False, break_type="none")

    fractals = _detect_feature_sequence_fractals(seq)
    if not fractals:
        return SegmentBreakResult(confirmed=False, break_type="none")

    first_fractal_idx, _ = fractals[0]
    anchor = seq[first_fractal_idx]
    anchor_price = anchor.high if segment_type == "up" else anchor.low

    # 口径：前二元素无缺口 => 第一类破坏；有缺口 => 需等待后续反向分型确认。
    first_two_has_gap = _has_gap_between_feature_elements(seq[0], seq[1]) if len(seq) >= 2 else False

    if not first_two_has_gap:
        return SegmentBreakResult(
            confirmed=True,
            break_type="first",
            anchor_pen_idx=anchor.pen_idx,
            anchor_idx=anchor.end_idx,
            anchor_datetime=anchor.end_datetime,
            anchor_price=anchor_price,
            confirm_pen_idx=anchor.pen_idx,
            confirm_idx=anchor.end_idx,
            confirm_datetime=anchor.end_datetime,
            confirm_price=anchor_price,
        )

    if len(fractals) < 2:
        return SegmentBreakResult(
            confirmed=False,
            break_type="none",
            anchor_pen_idx=anchor.pen_idx,
            anchor_idx=anchor.end_idx,
            anchor_datetime=anchor.end_datetime,
            anchor_price=anchor_price,
        )

    confirm_idx, _ = fractals[1]
    confirm = seq[confirm_idx]
    confirm_price = confirm.high if segment_type == "up" else confirm.low

    return SegmentBreakResult(
        confirmed=True,
        break_type="second",
        anchor_pen_idx=anchor.pen_idx,
        anchor_idx=anchor.end_idx,
        anchor_datetime=anchor.end_datetime,
        anchor_price=anchor_price,
        confirm_pen_idx=confirm.pen_idx,
        confirm_idx=confirm.end_idx,
        confirm_datetime=confirm.end_datetime,
        confirm_price=confirm_price,
    )


class SegmentIdentifier:
    """结构化线段识别入口。

    该类保留现有函数式 API，同时提供可序列化输出，便于计划表中的
    输入/输出规范、代码结构建议与文档示例统一落点。
    """

    def __init__(self, min_segment_pens: int = 3, include_incomplete_tail: bool = False) -> None:
        self.min_segment_pens = max(3, int(min_segment_pens))
        self.include_incomplete_tail = bool(include_incomplete_tail)

    @staticmethod
    def build_feature_sequence(
        pens: List[Pen],
        start_idx: int,
        end_idx: int,
        segment_type: str,
    ) -> List[FeatureSequenceElement]:
        return _build_feature_sequence(pens, start_idx, end_idx, segment_type)

    @staticmethod
    def handle_feature_sequence_include(
        feature_seq: List[FeatureSequenceElement],
        segment_type: str,
    ) -> List[FeatureSequenceElement]:
        return _handle_feature_sequence_include(feature_seq, segment_type)

    @staticmethod
    def detect_feature_sequence_fractals(
        feature_seq: List[FeatureSequenceElement],
    ) -> List[tuple[int, str]]:
        return _detect_feature_sequence_fractals(feature_seq)

    @staticmethod
    def assess_break(
        pens: List[Pen],
        start_idx: int,
        end_idx: int,
        segment_type: str,
    ) -> SegmentBreakResult:
        return assess_segment_break_by_feature_sequence(pens, start_idx, end_idx, segment_type)

    def build_segments(self, pens: List[Pen]) -> List[Segment]:
        return build_segments(
            pens,
            min_segment_pens=self.min_segment_pens,
            include_incomplete_tail=self.include_incomplete_tail,
        )

    def build_segment_records(self, pens: List[Pen]) -> List[dict[str, object]]:
        return [segment.to_record() for segment in self.build_segments(pens)]

    @staticmethod
    def identify_from_bi_list(
        bi_list: List[Pen],
        min_segment_pens: int = 3,
        include_incomplete_tail: bool = False,
    ) -> List[Segment]:
        return build_segments(
            bi_list,
            min_segment_pens=min_segment_pens,
            include_incomplete_tail=include_incomplete_tail,
        )

    @staticmethod
    def segment_records_from_bi_list(
        bi_list: List[Pen],
        min_segment_pens: int = 3,
        include_incomplete_tail: bool = False,
    ) -> List[dict[str, object]]:
        segments = build_segments(
            bi_list,
            min_segment_pens=min_segment_pens,
            include_incomplete_tail=include_incomplete_tail,
        )
        return [segment.to_record() for segment in segments]


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
    include_incomplete_tail: bool = False,
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
    segment_seq = 1
    last_complete_end: Optional[int] = None

    while i + 2 < len(pens):
        # 需要前三笔方向交替
        if not (
            pens[i].is_up != pens[i + 1].is_up
            and pens[i + 1].is_up != pens[i + 2].is_up
            and pens[i].is_up == pens[i + 2].is_up
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
        segment = _make_segment_from_pens(
            seg_pens,
            base_dir,
            f"SEG{segment_seq:03d}",
            list(range(i, best_end + 1)),
            True,
        )
        segments.append(segment)
        segment_seq += 1
        last_complete_end = best_end

        # 允许下一段从倒数第二笔开始尝试，避免错过跨界重叠
        i = best_end - 1

    if include_incomplete_tail:
        tail_start = 0 if last_complete_end is None else max(last_complete_end - 1, 0)
        tail_pens = pens[tail_start:]
        if len(tail_pens) >= 2:
            tail_dir = "up" if tail_pens[0].is_up else "down"
            segments.append(
                _make_segment_from_pens(
                    tail_pens,
                    tail_dir,
                    f"SEG{segment_seq:03d}",
                    list(range(tail_start, len(pens))),
                    False,
                )
            )

    print(f"[xd] 识别线段 {len(segments)} 条（min_segment_pens={min_segment_pens}）。")
    return segments


def build_segment_records(
    pens: List[Pen],
    min_segment_pens: int = 3,
    include_incomplete_tail: bool = False,
) -> List[dict[str, object]]:
    """返回符合 II.1.2 规范的结构化线段列表。"""
    return [
        segment.to_record()
        for segment in build_segments(
            pens,
            min_segment_pens=min_segment_pens,
            include_incomplete_tail=include_incomplete_tail,
        )
    ]
