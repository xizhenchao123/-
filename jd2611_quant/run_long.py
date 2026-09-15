# -*- coding: utf-8 -*-
"""长历史主力连续的干净检验：
  (1) 全样本默认参数回测（看样本内）
  (2) 固定划分 train→test：用前 70% 在网格里定参，后 30% 作为一次性样本外。
      这比滚动 walk-forward 少一个"每窗重拟合"的自由度，结果更易解读。
"""
import itertools

import config as C
from data import load_bars
from backtest import Backtest
import strategy as STRAT_MOD
import backtest as BACK_MOD
from walk_forward import apply_params, run_on, metrics_from, pick_best, GRID

PATH = "data/jd_main_hist.csv"


def full_sample_default(bars):
    apply_params(C.TREND_MA, C.SIGNAL_THRESHOLD, C.ATR_STOP_MULT)
    eq, trades = run_on(bars)
    total, mdd, pf, nt = metrics_from(eq, trades)
    bp = (bars[-1]["close"] - bars[0]["close"]) / bars[0]["close"]
    print(f"[全样本·默认参数]  {len(bars)} 根  TOT={total:.2%}  MDD={mdd:.2%}  "
          f"笔数={nt}  PF={pf:.2f}   买入持有={bp:.2%}")


def fixed_split(bars, ratio=0.70):
    n = len(bars)
    split = int(n * ratio)
    train, test = bars[:split], bars[split:]
    tm, th, sm = pick_best(train)
    apply_params(tm, th, sm)
    eq, trades = run_on(test)
    total, mdd, pf, nt = metrics_from(eq, trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    bt = (test[-1]["close"] - test[0]["close"]) / test[0]["close"]
    print(f"\n[固定划分 70/30]  训练起点={train[0]['date']} 定型=({tm},{th},{sm})")
    print(f"  训练样本 {len(train)} 根 → 测试样本外 {len(test)} 根 "
          f"({test[0]['date']} ~ {test[-1]['date']})")
    print(f"  样本外 TOT={total:.2%}  MDD={mdd:.2%}  笔数={nt}  胜率="
          f"{wins/max(1,nt):.0%}  PF={pf:.2f}   买入持有={bt:.2%}")
    for t in trades:
        print(f"    {t['entry_date']} {t['direction']}@{t['entry']} -> "
              f"{t['exit_date']} {t['exit']}  净{t['pnl']:>9,.0f}  [{t['reason']}]")
    return tm, th, sm


def main():
    apply_params(C.TREND_MA, C.SIGNAL_THRESHOLD, C.ATR_STOP_MULT)
    bars = load_bars(PATH)
    print("=" * 70)
    print(f"鸡蛋主力连续 2014-01 ~ 2026-09（{len(bars)} 根）· 参数集 "
          f"门控{C.TREND_MA}/阈值{C.SIGNAL_THRESHOLD}/止损{C.ATR_STOP_MULT}")
    print("=" * 70)
    full_sample_default(bars)
    fixed_split(bars, 0.70)


if __name__ == "__main__":
    main()