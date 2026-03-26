"""chancode.zs – 中枢（Zhongshu）识别。

缠论中枢：三笔的价格区间存在重叠部分，即为中枢。
相邻两个中枢若价格区间也重叠，则合并为同一中枢。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import pandas as pd

from chancode.bi import Pen
from chancode.xd import Segment
from chancode.config import Config


@dataclass
class Zhongshu:
    """中枢：多笔区间交集形成的价格重叠区间。"""

    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    low: float
    high: float
    confirm_idx: int = -1
    confirm_datetime: Optional[pd.Timestamp] = None


def _range_overlap(
    ranges: List[Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    """计算多个价格区间的交集。若无交集返回 None。"""
    lows, highs = zip(*ranges)
    lo, hi = max(lows), min(highs)
    return (lo, hi) if lo <= hi else None


def detect_zhongshu(pens: List[Pen]) -> List[Zhongshu]:
    """识别中枢（默认按笔中枢）。

    中枢确认与扩展规则：
    1) 至少 3 个单元（笔或线段）区间存在重叠，确认一个中枢；
    2) 中枢确认时刻为第 3 个单元结束时刻；
    3) 后续单元若与中枢核心区间仍有重叠，则仅时间上延伸，不缩窄核心区间；
    4) 一旦不重叠则结束该中枢，转入下一段重新确认，避免无穷合并。
    """
    return detect_zhongshu_with_basis(pens=pens, segments=None, level="bi")


def detect_zhongshu_with_basis(
    pens: List[Pen],
    segments: Optional[List[Segment]] = None,
    level: str = "bi",
    config: Optional[Config] = None,
) -> List[Zhongshu]:
    """按指定基准（bi/segment）识别中枢。"""
    if config is not None:
        level = config.zhongshu_level
    basis = (level or "").strip().lower()
    if basis not in {"bi", "segment"}:
        raise ValueError("level must be 'bi' or 'segment'")

    units: Sequence

    if basis == "segment":
        if segments is None:
            raise ValueError("segments are required when level='segment'")
        units = segments
    else:
        units = pens

    if len(units) < 3:
        return []

    zhongshus: List[Zhongshu] = []
    i = 0

    while i <= len(units) - 3:
        window = units[i : i + 3]
        overlap = _range_overlap([(u.low, u.high) for u in window])
        if overlap is None:
            i += 1
            continue

        lo, hi = overlap
        third = window[-1]
        zh = Zhongshu(
            start_idx=window[0].start_idx,
            end_idx=third.end_idx,
            start_datetime=window[0].start_datetime,
            end_datetime=third.end_datetime,
            low=lo,
            high=hi,
            confirm_idx=third.end_idx,
            confirm_datetime=third.end_datetime,
        )

        j = i + 3
        while j < len(units):
            unit = units[j]
            if _range_overlap([(zh.low, zh.high), (unit.low, unit.high)]) is None:
                break
            zh.end_idx = unit.end_idx
            zh.end_datetime = unit.end_datetime
            j += 1

        zhongshus.append(zh)

        # 从破坏点附近重新搜索，允许后续形成新中枢。
        i = max(j - 2, i + 1)

    print(f"[zs] 识别中枢 {len(zhongshus)} 个（level={basis}）。")
    return zhongshus
