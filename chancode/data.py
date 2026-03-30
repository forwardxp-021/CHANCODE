"""chancode.data – 行情数据下载与处理。

支持通过 yfinance 下载真实数据，也提供内置演示数据。
支持将下载数据缓存到本地，避免重复网络请求。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests
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


def _cache_paths(ticker: str, interval: str, num_periods: int, source_tag: str) -> tuple[Path, Path]:
    """Return parquet and csv cache paths for a given key; include source to avoid mixing."""
    key = f"{source_tag}_{ticker}_{interval}_{num_periods}"
    stem = hashlib.md5(key.encode()).hexdigest()
    return _CACHE_DIR / f"{stem}.parquet", _CACHE_DIR / f"{stem}.csv"


def _has_qveris_key() -> bool:
    return bool((os.getenv("QVERIS_API_KEY") or "").strip())


def _normalize_ticker_for_yfinance(ticker: str) -> str:
    """Normalize mainland A-share numeric code to yfinance suffix format."""
    t = (ticker or "").strip().upper()
    if "." in t:
        return t
    if len(t) == 6 and t.isdigit():
        if t.startswith(("6", "9")):
            return f"{t}.SS"
        return f"{t}.SZ"
    return t


def _period_to_num_periods(period: str, interval: str) -> int:
    """Rough conversion from yfinance-like period to bar count for QVeris calls."""
    p = (period or "").strip().lower()
    if not p:
        return DEFAULT_NUM_PERIODS

    unit = p[-1]
    try:
        value = int(p[:-1])
    except ValueError:
        return DEFAULT_NUM_PERIODS

    if unit == "d":
        if interval == "1d":
            return max(20, value)
        if interval == "1wk":
            return max(4, value // 5)
        if interval == "30m":
            return max(20, value * 8)
        if interval == "5m":
            return max(20, value * 48)
    if unit == "w":
        if interval == "1wk":
            return max(8, value)
        if interval == "1d":
            return max(20, value * 5)
    if unit == "m":  # month
        if interval == "1wk":
            return max(8, value * 4)
        if interval == "1d":
            return max(20, value * 22)
    if unit == "y":
        if interval == "1wk":
            return max(52, value * 52)
        if interval == "1d":
            return max(200, value * 250)

    return DEFAULT_NUM_PERIODS


def _parse_qveris_timestamp(v) -> pd.Timestamp:
    if isinstance(v, (int, float)):
        # auto-detect ms/seconds
        unit = "ms" if int(v) > 10**11 else "s"
        return pd.to_datetime(v, unit=unit)
    return pd.to_datetime(v)


def _qveris_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _qveris_tools_from_search_body(body) -> tuple[str | None, list[dict]]:
    if not isinstance(body, dict):
        return None, []

    search_id = body.get("search_id") or body.get("id")
    candidates = body.get("tools") or body.get("results") or body.get("data")

    if isinstance(candidates, list):
        tools = [x for x in candidates if isinstance(x, dict)]
        return search_id, tools

    if isinstance(candidates, dict):
        values = candidates.get("items") or candidates.get("tools") or candidates.get("results")
        if isinstance(values, list):
            tools = [x for x in values if isinstance(x, dict)]
            return search_id, tools

    return search_id, []


def _qveris_pick_tool(tools: list[dict]) -> dict:
    forced = (os.getenv("QVERIS_TOOL_ID") or "").strip()
    if forced:
        for t in tools:
            tid = str(t.get("tool_id") or t.get("id") or "")
            if tid == forced:
                return t

    def score(tool: dict) -> int:
        txt = " ".join(
            str(tool.get(k, "")) for k in ("tool_id", "id", "name", "title", "description")
        ).lower()
        s = 0
        for kw, w in (
            ("stock", 3),
            ("ohlcv", 4),
            ("kline", 4),
            ("candlestick", 3),
            ("market", 2),
            ("china", 2),
            ("a-share", 2),
            ("quote", 1),
        ):
            if kw in txt:
                s += w
        return s

    ranked = sorted(tools, key=score, reverse=True)
    return ranked[0]


def _qveris_rank_tools(tools: list[dict]) -> list[dict]:
    forced = (os.getenv("QVERIS_TOOL_ID") or "").strip()
    if forced:
        forced_tools = [t for t in tools if str(t.get("tool_id") or t.get("id") or "") == forced]
        if forced_tools:
            others = [t for t in tools if t not in forced_tools]
            return forced_tools + others

    def score(tool: dict) -> int:
        txt = " ".join(
            str(tool.get(k, "")) for k in ("tool_id", "id", "name", "title", "description")
        ).lower()
        s = 0
        for kw, w in (
            ("stock", 3),
            ("ohlcv", 4),
            ("kline", 4),
            ("candlestick", 3),
            ("history", 3),
            ("historical", 3),
            ("china", 2),
            ("a-share", 2),
            ("eod", 2),
            ("live", 1),
        ):
            if kw in txt:
                s += w
        return s

    return sorted(tools, key=score, reverse=True)


def _qveris_extract_param_names(tool: dict) -> set[str]:
    names: set[str] = set()
    params_list = tool.get("params")
    if isinstance(params_list, list):
        for p in params_list:
            if isinstance(p, dict) and p.get("name"):
                names.add(str(p.get("name")))

    for k in ("params", "parameters", "input", "input_schema", "schema"):
        v = tool.get(k)
        if isinstance(v, dict):
            props = v.get("properties") if isinstance(v.get("properties"), dict) else None
            if props:
                names.update(str(x) for x in props.keys())
            else:
                names.update(str(x) for x in v.keys())
    return {x for x in names if x and x not in {"type", "required", "description"}}


def _build_qveris_parameters(tool: dict, ticker: str, interval: str, num_periods: int) -> dict:
    names = _qveris_extract_param_names(tool)

    # If schema is unavailable, use a minimal common parameter set.
    if not names:
        return {
            "symbol": ticker,
            "interval": interval,
            "limit": int(max(1, num_periods)),
        }

    params: dict = {}

    def put(cands: tuple[str, ...], value):
        for c in cands:
            if c in names:
                params[c] = value
                return

    put(("symbol", "ticker", "code", "stock_code", "ts_code", "security", "instrument"), ticker)
    put(("interval", "timeframe", "freq", "period", "bar", "granularity"), interval)
    put(("limit", "count", "size", "num", "n"), int(max(1, num_periods)))

    if ticker.isdigit() and len(ticker) == 6:
        if ticker.startswith(("6", "9")):
            put(("exchange", "market", "board"), "SSE")
        else:
            put(("exchange", "market", "board"), "SZSE")

    return params


def _build_qveris_parameter_candidates(tool: dict, ticker: str, interval: str, num_periods: int) -> list[dict]:
    names = _qveris_extract_param_names(tool)

    ticker_variants = [ticker]
    if ticker.isdigit() and len(ticker) == 6:
        ticker_variants = [
            f"{ticker}.SH",
            f"{ticker}.SS",
            f"SH{ticker}",
            ticker,
            f"{ticker}.SZ",
            f"SZ{ticker}",
            f"{ticker}.XSHG",
            f"{ticker}.XSHE",
        ]

    today = pd.Timestamp.today().normalize()
    start = today - pd.Timedelta(days=max(120, num_periods * 3))
    start_s = start.strftime("%Y-%m-%d")
    end_s = today.strftime("%Y-%m-%d")
    start_compact = start.strftime("%Y%m%d")
    end_compact = today.strftime("%Y%m%d")

    interval_variants = {
        "1d": ["D", "1d", "daily"],
        "1wk": ["1wk", "W", "weekly"],
        "30m": ["30m", "30min", "30m", "intraday"],
        "5m": ["5m", "5min", "intraday"],
    }.get(interval, [interval])

    candidates: list[dict] = []

    # Candidate 1: generic mapped parameters
    base = _build_qveris_parameters(tool, ticker=ticker, interval=interval, num_periods=num_periods)
    candidates.append(base)

    # Candidate 2: tool-specific quick templates for fast_fin-like API
    if "codes" in names and ("startdate" in names or "enddate" in names):
        for tv in ticker_variants:
            for iv in interval_variants[:2]:
                d1 = {"codes": tv, "interval": iv}
                if "startdate" in names:
                    d1["startdate"] = start_s
                if "enddate" in names:
                    d1["enddate"] = end_s
                candidates.append(d1)

                d2 = {"codes": tv, "interval": iv}
                if "startdate" in names:
                    d2["startdate"] = start_compact
                if "enddate" in names:
                    d2["enddate"] = end_compact
                candidates.append(d2)

    # Candidate 2+: schema-aware variants for common financial APIs
    for tv in ticker_variants:
        for iv in interval_variants:
            p: dict = {}

            for key in ("codes", "symbols", "tickers"):
                if key in names:
                    p[key] = tv
            for key in ("symbol", "ticker", "code", "stock_code", "ts_code", "security", "instrument"):
                if key in names and key not in p:
                    p[key] = tv

            for key in ("startdate", "start_date", "start", "from", "begin", "since"):
                if key in names:
                    p[key] = start_s
            for key in ("enddate", "end_date", "end", "to", "until"):
                if key in names:
                    p[key] = end_s

            for key in ("interval", "timeframe", "freq", "period", "bar", "granularity"):
                if key in names:
                    p[key] = iv

            for key in ("limit", "count", "size", "num", "n"):
                if key in names:
                    p[key] = int(max(1, num_periods))

            if "indicators" in names:
                p["indicators"] = "stock_common"
            if "order" in names:
                p["order"] = "asc"
            if "adjust" in names:
                p["adjust"] = "none"
            if "market" in names and ticker.isdigit() and len(ticker) == 6 and "." not in tv:
                p["market"] = "SH" if ticker.startswith(("6", "9")) else "SZ"

            if p:
                candidates.append(p)

    # Deduplicate candidates while preserving order.
    uniq: list[dict] = []
    seen: set[str] = set()
    for c in candidates:
        k = json.dumps(c, sort_keys=True, ensure_ascii=False)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(c)

    return uniq


def _extract_ohlcv_rows_from_obj(obj) -> list[dict]:
    """Recursively extract OHLCV row dicts from arbitrary QVeris tool output."""
    rows: list[dict] = []

    def has_ohlc_keys(d: dict) -> bool:
        ks = {str(k).lower() for k in d.keys()}
        return (
            ("open" in ks and "high" in ks and "low" in ks and "close" in ks)
            or ({"o", "h", "l", "c"}.issubset(ks))
        )

    def walk(x):
        if isinstance(x, dict):
            if has_ohlc_keys(x):
                rows.append(x)
                return
            for v in x.values():
                walk(v)
            return

        if isinstance(x, list):
            for v in x:
                walk(v)
            return

        if isinstance(x, str):
            s = x.strip()
            if not s:
                return
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    walk(json.loads(s))
                except Exception:
                    pass

    walk(obj)
    return rows


def _extract_rows_from_qveris_exec_body(exec_body: dict, timeout: float) -> list[dict]:
    """Extract OHLCV rows, including follow-up download for truncated tool outputs."""
    rows = _extract_ohlcv_rows_from_obj(exec_body)
    if rows:
        return rows

    if not isinstance(exec_body, dict):
        return []

    result = exec_body.get("result") if isinstance(exec_body.get("result"), dict) else {}
    full_url = result.get("full_content_file_url") or exec_body.get("full_content_file_url")
    if not full_url:
        return []

    try:
        fr = requests.get(str(full_url), timeout=timeout)
        if fr.status_code >= 400:
            return []

        text = fr.text.strip()
        if not text:
            return []

        # Try JSON first.
        try:
            payload = fr.json()
        except Exception:
            payload = None
            if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None

        if payload is not None:
            rows = _extract_ohlcv_rows_from_obj(payload)
            if rows:
                return rows

        # Fallback: parse CSV-like content.
        if "," in text and "\n" in text:
            try:
                csv_df = pd.read_csv(io.StringIO(text))
                return csv_df.to_dict(orient="records")
            except Exception:
                return []
    except Exception:
        return []

    return []


def _fetch_ohlcv_qveris(
    ticker: str,
    interval: str,
    num_periods: int,
) -> pd.DataFrame:
    """Fetch OHLCV from QVeris official REST v1 (search + tools/execute)."""
    api_key = (os.getenv("QVERIS_API_KEY") or "").strip()
    if not api_key:
        raise ValueError("QVERIS_API_KEY is required for QVeris data source")

    base_url = (os.getenv("QVERIS_API_BASE") or "https://qveris.ai/api/v1").strip().rstrip("/")
    headers = _qveris_headers(api_key)

    search_query = (os.getenv("QVERIS_SEARCH_QUERY") or "China A-share stock OHLCV historical K-line API").strip()
    search_payload = {
        "query": search_query,
        "limit": int(max(3, int(os.getenv("QVERIS_SEARCH_LIMIT", "10")))),
    }
    search_timeout = float(os.getenv("QVERIS_SEARCH_TIMEOUT", "12"))
    exec_timeout = float(os.getenv("QVERIS_EXEC_TIMEOUT", "12"))

    s_resp = requests.post(f"{base_url}/search", json=search_payload, headers=headers, timeout=search_timeout)
    if s_resp.status_code >= 400:
        raise ConnectionError(f"QVeris /search failed: {s_resp.status_code} {s_resp.text[:200]}")

    search_body = s_resp.json()
    search_id, tools = _qveris_tools_from_search_body(search_body)
    if not tools:
        raise ValueError("QVeris /search returned no tools")

    ranked_tools = _qveris_rank_tools(tools)

    rows: list[dict] = []
    last_error = ""
    for tool in ranked_tools[: int(max(1, int(os.getenv("QVERIS_TRY_TOOLS", "3"))))]:
        tool_id = str(tool.get("tool_id") or tool.get("id") or "").strip()
        if not tool_id:
            continue

        param_candidates = _build_qveris_parameter_candidates(
            tool,
            ticker=ticker,
            interval=interval,
            num_periods=num_periods,
        )

        for params in param_candidates[: int(max(1, int(os.getenv("QVERIS_TRY_PARAMS", "3"))))]:
            exec_payload = {
                "search_id": search_id,
                "parameters": params,
                "max_response_size": int(os.getenv("QVERIS_MAX_RESPONSE_SIZE", "20480")),
            }
            try:
                e_resp = requests.post(
                    f"{base_url}/tools/execute",
                    params={"tool_id": tool_id},
                    json=exec_payload,
                    headers=headers,
                    timeout=exec_timeout,
                )
                if e_resp.status_code >= 400:
                    last_error = f"{tool_id}: HTTP {e_resp.status_code}"
                    continue

                exec_body = e_resp.json()
                if isinstance(exec_body, dict) and exec_body.get("success") is False:
                    last_error = str(exec_body.get("error_message") or f"{tool_id}: execution failed")
                    continue

                rows = _extract_rows_from_qveris_exec_body(exec_body, timeout=exec_timeout)
                if rows:
                    print(f"[data] QVeris tool selected: {tool_id}")
                    break

                last_error = f"{tool_id}: no parseable OHLCV rows"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{tool_id}: {exc}"
                continue

        if rows:
            break

    if not rows:
        hint = ""
        err_l = (last_error or "").lower()
        if "http 402" in err_l or "状态码:402" in err_l or "状态码: 402" in err_l:
            hint = " (HTTP 402，通常表示额度不足或当前账号无该工具权限；可切换 Yahoo 或升级 QVeris 配额/权限)"
        raise ValueError(f"QVeris execution failed for ticker={ticker}. Last error: {last_error or 'unknown'}{hint}")

    normalized = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        dt_raw = r.get("datetime", r.get("timestamp", r.get("date", r.get("time"))))
        if dt_raw is None:
            continue

        o = r.get("open", r.get("Open", r.get("o", r.get("O"))))
        h = r.get("high", r.get("High", r.get("h", r.get("H"))))
        l = r.get("low", r.get("Low", r.get("l", r.get("L"))))
        c = r.get("close", r.get("Close", r.get("c", r.get("C"))))
        v = r.get("volume", r.get("Volume", r.get("vol", r.get("v", 0))))

        if o is None or h is None or l is None or c is None:
            continue

        normalized.append(
            {
                "Date": _parse_qveris_timestamp(dt_raw),
                "Open": float(o),
                "High": float(h),
                "Low": float(l),
                "Close": float(c),
                "Volume": float(v),
            }
        )

    if not normalized:
        raise ValueError("QVeris returned rows but no parseable OHLCV records")

    df = pd.DataFrame(normalized).set_index("Date").sort_index()
    if len(df) > num_periods:
        df = df.iloc[-num_periods:]
    print(f"[data] 下载 {len(df)} 行数据（{ticker}, source=qveris）。")
    return df


def _cache_path(ticker: str, interval: str, num_periods: int, source_tag: str) -> Path:
    """根据参数生成缓存文件路径（parquet）。"""
    return _cache_paths(ticker, interval, num_periods, source_tag)[0]


def _cache_csv_path(ticker: str, interval: str, num_periods: int, source_tag: str) -> Path:
    """根据参数生成缓存文件路径（csv）。"""
    return _cache_paths(ticker, interval, num_periods, source_tag)[1]


def _fetch_ohlcv_yahoo(ticker: str, period: str, interval: str, num_periods: int | None = None) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance and normalize columns/index."""
    yf_ticker = _normalize_ticker_for_yfinance(ticker)
    df = yf.download(
        yf_ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False,
        prepost=False,
        threads=False,
    )
    if df.empty:
        raise ValueError(
            f"未下载到数据：ticker={ticker}, period={period}, interval={interval}，"
            "请检查网络连接或参数是否正确。"
        )

    # yfinance 有时返回 MultiIndex 列，展平为单层
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if num_periods is not None and len(df) > num_periods:
        df = df.iloc[-num_periods:]
    print(f"[data] 下载 {len(df)} 行数据（{yf_ticker}, source=yfinance）。")
    return df


