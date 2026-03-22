"""main.py – 缠论量化分析系统命令行入口。

示例：
    # 分析 AAPL，1 年日线，弹窗显示
    python main.py --ticker AAPL --period 1y --interval 1d

    # 使用演示数据，保存图片
    python main.py --demo --out result.png

    # 启动图形界面
    python main.py --gui
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="缠论量化分析系统 – ChanCode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--ticker",   type=str, default="AAPL",  help="股票/指数代码（默认 AAPL）")
    parser.add_argument("--period",   type=str, default="1y",    help="下载周期，如 1y / 6mo")
    parser.add_argument("--interval", type=str, default="1d",    help="K 线周期，如 1d / 1h")
    parser.add_argument("--out",      type=str, default=None,    help="输出图片路径（省略则弹窗显示）")
    parser.add_argument("--demo",     action="store_true",        help="使用内置演示数据")
    parser.add_argument("--gui",      action="store_true",        help="启动图形界面")
    args = parser.parse_args()

    if args.gui:
        from chancode.gui import run_gui
        run_gui()
        return

    try:
        from chancode.data import fetch_ohlcv
        from chancode.fractal import detect_fractals, filter_and_alternate_fractals
        from chancode.bi import build_pens
        from chancode.xd import build_segments
        from chancode.zs import detect_zhongshu
        from chancode.signal import detect_buy_sell_points
        from chancode.chart import plot_chan

        df = fetch_ohlcv(args.ticker, args.period, args.interval, use_demo_data=args.demo)

        raw_fractals = detect_fractals(df)
        fractals = filter_and_alternate_fractals(raw_fractals)
        pens = build_pens(fractals)
        segments = build_segments(pens)
        zhongshus = detect_zhongshu(pens)
        buys, sells = detect_buy_sell_points(df, zhongshus)

        print(
            f"[summary] 分型={len(fractals)}  笔={len(pens)}  线段={len(segments)}"
            f"  中枢={len(zhongshus)}  买点={len(buys)}  卖点={len(sells)}"
        )

        title = f"{args.ticker}  {args.period}/{args.interval}"
        plot_chan(df, fractals, pens, segments, zhongshus, buys, sells,
                  title=title, out=args.out)

    except KeyboardInterrupt:
        print("用户主动中断。")
        sys.exit(0)
    except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
        print(f"运行出错：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
