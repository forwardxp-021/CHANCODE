"""chancode.chart - visualization.

Use mplfinance + matplotlib to draw chart elements:
    - Candlesticks
    - Fractal markers
    - Pens
    - Segments
    - Centers (overlap zones)
    - Buy/Sell points
"""
from __future__ import annotations

from typing import Dict, List, Optional

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import mplfinance as mpf
import pandas as pd

from chancode.fractal import FractalPoint, MergedKlineBox
from chancode.bi import Pen
from chancode.xd import Segment
from chancode.zs import Zhongshu
from chancode.signal import BuySellPoint

# Buy/Sell point style
_BS_STYLE: Dict[str, Dict] = {
    "B1": {"color": "lime",    "marker": "^", "zorder": 6},
    "B2": {"color": "green",   "marker": "^", "zorder": 6},
    "B3": {"color": "teal",    "marker": "^", "zorder": 6},
    "S1": {"color": "red",     "marker": "v", "zorder": 6},
    "S2": {"color": "orange",  "marker": "v", "zorder": 6},
    "S3": {"color": "darkred", "marker": "v", "zorder": 6},
}


def _build_pos_map(df: pd.DataFrame) -> Dict[pd.Timestamp, int]:
    """构建时间戳到 mplfinance x 轴整数位置的映射。"""
    return {pd.Timestamp(dt): i for i, dt in enumerate(df.index)}


def _x_of(dt: pd.Timestamp, pos_map: Dict[pd.Timestamp, int], fallback: int) -> int:
    """将时间戳映射为 x 轴整数位置；缺失时回退到给定索引。"""
    return pos_map.get(pd.Timestamp(dt), fallback)


def _draw_merged_kline_boxes(
    ax: plt.Axes,
    merged_boxes: List[MergedKlineBox],
) -> None:
    """Draw a rectangle for each merged K-line group on the candle chart."""
    if not merged_boxes:
        return

    label_added = False
    for box in merged_boxes:
        left = box.start_pos - 0.5
        width = box.end_pos - box.start_pos + 1.0
        height = box.high - box.low

        if height <= 0:
            continue

        rect = Rectangle(
            (left, box.low),
            width,
            height,
            facecolor="none",
            edgecolor="goldenrod",
            linestyle="-",
            linewidth=1.2,
            alpha=0.9,
            zorder=4,
            label="Merged K Box" if not label_added else None,
        )
        ax.add_patch(rect)
        label_added = True


def plot_chan(
    df: pd.DataFrame,
    fractals: List[FractalPoint],
    pens: List[Pen],
    segments: List[Segment],
    zhongshus: List[Zhongshu],
    buys: List[BuySellPoint],
    sells: List[BuySellPoint],
    title: str = "Chan Chart",
    out: Optional[str] = None,
    figsize: tuple = (14, 9),
    merged_indices: Optional[set] = None,
    merged_boxes: Optional[List[MergedKlineBox]] = None,
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
    :param merged_indices: 原始 df 中参与合并的行位置集合（整数）
    :param merged_boxes: 包含关系分组方框信息（优先使用）
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
    pos_map = _build_pos_map(df)

    # ── 合并 K 线显示 ─────────────────────────────────────────
    if merged_boxes:
        _draw_merged_kline_boxes(ax, merged_boxes)
    elif merged_indices:
        # backward compatibility: no grouped box metadata available
        pass

    # ── 分型 ──────────────────────────────────────────────────
    top_x = [_x_of(f.datetime, pos_map, f.idx) for f in fractals if f.ftype == "top"]
    top_y = [f.high for f in fractals if f.ftype == "top"]
    bot_x = [_x_of(f.datetime, pos_map, f.idx) for f in fractals if f.ftype == "bottom"]
    bot_y = [f.low for f in fractals if f.ftype == "bottom"]
    if top_x:
        ax.scatter(top_x, top_y, marker="v", color="red", s=40, zorder=5, label="Top Fractal")
    if bot_x:
        ax.scatter(bot_x, bot_y, marker="^", color="green", s=40, zorder=5, label="Bottom Fractal")

    # ── 笔 ───────────────────────────────────────────────────
    for idx, pen in enumerate(pens):
        x0 = _x_of(pen.start_datetime, pos_map, pen.start_idx)
        x1 = _x_of(pen.end_datetime, pos_map, pen.end_idx)
        ax.plot(
            [x0, x1],
            [pen.start_price, pen.end_price],
            color="orange",
            linewidth=1.2,
            alpha=0.8,
            label="Pen" if idx == 0 else None,
        )

    # ── 线段 ─────────────────────────────────────────────────
    for idx, seg in enumerate(segments):
        color = "royalblue" if seg.is_up else "salmon"
        x0 = _x_of(seg.start_datetime, pos_map, seg.start_idx)
        x1 = _x_of(seg.end_datetime, pos_map, seg.end_idx)
        ax.plot(
            [x0, x1],
            [seg.start_price, seg.end_price],
            color=color,
            linewidth=2.5,
            alpha=0.85,
            label="Segment (Up)" if (idx == 0 and seg.is_up) else ("Segment (Down)" if (idx == 0 and not seg.is_up) else None),
        )

    # ── 中枢 ─────────────────────────────────────────────────
    for idx, zh in enumerate(zhongshus):
        x0 = _x_of(zh.start_datetime, pos_map, zh.start_idx)
        x1 = _x_of(zh.end_datetime, pos_map, zh.end_idx)
        rect = Rectangle(
            (x0, zh.low),
            x1 - x0,
            zh.high - zh.low,
            facecolor="purple",
            alpha=0.08,
            edgecolor="purple",
            linestyle="--",
            linewidth=1.2,
            label="Center" if idx == 0 else None,
        )
        ax.add_patch(rect)
        ax.hlines(
            [zh.low, zh.high],
            xmin=x0,
            xmax=x1,
            colors="purple",
            linestyles="dashed",
            linewidth=0.8,
        )

    # ── 买卖点 ───────────────────────────────────────────────
    for pt in buys:
        style = _BS_STYLE[pt.bstype]
        x = _x_of(pt.datetime, pos_map, pt.idx)
        ax.scatter(x, pt.price, marker=style["marker"], color=style["color"],
                   s=80, zorder=style["zorder"])
        ax.annotate(
            pt.bstype,
            xy=(x, pt.price),
            xytext=(0, 10),
            textcoords="offset points",
            color=style["color"],
            fontsize=7,
            fontweight="bold",
        )

    for pt in sells:
        style = _BS_STYLE[pt.bstype]
        x = _x_of(pt.datetime, pos_map, pt.idx)
        ax.scatter(x, pt.price, marker=style["marker"], color=style["color"],
                   s=80, zorder=style["zorder"])
        ax.annotate(
            pt.bstype,
            xy=(x, pt.price),
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
        print(f"[chart] Chart saved to {out}")
    else:
        plt.show()

    return fig
