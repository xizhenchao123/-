# -*- coding: utf-8 -*-
"""可视化：价格+买卖点、资金曲线、单笔盈亏 三合一图。
运行：python visualize.py → 输出 output/charts.png
"""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import config as C
from data import load_bars
from strategy import Strategy

# 中文字体：显式注册，找不到则回退默认
_CJK_PATHS = [
    os.path.expanduser("~/.fonts/NotoSansCJKsc-Regular.otf"),
]
for _p in _CJK_PATHS:
    if os.path.exists(_p):
        try:
            font_manager.fontManager.addfont(_p)
            plt.rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=_p).get_name()]
            break
        except Exception:
            pass
for f in font_manager.fontManager.ttflist:
    if any(k in f.name for k in (["Noto Sans CJK", "WenQuanYi", "Microsoft YaHei", "SimHei"])):
        plt.rcParams["font.sans-serif"] = [f.name]
        break
plt.rcParams["axes.unicode_minus"] = False
os.makedirs(C.OUTPUT_DIR, exist_ok=True)


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f)]


def main():
    bars = load_bars(C.DATA_CSV)
    strat = Strategy(bars)
    signals = strat.signal
    dates = [b["date"] for b in bars]
    close = [b["close"] for b in bars]

    trades = read_rows(os.path.join(C.OUTPUT_DIR, "trades.csv"))
    equity_rows = read_rows(os.path.join(C.OUTPUT_DIR, "equity_curve.csv"))
    equity = [float(r["equity"]) for r in equity_rows]
    eq_dates = [r["date"] for r in equity_rows]

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(13, 11),
                                        gridspec_kw={"height_ratios": [3, 1.6, 1.2]})

    # 顶部：价格 + 买卖点
    ax1.plot(range(len(close)), close, linewidth=1.4, color="#1f77b4", label="收盘价")
    ma5 = [strategy_ma_close(bars, i, 5) for i in range(len(bars))]
    ma20 = [strategy_ma_close(bars, i, 20) for i in range(len(bars))]
    ax1.plot(range(len(close)), ma5, color="#ff7f0e", linewidth=1, label="MA5")
    ax1.plot(range(len(close)), ma20, color="#d62728", linewidth=1, label="MA20")
    for t in trades:
        ed = dates.index(t["entry_date"])
        xd = dates.index(t["exit_date"])
        if t["direction"] == "多":
            ax1.scatter(ed, float(t["entry"]), marker="^", s=90, color="red", zorder=5)
            ax1.scatter(xd, float(t["exit"]), marker="v", s=90, color="blue")
        else:
            ax1.scatter(ed, float(t["entry"]), marker="v", s=90, color="blue")
            ax1.scatter(xd, float(t["exit"]), marker="^", s=90, color="red")
        ax1.annotate(f"{t['direction']}@{t['entry']}", (ed, float(t["entry"])),
                     textcoords="offset points", xytext=(0, 8), fontsize=9)
    ax1.set_title(f"JD2611 鸡蛋 · 回测买卖点（数据 {dates[0]}~{dates[-1]}）")
    ax1.set_ylabel("价格(元/500kg)")
    ax1.legend(loc="upper left", fontsize=9)
    ax1.xaxis.set_major_locator(plt.MaxNLocator(10))

    # 中部：资金曲线
    ax2.plot(range(len(equity)), equity, color="#2ca02c", linewidth=1.6, label="权益")
    ax2.axhline(C.INITIAL_CAPITAL, color="gray", linestyle="--", linewidth=0.8)
    ax2.set_title(f"资金曲线（期末 {equity[-1]:,.0f}，初始 {C.INITIAL_CAPITAL:,}）")
    ax2.set_ylabel("权益(元)")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.xaxis.set_major_locator(plt.MaxNLocator(10))

    # 底部：单笔盈亏柱
    pnls = [float(t["pnl"]) for t in trades]
    xs = list(range(len(pnls)))
    colors = ["#d62728" if p >= 0 else "#1f77b4" for p in pnls]
    ax3.bar(xs, pnls, color=colors)
    for i, p in enumerate(pnls):
        ax3.text(i, p, f"{p:,.0f}", ha="center",
                 va="bottom" if p >= 0 else "top", fontsize=9)
    ax3.axhline(0, color="black", linewidth=0.8)
    ax3.set_title(f"逐笔盈亏（共 {len(pnls)} 笔，胜率 "
                  f"{sum(1 for p in pnls if p > 0)/max(1,len(pnls)):.0%}）")
    ax3.set_ylabel("盈亏(元)")
    ax3.xaxis.set_major_locator(plt.MaxNLocator(20))

    plt.tight_layout()
    out = os.path.join(C.OUTPUT_DIR, "charts.png")
    plt.savefig(out, dpi=130)
    print(f"已保存图表 → {out}")
    return out


def strategy_ma_close(bars, i, period):
    """简单算 MA 供画图，头部分取到为准。"""
    if i + 1 < period:
        return None
    return sum(bars[j]["close"] for j in range(i - period + 1, i + 1)) / period


if __name__ == "__main__":
    main()