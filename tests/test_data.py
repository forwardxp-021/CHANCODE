"""tests/test_data.py – 测试数据下载与演示数据生成。"""
from __future__ import annotations

import pandas as pd
import pytest

import chancode.data as data_module
from chancode.data import _generate_demo_data, _is_cache_stale, fetch_ohlcv


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

    def test_default_dividend_type_is_front(self, monkeypatch):
        captured = {}

        def fake_fetch_ohlcv_tdx(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=pd.to_datetime(["2026-01-01"]))

        monkeypatch.setattr(data_module, "_fetch_ohlcv_tdx", fake_fetch_ohlcv_tdx)

        df = fetch_ohlcv("601800", "1y", "1d")
        assert isinstance(df, pd.DataFrame)
        assert captured["dividend_type"] == data_module.DEFAULT_DIVIDEND_TYPE

    def test_explicit_dividend_type_is_forwarded(self, monkeypatch):
        captured = {}

        def fake_fetch_ohlcv_tdx(**kwargs):
            captured.update(kwargs)
            return pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=pd.to_datetime(["2026-01-01"]))

        monkeypatch.setattr(data_module, "_fetch_ohlcv_tdx", fake_fetch_ohlcv_tdx)

        fetch_ohlcv("601800", "1y", "1d", dividend_type="back")
        assert captured["dividend_type"] == "back"


class TestCacheStaleness:
    def test_stale_when_old_daily(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Open": range(10), "High": range(10), "Low": range(10), "Close": range(10)}, index=idx)
        assert _is_cache_stale(df, "1d") is True

    def test_fresh_recent_intraday(self):
        idx = pd.date_range(pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=5, freq="30min")
        df = pd.DataFrame({"Open": range(5), "High": range(5), "Low": range(5), "Close": range(5)}, index=idx)
        assert _is_cache_stale(df, "30m") is False


class TestCachePaths:
    def test_dividend_type_affects_cache_key(self):
        p1 = data_module._cache_paths("601800", "1d", 120, "none")
        p2 = data_module._cache_paths("601800", "1d", 120, "front")
        assert p1 != p2
