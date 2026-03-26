"""chancode.fractal – 分型识别与 K 线合并处理。

标准三 K 线顶底分型（顶：中间 K 线高点高于两侧；底：低点低于两侧）。
去重与交替处理：连续同类型分型保留极端值，确保序列顶底交替。

K 线合并规则（缠论标准）：
  相邻两根 K 线若存在包含关系（一根的高低点区间被另一根完全覆盖），则合并为一根，
  合并方向跟随前期趋势（上涨取高高、下跌取低低）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set

import pandas as pd


@dataclass
class FractalPoint:
    """分型结构：索引、时间戳、类型（top/bottom）及对应高低价。"""

    idx: int
    datetime: pd.Timestamp
    ftype: str  # "top" 或 "bottom"
    high: float
    low: float

    @property
    def price(self) -> float:
        """顶分型返回高点价，底分型返回低点价。"""
        return self.high if self.ftype == "top" else self.low


@dataclass
class MergedKlineBox:
    """用于显示包含关系的方框信息（基于原始K线位置）。"""

    start_pos: int
    end_pos: int
    high: float
    low: float


@dataclass
class MergeKlineResult:
    """K线包含处理结果，含映射关系。"""

    merged_df: pd.DataFrame
    merged_indices: Set[int]
    merged_boxes: List[MergedKlineBox]
    merged_to_original: List[List[int]]
    orig_to_merged_index: List[int]

    def __iter__(self):
        """兼容旧调用：允许按 3 元组解包。"""
        yield self.merged_df
        yield self.merged_indices
        yield self.merged_boxes


def _is_more_extreme(curr: FractalPoint, ref: FractalPoint) -> bool:
    """同类型分型比较极值强弱。"""
    if curr.ftype != ref.ftype:
        return False
    if curr.ftype == "top":
        return curr.high > ref.high
    return curr.low < ref.low


def merge_klines(df: pd.DataFrame) -> MergeKlineResult:
    """对原始 K 线序列执行缠论标准包含关系处理（K 线合并）。

    当相邻两根 K 线存在包含关系时，将其合并为一根独立 K 线：
    - 前期上涨趋势（当前高点 > 前一高点）：取 max(high)、max(low)；
    - 前期下跌趋势：取 min(high)、min(low)。

    :param df: 含 Open/High/Low/Close/Volume 列的原始 OHLCV DataFrame
    :returns: MergeKlineResult
        - merged_df: 合并后的 K 线 DataFrame（行数 ≤ 原始行数）
        - merged_indices: 原始 DataFrame 中被"吸收"进合并的行的整数位置集合（不含组首行）
        - merged_boxes: 每个包含组对应的显示方框（宽度=该组K线宽度，高低=该组最高最低）
        - merged_to_original: 合并后每根K线对应的原始位置列表
        - orig_to_merged_index: 每根原始K线对应的合并后K线位置
    """
    highs = df["High"].values
    lows = df["Low"].values
    opens = df["Open"].values
    closes = df["Close"].values
    volumes = df["Volume"].values
    index = df.index

    # 记录每个合并后的逻辑 K 线（以列表存储各字段）
    m_open: list = []
    m_high: list = []
    m_low: list = []
    m_close: list = []
    m_volume: list = []
    m_index: list = []

    # 每个逻辑 K 线包含的原始行位置列表
    group_positions: list = []  # list of list[int]

    for i in range(len(df)):
        if not m_high:
            # 第一根，直接放入
            m_open.append(opens[i])
            m_high.append(highs[i])
            m_low.append(lows[i])
            m_close.append(closes[i])
            m_volume.append(volumes[i])
            m_index.append(index[i])
            group_positions.append([i])
            continue

        prev_h = m_high[-1]
        prev_l = m_low[-1]
        curr_h = highs[i]
        curr_l = lows[i]

        # 判断包含关系：curr 被 prev 包含，或 prev 被 curr 包含
        contained = (prev_h >= curr_h and prev_l <= curr_l) or (
            curr_h >= prev_h and curr_l <= prev_l
        )

        if contained:
            # 确定趋势：用合并前的前一个逻辑 K 线与当前逻辑 K 线的高点比较
            if len(m_high) >= 2:
                trend_up = m_high[-1] > m_high[-2]
            else:
                trend_up = curr_h >= prev_h  # 只有一根历史时，以当前走向为准

            if trend_up:
                m_high[-1] = max(prev_h, curr_h)
                m_low[-1] = max(prev_l, curr_l)
            else:
                m_high[-1] = min(prev_h, curr_h)
                m_low[-1] = min(prev_l, curr_l)

            # open/close/volume 沿用该组第一根的开盘价和最后一根的收盘价及累计成交量
            m_close[-1] = closes[i]
            m_volume[-1] = m_volume[-1] + volumes[i]
            group_positions[-1].append(i)
        else:
            m_open.append(opens[i])
            m_high.append(highs[i])
            m_low.append(lows[i])
            m_close.append(closes[i])
            m_volume.append(volumes[i])
            m_index.append(index[i])
            group_positions.append([i])

    merged_df = pd.DataFrame(
        {
            "Open": m_open,
            "High": m_high,
            "Low": m_low,
            "Close": m_close,
            "Volume": m_volume,
        },
        index=m_index,
    )
    merged_df.index.name = df.index.name

    # 收集被合并（非首行）的原始位置
    merged_indices: Set[int] = set()
    for group in group_positions:
        if len(group) > 1:
            merged_indices.update(group[1:])

    merged_boxes: List[MergedKlineBox] = []
    for group in group_positions:
        if len(group) <= 1:
            continue
        start_pos = group[0]
        end_pos = group[-1]
        grp_high = max(float(highs[pos]) for pos in group)
        grp_low = min(float(lows[pos]) for pos in group)
        merged_boxes.append(
            MergedKlineBox(
                start_pos=start_pos,
                end_pos=end_pos,
                high=grp_high,
                low=grp_low,
            )
        )

    orig_to_merged_index = [-1] * len(df)
    for merged_i, group in enumerate(group_positions):
        for orig_i in group:
            orig_to_merged_index[orig_i] = merged_i

    print(
        f"[fractal] K线合并：{len(df)} → {len(merged_df)} 根"
        f"（{len(merged_indices)} 个原始K线参与合并）。"
    )
    return MergeKlineResult(
        merged_df=merged_df,
        merged_indices=merged_indices,
        merged_boxes=merged_boxes,
        merged_to_original=[list(g) for g in group_positions],
        orig_to_merged_index=orig_to_merged_index,
    )


def detect_fractals(df: pd.DataFrame, allow_equal: bool = True) -> List[FractalPoint]:
    """在 df 中识别三 K 线顶/底分型。

        allow_equal=True 时，支持平顶/平底，但要求高低点都满足方向性：
            顶：
                ch >= ph and ch >= nh and
                cl >= pl and cl >= nl and
                (ch > ph or ch > nh) and
                (cl > pl or cl > nl)
            底：
                ch <= ph and ch <= nh and
                cl <= pl and cl <= nl and
                (ch < ph or ch < nh) and
                (cl < pl or cl < nl)

        allow_equal=False 时使用严格不等号。
    若同时满足（极罕见），按更极端幅度选择类型。

    :param df: 含 High/Low 列的 OHLCV DataFrame
    :returns: 原始分型列表（可能含连续同类型）
    """
    highs = df["High"].values
    lows = df["Low"].values
    fractals: List[FractalPoint] = []

    for i in range(1, len(df) - 1):
        ph, ch, nh = highs[i - 1], highs[i], highs[i + 1]
        pl, cl, nl = lows[i - 1], lows[i], lows[i + 1]
        dt = df.index[i]

        if allow_equal:
            is_top = (
                ch >= ph and ch >= nh
                and cl >= pl and cl >= nl
                and (ch > ph or ch > nh)
                and (cl > pl or cl > nl)
            )
            is_bot = (
                ch <= ph and ch <= nh
                and cl <= pl and cl <= nl
                and (ch < ph or ch < nh)
                and (cl < pl or cl < nl)
            )
        else:
            is_top = ch > ph and ch > nh and cl > pl and cl > nl
            is_bot = ch < ph and ch < nh and cl < pl and cl < nl

        if is_top and not is_bot:
            fractals.append(FractalPoint(i, dt, "top", ch, cl))
        elif is_bot and not is_top:
            fractals.append(FractalPoint(i, dt, "bottom", ch, cl))
        elif is_top and is_bot:
            # 按幅度决定
            if (ch - max(ph, nh)) >= (min(pl, nl) - cl):
                fractals.append(FractalPoint(i, dt, "top", ch, cl))
            else:
                fractals.append(FractalPoint(i, dt, "bottom", ch, cl))

    print(f"[fractal] 原始分型 {len(fractals)} 个。")
    return fractals


def cluster_fractals_for_display(
    fractals: List[FractalPoint],
    near_gap: int = 2,
) -> List[FractalPoint]:
    """生成展示用分型序列：尽量保留结构拐点，减少无意义近邻噪声。"""
    if not fractals:
        return []

    near_gap = max(1, int(near_gap))
    ordered = sorted(fractals, key=lambda x: x.idx)
    clustered: List[FractalPoint] = []

    for f in ordered:
        if not clustered:
            clustered.append(f)
            continue

        last = clustered[-1]
        if f.ftype == last.ftype:
            # 同类分型只保留更极端，避免“连续顶部/底部全标记”。
            if _is_more_extreme(f, last):
                clustered[-1] = f
            continue

        # 异类分型过近时优先保留后者，减少一根K线内来回翻转的噪声。
        if (f.idx - last.idx) < near_gap:
            clustered[-1] = f
            continue

        clustered.append(f)

    return clustered


def build_fractals_for_bi(
    fractals: List[FractalPoint],
    min_separation: int = 3,
    min_pen_separation: int = 7,
) -> List[FractalPoint]:
    """分型去重、交替与有效性约束。

    规则目标：
    1) 保证顶底交替；
    2) 抑制过密分型（最小间隔）；
    3) 与成笔规则协同，优先保留可形成有效笔的分型端点。
    """
    if not fractals:
        return []

    min_separation = max(1, int(min_separation))
    min_pen_separation = max(1, int(min_pen_separation))

    ordered = sorted(fractals, key=lambda x: x.idx)

    # Pass 1: 连续同类型先取更极端值，得到基础交替序列。
    alternating: List[FractalPoint] = []
    for f in ordered:
        if not alternating:
            alternating.append(f)
            continue
        last = alternating[-1]
        if f.ftype == last.ftype:
            if _is_more_extreme(f, last):
                alternating[-1] = f
        else:
            alternating.append(f)

    # Pass 2: 处理过密的异类分型。间距不足时，将其视为噪声反转，
    # 优先保留同类型里更极端的端点，避免形成短促伪笔。
    compact: List[FractalPoint] = []
    for f in alternating:
        if not compact:
            compact.append(f)
            continue

        last = compact[-1]
        if f.ftype == last.ftype:
            if _is_more_extreme(f, last):
                compact[-1] = f
            continue

        if (f.idx - last.idx) >= min_separation:
            compact.append(f)
            continue

        if len(compact) >= 2 and compact[-2].ftype == f.ftype:
            prev_same = compact[-2]
            if _is_more_extreme(f, prev_same):
                compact[-2] = f
            compact.pop()  # 删除中间的噪声反向分型
        else:
            # 序列开头出现过密反向分型时，保留后者可提升后续成笔概率。
            compact[-1] = f

    # Pass 3: 与成笔最小间距协同，避免留下无法成笔的近邻反转点。
    final: List[FractalPoint] = []
    for f in compact:
        if not final:
            final.append(f)
            continue

        last = final[-1]
        if f.ftype == last.ftype:
            if _is_more_extreme(f, last):
                final[-1] = f
            continue

        if (f.idx - last.idx) >= min_pen_separation:
            final.append(f)
            continue

        # 距离不足成笔，尝试替换为更大摆动幅度的端点。
        if len(final) >= 2 and final[-2].ftype == f.ftype:
            prev_same = final[-2]
            old_swing = abs(last.price - prev_same.price)
            new_swing = abs(f.price - prev_same.price)
            if new_swing >= old_swing:
                final[-1] = f

    print(
        f"[fractal] 交替后分型 {len(final)} 个"
        f"（min_sep={min_separation}, min_pen_sep={min_pen_separation}）。"
    )
    return final


def filter_and_alternate_fractals(
    fractals: List[FractalPoint],
    min_separation: int = 3,
    min_pen_separation: int = 7,
) -> List[FractalPoint]:
    """兼容旧接口：等价于 build_fractals_for_bi。"""
    return build_fractals_for_bi(
        fractals,
        min_separation=min_separation,
        min_pen_separation=min_pen_separation,
    )


def map_fractals_to_original(
    fractals: List[FractalPoint],
    merge_result: MergeKlineResult,
    anchor: str = "extreme",
    original_index: pd.Index | None = None,
    original_df: pd.DataFrame | None = None,
) -> List[FractalPoint]:
    """将 merged_df 上的分型映射到原始K线坐标位置。"""
    if not fractals:
        return []

    if original_index is None:
        original_index = merge_result.merged_df.index

    mapped: List[FractalPoint] = []
    for f in fractals:
        if f.idx < 0 or f.idx >= len(merge_result.merged_to_original):
            continue
        group = merge_result.merged_to_original[f.idx]
        if not group:
            continue

        if anchor == "left":
            orig_pos = group[0]
        elif anchor == "middle":
            orig_pos = group[len(group) // 2]
        elif anchor == "extreme" and original_df is not None:
            if f.ftype == "top":
                orig_pos = max(group, key=lambda x: float(original_df["High"].iloc[x]))
            else:
                orig_pos = min(group, key=lambda x: float(original_df["Low"].iloc[x]))
        else:
            orig_pos = group[-1]

        if orig_pos < 0 or orig_pos >= len(original_index):
            continue

        mapped.append(
            FractalPoint(
                idx=orig_pos,
                datetime=original_index[orig_pos],
                ftype=f.ftype,
                high=f.high,
                low=f.low,
            )
        )

    return mapped
