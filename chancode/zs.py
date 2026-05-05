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
    direction: str = ""  # "up" 或 "down"
    zg: float | None = None
    zd: float | None = None
    gg: float | None = None
    dd: float | None = None
    g: float | None = None  # 最小 g_n
    d: float | None = None  # 最大 d_n
    terminated_idx: int | None = None
    terminated_datetime: Optional[pd.Timestamp] = None
    terminated_reason: str = ""


def _range_overlap(
    ranges: List[Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    """计算多个价格区间的交集。若无交集返回 None。"""
    lows, highs = zip(*ranges)
    lo, hi = max(lows), min(highs)
    return (lo, hi) if lo <= hi else None


def _is_unit_complete(unit: object) -> bool:
    """是否为已完成的次级走势单元。

    兼容历史对象：若未定义 is_complete 字段，默认视为已完成。
    """
    return bool(getattr(unit, "is_complete", True))


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

    def _direction(u) -> str:
        return "up" if u.is_up else "down"

    def _update_metrics(zh: Zhongshu, dir_units: List) -> None:
        highs = [u.high for u in dir_units]
        lows = [u.low for u in dir_units]
        if highs and lows:
            zh.gg = max(highs)
            zh.dd = min(lows)
            zh.g = min(highs)
            zh.d = max(lows)
            if len(dir_units) >= 2:
                g1, g2 = dir_units[0].high, dir_units[1].high
                d1, d2 = dir_units[0].low, dir_units[1].low
                zh.zg = min(g1, g2)
                zh.zd = max(d1, d2)
            else:
                zh.zg = zh.high
                zh.zd = zh.low

    active: Zhongshu | None = None
    active_dir_units: List = []
    left_pending = False

    while i < len(units):
        if active is None:
            if i + 2 >= len(units):
                break
            window = units[i : i + 3]
            if not all(_is_unit_complete(u) for u in window):
                i += 1
                continue
            if not (
                window[0].is_up != window[1].is_up
                and window[1].is_up != window[2].is_up
                and window[0].is_up == window[2].is_up
            ):
                i += 1
                continue

            overlap = _range_overlap([(u.low, u.high) for u in window])
            if overlap is None:
                i += 1
                continue

            lo, hi = overlap
            third = window[-1]
            zh_direction = _direction(window[0])
            active_dir_units = [u for u in window if _direction(u) == zh_direction]

            active = Zhongshu(
                start_idx=window[0].start_idx,
                end_idx=third.end_idx,
                start_datetime=window[0].start_datetime,
                end_datetime=third.end_datetime,
                low=lo,
                high=hi,
                confirm_idx=third.end_idx,
                confirm_datetime=third.end_datetime,
                direction=zh_direction,
            )
            _update_metrics(active, active_dir_units)
            i = i + 3
            left_pending = False
            continue

        unit = units[i]
        if not _is_unit_complete(unit):
            i += 1
            continue
        overlap = _range_overlap([(active.low, active.high), (unit.low, unit.high)])
        if overlap is not None:
            active.end_idx = unit.end_idx
            active.end_datetime = unit.end_datetime
            if _direction(unit) == active.direction:
                active_dir_units.append(unit)
                _update_metrics(active, active_dir_units)
            left_pending = False
            i += 1
            continue

        # 第一次离开，等待回抽；第二次仍不重叠则终结当前中枢。
        if not left_pending:
            left_pending = True
            i += 1
            continue

        # 终结当前中枢，尝试从前两个单元重新启动。
        exit_unit = units[i - 1]
        active.terminated_idx = exit_unit.end_idx
        active.terminated_datetime = exit_unit.end_datetime
        active.terminated_reason = "leave_no_reentry"
        if zhongshus and _range_overlap([(zhongshus[-1].low, zhongshus[-1].high), (active.low, active.high)]):
            prev = zhongshus[-1]
            prev.end_idx = max(prev.end_idx, active.end_idx)
            prev.end_datetime = max(prev.end_datetime, active.end_datetime)
            prev.low = max(prev.low, active.low)
            prev.high = min(prev.high, active.high)
            prev.direction = prev.direction or active.direction
            prev.zg = prev.zg if prev.zg is not None else active.zg
            prev.zd = prev.zd if prev.zd is not None else active.zd
            prev.gg = prev.gg if prev.gg is not None else active.gg
            prev.dd = prev.dd if prev.dd is not None else active.dd
            prev.g = prev.g if prev.g is not None else active.g
            prev.d = prev.d if prev.d is not None else active.d
            if prev.terminated_idx is None:
                prev.terminated_idx = active.terminated_idx
                prev.terminated_datetime = active.terminated_datetime
                prev.terminated_reason = active.terminated_reason
        else:
            zhongshus.append(active)

        active = None
        active_dir_units = []
        left_pending = False
        i = max(i - 2, 0)

    if active is not None:
        if zhongshus and _range_overlap([(zhongshus[-1].low, zhongshus[-1].high), (active.low, active.high)]):
            prev = zhongshus[-1]
            prev.end_idx = max(prev.end_idx, active.end_idx)
            prev.end_datetime = max(prev.end_datetime, active.end_datetime)
            prev.low = max(prev.low, active.low)
            prev.high = min(prev.high, active.high)
            prev.direction = prev.direction or active.direction
            prev.zg = prev.zg if prev.zg is not None else active.zg
            prev.zd = prev.zd if prev.zd is not None else active.zd
            prev.gg = prev.gg if prev.gg is not None else active.gg
            prev.dd = prev.dd if prev.dd is not None else active.dd
            prev.g = prev.g if prev.g is not None else active.g
            prev.d = prev.d if prev.d is not None else active.d
            if prev.terminated_idx is None:
                prev.terminated_idx = active.terminated_idx
                prev.terminated_datetime = active.terminated_datetime
                prev.terminated_reason = active.terminated_reason
        else:
            zhongshus.append(active)

    print(f"[zs] 识别中枢 {len(zhongshus)} 个（level={basis}）。")
    return zhongshus
