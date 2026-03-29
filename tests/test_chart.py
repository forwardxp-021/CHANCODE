"""tests/test_chart.py - chart rendering behavior tests."""
from __future__ import annotations

import pandas as pd

from chancode.chart import plot_chan
from chancode.fractal import FractalPoint


def _make_df() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "Open": [10, 11, 10.5, 10.8, 11.2],
            "High": [10.5, 11.5, 10.9, 11.1, 11.6],
            "Low": [9.8, 10.7, 10.2, 10.4, 10.9],
            "Close": [10.2, 11.0, 10.6, 10.9, 11.4],
            "Volume": [100, 120, 90, 110, 130],
        },
        index=dates,
    )


def test_plot_chan_draws_fractal_strength_labels_for_top_and_bottom(monkeypatch):
    # 防止测试中弹出窗口。
    monkeypatch.setattr("matplotlib.pyplot.show", lambda: None)

    df = _make_df()
    fractals = [
        FractalPoint(idx=1, datetime=df.index[1], ftype="top", high=11.5, low=10.7),
        FractalPoint(idx=2, datetime=df.index[2], ftype="bottom", high=10.9, low=10.2),
    ]

    fig = plot_chan(
        df=df,
        fractals=fractals,
        pens=[],
        segments=[],
        zhongshus=[],
        buys=[],
        sells=[],
        title="unit-test",
        out=None,
        fractal_strength_labels={(1, "top"): "72", (2, "bottom"): "88"},
        show=False,
    )

    texts = [t.get_text() for t in fig.axes[0].texts]
    assert "88" in texts
    assert "72" in texts
