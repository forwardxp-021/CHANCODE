"""chancode.bi – 笔（Bi）识别。

笔由相邻异类型分型首尾连接构成：顶→底为下降笔，底→顶为上升笔。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from chancode.fractal import FractalPoint
from chancode.config import Config


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
    start_ftype: str = ""
    end_ftype: str = ""

    @property
    def direction(self) -> str:
        """由分型类型判定方向：bottom->top 为 up，top->bottom 为 down。"""
        if self.start_ftype == "bottom" and self.end_ftype == "top":
            return "up"
        if self.start_ftype == "top" and self.end_ftype == "bottom":
            return "down"
        # 兼容旧数据或异常输入的防御性回退
        return "up" if self.end_price > self.start_price else "down"

    @property
    def is_up(self) -> bool:
        return self.direction == "up"


def build_pens(
    fractals: List[FractalPoint],
    min_kline_count: Optional[int] = None,
    config: Optional[Config] = None,
) -> List[Pen]:
    """从分型序列构建笔。

    成笔条件：
    1) 起止分型必须为异类型；
    2) 起止分型索引间隔 >= min_kline_count（合并K线数量约束）；
    3) 价格区间必须有重叠，避免“顶在底下方”的伪笔。
    """
    pens: List[Pen] = []

    if len(fractals) < 2:
        return pens

    if min_kline_count is None:
        min_kline_count = (config.min_bi_separation if config else Config().min_bi_separation)
    min_kline_count = max(1, int(min_kline_count))

    i = 0
    while i < len(fractals) - 1:
        a = fractals[i]
        built = False

        for j in range(i + 1, len(fractals)):
            b = fractals[j]

            if a.ftype == b.ftype:
                # 同类分型出现时，更新起点为更极端者。
                if (a.ftype == "top" and b.high > a.high) or (
                    a.ftype == "bottom" and b.low < a.low
                ):
                    a = b
                    i = j
                continue

            gap = b.idx - a.idx
            if gap < min_kline_count:
                continue

            if not (
                (a.ftype == "bottom" and b.ftype == "top")
                or (a.ftype == "top" and b.ftype == "bottom")
            ):
                print(f"[bi] 跳过异常分型序列: {a.ftype}->{b.ftype} at {a.idx}->{b.idx}")
                continue

            high = max(a.high, b.high)
            low = min(a.low, b.low)
            if high <= low:
                print(
                    f"[bi] 跳过无价格重叠的分型: {a.ftype}->{b.ftype} high={high} low={low}"
                )
                continue

            pens.append(
                Pen(
                    start_idx=a.idx,
                    end_idx=b.idx,
                    start_datetime=a.datetime,
                    end_datetime=b.datetime,
                    start_price=a.price,
                    end_price=b.price,
                    high=high,
                    low=low,
                    start_ftype=a.ftype,
                    end_ftype=b.ftype,
                )
            )

            i = j
            built = True
            break

        if not built:
            i += 1

    print(f"[bi] 构建笔 {len(pens)} 条（min_kline_count={min_kline_count}）。")
    return pens
