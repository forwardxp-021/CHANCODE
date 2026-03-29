"""tests/test_gui_format.py - GUI helper formatting tests."""
from __future__ import annotations

import pandas as pd

from chancode.gui import _format_bar_identifier, _format_merge_group_identifier


def test_format_bar_identifier_daily_uses_date_only():
    ts = pd.Timestamp("2025-11-05 14:35:00")
    assert _format_bar_identifier(ts, "1d") == "2025-11-05"


def test_format_bar_identifier_minute_uses_datetime():
    ts = pd.Timestamp("2025-11-05 14:35:00")
    assert _format_bar_identifier(ts, "5m") == "2025-11-05 14:35"


def test_format_merge_group_identifier_uses_first_id_plus_count_daily():
    idx = pd.to_datetime(["2025-11-05", "2025-11-06", "2025-11-07"])
    assert _format_merge_group_identifier(idx, [0, 1, 2], "1d") == "2025-11-05+2"


def test_format_merge_group_identifier_returns_na_for_singleton_group():
    idx = pd.to_datetime(["2025-11-05"])
    assert _format_merge_group_identifier(idx, [0], "1d") == "N/A"
