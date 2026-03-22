"""chancode.gui – 基于 tkinter 的缠论图形界面。

界面布局：
  左侧控制面板  – 参数输入（股票代码、周期、K 线间隔）、分析按钮
  右侧图表区域  – 嵌入的 matplotlib 缠论图表
  底部信息栏    – 运行日志 / 买卖点汇总

运行方式：
    python -m chancode.gui
或从代码调用：
    from chancode.gui import run_gui
    run_gui()
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")  # 必须在导入 pyplot 之前设置

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from chancode.data import fetch_ohlcv
from chancode.fractal import detect_fractals, filter_and_alternate_fractals
from chancode.bi import build_pens
from chancode.xd import build_segments
from chancode.zs import detect_zhongshu
from chancode.signal import detect_buy_sell_points
from chancode.chart import plot_chan


class ChanApp(tk.Tk):
    """缠论分析主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("缠论量化分析系统 – ChanCode")
        self.geometry("1280x780")
        self.resizable(True, True)

        self._fig: Optional[plt.Figure] = None
        self._canvas: Optional[FigureCanvasTkAgg] = None

        self._build_ui()

    # ─── UI 构建 ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """构建界面布局：左侧控制面板 + 右侧图表区 + 底部日志。"""
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
        """左侧：参数输入与操作按钮。"""
        ttk.Label(parent, text="缠论参数", font=("", 12, "bold")).pack(pady=(12, 4))
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # 参数表单
        form = ttk.Frame(parent, padding=8)
        form.pack(fill=tk.X)

        fields = [
            ("股票代码", "AAPL"),
            ("下载周期", "1y"),
            ("K 线间隔", "1d"),
        ]
        self._vars: dict[str, tk.StringVar] = {}
        for label, default in fields:
            ttk.Label(form, text=label).pack(anchor=tk.W, pady=(6, 0))
            var = tk.StringVar(value=default)
            self._vars[label] = var
            ttk.Entry(form, textvariable=var).pack(fill=tk.X)

        # 演示数据选项
        self._demo_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="使用演示数据（离线）", variable=self._demo_var).pack(
            anchor=tk.W, pady=(10, 0)
        )

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=8)

        # 操作按钮
        btn_frame = ttk.Frame(parent, padding=(8, 0))
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="▶  开始分析", command=self._on_run).pack(
            fill=tk.X, pady=4
        )
        ttk.Button(btn_frame, text="💾  保存图表", command=self._on_save).pack(
            fill=tk.X, pady=4
        )

        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8, pady=8)

        # 信号汇总区（分析后填充）
        ttk.Label(parent, text="信号汇总", font=("", 10, "bold")).pack(anchor=tk.W, padx=8)
        self._summary_text = tk.Text(parent, height=12, state=tk.DISABLED,
                                     wrap=tk.WORD, font=("Courier", 8), relief=tk.FLAT)
        self._summary_text.pack(fill=tk.BOTH, padx=8, pady=(4, 0), expand=True)

    def _build_chart_area(self, parent: ttk.Frame) -> None:
        """右侧上方：matplotlib 嵌入图表。"""
        self._chart_frame = ttk.Frame(parent)
        self._chart_frame.pack(fill=tk.BOTH, expand=True)

        # 初始占位画布
        self._placeholder_label = ttk.Label(
            self._chart_frame,
            text="← 配置参数后点击「开始分析」",
            font=("", 11),
            foreground="gray",
        )
        self._placeholder_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _build_log_area(self, parent: ttk.Frame) -> None:
        """右侧下方：滚动日志框。"""
        log_frame = ttk.LabelFrame(parent, text="运行日志", padding=4)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=4, pady=4)

        self._log = scrolledtext.ScrolledText(
            log_frame, height=5, state=tk.DISABLED, font=("Courier", 8)
        )
        self._log.pack(fill=tk.X)

    # ─── 事件处理 ───────────────────────────────────────────────────────────

    def _on_run(self) -> None:
        """点击「开始分析」：在后台线程执行，避免阻塞 UI。"""
        self._log_clear()
        self._log_append("正在分析，请稍候…\n")
        thread = threading.Thread(target=self._run_analysis, daemon=True)
        thread.start()

    def _run_analysis(self) -> None:
        """后台执行缠论全流程，完成后更新图表与汇总。"""
        try:
            ticker = self._vars["股票代码"].get().strip().upper()
            period = self._vars["下载周期"].get().strip()
            interval = self._vars["K 线间隔"].get().strip()
            demo = self._demo_var.get()

            self._log_append(f"下载数据：{ticker}  period={period}  interval={interval}\n")
            df = fetch_ohlcv(ticker, period, interval, use_demo_data=demo)
            self._log_append(f"数据行数：{len(df)}\n")

            raw = detect_fractals(df)
            fractals = filter_and_alternate_fractals(raw)
            self._log_append(f"分型：{len(fractals)} 个\n")

            pens = build_pens(fractals)
            self._log_append(f"笔：{len(pens)} 条\n")

            segments = build_segments(pens)
            self._log_append(f"线段：{len(segments)} 条\n")

            zhongshus = detect_zhongshu(pens)
            self._log_append(f"中枢：{len(zhongshus)} 个\n")

            buys, sells = detect_buy_sell_points(df, zhongshus)
            self._log_append(f"买点：{len(buys)} 个，卖点：{len(sells)} 个\n")

            title = f"{ticker}  {period}/{interval}"
            fig = plot_chan(df, fractals, pens, segments, zhongshus, buys, sells,
                            title=title, out=None)

            # 在主线程中更新 UI
            self.after(0, lambda: self._update_chart(fig))
            self.after(0, lambda: self._update_summary(buys, sells, zhongshus, segments))
            self.after(0, lambda: self._log_append("✅ 分析完成。\n"))

        except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
            self.after(0, lambda: self._log_append(f"❌ 错误：{exc}\n"))
            self.after(0, lambda: messagebox.showerror("错误", str(exc)))

    def _on_save(self) -> None:
        """保存当前图表为 PNG 文件。"""
        if self._fig is None:
            messagebox.showinfo("提示", "请先运行分析以生成图表。")
            return
        from tkinter.filedialog import asksaveasfilename
        path = asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("所有文件", "*.*")],
            title="保存图表",
        )
        if path:
            self._fig.savefig(path, dpi=150, bbox_inches="tight")
            self._log_append(f"图表已保存至：{path}\n")

    # ─── UI 更新（主线程） ──────────────────────────────────────────────────

    def _update_chart(self, fig: plt.Figure) -> None:
        """将新图表嵌入到图表区域。"""
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
        """更新左侧信号汇总文本框。"""
        lines = []
        lines.append(f"线段数：{len(segments)}")
        lines.append(f"中枢数：{len(zhongshus)}")
        lines.append("")
        lines.append("─ 买点 ─")
        for b in buys:
            lines.append(f"  {b.bstype}  {b.datetime.date()}  ￥{b.price:.2f}")
        lines.append("")
        lines.append("─ 卖点 ─")
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


def run_gui() -> None:
    """启动缠论 GUI 应用程序。"""
    app = ChanApp()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
