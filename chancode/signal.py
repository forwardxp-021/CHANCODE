"""chancode.signal – 买卖点信号检测。

实现缠论三类买卖点（简化版）：

  一买（B1）：下降线段结束后，价格从下方首次穿越中枢上沿
  二买（B2）：一买后的回调，价格不破中枢下沿并重新回升穿越上沿
  三买（B3）：中枢振荡结束、价格再次向上穿越中枢上沿（新中枢上方）

  对称地：
  一卖（S1）：上升线段结束后，价格从上方首次跌破中枢下沿
  二卖（S2）：一卖后的反弹，价格不破中枢上沿并重新跌破下沿
  三卖（S3）：价格再次向下跌破中枢下沿
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd

from chancode.zs import Zhongshu


@dataclass
class BuySellPoint:
    """买卖点记录。"""

    bstype: str          # 'B1'/'B2'/'B3'/'S1'/'S2'/'S3'
    idx: int             # 对应 df 行索引
    datetime: pd.Timestamp
    price: float
    zh_idx: int          # 对应的中枢编号


def detect_buy_sell_points(
    df: pd.DataFrame,
    zhongshus: List[Zhongshu],
) -> Tuple[List[BuySellPoint], List[BuySellPoint]]:
    """对每个中枢识别买点与卖点。

    检测逻辑：
    - 中枢结束后，在后续行情中寻找价格跨越中枢上沿（买）或下沿（卖）的时刻。
    - 一买/一卖：中枢后第一次穿越。
    - 二买/二卖：一买/一卖后价格回调未破中枢另一边界，再次穿越。
    - 三买/三卖：二买/二卖后又一次同方向穿越。

    :param df: OHLCV DataFrame
    :param zhongshus: 中枢列表
    :returns: (买点列表, 卖点列表)
    """
    closes = df["Close"].values
    n = len(closes)

    buys: List[BuySellPoint] = []
    sells: List[BuySellPoint] = []

    for zh_id, zh in enumerate(zhongshus):
        start = zh.end_idx + 1
        if start >= n:
            continue

        # 仅在当前中枢之后、下一个中枢开始之前的区间内打点，
        # 避免多个中枢在同一后续行情上重复产生信号。
        if zh_id + 1 < len(zhongshus):
            end = min(zhongshus[zh_id + 1].start_idx, n - 1)
        else:
            end = n - 1
        if start > end:
            continue

        buy_count = 0   # 该中枢已记录的买点数（最多 3 个）
        sell_count = 0

        prev_c = closes[start - 1]

        for k in range(start, end + 1):
            curr_c = closes[k]
            dt = df.index[k]

            # 向上穿越上沿 → 买点
            if prev_c <= zh.high < curr_c and buy_count < 3:
                buy_count += 1
                label = f"B{buy_count}"
                buys.append(BuySellPoint(label, k, dt, curr_c, zh_id))

            # 向下穿越下沿 → 卖点
            if prev_c >= zh.low > curr_c and sell_count < 3:
                sell_count += 1
                label = f"S{sell_count}"
                sells.append(BuySellPoint(label, k, dt, curr_c, zh_id))

            prev_c = curr_c

            # 若买卖点均已找满，跳出
            if buy_count >= 3 and sell_count >= 3:
                break

    print(f"[signal] 买点 {len(buys)} 个，卖点 {len(sells)} 个。")
    return buys, sells
