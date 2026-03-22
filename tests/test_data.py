"""tests/test_data.py – 测试数据下载与演示数据生成。"""
from __future__ import annotations

import pandas as pd
import pytest

from chancode.data import fetch_ohlcv, _generate_demo_data


class TestGenerateDemoData:
    def test_returns_dataframe(self):
        df = _generate_demo_data()
        assert isinstance(df, pd.DataFrame)

    def test_has_ohlcv_columns(self):
        df = _generate_demo_data()
        for col in ("Open", "High", "Low", "Close", "Volume"):
            assert col in df.columns

    def test_default_row_count(self):
        df = _generate_demo_data(n=60)
        assert len(df) == 60

    def test_high_ge_low(self):
        df = _generate_demo_data()
        assert (df["High"] >= df["Low"]).all()

    def test_reproducible_with_seed(self):
        df1 = _generate_demo_data(seed=0)
        df2 = _generate_demo_data(seed=0)
        pd.testing.assert_frame_equal(df1, df2)


class TestFetchOhlcv:
    def test_demo_flag_returns_dataframe(self):
        df = fetch_ohlcv("AAPL", "1y", "1d", use_demo_data=True)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0
