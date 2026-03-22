"""tests/test_signal.py – 测试买卖点检测。"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from chancode.zs import Zhongshu
from chancode.signal import detect_buy_sell_points, BuySellPoint


def _make_df_with_closes(closes):
    """构建仅含 Close 列的 DataFrame（其余列以 Close 代替）。"""
    n = len(closes)
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    arr = np.array(closes, dtype=float)
    return pd.DataFrame(
        {"Open": arr, "High": arr + 0.5, "Low": arr - 0.5, "Close": arr, "Volume": 1.0},
        index=dates,
    )


def _make_zhongshu(low, high, end_idx=2):
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    return Zhongshu(0, end_idx, dates[0], dates[end_idx], low, high)


class TestDetectBuySellPoints:
    def test_empty_zhongshu(self):
        df = _make_df_with_closes([10, 11, 12, 13])
        buys, sells = detect_buy_sell_points(df, [])
        assert buys == []
        assert sells == []

    def test_buy_signal_on_breakout(self):
        # 中枢上沿 = 15，close 序列：…在中枢内… → 穿越上沿
        zh = _make_zhongshu(low=10, high=15, end_idx=2)
        closes = [12, 13, 14, 14.9, 15.1, 14]  # 第 4→5 穿越 15
        df = _make_df_with_closes(closes)
        buys, sells = detect_buy_sell_points(df, [zh])
        assert len(buys) >= 1
        assert buys[0].bstype == "B1"

    def test_sell_signal_on_breakdown(self):
        # 中枢下沿 = 10，close 序列穿越下沿
        zh = _make_zhongshu(low=10, high=15, end_idx=2)
        closes = [13, 12, 11, 10.1, 9.9, 11]  # 第 4→5 穿越 10
        df = _make_df_with_closes(closes)
        buys, sells = detect_buy_sell_points(df, [zh])
        assert len(sells) >= 1
        assert sells[0].bstype == "S1"

    def test_no_signal_within_zhongshu(self):
        # close 始终在中枢内，不产生信号
        zh = _make_zhongshu(low=10, high=20, end_idx=2)
        closes = [12, 13, 14, 15, 16, 17]
        df = _make_df_with_closes(closes)
        buys, sells = detect_buy_sell_points(df, [zh])
        assert buys == []
        assert sells == []
