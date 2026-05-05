"""chancode.gui – 基于 tkinter 的缠论图形界面。

界面布局：
  左侧控制面板  – 参数输入（股票代码、K 线种类下拉菜单）、分析按钮
  右侧图表区域  – 嵌入的 matplotlib 缠论图表
  底部信息栏    – 运行日志 / 买卖点汇总

运行方式：
    python -m chancode.gui
或从代码调用：
    from chancode.gui import run_gui
    run_gui()
"""
from __future__ import annotations

import os
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Optional

# 允许直接运行 `python chancode/gui.py`：
# 1) 将项目根目录加入 sys.path，保证 `from chancode...` 可导入。
# 2) 移除脚本目录，避免 `chancode/signal.py` 阴影标准库 `signal`。
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
    _root_dir = os.path.dirname(_pkg_dir)
    if _root_dir not in sys.path:
        sys.path.insert(0, _root_dir)
    if _pkg_dir in sys.path:
        sys.path.remove(_pkg_dir)

import pandas as pd

import matplotlib
matplotlib.use("TkAgg")  # 必须在导入 pyplot 之前设置

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.backends._backend_tk import NavigationToolbar2Tk
from matplotlib.figure import Figure

from chancode.config import Config, load_config
from chancode.data import fetch_ohlcv_cached, DEFAULT_NUM_PERIODS
from chancode.fractal import (
    detect_fractals,
    cluster_fractals_for_display,
    build_fractals_for_bi,
    assess_fractals,
    map_fractals_to_original,
    merge_klines,
)
from chancode.bi import build_pens
from chancode.xd import build_segments
from chancode.zs import detect_zhongshu_with_basis
from chancode.signal import detect_buy_sell_points
from chancode.chart import plot_chan

# Interval options: display name -> TDX period code
_INTERVAL_OPTIONS: dict[str, str] = {
    "5 min":  "5m",
    "30 min": "30m",
    "Daily":  "1d",
    "Weekly": "1wk",
}

_DISPLAY_DENOISE_OPTIONS: dict[str, int] = {
    "Low (near_gap=1)": 1,
    "Medium (near_gap=2)": 2,
    "High (near_gap=3)": 3,
}

def _display_denoise_label_for_value(value: int) -> str:
    for label, gap in _DISPLAY_DENOISE_OPTIONS.items():
        if gap == value:
            return label
    return "Medium (near_gap=2)"


