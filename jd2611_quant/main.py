# -*- coding: utf-8 -*-
"""入口：加载数据 → 跑策略 → 回测 → 输出绩效报告。

运行：python main.py
输出：output/report.txt、output/trades.csv、output/equity_curve.csv
"""
import os
import csv
from data import load_bars
from strategy import Strategy
from backtest import Backtest
import config as C

os.makedirs(C.OUTPUT_DIR, exist_ok=True)


def max_drawdown(equity):
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            mdd = max(mdd, dd)
    return mdd


def build_report(bars, equity, trades, signals):
    final = equity[-1]
    total_ret = final / C.INITIAL_CAPITAL - 1.0
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / len(trades) if trades else 0.0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss else float("inf")
    avg_pnl = (final - C.INITIAL_CAPITAL) / len(trades) if trades else 0.0
    mdd = max_drawdown(equity)
    n_hero_day = 0
    hold_days = []
    for t in trades:
        if t["reason"] == "move_stop":
            n_hero_day += 1

    lines = []
    lines.append("=" * 66)
    lines.append(f"  JD2611(鸡蛋) 技术面量化回测报告   |   数据区间 {bars[0]['date']} ~ {bars[-1]['date']}")
    lines.append("=" * 66)
    lines.append(f"初始资金            : {C.INITIAL_CAPITAL:>14,.0f}")
    lines.append(f"期末权益            : {final:>14,.0f}")
    lines.append(f"总收益率            : {total_ret:>13.2%}")
    lines.append(f"最大回撤            : {mdd:>13.2%}")
    lines.append(f"交易笔数            : {len(trades):>14d}")
    lines.append(f"胜率                : {win_rate:>13.2%}")
    lines.append(f"盈利因子(PF)        : {pf:>13.2f}")
    lines.append(f"平均每笔盈亏        : {avg_pnl:>14,.0f}")
    lines.append(f"回撤后按移动止损离场: {n_hero_day:>12d} 笔")
    lines.append("-" * 66)
    lines.append("【傅海棠纪律执行检查】")
    lines.append("  · 顺势门控：仅在中周期均线方向内做单，逆势信号被拒。")
    lines.append("  · 以损定仓：单笔最大风险 = 资金×%.0f%%，按止损距离倒推手数。" % (C.RISK_PER_TRADE * 100))
    lines.append("  · 不扛单  ：每笔开仓即带 ATR×%.1f 硬止损，无条件执行。" % C.ATR_STOP_MULT)
    lines.append("  · 看对拿住：盈利≥%.0f%%后启动移动止损(ATR×%.1f)跟踪大趋势。" % (C.TRAIL_STOP_TRIGGER * 100, C.TRAIL_STOP_ATR))
    lines.append("=" * 66)
    lines.append("说明：JD2611 自上市(2026-03-25)至今仅约 120 日，样本短、含上市初期"
                 "及 6 月单边行情，回测结果仅用于系统验证，不构成未来收益承诺。")
    return "\n".join(lines)


def main():
    bars = load_bars(C.DATA_CSV)
    print(f"[1/3] 加载数据 {len(bars)} 根日线：{bars[0]['date']} ~ {bars[-1]['date']}")

    strat = Strategy(bars)
    signals = strat.signal
    n_signals = sum(1 for s in signals if s != 0)
    print(f"[2/3] 生成信号：多头方向信号 {signals.count(1)} 个，空头方向信号 {signals.count(-1)} 个")

    bt = Backtest(bars, signals)
    bt.run()

    equity = bt.equity
    report = build_report(bars, equity, bt.trades, signals)
    print(report)

    # 导出
    with open(os.path.join(C.OUTPUT_DIR, "report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    if bt.trades:
        with open(os.path.join(C.OUTPUT_DIR, "trades.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(bt.trades[0].keys()))
            w.writeheader()
            w.writerows(bt.trades)
    with open(os.path.join(C.OUTPUT_DIR, "equity_curve.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "equity"])
        for i, b in enumerate(bars):
            w.writerow([b["date"], round(equity[i], 2)])
    print(f"\n[3/3] 已输出到 {C.OUTPUT_DIR}/：report.txt、trades.csv、equity_curve.csv")


if __name__ == "__main__":
    main()