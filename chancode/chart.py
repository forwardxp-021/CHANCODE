"""chancode.chart – 可视化。

使用 mplfinance + matplotlib 绘制缠论全要素图表：
  - K 线蜡烛图
  - 分型标注（顶/底三角）
  - 笔（橙色折线）
  - 线段（蓝色粗线）
  - 中枢（半透明矩形区域）
  - 买卖点（彩色标记与标签）
"""
from __future__ import annotations

from typing import Dict, List, Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import mplfinance as mpf
import pandas as pd

from chancode.fractal import FractalPoint
from chancode.bi import Pen
from chancode.xd import Segment
from chancode.zs import Zhongshu
from chancode.signal import BuySellPoint

# 买卖点配色
_BS_STYLE: Dict[str, Dict] = {
    "B1": {"color": "lime",    "marker": "^", "zorder": 6},
    "B2": {"color": "green",   "marker": "^", "zorder": 6},
    "B3": {"color": "teal",    "marker": "^", "zorder": 6},
    "S1": {"color": "red",     "marker": "v", "zorder": 6},
    "S2": {"color": "orange",  "marker": "v", "zorder": 6},
    "S3": {"color": "darkred", "marker": "v", "zorder": 6},
}


def plot_chan(
    df: pd.DataFrame,
    fractals: List[FractalPoint],
    pens: List[Pen],
    segments: List[Segment],
    zhongshus: List[Zhongshu],
    buys: List[BuySellPoint],
    sells: List[BuySellPoint],
    title: str = "缠论图表",
    out: Optional[str] = None,
    figsize: tuple = (14, 9),
) -> plt.Figure:
    """绘制完整的缠论分析图。

    :param df: OHLCV DataFrame
    :param fractals: 交替分型列表
    :param pens: 笔列表
    :param segments: 线段列表
    :param zhongshus: 中枢列表
    :param buys: 买点列表
    :param sells: 卖点列表
    :param title: 图表标题
    :param out: 输出图片路径；为 None 时弹窗显示
    :param figsize: 图表尺寸
    :returns: matplotlib Figure 对象
    """
    fig, axes = mpf.plot(
        df,
        type="candle",
        style="yahoo",
        returnfig=True,
        figsize=figsize,
        volume=False,
        show_nontrading=False,
    )
    ax: plt.Axes = axes[0]

    # ── 分型 ──────────────────────────────────────────────────
    top_x = [f.datetime for f in fractals if f.ftype == "top"]
    top_y = [f.high for f in fractals if f.ftype == "top"]
    bot_x = [f.datetime for f in fractals if f.ftype == "bottom"]
    bot_y = [f.low for f in fractals if f.ftype == "bottom"]
    if top_x:
        ax.scatter(top_x, top_y, marker="v", color="red", s=40, zorder=5, label="顶分型")
    if bot_x:
        ax.scatter(bot_x, bot_y, marker="^", color="green", s=40, zorder=5, label="底分型")

    # ── 笔 ───────────────────────────────────────────────────
    for idx, pen in enumerate(pens):
        ax.plot(
            [pen.start_datetime, pen.end_datetime],
            [pen.start_price, pen.end_price],
            color="orange",
            linewidth=1.2,
            alpha=0.8,
            label="笔" if idx == 0 else None,
        )

    # ── 线段 ─────────────────────────────────────────────────
    for idx, seg in enumerate(segments):
        color = "royalblue" if seg.is_up else "salmon"
        ax.plot(
            [seg.start_datetime, seg.end_datetime],
            [seg.start_price, seg.end_price],
            color=color,
            linewidth=2.5,
            alpha=0.85,
            label="线段(上)" if (idx == 0 and seg.is_up) else ("线段(下)" if (idx == 0 and not seg.is_up) else None),
        )

    # ── 中枢 ─────────────────────────────────────────────────
    for idx, zh in enumerate(zhongshus):
        x0 = mdates.date2num(zh.start_datetime)
        x1 = mdates.date2num(zh.end_datetime)
        rect = Rectangle(
            (x0, zh.low),
            x1 - x0,
            zh.high - zh.low,
            facecolor="purple",
            alpha=0.08,
            edgecolor="purple",
            linestyle="--",
            linewidth=1.2,
            label="中枢" if idx == 0 else None,
        )
        ax.add_patch(rect)
        ax.hlines(
            [zh.low, zh.high],
            xmin=zh.start_datetime,
            xmax=zh.end_datetime,
            colors="purple",
            linestyles="dashed",
            linewidth=0.8,
        )

    # ── 买卖点 ───────────────────────────────────────────────
    for pt in buys:
        style = _BS_STYLE[pt.bstype]
        ax.scatter(pt.datetime, pt.price, marker=style["marker"], color=style["color"],
                   s=80, zorder=style["zorder"])
        ax.annotate(
            pt.bstype,
            xy=(pt.datetime, pt.price),
            xytext=(0, 10),
            textcoords="offset points",
            color=style["color"],
            fontsize=7,
            fontweight="bold",
        )

    for pt in sells:
        style = _BS_STYLE[pt.bstype]
        ax.scatter(pt.datetime, pt.price, marker=style["marker"], color=style["color"],
                   s=80, zorder=style["zorder"])
        ax.annotate(
            pt.bstype,
            xy=(pt.datetime, pt.price),
            xytext=(0, -14),
            textcoords="offset points",
            color=style["color"],
            fontsize=7,
            fontweight="bold",
        )

    # ── 图例与标题 ───────────────────────────────────────────
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title(title, fontsize=12)

    if out:
        fig.savefig(out, dpi=150, bbox_inches="tight")
        print(f"[chart] 图表已保存至 {out}")
    else:
        plt.show()

    return fig
