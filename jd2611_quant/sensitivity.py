# -*- coding: utf-8 -*-
"""参数敏感性扫描：遍历关键参数组合，评估策略稳健性。
运行：python sensitivity.py → 输出 output/sensitivity.csv

扫描维度1：TREND_MA（趋势门控周期，顺大势的"大势"尺度）× SIGNAL_THRESHOLD（共振阈值）
扫描维度2：ATR_STOP_MULT（铁律止损倍数）

通过 monkeypatch 覆盖 strategy.py / backtest.py 模块级常量，只保留本次要扫的参数可变。
"""
import os
import csv
import itertools
import importlib

import config as C
from data import load_bars
import strategy as STRAT_MOD
import backtest as BACK_MOD


def run_once(trend_ma, threshold, stop_mult, risk=0.02):
    """在给定参数下跑一次回测，返回指标 dict。"""
    # 覆盖模块级常量（strategy.py 内部用模块全局名引用）
    STRAT_MOD.TREND_MA = trend_ma
    STRAT_MOD.SIGNAL_THRESHOLD = threshold
    STRAT_MOD.MA_SHORT = C.MA_SHORT
    STRAT_MOD.MA_LONG = C.MA_LONG
    STRAT_MOD.COST_REF = C.COST_REF
    STRAT_MOD.COST_OVERSHOOT = C.COST_OVERSHOOT
    # backtest.py 风控
    BACK_MOD.ATR_STOP_MULT = stop_mult
    BACK_MOD.TRAIL_STOP_ATR = C.TRAIL_STOP_ATR
    BACK_MOD.TRAIL_STOP_TRIGGER = C.TRAIL_STOP_TRIGGER
    BACK_MOD.RISK_PER_TRADE = risk

    bars = load_bars(C.DATA_CSV)
    bt = BACK_MOD.Backtest(bars, STRAT_MOD.Strategy(bars).signal)
    bt.run()
    eq = bt.equity
    final = eq[-1]
    trades = bt.trades
    total = final / C.INITIAL_CAPITAL - 1
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / gl if gl else float("inf")
    return {
        "trend_ma": trend_ma, "threshold": threshold, "stop_mult": stop_mult,
        "trades": len(trades),
        "winrate": len(wins) / len(trades) if trades else 0,
        "total": total, "mdd": mdd, "pf": pf,
    }


def grid_scan():
    os.makedirs(C.OUTPUT_DIR, exist_ok=True)
    rows = []
    # 维度1：门控周期 × 共振阈值
    print("【维度1】TREND_MA × SIGNAL_THRESHOLD（ATR止损=2.5）")
    for tm, th in itertools.product([10, 15, 20, 30, 45], [3, 4, 5]):
        rows.append(run_once(tm, th, 2.5))
        r = rows[-1]
        print(f"  trend_ma={tm:>3} thr={th} → 交易{r['trades']:>3} 盈利率{r['total']:>8.2%} "
              f"回撤{r['mdd']:>7.2%} 胜率{r['winrate']:>6.1%} PF{r['pf']:>6.2f}")

    # 维度2：ATR 止损倍数（默认门控30、阈值4）
    print("\n【维度2】ATR_STOP_MULT（门控30、阈值4）")
    for sm in [1.5, 2.0, 2.5, 3.0, 4.0]:
        r = run_once(30, 4, sm)
        rows.append(r)
        print(f"  stop_mult={sm} → 交易{r['trades']:>3} 盈利率{r['total']:>8.2%} "
              f"回撤{r['mdd']:>7.2%} 胜率{r['winrate']:>6.1%} PF{r['pf']:>6.2f}")

    with open(os.path.join(C.OUTPUT_DIR, "sensitivity.csv"), "w",
              newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\n已输出 → output/sensitivity.csv（共 {len(rows)} 组）")


if __name__ == "__main__":
    grid_scan()