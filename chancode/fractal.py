"""chancode.fractal – 分型识别。

标准三 K 线顶底分型（顶：中间 K 线高点高于两侧；底：低点低于两侧）。
去重与交替处理：连续同类型分型保留极端值，确保序列顶底交替。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

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
