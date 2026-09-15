# -*- coding: utf-8 -*-
"""C：滚动 Walk-Forward（样本外）检验。

方法（教科书式 rolling walk-forward optimization）：
  · 参数网格：TREND_MA × SIGNAL_THRESHOLD × ATR_STOP_MULT（小网格，避免窗内过拟合）
  · 每个训练窗用网格挑「风险调整后」最优组合（train），立刻拿到下一段样本外窗（test）跑，只统计落入 test 窗口的成交。
  · 滚动窗口：lookback(训练) / 前推(样本外)。
  · 最终汇报所有 test(样本外) 成交的合计绩效 —— 这才是参数未经历过的新数据。

诚实说明：股票/期货回测 walk-forward 需要足够长的多年数据；这里的鸡蛋合约仅 120~174
根日线，训练窗 ~60、样本外窗 ~30，样本外成交很少，统计上偏弱——结果只能看方向，不能当结论。
"""
import itertools

import config as C
from data import load_bars
import strategy as STRAT_MOD
import backtest as BACK_MOD

# 参数网格（小尺寸）
GRID = {
    "trend_ma": [15, 30],
    "threshold": [3, 4],
    "stop_mult": [2.0, 2.5],
}


def apply_params(tm, th, sm):
    STRAT_MOD.TREND_MA = tm
    STRAT_MOD.SIGNAL_THRESHOLD = th
    STRAT_MOD.ATR_STOP_MULT = sm
    STRAT_MOD.MA_SHORT = C.MA_SHORT
    STRAT_MOD.MA_LONG = C.MA_LONG
    STRAT_MOD.TREND_MA_MAJOR = C.TREND_MA_MAJOR
    STRAT_MOD.MIN_OI = C.MIN_OI
    STRAT_MOD.ENTRY_REQUIRE_CROSS = C.ENTRY_REQUIRE_CROSS
    STRAT_MOD.COST_REF = C.COST_REF
    STRAT_MOD.COST_OVERSHOOT = C.COST_OVERSHOOT
    BACK_MOD.ATR_STOP_MULT = sm
    BACK_MOD.TRAIL_STOP_ATR = C.TRAIL_STOP_ATR
    BACK_MOD.TRAIL_STOP_TRIGGER = C.TRAIL_STOP_TRIGGER
    BACK_MOD.RISK_PER_TRADE = C.RISK_PER_TRADE
    BACK_MOD.MIN_TRADE_INTERVAL = C.MIN_TRADE_INTERVAL


def run_on(bars):
    """跑一次完整回测，返回 (equity, trades)。"""
    bt = BACK_MOD.Backtest(bars, STRAT_MOD.Strategy(bars).signal)
    bt.run()
    return bt.equity, bt.trades


def metrics_from(equity, trades, initial=0.0):
    if not initial:
        initial = C.INITIAL_CAPITAL
    final = equity[-1]
    total = final / initial - 1
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    wins = [t for t in trades if t["pnl"] > 0]
    gp = sum(t["pnl"] for t in wins)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / gl if gl else float("inf")
    return total, mdd, pf, len(trades)


def pick_best(bars_train):
    """在训练段网格选最优：分数 = total / (1+mdd)，交易过少则排除。"""
    best = None
    best_score = -1e18
    for tm, th, sm in itertools.product(GRID["trend_ma"], GRID["threshold"],
                                        GRID["stop_mult"]):
        apply_params(tm, th, sm)
        eq, trades = run_on(bars_train)
        total, mdd, pf, nt = metrics_from(eq, trades, initial=C.INITIAL_CAPITAL)
        if nt < 1:
            continue
        score = total / (1.0 + mdd)
        if score > best_score:
            best_score = score
            best = (tm, th, sm)
    return best or (GRID["trend_ma"][0], GRID["threshold"][0], GRID["stop_mult"][0])


def walk_forward(bars, name, lookback=60, oos_len=30):
    apply_params(C.TREND_MA, C.SIGNAL_THRESHOLD, C.ATR_STOP_MULT)
    n = len(bars)
    oos_trades = []
    start = lookback
    wins_all, losses_all = 0, 0
    bench_bars = [b["close"] for b in bars]
    # 买入持有基准
    bench = (bench_bars[-1] - bench_bars[0]) / bench_bars[0]
    fold = 0
    while start < n - oos_len:
        split = start
        test_start = split
        test_end = min(split + oos_len, n)
        train_bars = bars[:split]
        tm, th, sm = pick_best(train_bars)
        apply_params(tm, th, sm)
        # 在前半段之上继续跑到 test_end，只取入场在 test 段的成交
        eq, trades = run_on(bars[:test_end])
        test_date = bars[test_start]["date"]
        for t in trades:
            if t["entry_date"] >= test_date:
                oos_trades.append(t)
                if t["pnl"] > 0:
                    wins_all += 1
                else:
                    losses_all += 1
        fold += 1
        start += oos_len
    # 还原默认
    apply_params(C.TREND_MA, C.SIGNAL_THRESHOLD, C.ATR_STOP_MULT)
    tot = sum(t["pnl"] for t in oos_trades)
    winr = wins_all / (wins_all + losses_all) if (wins_all + losses_all) else 0.0
    return {"name": name, "oos": len(oos_trades), "tot": tot, "winr": winr,
            "bench": bench}


def main():
    print("=" * 72)
    print(f"Walk-Forward 样本外检验（lookback={60}, oos={30}，网格 "
          f"{len(list(itertools.product(*GRID.values())))} 组）")
    print("=" * 72)
    rows = []
    for name, path, lb, oos in [
        ("JD2611", "data/jd2611_daily.csv", 60, 30),
        ("JD2612", "data/jd2612_daily.csv", 60, 30),
        ("主力连续", "data/jd_main_hist.csv", 250, 125),
    ]:
        bars = load_bars(path)
        r = walk_forward(bars, name, lookback=lb, oos_len=oos)
        rows.append(r)
    print(f'{"合约":<8}{"样本外成交":>10}{"样本外净盈亏":>14}{"样本外胜率":>10}{"买入持有":>10}')
    print("-" * 72)
    for r in rows:
        print(f'{r["name"]:<10}{r["oos"]:>10}{r["tot"]:>14,.0f}'
              f'{r["winr"]:>10.0%}{r["bench"]:>10.2%}')
    print("=" * 72)
    combined = sum((r["oos"] for r in rows), 0)
    tot = sum(r["tot"] for r in rows)
    print(f"\n合计样本外交易 {combined} 笔，合计净盈亏 {tot:,.0f} 元。")
    print("若样本外合计为负或接近 0，说明策略在数据未经验证的时段无法稳定获利——")


if __name__ == "__main__":
    main()