# ChanCode – 缠论量化交易分析系统

基于缠论（Chan Theory）的 Python 量化分析框架，涵盖行情数据下载、分型/笔/线段/中枢识别、买卖点信号检测与可视化 GUI。

## 功能模块

| 模块 | 说明 |
|------|------|
| `chancode/data.py` | 通过通达信 TQ Python 接口获取 OHLCV 行情数据，支持离线演示数据 |
| `chancode/fractal.py` | 三 K 线顶底**分型**识别与交替去重 |
| `chancode/bi.py` | **笔**（Bi）构建：连接相邻异类型分型 |
| `chancode/xd.py` | **线段**（Segment）识别：至少三笔、同向突破 |
| `chancode/zs.py` | **中枢**（Zhongshu）识别：三笔区间交集与合并 |
| `chancode/signal.py` | **买卖点**信号（B1/B2/B3、S1/S2/S3）检测 |
| `chancode/chart.py` | 全要素缠论图表（K 线 + 分型 + 笔 + 线段 + 中枢 + 买卖点） |
| `chancode/gui.py` | 基于 tkinter 的图形界面（参数输入 + 嵌入图表 + 信号汇总） |

中枢识别补充约束：构成中枢的前三个连续次级走势必须为“已完成”单元。`Pen` 与 `Segment` 默认 `is_complete=True`，可在高级场景下显式标记未完成单元并跳过中枢确认。

## 安装依赖

```bash
pip install -r requirements.txt
```

默认行情源：通达信 TQ Python 接口（tdxref）。请确保已启动并登录通达信客户端，TPythClient.dll 与项目同级存放（仓库已附带）。

## 快速开始

### 命令行模式

```bash
# 下载 AAPL 一年日线数据并保存图表
# 下载 601800 一年日线数据并保存图表（默认走通达信接口）
python main.py --ticker 601800 --period 1y --interval 1d --out result.png

# 使用内置演示数据（无需网络），弹窗显示
python main.py --demo

# 启动图形界面
python main.py --gui
```

### 图形界面

```bash
python main.py --gui
# 或
python -m chancode.gui
```

### 作为库使用

```python
from chancode.data import fetch_ohlcv
from chancode.fractal import detect_fractals, filter_and_alternate_fractals
from chancode.bi import build_pens
from chancode.xd import build_segments
from chancode.zs import detect_zhongshu
from chancode.signal import detect_buy_sell_points
from chancode.chart import plot_chan

df = fetch_ohlcv("601800", "1y", "1d")
fractals = filter_and_alternate_fractals(detect_fractals(df))
pens = build_pens(fractals)
segments = build_segments(pens)
zhongshus = detect_zhongshu(pens)
buys, sells = detect_buy_sell_points(df, zhongshus)
plot_chan(df, fractals, pens, segments, zhongshus, buys, sells, out="result.png")
```

## 运行测试

```bash
python -m pytest tests/ -v
```

## 缠论要素说明

