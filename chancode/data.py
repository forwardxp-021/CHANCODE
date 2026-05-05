"""chancode.data – 行情数据获取与演示数据。

默认使用通达信 TQ Python 接口（tdxref/tqcenter.py）。
支持本地缓存与内置演示数据；GUI 仍支持本地 Excel/文本附件加载。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_tq = None
_tdx_import_error: Exception | None = None

# 默认下载 K 线根数
DEFAULT_NUM_PERIODS: int = 120

# 默认使用前复权
DEFAULT_DIVIDEND_TYPE: str = "front"

# 本地缓存目录
_CACHE_DIR: Path = Path.home() / ".chancode_cache"

# GUI/CLI 使用的间隔 → 通达信周期代码
_INTERVAL_TO_TDX: dict[str, str] = {
    "5m": "5m",
    "30m": "30m",
    "1d": "1d",
    "1wk": "1w",
    "1w": "1w",
}


def _get_tq():
    """Lazy import tqcenter; raise clear error if DLL/middleware is missing."""
    global _tq, _tdx_import_error
    if _tq is not None:
        return _tq
    if _tdx_import_error is not None:
        raise _tdx_import_error
    try:
        from tdxref.tqcenter import tq as _tq_mod  # type: ignore
        _tq = _tq_mod
        return _tq
    except Exception as exc:  # noqa: BLE001
        _tdx_import_error = exc
        raise


def _cache_paths(
    ticker: str,
    interval: str,
    num_periods: int,
    dividend_type: str = DEFAULT_DIVIDEND_TYPE,
) -> tuple[Path, Path]:
    """Return parquet and csv cache paths for a given key."""
    key = f"tdx_{ticker}_{interval}_{num_periods}_{dividend_type}"
    stem = hashlib.md5(key.encode()).hexdigest()
    return _CACHE_DIR / f"{stem}.parquet", _CACHE_DIR / f"{stem}.csv"


def _is_cache_stale(df: pd.DataFrame, interval: str) -> bool:
    """Heuristically decide whether cached OHLCV is too old for reuse."""
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return True

    last_dt = pd.to_datetime(df.index.max()).normalize()
    today = pd.Timestamp.today().normalize()

    # Weekly tolerance is longer; intraday/daily should stay fresh.
    max_age_days = 10 if interval.lower() in {"1w", "1wk"} else 3
    return (today - last_dt).days > max_age_days


def _normalize_ticker_for_tdx(ticker: str) -> str:
    """Normalize mainland numeric code to TDX suffix (SH/SZ), keep provided suffix otherwise."""
    t = (ticker or "").strip().upper()
    if not t:
        raise ValueError("Ticker is required")
    if "." in t:
        return t
    if len(t) == 6 and t.isdigit():
        return f"{t}.SH" if t.startswith(("6", "9")) else f"{t}.SZ"
    return t


def _tdx_period(interval: str) -> str:
    iv = (interval or "").strip().lower()
    if iv in _INTERVAL_TO_TDX:
        return _INTERVAL_TO_TDX[iv]
    raise ValueError(f"Unsupported interval for TDX: {interval}")


def _period_to_num_periods(period: str, interval: str) -> int:
    """Roughly convert a period string (e.g. 1y/6mo) to bar count for TDX requests."""
    p = (period or "").strip().lower()
    if not p:
        return DEFAULT_NUM_PERIODS

    unit = p[-1]
    try:
        value = int(p[:-1])
    except ValueError:
        return DEFAULT_NUM_PERIODS

    if unit == "d":
        if interval in {"1d", "1w", "1wk"}:
            return max(20, value)
        if interval == "30m":
            return max(20, value * 8)
        if interval == "5m":
            return max(20, value * 48)
    if unit == "w":
        if interval in {"1w", "1wk"}:
            return max(8, value)
        if interval == "1d":
            return max(20, value * 5)
    if unit == "m":
        if interval in {"1w", "1wk"}:
            return max(8, value * 4)
        if interval == "1d":
            return max(20, value * 22)
    if unit == "y":
        if interval in {"1w", "1wk"}:
            return max(52, value * 52)
        if interval == "1d":
            return max(200, value * 250)

    return DEFAULT_NUM_PERIODS


def _fetch_ohlcv_tdx(
    ticker: str,
    interval: str,
    num_periods: int,
    dividend_type: str = DEFAULT_DIVIDEND_TYPE,
) -> pd.DataFrame:
    """Fetch OHLCV from Tongdaxin via tqcenter wrapper."""
    try:
        tq = _get_tq()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"TDX 接口加载失败：{exc}"
        ) from exc
    normalized = _normalize_ticker_for_tdx(ticker)
    period_code = _tdx_period(interval)

    # Ensure connection; auto close is handled by tqcenter finalizer.
    try:
        tq.initialize(__file__)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"TDX 接口初始化失败，请确认通达信客户端已启动并登录。（原因：{exc}）"
        ) from exc

    count = int(max(1, num_periods))
    required_fields = ["Open", "High", "Low", "Close", "Volume"]

    data = tq.get_market_data(
        stock_list=[normalized],
        period=period_code,
        count=count,
        dividend_type=dividend_type,
        field_list=required_fields,
        fill_data=True,
    )

    if not data:
        raise ValueError(f"未获取到行情数据：{normalized} ({period_code})")

    def _pick(field: str) -> pd.Series:
        if field not in data:
            raise ValueError(f"TDX 数据缺少字段 {field}")
        series = data[field]
        if isinstance(series, pd.DataFrame):
            if normalized not in series.columns:
                raise ValueError(f"字段 {field} 中不存在 {normalized} 列")
            series = series[normalized]
        if not isinstance(series.index, pd.DatetimeIndex):
            series.index = pd.to_datetime(series.index)
        return pd.to_numeric(series, errors="coerce")

    open_s = _pick("Open")
    high_s = _pick("High")
    low_s = _pick("Low")
    close_s = _pick("Close")
    volume_s = _pick("Volume") if "Volume" in data else pd.Series(0.0, index=open_s.index)

    df = pd.DataFrame(
        {
            "Open": open_s,
            "High": high_s,
            "Low": low_s,
            "Close": close_s,
            "Volume": volume_s,
        }
    ).dropna(subset=["Open", "High", "Low", "Close"])

    df = df.sort_index()
    if len(df) > num_periods:
        df = df.iloc[-num_periods:]
    df.index.name = "Date"
    print(f"[data] 下载 {len(df)} 行数据（{normalized}, source=tdx）。")
    return df


def fetch_ohlcv(
    ticker: str,
    period: str,
    interval: str,
    use_demo_data: bool = False,
    dividend_type: str = DEFAULT_DIVIDEND_TYPE,
) -> pd.DataFrame:
    """下载 OHLCV 数据或生成演示数据。

    :param ticker: 股票/指数代码，例如 ``600519`` 或 ``600519.SH``
    :param period: 近似周期字符串（用于推算需要的根数），例如 ``1y``、``6mo``
    :param interval: K 线周期，例如 ``1d``、``30m``、``5m``、``1wk``
    :param use_demo_data: 为 True 时生成本地演示数据，跳过行情接口
    :param dividend_type: 复权类型，默认前复权（front）
    :returns: 带有 Open/High/Low/Close/Volume 列的 DataFrame，索引为日期
    """
    if use_demo_data:
        return _generate_demo_data()

    num_periods = _period_to_num_periods(period, interval)
    return _fetch_ohlcv_tdx(
        ticker=ticker,
        interval=interval,
        num_periods=num_periods,
        dividend_type=dividend_type,
    )


def fetch_ohlcv_cached(
    ticker: str,
    interval: str,
    num_periods: int = DEFAULT_NUM_PERIODS,
    use_offline_data: bool = False,
    force_refresh: bool = False,
    dividend_type: str = DEFAULT_DIVIDEND_TYPE,
) -> pd.DataFrame:
    """下载并缓存 OHLCV 数据，支持离线读取。"""
    cache_parquet, cache_csv = _cache_paths(ticker, interval, num_periods, dividend_type)

    def _read_cache() -> Optional[pd.DataFrame]:
        if force_refresh:
            return None
        for path, reader in (
            (cache_parquet, pd.read_parquet),
            (cache_csv, lambda p: pd.read_csv(p, parse_dates=[0], index_col=0)),
        ):
            if not path.exists():
                continue
            try:
                df = reader(path)
            except Exception:
                continue
            if len(df) > num_periods:
                df = df.iloc[-num_periods:]
            if _is_cache_stale(df, interval):
                print(f"[data] 缓存过旧，忽略：{path}")
                continue
            print(f"[data] 读取本地缓存：{path}")
            return df
        return None

    if use_offline_data:
        cached = _read_cache()
        if cached is not None:
            return cached
        raise ValueError(
            f"离线模式未找到本地数据：{cache_parquet} 或 {cache_csv}，请先联网下载一次再使用离线模式。"
        )

    cached = _read_cache()
    if cached is not None:
        return cached

    df = _fetch_ohlcv_tdx(
        ticker=ticker,
        interval=interval,
        num_periods=num_periods,
        dividend_type=dividend_type,
    )

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(cache_parquet)
        print(f"[data] 写入本地缓存：{cache_parquet}")
    except Exception:
        df.to_csv(cache_csv)
        print(f"[data] 写入本地缓存（csv）：{cache_csv}")

    return df


def _generate_demo_data(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """生成正弦叠加随机噪声的演示 OHLCV 数据。"""
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
