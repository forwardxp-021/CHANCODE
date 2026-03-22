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
from typing import List

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


def build_segments(pens: List[Pen]) -> List[Segment]:
    """从笔序列中识别线段。

    算法说明：
    1. 从位置 i 开始，确定第一笔方向（is_up）。
    2. 向右每隔 2 步（同向笔）检查是否突破第一笔极值，记录最远有效端点。
    3. 若找到有效端点，生成线段对象，i 跳过该线段继续；否则 i += 1 重试。
    4. 重复直到剩余笔不足 3 条。

    :param pens: 笔列表（应已交替方向）
    :returns: 线段列表
    """
    if len(pens) < 3:
        return []

    segments: List[Segment] = []
    i = 0

    while i < len(pens) - 2:
        pen0 = pens[i]
        is_up = pen0.is_up

        seg_end: Optional[int] = None  # 当前找到的最远有效终点（笔列表索引）

        # 第一笔的极值（用于突破判断）
        first_extreme = pen0.high if is_up else pen0.low

        j = i + 2  # 步长 2：跳过反向笔，落在同向笔上
        while j < len(pens):
            pen_j = pens[j]

            # 同向笔方向应与 pen0 一致（由交替分型保证）
            # 如不一致（数据异常），停止延伸
            if pen_j.is_up != is_up:
                break

            if is_up and pen_j.high > first_extreme:
                seg_end = j
                # 继续尝试延伸（贪心）
            elif not is_up and pen_j.low < first_extreme:
                seg_end = j

            j += 2  # 继续检查下一个同向笔

        if seg_end is not None:
            end_pen = pens[seg_end]
            seg_pens = pens[i : seg_end + 1]
            segment = Segment(
                start_idx=pen0.start_idx,
                end_idx=end_pen.end_idx,
                start_datetime=pen0.start_datetime,
                end_datetime=end_pen.end_datetime,
                start_price=pen0.start_price,
                end_price=end_pen.end_price,
                direction="up" if is_up else "down",
                high=max(p.high for p in seg_pens),
                low=min(p.low for p in seg_pens),
                pen_count=len(seg_pens),
            )
            segments.append(segment)
            i = seg_end + 1  # 下一线段从当前线段终点后开始
        else:
            i += 1  # 无法从 i 开始形成线段，往前移一步

    print(f"[xd] 识别线段 {len(segments)} 条。")
    return segments
