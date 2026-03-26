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


class ChanApp(tk.Tk):
    """Main window for Chan analysis."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__()
        self.title("ChanCode Quant Analyzer")
        self.geometry("1280x780")
        self.resizable(True, True)

        self._base_config = load_config(config_path)

        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None

        self._build_ui()

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

        # 右侧（图表 + 日志）
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._build_control_panel(left_frame)
        self._build_chart_area(right_frame)
        self._build_log_area(right_frame)

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

    def _build_chart_area(self, parent: ttk.Frame) -> None:
        """Right top: embedded matplotlib chart."""
        self._chart_frame = ttk.Frame(parent)
        self._chart_frame.pack(fill=tk.BOTH, expand=True)

        # 初始占位画布
        self._placeholder_label = ttk.Label(
            self._chart_frame,
            text="← Configure parameters and click Analyze",
            font=("", 11),
            foreground="gray",
        )
        self._placeholder_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _build_log_area(self, parent: ttk.Frame) -> None:
        """Right bottom: scrolling log box."""
        log_frame = ttk.LabelFrame(parent, text="Run Log", padding=4)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=4)

        self._log = scrolledtext.ScrolledText(
            log_frame, height=5, state=tk.DISABLED, font=("Courier", 8)
        )
        self._log.pack(fill=tk.X)

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
                zhongshu_level=zh_level,
            )
            if runtime_cfg.min_bi_separation < 1:
                raise ValueError("Min Bi separation must be >= 1")
            if runtime_cfg.zhongshu_level not in {"bi", "segment"}:
                raise ValueError("Zhongshu level must be 'bi' or 'segment'")

            self._log_append(
                f"Fetching data: {ticker}  interval={interval_label}({interval})"
                f"  bars={num_periods}"
                f"  min_bi_sep={runtime_cfg.min_bi_separation}"
                f"  zh_level={runtime_cfg.zhongshu_level}\n"
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
            raw = detect_fractals(merged_df, allow_equal=True)
            fractals_all_merged = cluster_fractals_for_display(raw, near_gap=2)
            fractals_for_bi = build_fractals_for_bi(
                fractals_all_merged,
                min_separation=3,
                min_pen_separation=runtime_cfg.min_bi_separation,
            )
            fractals_for_plot = map_fractals_to_original(
                fractals_all_merged,
                merge_result,
                anchor="extreme",
                original_index=df.index,
                original_df=df,
            )
            self._log_append(
                f"Fractals (display): {len(fractals_for_plot)}"
                f" / for_bi: {len(fractals_for_bi)}\n"
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

            title = f"{ticker}  {interval_label}  ({len(df)} bars)"
            fig = plot_chan(
                df, fractals_for_plot, pens, segments, zhongshus, buys, sells,
                title=title, out=None, merged_indices=merged_indices, merged_boxes=merged_boxes
            )

            # 在主线程中更新 UI
            self.after(0, lambda: self._update_chart(fig))
            self.after(0, lambda: self._update_summary(buys, sells, zhongshus, segments))
            self.after(0, lambda: self._log_append("Analysis completed.\n"))

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

    # ─── UI 更新（主线程） ──────────────────────────────────────────────────

    def _update_chart(self, fig: Figure) -> None:
        """Embed a new chart in the chart area."""
        # 移除占位文字
        self._placeholder_label.place_forget()

        # 销毁旧画布
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None

        self._fig = fig
        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        widget = canvas.get_tk_widget()
        widget.pack(fill=tk.BOTH, expand=True)

        toolbar_frame = ttk.Frame(self._chart_frame)
        toolbar_frame.pack(fill=tk.X)
        NavigationToolbar2Tk(canvas, toolbar_frame)

        self._canvas = canvas

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
    app.mainloop()


if __name__ == "__main__":
    run_gui()
