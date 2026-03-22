"""chancode.data – 行情数据下载与处理。

支持通过 yfinance 下载真实数据，也提供内置演示数据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_ohlcv(
    ticker: str,
    period: str,
    interval: str,
    use_demo_data: bool = False,
) -> pd.DataFrame:
    """下载 OHLCV 数据，或生成内置演示数据。

    :param ticker: 股票/指数代码，例如 ``AAPL``、``600519.SS``
    :param period: 下载周期，例如 ``1y``、``6mo``（yfinance 格式）
    :param interval: K 线周期，例如 ``1d``、``1h``
    :param use_demo_data: 为 True 时生成本地演示数据，跳过网络请求
    :returns: 带有 Open/High/Low/Close/Volume 列的 DataFrame，索引为日期
    """
    if use_demo_data:
        return _generate_demo_data()

    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError(
            f"未下载到数据：ticker={ticker}, period={period}, interval={interval}，"
            "请检查网络连接或参数是否正确。"
        )

    # yfinance 有时返回 MultiIndex 列，展平为单层
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    print(f"[data] 下载 {len(df)} 行数据（{ticker}）。")
    return df


def _generate_demo_data(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """生成正弦叠加随机噪声的演示 OHLCV 数据。"""
    # 用 start= 保证生成的交易日数量精确等于 n
    end_date = pd.Timestamp.today().normalize()
    start_date = end_date - pd.tseries.offsets.BDay(n - 1)
    dates = pd.bdate_range(start=start_date, periods=n)
    rng = np.random.default_rng(seed)

    trend = np.linspace(100, 115, num=n)
    wave = np.sin(np.linspace(0, 4 * np.pi, num=n)) * 5
    base = trend + wave

    close = base + rng.normal(0, 1.5, size=n)
    open_ = close + rng.normal(0, 0.8, size=n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 1.2, size=n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 1.2, size=n))
    volume = rng.integers(int(1e5), int(5e5), size=n).astype(float)

    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )
    df.index.name = "Date"
    print(f"[data] 生成 {len(df)} 行演示数据。")
    return df
