"""tests/conftest.py – 测试公共工具函数。"""
from __future__ import annotations

import pandas as pd


def make_date_range(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
    """生成含 n 个工作日的日期索引，供各模块测试使用。"""
    return pd.bdate_range(start=start, periods=n)
