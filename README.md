# Chan Theory Visualization Demo
_Author: GitHub Copilot Agent_

生成并可视化缠论分型、笔与中枢的示例脚本。

## 1. 安装依赖

```bash
pip install -r requirements.txt
```

## 2. 运行示例

- 从 yfinance 下载数据并保存图片：

```bash
python chan_theory_yfinance.py --ticker AAPL --period 1y --interval 1d --out result.png
```

- 使用内置 demo 数据（无需网络）并弹窗展示：

```bash
python chan_theory_yfinance.py --demo
```

脚本将打印下载行数、分型/笔/中枢数量及示例买卖点，并在图中标注分型（三角）、笔（橙线）、中枢（蓝色矩形）与简单买卖信号。
