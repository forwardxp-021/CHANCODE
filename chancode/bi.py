"""chancode.bi – 笔（Bi）识别。

笔由相邻异类型分型首尾连接构成：顶→底为下降笔，底→顶为上升笔。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from chancode.fractal import FractalPoint, MergeKlineResult
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
    is_complete: bool = True

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
    3) 价格方向必须与分型类型一致：bottom->top 必须上涨，top->bottom 必须下跌。
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

            if a.ftype == "bottom" and b.ftype == "top" and b.price <= a.price:
                print(
                    f"[bi] 跳过价格方向错误的上升笔: {a.idx}->{b.idx} "
                    f"price={a.price}->{b.price}"
                )
                continue
            if a.ftype == "top" and b.ftype == "bottom" and b.price >= a.price:
                print(
                    f"[bi] 跳过价格方向错误的下降笔: {a.idx}->{b.idx} "
                    f"price={a.price}->{b.price}"
                )
                continue

            high = max(a.high, b.high)
            low = min(a.low, b.low)

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


def map_pens_to_original(
    pens: List[Pen],
    merge_result: MergeKlineResult,
    original_index: pd.Index,
    original_df: pd.DataFrame,
) -> List[Pen]:
    """将基于合并K线的笔端点映射回原始K线极值位置，用于绘图显示。"""
    mapped: List[Pen] = []

    def _endpoint(idx: int, ftype: str, fallback_dt: pd.Timestamp, fallback_price: float):
        if idx < 0 or idx >= len(merge_result.merged_to_original):
            return idx, fallback_dt, fallback_price

        group = merge_result.merged_to_original[idx]
        if not group:
            return idx, fallback_dt, fallback_price

        if ftype == "top":
            orig_pos = max(group, key=lambda pos: float(original_df["High"].iloc[pos]))
            price = float(original_df["High"].iloc[orig_pos])
        elif ftype == "bottom":
            orig_pos = min(group, key=lambda pos: float(original_df["Low"].iloc[pos]))
            price = float(original_df["Low"].iloc[orig_pos])
        else:
            orig_pos = group[-1]
            price = fallback_price

        if orig_pos < 0 or orig_pos >= len(original_index):
            return idx, fallback_dt, fallback_price
        return orig_pos, pd.Timestamp(original_index[orig_pos]), price

    for pen in pens:
        start_idx, start_dt, start_price = _endpoint(
            pen.start_idx,
            pen.start_ftype,
            pen.start_datetime,
            pen.start_price,
        )
        end_idx, end_dt, end_price = _endpoint(
            pen.end_idx,
            pen.end_ftype,
            pen.end_datetime,
            pen.end_price,
        )
        mapped.append(
            Pen(
                start_idx=start_idx,
                end_idx=end_idx,
                start_datetime=start_dt,
                end_datetime=end_dt,
                start_price=start_price,
                end_price=end_price,
                high=max(start_price, end_price),
                low=min(start_price, end_price),
                start_ftype=pen.start_ftype,
                end_ftype=pen.end_ftype,
                is_complete=pen.is_complete,
            )
        )

    return mapped