def fetch_ohlcv(
    ticker: str,
    period: str,
    interval: str,
    use_demo_data: bool = False,
    source: str | None = None,
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

    prefer_qveris = (source or "").lower() == "qveris"
    prefer_yf = (source or "").lower() == "yahoo"

    if prefer_qveris and not _has_qveris_key():
        raise ValueError("QVeris selected but QVERIS_API_KEY is not configured; please set it or choose Yahoo.")

    if prefer_qveris or (_has_qveris_key() and not prefer_yf):
        num_periods = _period_to_num_periods(period, interval)
        return _fetch_ohlcv_qveris(ticker=ticker, interval=interval, num_periods=num_periods)

    return _fetch_ohlcv_yahoo(ticker=ticker, period=period, interval=interval)


def fetch_ohlcv_cached(
    ticker: str,
    interval: str,
    num_periods: int = DEFAULT_NUM_PERIODS,
    use_offline_data: bool = False,
    force_refresh: bool = False,
    source: str | None = None,
) -> pd.DataFrame:
    """下载并缓存 OHLCV 数据，支持离线读取。

    :param ticker: 股票/指数代码，例如 ``AAPL``、``600519.SS``
    :param interval: K 线周期，``"5m"``、``"30m"``、``"1d"``、``"1wk"``
    :param num_periods: 返回的最大 K 线根数，默认 120
    :param use_offline_data: 为 True 时只读本地缓存，不发起网络请求
    :param force_refresh: 强制重新下载，忽略缓存（仅在线模式）
    :returns: 带有 Open/High/Low/Close/Volume 列的 DataFrame，索引为日期
    """
    source_tag = (source or "auto").lower()
    cache_parquet = _cache_path(ticker, interval, num_periods, source_tag)
    cache_csv = _cache_csv_path(ticker, interval, num_periods, source_tag)

    if use_offline_data:
        if cache_parquet.exists():
            print(f"[data] 离线读取本地缓存：{cache_parquet}")
            df = pd.read_parquet(cache_parquet)
            if len(df) > num_periods:
                df = df.iloc[-num_periods:]
            return df
        if cache_csv.exists():
            print(f"[data] 离线读取本地缓存：{cache_csv}")
            df = pd.read_csv(cache_csv, parse_dates=[0], index_col=0)
            if len(df) > num_periods:
                df = df.iloc[-num_periods:]
            return df
        raise ValueError(
            f"离线模式未找到本地数据：{cache_parquet} 或 {cache_csv}，请先联网下载一次再使用离线模式。"
        )

    prefer_qveris = source_tag == "qveris"

    def _read_fresh_cache() -> pd.DataFrame | None:
        if force_refresh:
            return None
        for path, reader in (
            (cache_parquet, pd.read_parquet),
            (cache_csv, lambda p: pd.read_csv(p, parse_dates=[0], index_col=0)),
        ):
            if not path.exists():
                continue
            mtime = pd.Timestamp(os.path.getmtime(path), unit="s", tz="UTC")
            if mtime >= pd.Timestamp.utcnow().normalize():
                print(f"[data] 读取本地缓存：{path}")
                return reader(path)
        return None

    def _save_cache(df: pd.DataFrame) -> None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            df.to_parquet(cache_parquet)
            print(f"[data] 写入本地缓存：{cache_parquet}")
        except ImportError:
            df.to_csv(cache_csv)
            print(f"[data] 写入本地缓存（csv）：{cache_csv}")

    if prefer_qveris:
        if not _has_qveris_key():
            raise ValueError("QVeris selected but QVERIS_API_KEY is not configured; please set it or choose Yahoo.")
        cached = _read_fresh_cache()
        if cached is not None:
            return cached
        df = _fetch_ohlcv_qveris(ticker=ticker, interval=interval, num_periods=num_periods)
        _save_cache(df)
        return df

    if source_tag == "auto" and _has_qveris_key():
        cached = _read_fresh_cache()
        if cached is not None:
            return cached
        try:
            df = _fetch_ohlcv_qveris(ticker=ticker, interval=interval, num_periods=num_periods)
            _save_cache(df)
            return df
        except Exception as exc:  # noqa: BLE001
            print(f"[data] QVeris auto mode failed, fallback to Yahoo: {exc}")

    # 判断缓存是否有效（同一自然日内）
    fresh = _read_fresh_cache()
    if fresh is not None:
        return fresh

    # 查找合适的下载周期
    period = _INTERVAL_TO_PERIOD.get(interval, "1y")
    df = _fetch_ohlcv_yahoo(ticker=ticker, period=period, interval=interval, num_periods=num_periods)
    print("[data] Yahoo 数据已保存至缓存。")

    # 写缓存
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(cache_parquet)
        print(f"[data] 写入本地缓存：{cache_parquet}")
    except ImportError:
        df.to_csv(cache_csv)
        print(f"[data] 写入本地缓存（csv）：{cache_csv}")

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
