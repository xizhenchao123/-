# -*- coding: utf-8 -*-
"""模拟盘读单工具：打印截至最后一个交易日的策略持仓状态。

说明：
  · 用「收盘信号 → 次日开盘成交」口径（与回测一致）。
  · 若回测末 bar 仍持有 → 打印持仓方向/手数/开仓价/当前止损；
    若已平仓/无信号 → 打印最新一个入场信号的方向与日期（对应次日开盘可执行），或"无新信号"。
运行：python paper_signal.py [--csv data/jd_main_hist.csv]
"""
import argparse

import config as C
from data import load_bars
from backtest import Backtest
import strategy as STRAT_MOD
import backtest as BACK_MOD


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data/jd_main_hist.csv")
    args = ap.parse_args()
    bars = load_bars(args.csv)
    strat = STRAT_MOD.Strategy(bars)
    bt = Backtest(bars, strat.signal)
    bt.run()

    last = bars[-1]
    print("=" * 60)
    print(f"交易日       : {last['date']}   收盘 {last['close']}   持仓量 {last['open_interest']}")
    print(f"合约/口径    : {args.csv}  [{len(bars)} 根]")
    print("-" * 60)

    if bt.lots:
        d = "多" if bt.dir == 1 else "空"
        tr = "（移动止损已启动）" if bt.trail_active else ""
        print(f"当前持仓      : {d}单 {bt.lots} 手  开仓 {bt.entry_price}  当前止损 {bt.stop_price}{tr}")
    else:
        print("当前持仓      : 空仓")

    # 最近一次离场日期（区分"已成交的旧信号" vs "待执行新信号"）
    last_exit = "2000-01-01"
    if bt.trades:
        t = bt.trades[-1]
        last_exit = t["exit_date"]
        print(f"最近平仓      : {t['entry_date']}→{t['exit_date']}  {t['direction']}单 "
              f"净{t['pnl']:,.0f} 离场=({t['reason']})")

    # 待执行信号：与回测端成交条件逐一对齐
    #   回测仅在 sig=signals[n-1] 且 空仓 且 (n-1-last_exit)>=冷却期 时于下一 bar 开仓。
    #   因此逆推：仅当 signals[-1]!=0 且当前空仓且冷却期已满足，才是真正"待执行"。
    actionable = None
    if bt.lots == 0 and strat.signal[-1] != 0:
        cool_ok = (len(bars) - 1 - bt.last_exit_idx) >= BACK_MOD.MIN_TRADE_INTERVAL
        if cool_ok:
            actionable = len(bars) - 1
    if actionable is not None:
        d = "多" if strat.signal[actionable] == 1 else "空"
        print(f"待执行信号    : {d}  于 {bars[actionable]['date']} 收盘触发，"
              f"之后首个交易日开盘可执行")
    else:
        print("待执行信号    : 无（当前空仓，无新入场信号）")
    print("=" * 60)
    print("提示：信号基于收盘价，实际以次日开盘价(+滑点/手续费)成交。仅供研究，不构成投资建议。")


if __name__ == "__main__":
    main()