"""chan_theory_yfinance.py

演示缠论分型、笔与中枢的简单可视化示例脚本。

运行示例：
    python chan_theory_yfinance.py --ticker AAPL --period 1y --interval 1d --out result.png

作者: GitHub Copilot Agent
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf


@dataclass
class FractalPoint:
    """分型结构：记录索引、时间、极值与类型（顶/底）。"""

    idx: int
    datetime: pd.Timestamp
    ftype: str  # "top" 或 "bottom"
    high: float
    low: float

    @property
    def price(self) -> float:
        """顶分型取高点，底分型取低点。"""
        return self.high if self.ftype == "top" else self.low


@dataclass
class Pen:
    """笔：由相邻不同类型的分型首尾连接。"""

    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    start_price: float
    end_price: float
    high: float
    low: float


@dataclass
class Zhongshu:
    """中枢：三笔滑窗交集形成的价格重叠区间。"""

    start_idx: int
    end_idx: int
    start_datetime: pd.Timestamp
    end_datetime: pd.Timestamp
    low: float
    high: float


def fetch_ohlcv(ticker: str, period: str, interval: str, demo: bool = False) -> pd.DataFrame:
    """使用 yfinance 下载 OHLCV 数据，或使用内置 demo 数据。

    :param ticker: 股票代码
    :param period: 下载周期（传给 yfinance）
    :param interval: K 线周期
    :param demo: 是否使用内置演示数据
    """
    if demo:
        # 内置 demo 数据，方便在无网络环境快速演示
        dates = pd.date_range(end=pd.Timestamp.today(), periods=30, freq="D")
        base = np.linspace(100, 110, num=30) + np.sin(np.linspace(0, 3, num=30)) * 3
        noise = np.random.default_rng(42).normal(0, 1.5, size=30)
        close = base + noise
        open_ = close + np.random.default_rng(1).normal(0, 0.8, size=30)
        high = np.maximum(open_, close) + np.abs(np.random.default_rng(2).normal(0, 1, size=30))
        low = np.minimum(open_, close) - np.abs(np.random.default_rng(3).normal(0, 1, size=30))
        volume = np.random.default_rng(4).integers(1e5, 5e5, size=30)
        df = pd.DataFrame(
            {
                "Open": open_,
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": volume,
            },
            index=dates,
        )
        df.index.name = "Date"
        print(f"[demo] Generated {len(df)} rows demo data.")
        return df

    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if df.empty:
        raise ValueError("未下载到数据，请检查网络或参数。")
    df = df.dropna()
    print(f"Downloaded {len(df)} rows for {ticker}.")
    return df


def detect_fractals(df: pd.DataFrame) -> List[FractalPoint]:
    """检测三根 K 线分型：顶（中间高于两侧）、底（中间低于两侧）。"""
    highs = df["High"].values
    lows = df["Low"].values
    fractals: List[FractalPoint] = []

    for i in range(1, len(df) - 1):
        prev_h, curr_h, next_h = highs[i - 1], highs[i], highs[i + 1]
        prev_l, curr_l, next_l = lows[i - 1], lows[i], lows[i + 1]
        dt = df.index[i]

        is_top = curr_h > prev_h and curr_h > next_h
        is_bottom = curr_l < prev_l and curr_l < next_l

        # 若同时满足顶/底（极罕见），按更极端的幅度选择
        if is_top and not is_bottom:
            fractals.append(FractalPoint(i, dt, "top", curr_h, curr_l))
        elif is_bottom and not is_top:
            fractals.append(FractalPoint(i, dt, "bottom", curr_h, curr_l))
        elif is_top and is_bottom:
            if (curr_h - max(prev_h, next_h)) >= (min(prev_l, next_l) - curr_l):
                fractals.append(FractalPoint(i, dt, "top", curr_h, curr_l))
            else:
                fractals.append(FractalPoint(i, dt, "bottom", curr_h, curr_l))

    print(f"Detected {len(fractals)} raw fractals.")
    return fractals


def filter_and_alternate_fractals(fractals: List[FractalPoint]) -> List[FractalPoint]:
    """分型去重与交替：连续同类分型保留极端值，确保顶底交替。"""
    if not fractals:
        return []

    filtered: List[FractalPoint] = [fractals[0]]
    for f in fractals[1:]:
        last = filtered[-1]
        if f.ftype == last.ftype:
            # 此处为分型去重：连续顶分型取最高，连续底分型取最低
            if f.ftype == "top" and f.high > last.high:
                filtered[-1] = f
            elif f.ftype == "bottom" and f.low < last.low:
                filtered[-1] = f
        else:
            filtered.append(f)

    print(f"Filtered to {len(filtered)} alternating fractals.")
    return filtered


def build_pens(fractals: List[FractalPoint]) -> List[Pen]:
    """由相邻不同类型的分型构建笔。"""
    pens: List[Pen] = []
    for i in range(len(fractals) - 1):
        a, b = fractals[i], fractals[i + 1]
        if a.ftype == b.ftype:
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
            )
        )
    print(f"Built {len(pens)} pens.")
    return pens


def _range_overlap(ranges: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """计算多个区间交集，若无交集返回 None。"""
    lows, highs = zip(*ranges)
    low, high = max(lows), min(highs)
    if low <= high:
        return low, high
    return None


def detect_zhongshu(pens: List[Pen]) -> List[Zhongshu]:
    """三笔滑窗判断中枢，重叠即为中枢，并合并相邻重叠中枢。"""
    zhongshus: List[Zhongshu] = []
    for i in range(len(pens) - 2):
        window = pens[i : i + 3]
        overlap = _range_overlap([(p.low, p.high) for p in window])
        if overlap is None:
            continue
        low, high = overlap
        candidate = Zhongshu(
            start_idx=window[0].start_idx,
            end_idx=window[-1].end_idx,
            start_datetime=window[0].start_datetime,
            end_datetime=window[-1].end_datetime,
            low=low,
            high=high,
        )
        previous_overlap = (
            _range_overlap([(zhongshus[-1].low, zhongshus[-1].high), (candidate.low, candidate.high)])
            if zhongshus
            else None
        )
        if previous_overlap:
            # 合并重叠中枢：价格取交集，时间延长
            last = zhongshus[-1]
            merged_low, merged_high = previous_overlap
            last.end_idx = candidate.end_idx
            last.end_datetime = candidate.end_datetime
            last.low = merged_low
            last.high = merged_high
        else:
            zhongshus.append(candidate)

    print(f"Detected {len(zhongshus)} zhongshu.")
    return zhongshus


def detect_simple_breaks(
    df: pd.DataFrame, zhongshus: List[Zhongshu]
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """简单突破示例：中枢上沿突破为 BUY，下沿跌破为 SELL（每个中枢只取首个）。"""
    buys: List[Dict[str, object]] = []
    sells: List[Dict[str, object]] = []

    closes = df["Close"].values
    for zh in zhongshus:
        start = zh.end_idx + 1
        if start >= len(df):
            continue
        for i in range(start + 1, len(df)):
            prev_close, curr_close = closes[i - 1], closes[i]
            dt = df.index[i]
            if prev_close <= zh.high and curr_close > zh.high and not any(b["zh_idx"] == zh.start_idx for b in buys):
                buys.append({"idx": i, "datetime": dt, "price": curr_close, "zh_idx": zh.start_idx})
                break
            if prev_close >= zh.low and curr_close < zh.low and not any(s["zh_idx"] == zh.start_idx for s in sells):
                sells.append({"idx": i, "datetime": dt, "price": curr_close, "zh_idx": zh.start_idx})
                break

    print(f"Detected {len(buys)} buys, {len(sells)} sells.")
    return buys, sells


def plot_with_annotations(
    df: pd.DataFrame,
    fractals: List[FractalPoint],
    pens: List[Pen],
    zhongshus: List[Zhongshu],
    buys: List[Dict[str, object]],
    sells: List[Dict[str, object]],
    out: Optional[str] = None,
) -> None:
    """绘制 K 线、分型、笔、中枢与买卖点标注。"""
    fig, axes = mpf.plot(
        df,
        type="candle",
        style="yahoo",
        returnfig=True,
        figsize=(12, 8),
        volume=False,
        show_nontrading=False,
    )
    ax = axes[0]

    # 绘制分型
    top_x = [f.datetime for f in fractals if f.ftype == "top"]
    top_y = [f.high for f in fractals if f.ftype == "top"]
    bot_x = [f.datetime for f in fractals if f.ftype == "bottom"]
    bot_y = [f.low for f in fractals if f.ftype == "bottom"]
    if top_x:
        ax.scatter(top_x, top_y, marker="v", color="red", label="Top fractal")
    if bot_x:
        ax.scatter(bot_x, bot_y, marker="^", color="green", label="Bottom fractal")

    # 绘制笔
    for idx, pen in enumerate(pens):
        ax.plot(
            [pen.start_datetime, pen.end_datetime],
            [pen.start_price, pen.end_price],
            color="orange",
            linewidth=1.5,
            label="Pen" if idx == 0 else None,
        )

    # 绘制中枢
    for idx, zh in enumerate(zhongshus):
        x0 = mdates.date2num(zh.start_datetime)
        x1 = mdates.date2num(zh.end_datetime)
        rect = Rectangle(
            (x0, zh.low),
            x1 - x0,
            zh.high - zh.low,
            facecolor="blue",
            alpha=0.1,
            edgecolor="blue",
            linestyle="--",
            label="Zhongshu" if idx == 0 else None,
        )
        ax.add_patch(rect)
        ax.hlines([zh.low, zh.high], xmin=zh.start_datetime, xmax=zh.end_datetime, colors="blue", linestyles="dashed")

    # 买卖点标注
    if buys:
        ax.scatter([b["datetime"] for b in buys], [b["price"] for b in buys], marker="o", color="magenta", label="BUY")
        for b in buys:
            ax.annotate("BUY", xy=(b["datetime"], b["price"]), xytext=(0, 8), textcoords="offset points", color="magenta")
    if sells:
        ax.scatter([s["datetime"] for s in sells], [s["price"] for s in sells], marker="x", color="black", label="SELL")
        for s in sells:
            ax.annotate("SELL", xy=(s["datetime"], s["price"]), xytext=(0, -12), textcoords="offset points", color="black")

    ax.legend(loc="best")
    ax.set_title("Chan Theory Demo - Fractal, Pen, Zhongshu")

    if out:
        fig.savefig(out, dpi=200, bbox_inches="tight")
        print(f"Saved figure to {out}")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="缠论分型/笔/中枢演示")
    parser.add_argument("--ticker", type=str, default="AAPL", help="股票代码，默认 AAPL")
    parser.add_argument("--period", type=str, default="1y", help="下载周期，例如 1y, 6mo")
    parser.add_argument("--interval", type=str, default="1d", help="K 线周期，例如 1d, 1h")
    parser.add_argument("--out", type=str, default=None, help="输出图片路径，未提供则弹窗显示")
    parser.add_argument("--demo", action="store_true", help="使用内置 demo 数据，跳过网络请求")
    args = parser.parse_args()

    try:
        df = fetch_ohlcv(args.ticker, args.period, args.interval, demo=args.demo)
        fractals_raw = detect_fractals(df)
        fractals = filter_and_alternate_fractals(fractals_raw)
        pens = build_pens(fractals)
        zhongshus = detect_zhongshu(pens)
        buys, sells = detect_simple_breaks(df, zhongshus)

        print(
            f"Summary: fractals={len(fractals)}, pens={len(pens)}, "
            f"zhongshu={len(zhongshus)}, buys={len(buys)}, sells={len(sells)}"
        )
        plot_with_annotations(df, fractals, pens, zhongshus, buys, sells, out=args.out)
    except KeyboardInterrupt:
        print("用户主动中断，已退出。")
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"运行出错：{exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
