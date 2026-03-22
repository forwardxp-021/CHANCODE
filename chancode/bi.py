"""chancode.bi – 笔（Bi）识别。

笔由相邻异类型分型首尾连接构成：顶→底为下降笔，底→顶为上升笔。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd

from chancode.fractal import FractalPoint


@dataclass
class Pen:
    """笔：连接相邻顶底分型的线段，记录方向、价格区间与时间范围。"""

    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    start_price: float
    end_price: float
    high: float
    low: float

    @property
    def direction(self) -> str:
        """上升笔返回 'up'，下降笔返回 'down'。"""
        return "up" if self.end_price > self.start_price else "down"

    @property
    def is_up(self) -> bool:
        return self.direction == "up"


def build_pens(fractals: List[FractalPoint]) -> List[Pen]:
    """从交替分型序列中构建笔。

    相邻两个不同类型的分型构成一笔；由于输入已交替，此处逐对连接即可。

    :param fractals: 已交替的分型列表
    :returns: 笔列表
    """
    pens: List[Pen] = []
    for i in range(len(fractals) - 1):
        a, b = fractals[i], fractals[i + 1]
        if a.ftype == b.ftype:
            # 交替分型中不应出现，防御性跳过
            continue
        pens.append(
            Pen(
                start_idx=a.idx,
                end_idx=b.idx,
                start_datetime=a.datetime,
                end_datetime=b.datetime,
                start_price=a.price,
                end_price=b.price,
                high=max(a.high, b.high),
                low=min(a.low, b.low),
            )
        )

    print(f"[bi] 构建笔 {len(pens)} 条。")
    return pens
