"""chancode.fractal – 分型识别与 K 线合并处理。

标准三 K 线顶底分型（顶：中间 K 线高点高于两侧；底：低点低于两侧）。
去重与交替处理：连续同类型分型保留极端值，确保序列顶底交替。

K 线合并规则（缠论标准）：
  相邻两根 K 线若存在包含关系（一根的高低点区间被另一根完全覆盖），则合并为一根，
  合并方向跟随前期趋势（上涨取高高、下跌取低低）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Tuple

import pandas as pd


@dataclass
class FractalPoint:
    """分型结构：索引、时间戳、类型（top/bottom）及对应高低价。"""

    idx: int
    datetime: pd.Timestamp
    ftype: str  # "top" 或 "bottom"
    high: float
    low: float

    @property
    def price(self) -> float:
        """顶分型返回高点价，底分型返回低点价。"""
        return self.high if self.ftype == "top" else self.low


def merge_klines(df: pd.DataFrame) -> Tuple[pd.DataFrame, Set[int]]:
    """对原始 K 线序列执行缠论标准包含关系处理（K 线合并）。

    当相邻两根 K 线存在包含关系时，将其合并为一根独立 K 线：
    - 前期上涨趋势（当前高点 > 前一高点）：取 max(high)、max(low)；
    - 前期下跌趋势：取 min(high)、min(low)。

    :param df: 含 Open/High/Low/Close/Volume 列的原始 OHLCV DataFrame
    :returns: (merged_df, merged_indices)
        - merged_df: 合并后的 K 线 DataFrame（行数 ≤ 原始行数）
        - merged_indices: 原始 DataFrame 中被"吸收"进合并的行的整数位置集合（不包含合并组的第一行）
    """
    highs = df["High"].values
    lows = df["Low"].values
    opens = df["Open"].values
    closes = df["Close"].values
    volumes = df["Volume"].values
    index = df.index

    # 记录每个合并后的逻辑 K 线（以列表存储各字段）
    m_open: list = []
    m_high: list = []
    m_low: list = []
    m_close: list = []
    m_volume: list = []
    m_index: list = []

    # 每个逻辑 K 线包含的原始行位置列表
    group_positions: list = []  # list of list[int]

    for i in range(len(df)):
        if not m_high:
            # 第一根，直接放入
            m_open.append(opens[i])
            m_high.append(highs[i])
            m_low.append(lows[i])
            m_close.append(closes[i])
            m_volume.append(volumes[i])
            m_index.append(index[i])
            group_positions.append([i])
            continue

        prev_h = m_high[-1]
        prev_l = m_low[-1]
        curr_h = highs[i]
        curr_l = lows[i]

        # 判断包含关系：curr 被 prev 包含，或 prev 被 curr 包含
        contained = (prev_h >= curr_h and prev_l <= curr_l) or (
            curr_h >= prev_h and curr_l <= prev_l
        )

        if contained:
            # 确定趋势：用合并前的前一个逻辑 K 线与当前逻辑 K 线的高点比较
            if len(m_high) >= 2:
                trend_up = m_high[-1] > m_high[-2]
            else:
                trend_up = curr_h >= prev_h  # 只有一根历史时，以当前走向为准

            if trend_up:
                m_high[-1] = max(prev_h, curr_h)
                m_low[-1] = max(prev_l, curr_l)
            else:
                m_high[-1] = min(prev_h, curr_h)
                m_low[-1] = min(prev_l, curr_l)

            # open/close/volume 沿用该组第一根的开盘价和最后一根的收盘价及累计成交量
            m_close[-1] = closes[i]
            m_volume[-1] = m_volume[-1] + volumes[i]
            group_positions[-1].append(i)
        else:
            m_open.append(opens[i])
            m_high.append(highs[i])
            m_low.append(lows[i])
            m_close.append(closes[i])
            m_volume.append(volumes[i])
            m_index.append(index[i])
            group_positions.append([i])

    merged_df = pd.DataFrame(
        {
            "Open": m_open,
            "High": m_high,
            "Low": m_low,
            "Close": m_close,
            "Volume": m_volume,
        },
        index=m_index,
    )
    merged_df.index.name = df.index.name

    # 收集被合并（非首行）的原始位置
    merged_indices: Set[int] = set()
    for group in group_positions:
        if len(group) > 1:
            merged_indices.update(group[1:])
            # 也标记首行（整个组都参与了合并）
            merged_indices.add(group[0])

    print(
        f"[fractal] K线合并：{len(df)} → {len(merged_df)} 根"
        f"（{len(merged_indices)} 个原始K线参与合并）。"
    )
    return merged_df, merged_indices


def detect_fractals(df: pd.DataFrame) -> List[FractalPoint]:
    """在 df 中识别三 K 线顶/底分型。

    顶分型：第 i 根 K 线高点严格高于第 i-1 和第 i+1 根 K 线。
    底分型：第 i 根 K 线低点严格低于第 i-1 和第 i+1 根 K 线。
    若同时满足（极罕见），按更极端幅度选择类型。

    :param df: 含 High/Low 列的 OHLCV DataFrame
    :returns: 原始分型列表（可能含连续同类型）
    """
    highs = df["High"].values
    lows = df["Low"].values
    fractals: List[FractalPoint] = []

    for i in range(1, len(df) - 1):
        ph, ch, nh = highs[i - 1], highs[i], highs[i + 1]
        pl, cl, nl = lows[i - 1], lows[i], lows[i + 1]
        dt = df.index[i]

        is_top = ch > ph and ch > nh
        is_bot = cl < pl and cl < nl

        if is_top and not is_bot:
            fractals.append(FractalPoint(i, dt, "top", ch, cl))
        elif is_bot and not is_top:
            fractals.append(FractalPoint(i, dt, "bottom", ch, cl))
        elif is_top and is_bot:
            # 按幅度决定
            if (ch - max(ph, nh)) >= (min(pl, nl) - cl):
                fractals.append(FractalPoint(i, dt, "top", ch, cl))
            else:
                fractals.append(FractalPoint(i, dt, "bottom", ch, cl))

    print(f"[fractal] 原始分型 {len(fractals)} 个。")
    return fractals


def filter_and_alternate_fractals(fractals: List[FractalPoint]) -> List[FractalPoint]:
    """去重与交替：连续同类分型保留最极端一个，确保顶底严格交替。

    :param fractals: 原始分型列表
    :returns: 交替排列的分型列表
    """
    if not fractals:
        return []

    filtered: List[FractalPoint] = [fractals[0]]
    for f in fractals[1:]:
        last = filtered[-1]
        if f.ftype == last.ftype:
            # 同类型去重：顶取最高，底取最低
            if f.ftype == "top" and f.high > last.high:
                filtered[-1] = f
            elif f.ftype == "bottom" and f.low < last.low:
                filtered[-1] = f
        else:
            filtered.append(f)

    print(f"[fractal] 交替后分型 {len(filtered)} 个。")
    return filtered
