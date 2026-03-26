"""Demo script that reuses chancode core logic.

Example:
    python chan_theory_yfinance.py --ticker AAPL --period 1y --interval 1d --out result.png
"""
from __future__ import annotations

import argparse

from chancode.data import fetch_ohlcv
from chancode.config import load_config
from chancode.fractal import (
    merge_klines,
    detect_fractals,
    cluster_fractals_for_display,
    build_fractals_for_bi,
    map_fractals_to_original,
)
from chancode.bi import build_pens
from chancode.xd import build_segments
from chancode.zs import detect_zhongshu_with_basis
from chancode.signal import detect_buy_sell_points
from chancode.chart import plot_chan


def main() -> None:
    parser = argparse.ArgumentParser(description="Chan theory demo (reuse chancode core modules)")
    parser.add_argument("--ticker", type=str, default="601800", help="Ticker symbol")
    parser.add_argument("--period", type=str, default="1y", help="Download period, e.g. 1y / 6mo")
    parser.add_argument("--interval", type=str, default="1d", help="Bar interval, e.g. 1d / 1h")
    parser.add_argument("--out", type=str, default=None, help="Output chart path")
    parser.add_argument("--demo", action="store_true", help="Use built-in demo data")
    parser.add_argument("--config", type=str, default=None, help="YAML config path")
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
        df = fetch_ohlcv(args.ticker, args.period, args.interval, use_demo_data=args.demo)
        merge_result = merge_klines(df)
        merged_df = merge_result.merged_df
        merged_indices = merge_result.merged_indices
        merged_boxes = merge_result.merged_boxes

        fractals_raw = detect_fractals(merged_df, allow_equal=True)
        fractals_all_merged = cluster_fractals_for_display(fractals_raw, near_gap=2)
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
            f"[summary] fractals_display={len(fractals_for_plot)}, "
            f"fractals_for_bi={len(fractals_for_bi)}, pens={len(pens)}, "
            f"segments={len(segments)}, centers={len(zhongshus)}, "
            f"buys={len(buys)}, sells={len(sells)}"
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
        print("Interrupted by user.")
        raise
    except (ValueError, RuntimeError, ConnectionError, OSError) as exc:
        print(f"Run failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
