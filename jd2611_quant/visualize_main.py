# -*- coding: utf-8 -*-
"""主力连续长历史的买卖点可视化 + 资金曲线 + 逐笔盈亏。
运行：python visualize_main.py → 输出 output/charts_main_continuous.png
"""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import config as C
from data import load_bars
import strategy as STRAT_MOD
import backtest as BACK_MOD

PATH = "data/jd_main_hist.csv"
OUT_PNG = os.path.join(C.OUTPUT_DIR, "charts_main_continuous.png")
os.makedirs(C.OUTPUT_DIR, exist_ok=True)

# 中文字体
for _p in [os.path.expanduser("~/.fonts/NotoSansCJKsc-Regular.otf")]:
    if os.path.exists(_p):
        try:
            font_manager.fontManager.addfont(_p)
            plt.rcParams["font.sans-serif"] = [font_manager.FontProperties(fname=_p).get_name()]
            break
        except Exception:
            pass


def main():
    bars = load_bars(PATH)
    # 找回 70/30 定型参数
    STRAT_MOD.TREND_MA = C.TREND_MA
    STRAT_MOD.SIGNAL_THRESHOLD = C.SIGNAL_THRESHOLD
    BACK_MOD.ATR_STOP_MULT = C.ATR_STOP_MULT
    bt = BACK_MOD.Backtest(bars, STRAT_MOD.Strategy(bars).signal)
    bt.run()
    trades = bt.trades
    equity = bt.equity
    dates = [b["date"] for b in bars]
    close = [b["close"] for b in bars]
    n = len(bars)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(15, 11),
                                        gridspec_kw={"height_ratios": [3, 1.4, 1.1]})
    ax1.plot(range(n), close, linewidth=1.0, color="#1f77b4", label="收盘价")
    for t in trades:
        ed = dates.index(t["entry_date"]); xd = dates.index(t["exit_date"])
        if t["direction"] == "多":
            ax1.scatter(ed, float(t["entry"]), marker="^", s=60, color="red", zorder=5)
            ax1.scatter(xd, float(t["exit"]), marker="v", s=60, color="blue")
        else:
            ax1.scatter(ed, float(t["entry"]), marker="v", s=60, color="blue")
            ax1.scatter(xd, float(t["exit"]), marker="^", s=60, color="red")
    ax1.set_title(f"鸡蛋主力连续 · 全样本回测买卖点（{dates[0]}~{dates[-1]}，{len(trades)} 笔）")
    ax1.set_ylabel("价格(元/500kg)"); ax1.legend(loc="upper left", fontsize=9)
    ax1.xaxis.set_major_locator(plt.MaxNLocator(10))

    ax2.plot(range(n), equity, color="#2ca02c", linewidth=0.9, label="权益(默认参数)")
    ax2.axhline(C.INITIAL_CAPITAL, color="gray", ls="--", lw=0.8)
    total = equity[-1] / C.INITIAL_CAPITAL - 1
    ax2.set_title(f"资金曲线 · 全样本默认参数 TOT={total:.2%}（期末 {equity[-1]:,.0f}）")
    ax2.axvspan(len(bars)*0.7, n, color="#fff3cd", alpha=0.5, label="样本外测试段(后30%)")
    ax2.legend(loc="upper left", fontsize=9); ax2.xaxis.set_major_locator(plt.MaxNLocator(10))

    pnls = [t["pnl"] for t in trades]
    xs = list(range(len(pnls)))
    ax3.bar(xs, pnls, color=["#d62728" if p >= 0 else "#1f77b4" for p in pnls])
    ax3.axhline(0, color="black", lw=0.8)
    winr = sum(1 for p in pnls if p > 0) / max(1, len(pnls))
    ax3.set_title(f"逐笔盈亏 共{len(pnls)}笔 胜率{winr:.0%}")
    ax3.set_ylabel("盈亏(元)"); ax3.xaxis.set_major_locator(plt.MaxNLocator(20))

    plt.tight_layout()
    plt.savefig(OUT_PNG, dpi=120)
    print(f"已保存 → {OUT_PNG}")


if __name__ == "__main__":
    main()