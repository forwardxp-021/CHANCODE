"""chancode.zs – 中枢（Zhongshu）识别。

缠论中枢：三笔的价格区间存在重叠部分，即为中枢。
相邻两个中枢若价格区间也重叠，则合并为同一中枢。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from chancode.bi import Pen


@dataclass
class Zhongshu:
    """中枢：多笔区间交集形成的价格重叠区间。"""

    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    low: float
    high: float


def _range_overlap(
    ranges: List[Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    """计算多个价格区间的交集。若无交集返回 None。"""
    lows, highs = zip(*ranges)
    lo, hi = max(lows), min(highs)
    return (lo, hi) if lo <= hi else None


def detect_zhongshu(pens: List[Pen]) -> List[Zhongshu]:
    """三笔滑窗法识别中枢，并合并价格区间重叠的相邻中枢。

    :param pens: 笔列表
    :returns: 中枢列表
    """
    zhongshus: List[Zhongshu] = []

    for i in range(len(pens) - 2):
        window = pens[i : i + 3]
        overlap = _range_overlap([(p.low, p.high) for p in window])
        if overlap is None:
            continue

        lo, hi = overlap
        candidate = Zhongshu(
            start_idx=window[0].start_idx,
            end_idx=window[-1].end_idx,
            start_datetime=window[0].start_datetime,
            end_datetime=window[-1].end_datetime,
            low=lo,
            high=hi,
        )

        if zhongshus:
            prev_overlap = _range_overlap(
                [(zhongshus[-1].low, zhongshus[-1].high), (candidate.low, candidate.high)]
            )
            if prev_overlap:
                # 合并相邻重叠中枢：价格取交集，时间向右延伸
                last = zhongshus[-1]
                last.end_idx = candidate.end_idx
                last.end_datetime = candidate.end_datetime
                last.low, last.high = prev_overlap
                continue

        zhongshus.append(candidate)

    print(f"[zs] 识别中枢 {len(zhongshus)} 个。")
    return zhongshus
