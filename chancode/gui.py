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
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
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
    diagnose_fractal_bar,
    map_fractals_to_original,
    merge_klines,
)
from chancode.bi import build_pens
from chancode.xd import build_segments
from chancode.zs import detect_zhongshu_with_basis
from chancode.signal import detect_buy_sell_points
from chancode.chart import plot_chan

# Interval options: display name -> yfinance interval code
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
    return "Low (near_gap=1)"


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

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda _e: self._on_close())
        self.bind("<Control-q>", lambda _e: self._on_close())

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

        # Fractal diagnostics
        self._diag_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Enable fractal diagnostics", variable=self._diag_var).pack(
            anchor=tk.W, pady=(10, 0)
        )
        ttk.Label(form, text="Diagnostic date (YYYY-MM-DD)").pack(anchor=tk.W, pady=(6, 0))
        self._diag_date_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self._diag_date_var).pack(fill=tk.X)

        # Display fractal denoise strength
        ttk.Label(form, text="Display fractal denoise").pack(anchor=tk.W, pady=(10, 0))
        self._display_denoise_var = tk.StringVar(
            value=_display_denoise_label_for_value(self._base_config.display_near_gap)
        )
        denoise_combo = ttk.Combobox(
            form,
            textvariable=self._display_denoise_var,
            values=list(_DISPLAY_DENOISE_OPTIONS.keys()),
            state="readonly",
            width=18,
        )
        denoise_combo.pack(fill=tk.X)

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
        self._log_clear()
        self._log_append("Analyzing, please wait...\n")
        thread = threading.Thread(target=self._run_analysis, daemon=True)
        thread.start()

    def _run_analysis(self) -> None:
        """Run full analysis in background, then update UI."""
        try:
            ticker = self._ticker_var.get().strip().upper()
            interval_label = self._interval_label_var.get().strip()
            interval = _INTERVAL_OPTIONS.get(interval_label, "1d")
            use_offline = self._offline_var.get()
            enable_diag = self._diag_var.get()
            diag_date_text = self._diag_date_var.get().strip()
            display_denoise_label = self._display_denoise_var.get().strip()
            display_near_gap = _DISPLAY_DENOISE_OPTIONS.get(display_denoise_label, 1)

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

            diag_target: pd.Timestamp | None = None
            if enable_diag:
                if not diag_date_text:
                    raise ValueError("Diagnostic mode enabled: please input diagnostic date (YYYY-MM-DD)")
                try:
                    diag_target = pd.Timestamp(diag_date_text)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError("Diagnostic date format must be YYYY-MM-DD") from exc

            self._log_append(
                f"Fetching data: {ticker}  interval={interval_label}({interval})"
                f"  bars={num_periods}"
                f"  min_bi_sep={runtime_cfg.min_bi_separation}"
                f"  zh_level={runtime_cfg.zhongshu_level}"
                f"  display_near_gap={runtime_cfg.display_near_gap}"
                f"  fractal_min_sep={runtime_cfg.fractal_min_separation}"
                f"  assess_lookahead={runtime_cfg.fractal_assess_lookahead_bars}"
                f"  assess_lower_gap={runtime_cfg.fractal_assess_lower_level_gap_bars}\n"
            )

            df = fetch_ohlcv_cached(
                ticker,
                interval,
                num_periods=num_periods,
                use_offline_data=use_offline,
                force_refresh=False,
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

            if enable_diag and diag_target is not None:
                diag_msg = diagnose_fractal_bar(
                    original_df=df,
                    merge_result=merge_result,
                    raw_fractals_merged=raw,
                    clustered_fractals_merged=fractals_all_merged,
                    mapped_fractals_original=fractals_for_plot,
                    target_datetime=diag_target,
                    allow_equal=runtime_cfg.fractal_allow_equal,
                )
                self._log_append(diag_msg + "\n")

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
                ),
            )

        except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
            # Capture error text eagerly to avoid late-binding issues in Tk callbacks.
            err_msg = str(exc)
            self.after(0, lambda m=err_msg: self._log_append(f"Error: {m}\n"))
            self.after(0, lambda m=err_msg: messagebox.showerror("Error", m))

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
            show=False,
        )
        self._update_chart(fig)
        self._update_summary(buys, sells, zhongshus, segments)
        self._set_bar_info_text("Hover on a bar to inspect attributes.")
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