def _normalize_ticker_for_tdx(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if not t:
        return t
    if "." in t:
        return t
    if len(t) == 6 and t.isdigit():
        return f"{t}.SH" if t.startswith(("6", "9")) else f"{t}.SZ"
    return t


def _resample_ohlcv(df: pd.DataFrame, rule: str, bars: int) -> pd.DataFrame:
    """Resample OHLCV and keep latest bars."""
    if df.empty:
        return df
    agg = (
        df.sort_index()
        .resample(rule, label="right", closed="right")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Open", "High", "Low", "Close"])
    )
    if len(agg) > bars:
        agg = agg.iloc[-bars:]
    agg.index.name = "Date"
    return agg


def _format_bar_identifier(ts: pd.Timestamp, interval: str) -> str:
    """Format bar id: date for daily/weekly, datetime for intraday."""
    iv = (interval or "").strip().lower()
    if iv in {"1d", "1wk"}:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def _format_merge_group_identifier(
    index: pd.Index,
    group_positions: list[int],
    interval: str,
) -> str:
    """Format merged-group id as first bar id + contained count, e.g. 2025-11-05+2."""
    if not group_positions or len(group_positions) <= 1:
        return "N/A"
    first_ts = pd.Timestamp(index[group_positions[0]])
    first_id = _format_bar_identifier(first_ts, interval)
    return f"{first_id}+{len(group_positions) - 1}"


def _load_ohlcv_from_attachment(file_path: str, num_periods: int) -> pd.DataFrame:
    """Load OHLC data from user attachment with columns: time/open/high/low/close."""
    last_err: Exception | None = None
    df_raw: pd.DataFrame | None = None

    def _extract_report_rows() -> pd.DataFrame | None:
        """Parse vendor text-report exports (.xls suffix but plain text)."""
        nonlocal last_err
        report_text = ""
        for enc in ("utf-8-sig", "gb18030", "gbk"):
            try:
                with open(file_path, "r", encoding=enc, errors="ignore") as f:
                    report_text = f.read()
                if report_text.strip():
                    break
            except Exception as exc:  # noqa: BLE001
                last_err = exc

        if not report_text.strip():
            return None

        matches = re.findall(
            r"(?m)^\s*(\d{4}/\d{2}/\d{2}(?:-\d{2}:\d{2})?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)",
            report_text,
        )
        if not matches:
            return None
        return pd.DataFrame(matches, columns=["Date", "Open", "High", "Low", "Close"])

    # Prefer Excel parser for .xls/.xlsx; if unavailable/failed, fallback to delimited text.
    try:
        df_raw = pd.read_excel(file_path)
    except Exception as exc:  # noqa: BLE001
        last_err = exc

    if df_raw is None:
        for enc in ("utf-8-sig", "gb18030", "gbk"):
            try:
                df_raw = pd.read_csv(file_path, sep=None, engine="python", encoding=enc)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc

    if df_raw is None or df_raw.empty:
        df_raw = _extract_report_rows()

    if df_raw is None or df_raw.empty:
        raise ValueError(f"Failed to read attachment file: {file_path}. {last_err}")

    if df_raw.shape[1] < 5:
        raise ValueError("Attachment must contain at least 5 columns: time/open/high/low/close")

    sliced = df_raw.iloc[:, :5].copy()
    sliced.columns = ["Date", "Open", "High", "Low", "Close"]

    sliced["Date"] = pd.to_datetime(sliced["Date"], errors="coerce")
    for c in ("Open", "High", "Low", "Close"):
        sliced[c] = pd.to_numeric(sliced[c], errors="coerce")

    cleaned = sliced.dropna(subset=["Date", "Open", "High", "Low", "Close"]).copy()
    if cleaned.empty:
        extracted = _extract_report_rows()
        if extracted is not None:
            extracted["Date"] = pd.to_datetime(extracted["Date"], errors="coerce")
            for c in ("Open", "High", "Low", "Close"):
                extracted[c] = pd.to_numeric(extracted[c], errors="coerce")
            cleaned = extracted.dropna(subset=["Date", "Open", "High", "Low", "Close"]).copy()

    if cleaned.empty:
        raise ValueError("Attachment has no valid rows after parsing first five columns")

    cleaned["Volume"] = 0.0
    df = cleaned.set_index("Date").sort_index()
    if len(df) > num_periods:
        df = df.iloc[-num_periods:]
    return df


class ChanApp(tk.Tk):
    """Main window for Chan analysis."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__()
        self.title("ChanCode Quant Analyzer")
        self.geometry("1280x780")
        self.resizable(True, True)
        self._closing = False

        self._base_config = load_config(config_path)

        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None
        self._toolbar_frame: Optional[ttk.Frame] = None
        self._hover_cid: Optional[int] = None

        self._current_df: Optional[pd.DataFrame] = None
        self._current_interval: str = "1d"
        self._fractal_top_indices: set[int] = set()
        self._fractal_bottom_indices: set[int] = set()
        self._merged_indices_set: set[int] = set()
        self._merged_to_original_groups: list[list[int]] = []
        self._orig_to_merged_index: list[int] = []
        self._last_hover_idx: Optional[int] = None
        self._mouse_in_chart: bool = False
        self._analysis_running: bool = False

        self._rt_active: bool = False
        self._rt_ticker: str = ""
        self._rt_callback = None
        self._rt_refresh_pending: bool = False
        self._rt_last_refresh_ts: float = 0.0

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._on_close())
        self.bind("<Control-q>", lambda _e: self._on_close())
        self.bind_all("<Up>", self._on_key_up)
        self.bind_all("<Down>", self._on_key_down)

    # ─── UI 构建 ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build layout: left controls + right chart + bottom logs."""
        # 主分区
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左侧控制面板
        left_frame = ttk.Frame(paned, width=220)
        left_frame.pack_propagate(False)
        paned.add(left_frame, weight=0)

        # 右侧（图表 + 日志，可拖拽）
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        right_paned = ttk.PanedWindow(right_frame, orient=tk.VERTICAL)
        right_paned.pack(fill=tk.BOTH, expand=True)

        self._build_control_panel(left_frame)
        self._build_chart_area(right_paned)
        self._build_log_area(right_paned)

    def _build_control_panel(self, parent: ttk.Frame) -> None:
        """Left side: inputs and action buttons."""
        ttk.Label(parent, text="Parameters", font=("", 12, "bold")).pack(pady=(12, 4))
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # 参数表单
        form = ttk.Frame(parent, padding=8)
        form.pack(fill=tk.X)

        # Ticker input
        ttk.Label(form, text="Ticker").pack(anchor=tk.W, pady=(6, 0))
        self._ticker_var = tk.StringVar(value="601800")
        ttk.Entry(form, textvariable=self._ticker_var).pack(fill=tk.X)

        # Interval dropdown
        ttk.Label(form, text="Interval").pack(anchor=tk.W, pady=(10, 0))
        self._interval_label_var = tk.StringVar(value="Daily")
        interval_combo = ttk.Combobox(
            form,
            textvariable=self._interval_label_var,
            values=list(_INTERVAL_OPTIONS.keys()),
            state="readonly",
            width=16,
        )
        interval_combo.pack(fill=tk.X)

        self._use_attachment_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Use local attachment file", variable=self._use_attachment_var).pack(
            anchor=tk.W, pady=(10, 0)
        )
        ttk.Label(form, text="Attachment (time/open/high/low/close)").pack(anchor=tk.W, pady=(6, 0))
        self._attachment_path_var = tk.StringVar(value="")
        attachment_row = ttk.Frame(form)
        attachment_row.pack(fill=tk.X)
        ttk.Entry(attachment_row, textvariable=self._attachment_path_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(attachment_row, text="Browse", command=self._on_browse_attachment).pack(side=tk.LEFT, padx=(4, 0))

        # Number of bars (default 120)
        ttk.Label(form, text=f"Bars to download (default {DEFAULT_NUM_PERIODS})").pack(anchor=tk.W, pady=(10, 0))
        self._periods_var = tk.StringVar(value=str(DEFAULT_NUM_PERIODS))
        ttk.Entry(form, textvariable=self._periods_var).pack(fill=tk.X)

        # Min separation to form a pen
        ttk.Label(form, text="Min Bi separation (bars)").pack(anchor=tk.W, pady=(10, 0))
        self._min_bi_sep_var = tk.StringVar(value=str(self._base_config.min_bi_separation))
        ttk.Entry(form, textvariable=self._min_bi_sep_var).pack(fill=tk.X)

        # Zhongshu level
        ttk.Label(form, text="Zhongshu level").pack(anchor=tk.W, pady=(10, 0))
        self._zh_level_var = tk.StringVar(value=self._base_config.zhongshu_level)
        zh_combo = ttk.Combobox(
            form,
            textvariable=self._zh_level_var,
            values=["bi", "segment"],
            state="readonly",
            width=16,
        )
        zh_combo.pack(fill=tk.X)

        # Offline data option
        self._offline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Use data offline", variable=self._offline_var).pack(
            anchor=tk.W, pady=(10, 0)
        )

        # Realtime mode
        self._realtime_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Realtime mode (subscribe_hq)", variable=self._realtime_var).pack(
            anchor=tk.W, pady=(10, 0)
        )

        # Display fractal denoise strength
        ttk.Label(form, text="Display fractal denoise").pack(anchor=tk.W, pady=(10, 0))
        self._display_denoise_var = tk.StringVar(
            value="Medium (near_gap=2)"
        )
        denoise_combo = ttk.Combobox(
            form,
            textvariable=self._display_denoise_var,
            values=list(_DISPLAY_DENOISE_OPTIONS.keys()),
            state="readonly",
            width=18,
        )
        denoise_combo.pack(fill=tk.X)

        ttk.Label(form, text="Display layers").pack(anchor=tk.W, pady=(10, 0))
        self._show_top_var = tk.BooleanVar(value=True)
        self._show_bottom_var = tk.BooleanVar(value=True)
        self._show_boxes_var = tk.BooleanVar(value=True)
        self._show_zhongshu_var = tk.BooleanVar(value=True)
        self._show_pens_var = tk.BooleanVar(value=True)
        self._show_segments_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Top fractals", variable=self._show_top_var).pack(anchor=tk.W)
        ttk.Checkbutton(form, text="Bottom fractals", variable=self._show_bottom_var).pack(anchor=tk.W)
        ttk.Checkbutton(form, text="Merged boxes", variable=self._show_boxes_var).pack(anchor=tk.W)
        ttk.Checkbutton(form, text="Centers (Zhongshu)", variable=self._show_zhongshu_var).pack(anchor=tk.W)
        ttk.Checkbutton(form, text="Pens", variable=self._show_pens_var).pack(anchor=tk.W)
        ttk.Checkbutton(form, text="Segments", variable=self._show_segments_var).pack(anchor=tk.W)

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=8)

        # Action buttons
        btn_frame = ttk.Frame(parent, padding=(8, 0))
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="▶  Analyze", command=self._on_run).pack(
            fill=tk.X, pady=4
        )
        ttk.Button(btn_frame, text="💾  Save Chart", command=self._on_save).pack(
            fill=tk.X, pady=4
        )

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=8)

        # Signal summary area
        ttk.Label(parent, text="Signal Summary", font=("", 10, "bold")).pack(anchor=tk.W, padx=8)
        self._summary_text = tk.Text(parent, height=12, state=tk.DISABLED,
                                     wrap=tk.WORD, font=("Courier", 8), relief=tk.FLAT)
        self._summary_text.pack(fill=tk.BOTH, padx=8, pady=(4, 0), expand=True)

    def _build_chart_area(self, parent: ttk.PanedWindow) -> None:
        """Right top: embedded matplotlib chart."""
        container = ttk.Frame(parent)
        parent.add(container, weight=4)

        top_paned = ttk.PanedWindow(container, orient=tk.HORIZONTAL)
        top_paned.pack(fill=tk.BOTH, expand=True)

        self._info_frame = ttk.LabelFrame(container, text="Bar Info", padding=6)
        self._info_frame.configure(width=220)
        self._info_frame.pack_propagate(False)
        top_paned.add(self._info_frame, weight=0)

        self._bar_info = tk.Text(
            self._info_frame,
            height=16,
            state=tk.DISABLED,
            wrap=tk.WORD,
            font=("Courier", 9),
            relief=tk.FLAT,
        )
        self._bar_info.pack(fill=tk.BOTH, expand=True)
        self._set_bar_info_text("Hover on a bar to inspect attributes.")

        self._chart_frame = ttk.Frame(container)
        top_paned.add(self._chart_frame, weight=1)

        # 初始占位画布
        self._placeholder_label = ttk.Label(
            self._chart_frame,
            text="← Configure parameters and click Analyze",
            font=("", 11),
            foreground="gray",
        )
        self._placeholder_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _build_log_area(self, parent: ttk.PanedWindow) -> None:
        """Right bottom: scrolling log box."""
        log_frame = ttk.LabelFrame(parent, text="Run Log", padding=4)
        parent.add(log_frame, weight=1)

        self._log = scrolledtext.ScrolledText(
            log_frame, height=5, state=tk.DISABLED, font=("Courier", 8)
        )
        self._log.pack(fill=tk.BOTH, expand=True)

    # ─── 事件处理 ───────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        """Analyze in background to avoid blocking UI."""
        if self._analysis_running:
            self._log_append("Analysis is running, please wait...\n")
            return
        self._log_clear()
        self._log_append("Analyzing, please wait...\n")
        thread = threading.Thread(target=self._run_analysis, daemon=True)
        thread.start()

    def _on_browse_attachment(self) -> None:
        """Pick local attachment file for OHLC analysis."""
        path = filedialog.askopenfilename(
            title="Select attachment file",
            filetypes=[
                ("Excel files", "*.xls *.xlsx"),
                ("CSV/Text", "*.csv *.txt"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._attachment_path_var.set(path)

    def _run_analysis(self) -> None:
        """Run full analysis in background, then update UI."""
        if self._analysis_running:
            return
        self._analysis_running = True
        try:
            ticker = self._ticker_var.get().strip().upper()
            interval_label = self._interval_label_var.get().strip()
            interval = _INTERVAL_OPTIONS.get(interval_label, "1d")
            use_offline = self._offline_var.get()
            realtime_mode = self._realtime_var.get()
            display_denoise_label = self._display_denoise_var.get().strip()
            display_near_gap = _DISPLAY_DENOISE_OPTIONS.get(display_denoise_label, 2)
            use_attachment = self._use_attachment_var.get()
            attachment_path = self._attachment_path_var.get().strip()
            show_fractal_tops = self._show_top_var.get()
            show_fractal_bottoms = self._show_bottom_var.get()
            show_boxes = self._show_boxes_var.get()
            show_zhongshu = self._show_zhongshu_var.get()
            show_pens = self._show_pens_var.get()
            show_segments = self._show_segments_var.get()

            try:
                num_periods = int(self._periods_var.get().strip())
            except ValueError:
                num_periods = DEFAULT_NUM_PERIODS

            try:
                min_bi_sep = int(self._min_bi_sep_var.get().strip())
            except ValueError as exc:
                raise ValueError("Min Bi separation must be an integer") from exc

            zh_level = self._zh_level_var.get().strip().lower()
            runtime_cfg = Config(
                min_bi_separation=min_bi_sep,
                fractal_allow_equal=self._base_config.fractal_allow_equal,
                display_near_gap=display_near_gap,
                fractal_min_separation=self._base_config.fractal_min_separation,
                fractal_assess_lookahead_bars=self._base_config.fractal_assess_lookahead_bars,
                fractal_assess_lower_level_gap_bars=self._base_config.fractal_assess_lower_level_gap_bars,
                zhongshu_level=zh_level,
            )
            if runtime_cfg.min_bi_separation < 1:
                raise ValueError("Min Bi separation must be >= 1")
            if runtime_cfg.zhongshu_level not in {"bi", "segment"}:
                raise ValueError("Zhongshu level must be 'bi' or 'segment'")

            self._log_append(
                f"Fetching data: {ticker}  interval={interval_label}({interval})"
                f"  bars={num_periods}"
                f"  realtime={'on' if realtime_mode else 'off'}"
                f"  min_bi_sep={runtime_cfg.min_bi_separation}"
                f"  zh_level={runtime_cfg.zhongshu_level}"
                f"  display_near_gap={runtime_cfg.display_near_gap}"
                f"  fractal_min_sep={runtime_cfg.fractal_min_separation}"
                f"  assess_lookahead={runtime_cfg.fractal_assess_lookahead_bars}"
                f"  assess_lower_gap={runtime_cfg.fractal_assess_lower_level_gap_bars}\n"
            )
            if use_attachment:
                if not attachment_path:
                    raise ValueError("Attachment mode enabled: please select a local file")
                if not os.path.exists(attachment_path):
                    raise ValueError(f"Attachment file not found: {attachment_path}")
                self._log_append(f"Data source: attachment file\n")
                self._log_append(f"Attachment: {attachment_path}\n")
                df = _load_ohlcv_from_attachment(attachment_path, num_periods=num_periods)
            else:
                self._log_append("Data source: TDX (Tongdaxin)\n")
                if realtime_mode and not use_offline:
                    self._refresh_realtime_kline_cache(ticker=ticker, interval=interval)

                if realtime_mode and interval == "30m" and not use_offline:
                    # TDX refresh_kline 不支持 30m，实时模式改为 5m 拉取后本地聚合 30m。
                    bars_5m = max(num_periods * 6 + 30, 180)
                    df_5m = fetch_ohlcv_cached(
                        ticker,
                        "5m",
                        num_periods=bars_5m,
                        use_offline_data=False,
                        force_refresh=True,
                    )
                    df = _resample_ohlcv(df_5m, "30min", num_periods)
                    self._log_append(
                        f"Realtime 30m mode: fetched 5m({len(df_5m)}) and resampled to 30m({len(df)})\n"
                    )
                else:
                    df = fetch_ohlcv_cached(
                        ticker,
                        interval,
                        num_periods=num_periods,
                        use_offline_data=use_offline,
                        force_refresh=True,  # 强制刷新数据
                    )
            self._log_append(f"Rows: {len(df)}\n")

            # K-line merge
            merge_result = merge_klines(df)
            merged_df = merge_result.merged_df
            merged_indices = merge_result.merged_indices
            merged_boxes = merge_result.merged_boxes
            self._log_append(
                f"Merge: {len(df)} -> {len(merged_df)} bars"
                f" ({len(merged_indices)} original bars merged)\n"
            )

            # Fractal analysis on merged bars
            raw = detect_fractals(merged_df, allow_equal=runtime_cfg.fractal_allow_equal)
            fractals_all_merged = cluster_fractals_for_display(
                raw,
                near_gap=runtime_cfg.display_near_gap,
            )

            # 次级别联动确认使用原始K线分型作为代理输入（更高密度）。
            raw_lower_level = detect_fractals(df, allow_equal=runtime_cfg.fractal_allow_equal)
            assessed = assess_fractals(
                merged_df,
                fractals_all_merged,
                lookahead_bars=runtime_cfg.fractal_assess_lookahead_bars,
                lower_level_fractals=raw_lower_level,
                lower_level_gap_bars=runtime_cfg.fractal_assess_lower_level_gap_bars,
            )

            fractals_for_bi = build_fractals_for_bi(
                fractals_all_merged,
                min_separation=runtime_cfg.fractal_min_separation,
                min_pen_separation=runtime_cfg.min_bi_separation,
            )
            fractals_for_plot = map_fractals_to_original(
                fractals_all_merged,
                merge_result,
                anchor="extreme",
                original_index=df.index,
                original_df=df,
            )

            # 在图上标注所有显示分型（顶+底）的力度。
            fractal_strength_labels = {}
            for merged_f, plotted_f in zip(fractals_all_merged, fractals_for_plot):
                match = next(
                    (x for x in assessed if x.point.ftype == merged_f.ftype and x.point.idx == merged_f.idx),
                    None,
                )
                if match is None:
                    continue
                fractal_strength_labels[(int(plotted_f.idx), merged_f.ftype)] = f"{int(round(match.strength_score))}"
            self._log_append(
                f"Fractals (display): {len(fractals_for_plot)}"
                f" / for_bi: {len(fractals_for_bi)}\n"
            )

            if assessed:
                strong_n = sum(1 for x in assessed if x.strength_level == "strong")
                reversal_n = sum(1 for x in assessed if x.structure_label == "reversal")
                lower_ok_n = sum(1 for x in assessed if x.lower_level_confirmed)
                self._log_append(
                    f"Fractal quality: strong={strong_n}/{len(assessed)}"
                    f"  reversal={reversal_n}"
                    f"  lower_confirmed={lower_ok_n}\n"
                )

            pens = build_pens(fractals_for_bi, config=runtime_cfg)
            self._log_append(f"Pens: {len(pens)}\n")

            segments = build_segments(pens)
            self._log_append(f"Segments: {len(segments)}\n")

            zhongshus = detect_zhongshu_with_basis(
                pens,
                segments=segments,
                config=runtime_cfg,
            )
            self._log_append(f"Centers: {len(zhongshus)}\n")

            buys, sells = detect_buy_sell_points(merged_df, zhongshus)
            self._log_append(f"Buy points: {len(buys)}, Sell points: {len(sells)}\n")

            # 绘图需要在主线程执行，避免 Matplotlib 线程警告/潜在崩溃。
            self.after(
                0,
                lambda: self._finish_analysis_render(
                    df=df,
                    fractals_for_plot=fractals_for_plot,
                    pens=pens,
                    segments=segments,
                    zhongshus=zhongshus,
                    buys=buys,
                    sells=sells,
                    interval_label=interval_label,
                    interval_code=interval,
                    ticker=ticker,
                    merged_indices=merged_indices,
                    merged_boxes=merged_boxes,
                    merged_to_original=merge_result.merged_to_original,
                    orig_to_merged_index=merge_result.orig_to_merged_index,
                    fractal_strength_labels=fractal_strength_labels,
                    show_fractal_tops=show_fractal_tops,
                    show_fractal_bottoms=show_fractal_bottoms,
                    show_boxes=show_boxes,
                    show_zhongshu=show_zhongshu,
                    show_pens=show_pens,
                    show_segments=show_segments,
                    realtime_mode=realtime_mode,
                    use_attachment=use_attachment,
                    use_offline=use_offline,
                ),
            )

        except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
            # Capture error text eagerly to avoid late-binding issues in Tk callbacks.
            err_msg = str(exc)
            self.after(0, lambda m=err_msg: self._log_append(f"Error: {m}\n"))
            self.after(0, lambda m=err_msg: messagebox.showerror("Error", m))
        finally:
            self._analysis_running = False
            self._rt_refresh_pending = False

    def _on_save(self) -> None:
        """Save current chart to PNG."""
        if self._fig is None:
            messagebox.showinfo("Info", "Please run analysis first.")
            return
        from tkinter.filedialog import asksaveasfilename
        path = asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
            title="Save Chart",
        )
        if path:
            self._fig.savefig(path, dpi=150, bbox_inches="tight")
            self._log_append(f"Chart saved to: {path}\n")

    def _on_close(self) -> None:
        """Gracefully close Tk app and embedded matplotlib resources."""
        if self._closing:
            return
        self._closing = True

        try:
            self._stop_realtime_subscription()
        except Exception:
            pass

        try:
            if self._canvas is not None and self._hover_cid is not None:
                self._canvas.mpl_disconnect(self._hover_cid)
                self._hover_cid = None
        except Exception:
            pass

        try:
            if self._fig is not None:
                plt.close(self._fig)
        except Exception:
            pass

        try:
            self.quit()
        except Exception:
            pass

        try:
            self.destroy()
        except Exception:
            pass

    def _finish_analysis_render(
        self,
        df,
        fractals_for_plot,
        pens,
        segments,
        zhongshus,
        buys,
        sells,
        interval_label,
        interval_code,
        ticker,
        merged_indices,
        merged_boxes,
        merged_to_original,
        orig_to_merged_index,
        fractal_strength_labels,
        show_fractal_tops,
        show_fractal_bottoms,
        show_boxes,
        show_zhongshu,
        show_pens,
        show_segments,
        realtime_mode,
        use_attachment,
        use_offline,
    ) -> None:
        """在主线程渲染图表并刷新 UI。"""
        self._current_df = df
        self._current_interval = interval_code
        self._fractal_top_indices = {int(f.idx) for f in fractals_for_plot if f.ftype == "top"}
        self._fractal_bottom_indices = {int(f.idx) for f in fractals_for_plot if f.ftype == "bottom"}
        self._merged_indices_set = set(merged_indices or set())
        self._merged_to_original_groups = list(merged_to_original or [])
        self._orig_to_merged_index = list(orig_to_merged_index or [])
        self._last_hover_idx = None

        title = f"{ticker}  {interval_label}  ({len(df)} bars)"
        fig = plot_chan(
            df,
            fractals_for_plot,
            pens,
            segments,
            zhongshus,
            buys,
            sells,
            title=title,
            out=None,
            merged_indices=merged_indices,
            merged_boxes=merged_boxes,
            fractal_strength_labels=fractal_strength_labels,
            show_fractal_tops=show_fractal_tops,
            show_fractal_bottoms=show_fractal_bottoms,
            show_merged_boxes=show_boxes,
            show_pens=show_pens,
            show_segments=show_segments,
            show_zhongshus=show_zhongshu,
            show=False,
        )
        self._update_chart(fig)
        self._update_summary(buys, sells, zhongshus, segments)
        self._set_bar_info_text("Hover on a bar to inspect attributes.")

        if realtime_mode and not use_attachment and not use_offline:
            self._start_realtime_subscription(ticker)
        else:
            self._stop_realtime_subscription()

        self._log_append("Analysis completed.\n")

    # ─── UI 更新（主线程） ──────────────────────────────────────────────────

    def _update_chart(self, fig: Figure) -> None:
        """Embed a new chart in the chart area."""
        # 移除占位文字
        self._placeholder_label.place_forget()

        # 销毁旧画布
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        if self._toolbar_frame is not None:
            self._toolbar_frame.destroy()
            self._toolbar_frame = None

        self._fig = fig
        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.pack(fill=tk.BOTH, expand=True)

        toolbar_frame = ttk.Frame(self._chart_frame)
        toolbar_frame.pack(fill=tk.X)
        NavigationToolbar2Tk(canvas, toolbar_frame)

        self._canvas = canvas
        self._toolbar_frame = toolbar_frame
        self._hover_cid = canvas.mpl_connect("motion_notify_event", self._on_chart_hover)
        widget.bind("<Enter>", self._on_chart_enter)
        widget.bind("<Leave>", self._on_chart_leave)

    def _on_chart_enter(self, _event) -> None:
        self._mouse_in_chart = True

    def _on_chart_leave(self, _event) -> None:
        self._mouse_in_chart = False

    def _on_key_up(self, _event) -> None:
        if not self._mouse_in_chart:
            return
        self._adjust_bars_and_refresh(-20)

    def _on_key_down(self, _event) -> None:
        if not self._mouse_in_chart:
            return
        self._adjust_bars_and_refresh(20)

    def _adjust_bars_and_refresh(self, delta: int) -> None:
        try:
            current = int(self._periods_var.get().strip())
        except ValueError:
            current = DEFAULT_NUM_PERIODS
        new_value = max(20, current + delta)
        self._periods_var.set(str(new_value))
        self._log_append(f"Bars changed: {current} -> {new_value}\n")
        self._on_run()

    def _start_realtime_subscription(self, ticker: str) -> None:
        normalized = _normalize_ticker_for_tdx(ticker)
        if not normalized:
            self._log_append("Realtime subscription skipped: empty ticker.\n")
            return
        if self._rt_active and self._rt_ticker == normalized:
            return
        self._stop_realtime_subscription()
        try:
            from tdxref.tqcenter import tq as _tq_mod  # type: ignore

            def _callback(data_str) -> None:
                if self._closing:
                    return
                self.after(0, lambda d=data_str: self._on_realtime_tick(d))

            self._rt_callback = _callback
            _tq_mod.subscribe_hq(stock_list=[normalized], callback=_callback)
            self._rt_active = True
            self._rt_ticker = normalized
            self._log_append(f"Realtime subscribed: {normalized}\n")
        except Exception as exc:  # noqa: BLE001
            self._rt_active = False
            self._rt_ticker = ""
            self._rt_callback = None
            self._log_append(f"Realtime subscribe failed: {exc}\n")

    def _stop_realtime_subscription(self) -> None:
        if not self._rt_active or not self._rt_ticker:
            self._rt_active = False
            self._rt_ticker = ""
            self._rt_callback = None
            return
        try:
            from tdxref.tqcenter import tq as _tq_mod  # type: ignore

            _tq_mod.unsubscribe_hq(stock_list=[self._rt_ticker])
            self._log_append(f"Realtime unsubscribed: {self._rt_ticker}\n")
        except Exception as exc:  # noqa: BLE001
            self._log_append(f"Realtime unsubscribe warning: {exc}\n")
        finally:
            self._rt_active = False
            self._rt_ticker = ""
            self._rt_callback = None

    def _on_realtime_tick(self, _data_str) -> None:
        if not self._rt_active or self._closing:
            return
        now = time.monotonic()
        if now - self._rt_last_refresh_ts < 1.0:
            return
        if self._analysis_running or self._rt_refresh_pending:
            return

        self._rt_last_refresh_ts = now
        self._rt_refresh_pending = True
        self._log_append("Realtime tick received, refreshing chart...\n")
        thread = threading.Thread(target=self._run_analysis, daemon=True)
        thread.start()

    def _refresh_realtime_kline_cache(self, ticker: str, interval: str) -> None:
        """Refresh TDX cache before realtime re-analysis."""
        normalized = _normalize_ticker_for_tdx(ticker)
        if not normalized:
            return

        period = ""
        iv = (interval or "").lower()
        if iv == "5m":
            period = "5m"
        elif iv == "30m":
            period = "5m"
        elif iv == "1d":
            period = "1d"

        if not period:
            return

        try:
            from tdxref.tqcenter import tq as _tq_mod  # type: ignore

            _tq_mod.refresh_kline(stock_list=[normalized], period=period)
            if iv == "30m":
                self._log_append("Realtime cache refresh: using 5m source for 30m aggregation.\n")
        except Exception as exc:  # noqa: BLE001
            self._log_append(f"Realtime cache refresh warning: {exc}\n")

    def _on_chart_hover(self, event) -> None:
        """Update bar info when hovering on the chart."""
        if self._current_df is None:
            return
        if event.inaxes is None or event.xdata is None:
            return

        idx = int(round(event.xdata))
        if idx < 0 or idx >= len(self._current_df):
            return
        if self._last_hover_idx == idx:
            return
        self._last_hover_idx = idx
        self._update_bar_info(idx)

    def _set_bar_info_text(self, text: str) -> None:
        self._bar_info.config(state=tk.NORMAL)
        self._bar_info.delete("1.0", tk.END)
        self._bar_info.insert(tk.END, text)
        self._bar_info.config(state=tk.DISABLED)

    def _update_bar_info(self, idx: int) -> None:
        if self._current_df is None:
            return

        row = self._current_df.iloc[idx]
        ts = pd.Timestamp(self._current_df.index[idx])
        bar_id = _format_bar_identifier(ts, self._current_interval)
        is_top = idx in self._fractal_top_indices
        is_bottom = idx in self._fractal_bottom_indices
        is_contained = idx in self._merged_indices_set
        merged_group_id = "N/A"
        if 0 <= idx < len(self._orig_to_merged_index):
            merged_i = self._orig_to_merged_index[idx]
            if 0 <= merged_i < len(self._merged_to_original_groups):
                merged_group_id = _format_merge_group_identifier(
                    self._current_df.index,
                    self._merged_to_original_groups[merged_i],
                    self._current_interval,
                )

        text = (
            f"Bar ID: {bar_id}\n"
            f"Index: {idx}\n"
            f"Datetime: {ts.strftime('%Y-%m-%d %H:%M')}\n"
            f"Open: {float(row['Open']):.4f}\n"
            f"High: {float(row['High']):.4f}\n"
            f"Low: {float(row['Low']):.4f}\n"
            f"Close: {float(row['Close']):.4f}\n"
            f"Top fractal: {'Yes' if is_top else 'No'}\n"
            f"Bottom fractal: {'Yes' if is_bottom else 'No'}\n"
            f"Contained by merge: {'Yes' if is_contained else 'No'}\n"
            f"Merged Group ID: {merged_group_id}\n"
        )
        self._set_bar_info_text(text)

    def _update_summary(self, buys, sells, zhongshus, segments) -> None:
        """Update signal summary textbox."""
        lines = []
        lines.append(f"Segments: {len(segments)}")
        lines.append(f"Centers: {len(zhongshus)}")
        lines.append("")
        lines.append("- Buy Points -")
        for b in buys:
            lines.append(f"  {b.bstype}  {b.datetime.date()}  ￥{b.price:.2f}")
        lines.append("")
        lines.append("- Sell Points -")
        for s in sells:
            lines.append(f"  {s.bstype}  {s.datetime.date()}  ￥{s.price:.2f}")

        self._summary_text.config(state=tk.NORMAL)
        self._summary_text.delete("1.0", tk.END)
        self._summary_text.insert(tk.END, "\n".join(lines))
        self._summary_text.config(state=tk.DISABLED)

    def _log_append(self, text: str) -> None:
        """向日志框追加文本。"""
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, text)
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _log_clear(self) -> None:
        self._log.config(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.config(state=tk.DISABLED)


def run_gui(config_path: Optional[str] = None) -> None:
    """启动缠论 GUI 应用程序。"""
    app = ChanApp(config_path=config_path)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app._on_close()


if __name__ == "__main__":
    run_gui()
