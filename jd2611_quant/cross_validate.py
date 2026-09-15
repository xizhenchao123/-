# -*- coding: utf-8 -*-
"""交叉验证：同一套默认参数，分别在 JD2611 与 JD2612 上回测，评估是否过拟合某一合约。
运行：python cross_validate.py
说明：
  · JD2611 与 JD2612 是同一个上市周期内的不同到期月合约，2026-03~09 时间重叠，
    因此本检验衡量的是「参数在不同合约上的稳健性」，而非时间维度的独立性。
"""
import os

import config as C
from data import load_bars
import strategy as STRAT_MOD
import backtest as BACK_MOD

PAIRS = [
    ("JD2611（3月上市）", "data/jd2611_daily.csv"),
    ("JD2612（25年12月上市）", "data/jd2612_daily.csv"),
]


def run(path):
    bars = load_bars(path)
    bt = BACK_MOD.Backtest(bars, STRAT_MOD.Strategy(bars).signal)
    bt.run()
    eq = bt.equity
    final = eq[-1]
    total = final / C.INITIAL_CAPITAL - 1
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    trades = bt.trades
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / gl if gl else float("inf")
    return {
        "n": len(bars),
        "range": f"{bars[0]['date']}~{bars[-1]['date']}",
        "total": total, "mdd": mdd,
        "trades": len(trades),
        "winrate": len(wins) / len(trades) if trades else 0,
        "pf": pf,
        "final": final,
    }


def main():
    print("=" * 70)
    print(f"交叉验证 · 默认参数（门控15/阈值3/止损2.0）")
    print("=" * 70)
    head = f'{"合约":<22}{"K线":>5} {"区间":<24}{"收益率":>8}{"回撤":>7}{"笔数":>4}{"胜率":>7}{"PF":>6}'
    print(head)
    print("-" * 70)
    rows = []
    for name, path in PAIRS:
        r = run(path)
        rows.append(r)
        print(f'{name:<24}{r["n"]:>5} {r["range"]:<22}{r["total"]:>7.2%}{r["mdd"]:>7.2%}'
              f'{r["trades"]:>5}{r["winrate"]:>7.1%}{r["pf"]:>6.2f}')
    print("=" * 70)


if __name__ == "__main__":
    main()