"""chancode – 缠论量化交易分析包。

模块说明：
  data    – 行情数据下载与处理
  fractal – 分型识别
  bi      – 笔识别
  xd      – 线段识别
  zs      – 中枢识别
  signal  – 买卖点信号
  chart   – 可视化
  gui     – 图形界面
"""
from __future__ import annotations

from chancode.data import fetch_ohlcv
from chancode.fractal import (
  FractalPoint,
  detect_fractals,
  cluster_fractals_for_display,
  build_fractals_for_bi,
  filter_and_alternate_fractals,
  map_fractals_to_original,
  merge_klines,
)
from chancode.bi import Pen, build_pens
from chancode.xd import Segment, build_segments
from chancode.zs import Zhongshu, detect_zhongshu, detect_zhongshu_with_basis
from chancode.signal import detect_buy_sell_points, BuySellPoint
from chancode.config import Config, load_config

__all__ = [
    "fetch_ohlcv",
    "FractalPoint",
    "detect_fractals",
    "cluster_fractals_for_display",
    "build_fractals_for_bi",
    "filter_and_alternate_fractals",
    "map_fractals_to_original",
    "merge_klines",
    "Pen",
    "build_pens",
    "Segment",
    "build_segments",
    "Zhongshu",
    "detect_zhongshu",
    "detect_zhongshu_with_basis",
    "detect_buy_sell_points",
    "BuySellPoint",
    "Config",
    "load_config",
]
