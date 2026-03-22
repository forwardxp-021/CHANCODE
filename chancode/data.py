"""chancode.data – 行情数据下载与处理。

支持通过 yfinance 下载真实数据，也提供内置演示数据。
支持将下载数据缓存到本地，避免重复网络请求。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# 默认下载 K 线根数
DEFAULT_NUM_PERIODS: int = 120

# 各 K 线间隔对应的 yfinance period 字符串（保证能覆盖 120 根以上 K 线）
# 5m / 30m 受 yfinance 限制只能拉近 60 天数据
_INTERVAL_TO_PERIOD: dict[str, str] = {
    "5m":  "5d",    # 5 分钟 K 线，约 5 个交易日（A 股 48 根/天 × 5 ≈ 240 根）
    "30m": "1mo",   # 30 分钟 K 线，约 1 个月（A 股 8 根/天 × 22 ≈ 176 根）
    "1d":  "6mo",   # 日线，约 6 个月（约 130 个交易日）
    "1wk": "3y",    # 周线，约 3 年（约 156 根）
}

# 本地缓存目录
_CACHE_DIR: Path = Path.home() / ".chancode_cache"


def _cache_path(ticker: str, interval: str, num_periods: int) -> Path:
    """根据参数生成缓存文件路径。"""
    key = f"{ticker}_{interval}_{num_periods}"
    filename = hashlib.md5(key.encode()).hexdigest() + ".parquet"
    return _CACHE_DIR / filename


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


def fetch_ohlcv_cached(
    ticker: str,
    interval: str,
    num_periods: int = DEFAULT_NUM_PERIODS,
    use_demo_data: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """下载并缓存 OHLCV 数据，若本地缓存（当天之内）存在则直接读取。

    :param ticker: 股票/指数代码，例如 ``AAPL``、``600519.SS``
    :param interval: K 线周期，``"5m"``、``"30m"``、``"1d"``、``"1wk"``
    :param num_periods: 返回的最大 K 线根数，默认 120
    :param use_demo_data: 为 True 时生成本地演示数据，跳过网络请求
    :param force_refresh: 强制重新下载，忽略缓存
    :returns: 带有 Open/High/Low/Close/Volume 列的 DataFrame，索引为日期
    """
    if use_demo_data:
        df = _generate_demo_data(n=num_periods)
        return df

    cache_file = _cache_path(ticker, interval, num_periods)

    # 判断缓存是否有效（同一自然日内）
    if not force_refresh and cache_file.exists():
        mtime = pd.Timestamp(os.path.getmtime(cache_file), unit="s", tz="UTC")
        today = pd.Timestamp.utcnow().normalize()
        if mtime >= today:
            print(f"[data] 读取本地缓存：{cache_file}")
            return pd.read_parquet(cache_file)

    # 查找合适的下载周期
    period = _INTERVAL_TO_PERIOD.get(interval, "1y")
    df = yf.download(ticker, period=period, interval=interval, progress=False)

    if df.empty:
        raise ValueError(
            f"未下载到数据：ticker={ticker}, period={period}, interval={interval}，"
            "请检查网络连接或参数是否正确。"
        )

    # 展平 MultiIndex 列
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # 取最近 num_periods 根 K 线
    if len(df) > num_periods:
        df = df.iloc[-num_periods:]

    print(f"[data] 下载 {len(df)} 行数据（{ticker}），已保存至缓存。")

    # 写缓存
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file)

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
