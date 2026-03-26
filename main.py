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
    parser.add_argument("--ticker",   type=str, default="601800",  help="股票/指数代码（默认 601800）")
    parser.add_argument("--period",   type=str, default="1y",    help="下载周期，如 1y / 6mo")
    parser.add_argument("--interval", type=str, default="1d",    help="K 线周期，如 1d / 1h")
    parser.add_argument("--out",      type=str, default=None,    help="输出图片路径（省略则弹窗显示）")
    parser.add_argument("--demo",     action="store_true",        help="使用内置演示数据")
    parser.add_argument("--gui",      action="store_true",        help="启动图形界面")
    parser.add_argument("--config",   type=str, default=None,      help="YAML 配置文件路径")
    args = parser.parse_args()

    if args.gui:
        from chancode.gui import run_gui
        run_gui(config_path=args.config)
        return

    try:
        from chancode.data import fetch_ohlcv
        from chancode.config import load_config
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

        cfg = load_config(args.config)

        df = fetch_ohlcv(args.ticker, args.period, args.interval, use_demo_data=args.demo)

        merge_result = merge_klines(df)
        merged_df = merge_result.merged_df
        merged_indices = merge_result.merged_indices
        merged_boxes = merge_result.merged_boxes

        raw_fractals = detect_fractals(merged_df, allow_equal=True)
        fractals_all_merged = cluster_fractals_for_display(raw_fractals, near_gap=2)
        fractals_for_bi = build_fractals_for_bi(
            fractals_all_merged,
            min_separation=3,
            min_pen_separation=cfg.min_bi_separation,
        )
        fractals_for_plot = map_fractals_to_original(
            fractals_all_merged,
            merge_result,
            anchor="extreme",
            original_index=df.index,
            original_df=df,
        )

        pens = build_pens(fractals_for_bi, config=cfg)
        segments = build_segments(pens)
        zhongshus = detect_zhongshu_with_basis(
            pens,
            segments=segments,
            config=cfg,
        )
        buys, sells = detect_buy_sell_points(merged_df, zhongshus)

        print(
            f"[summary] 分型显示={len(fractals_for_plot)}  成笔分型={len(fractals_for_bi)}"
            f"  笔={len(pens)}  线段={len(segments)}"
            f"  中枢={len(zhongshus)}  买点={len(buys)}  卖点={len(sells)}"
        )

        title = f"{args.ticker}  {args.period}/{args.interval}"
        plot_chan(
            df,
            fractals_for_plot,
            pens,
            segments,
            zhongshus,
            buys,
            sells,
            title=title,
            out=args.out,
            merged_indices=merged_indices,
            merged_boxes=merged_boxes,
        )

    except KeyboardInterrupt:
        print("用户主动中断。")
        sys.exit(0)
    except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
        print(f"运行出错：{exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
