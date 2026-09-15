# -*- coding: utf-8 -*-
"""回测引擎（逐日、次日开盘成交）。

傅海棠纪律落点：
  · 以损定仓：单笔风险 = 资金 × RISK_PER_TRADE，按止损距离倒推手数；
    看对就敢于重仓，但每一笔的下行风险被固定（不孤注一掷且不无限重仓）。
  · 不扛单：开仓即带硬止损（ATR 铁律），到价无条件离场，杜绝死扛。
  · 看对拿住：盈利达标后激活移动止损，跟踪大趋势，不因小回调下车。
"""
from config import (
    CONTRACT_MULTIPLIER, MARGIN_RATE, FEE_PER_LOT, SLIPPAGE_TICKS,
    INITIAL_CAPITAL, RISK_PER_TRADE, MIN_LOTS,
    ATR_STOP_MULT, TRAIL_STOP_ATR, TRAIL_STOP_TRIGGER,
    MIN_TRADE_INTERVAL,
)
from indicators import atr


class Backtest:
    def __init__(self, bars, signals, multiplier=CONTRACT_MULTIPLIER,
                 initial=INITIAL_CAPITAL):
        self.bars = bars
        self.signals = signals
        self.mult = multiplier
        self.n = len(bars)
        self.risk_amt = initial * RISK_PER_TRADE
        self.cash = initial
        self.lots = 0
        self.dir = 0
        self.entry_price = 0.0
        self.stop_price = 0.0
        self.trail_active = False
        self.trail_stop = 0.0
        self.highest = 0.0
        self.lowest = float("inf")
        self.cur_atr = 0.0
        self.trades = []
        self.last_exit_idx = -10**9    # 平仓冷却起点
        self.equity = [0.0] * self.n
        self.equity[0] = initial
        self._atr = atr(bars)

    @property
    def capital(self):
        """权益 = 现金 + 持仓浮动盈亏。"""
        mkt = 0.0
        if self.lots:
            px = self.bars[self.i]["close"]
            mkt = (px - self.entry_price) * self.mult * self.lots * self.dir
        return self.cash + mkt

    def _signal_exit(self, i):
        """信号反向翻转（趋势门控内的同向信号）→ 平仓。"""
        sig = self.signals[i - 1]
        if sig != 0 and sig != self.dir:
            return True
        # 同方向但已无信号保持 → 不主动平
        return False

    def run(self):
        for i in range(1, self.n):
            self.i = i
            b = self.bars[i]
            prev_a = self._atr[i - 1]
            if prev_a:
                self.cur_atr = prev_a

            # ---------- 在持仓：先处理止损/移动止损 ----------
            if self.lots:
                # 更新极值，用于移动止损
                if self.dir == 1:
                    self.highest = max(self.highest, b["high"])
                    if not self.trail_active:
                        unreal = (b["high"] - self.entry_price) * self.mult * self.lots
                        if unreal >= self.entry_price * TRAIL_STOP_TRIGGER * self.mult * self.lots:
                            self.trail_active = True
                    if self.trail_active:
                        cand = self.highest - TRAIL_STOP_ATR * self.cur_atr
                        self.trail_stop = max(self.trail_stop, cand)
                        self.stop_price = max(self.stop_price, self.trail_stop)
                    # 触发
                    if b["low"] <= self.stop_price:
                        exit_px = self.stop_price
                        self._close(i, exit_px, "move_stop" if self.trail_active else "hard_stop")
                        continue
                else:
                    self.lowest = min(self.lowest, b["low"])
                    if not self.trail_active:
                        unreal = (self.entry_price - b["low"]) * self.mult * self.lots
                        if unreal >= self.entry_price * TRAIL_STOP_TRIGGER * self.mult * self.lots:
                            self.trail_active = True
                    if self.trail_active:
                        cand = self.lowest + TRAIL_STOP_ATR * self.cur_atr
                        self.trail_stop = self.trail_stop if self.trail_stop else cand
                        self.trail_stop = min(self.trail_stop, cand)
                        self.stop_price = self.stop_price if self.stop_price else self.trail_stop
                        self.stop_price = min(self.stop_price, self.trail_stop)
                    if b["high"] >= self.stop_price:
                        exit_px = self.stop_price
                        self._close(i, exit_px, "move_stop" if self.trail_active else "hard_stop")
                        continue
                # 信号反向平仓
                if self._signal_exit(i):
                    self._close(i, b["open"], "signal")
                    continue

            # ---------- 开新仓：次日开盘，按资金倒推手数 ----------
            sig = self.signals[i - 1]
            if sig != 0 and self.lots == 0 and (i - self.last_exit_idx) >= MIN_TRADE_INTERVAL:
                o = b["open"]
                slip = SLIPPAGE_TICKS * self.mult * sig
                fill = o + sign(sig) * slip
                if self.cur_atr > 0:
                    stop_dist = ATR_STOP_MULT * self.cur_atr
                    risk_per_lot = stop_dist * self.mult
                    lots = int(self.risk_amt / risk_per_lot) if risk_per_lot > 0 else 0
                    lots = max(lots, MIN_LOTS)
                else:
                    lots = MIN_LOTS
                # 保证金约束
                margin_needed = fill * self.mult * lots * MARGIN_RATE
                if lots > 0 and margin_needed <= self.cash + self.risk_amt:
                    self.lots = lots
                    self.dir = sig
                    self.entry_price = fill
                    self.stop_price = fill - sign(sig) * self.cur_atr * ATR_STOP_MULT
                    self.trail_active = False
                    self.trail_stop = 0.0
                    self.highest = fill
                    self.lowest = fill
                    self._open_charge = FEE_PER_LOT * lots
                    self._open_trade = {
                        "entry_date": self.bars[i]["date"],
                        "direction": "多" if sig == 1 else "空",
                        "entry": fill,
                        "lots": lots,
                        "stop": self.stop_price,
                    }
            self.equity[i] = self.capital

        # 期末强平
        if self.lots:
            last = self.n - 1
            self.i = last
            self._close(last, self.bars[last]["close"], "eod_force")

    def _close(self, i, px, reason):
        b = self.bars[i]
        slip = SLIPPAGE_TICKS * self.mult * self.dir
        fill = px - sign(self.dir) * slip
        pnl = (fill - self.entry_price) * self.mult * self.lots * self.dir
        fees = (self._open_charge or 0) + FEE_PER_LOT * self.lots
        net = pnl - fees
        self.cash += net
        self.equity[i] = self.cash
        data = dict(self._open_trade)
        data.update({
            "exit_date": b["date"],
            "exit": fill,
            "pnl": net,
            "pnl_pct": net / max(1e-9, self.entry_price * self.mult * self.lots),
            "reason": reason,
        })
        self.trades.append(data)
        self.lots = 0
        self.dir = 0
        self.last_exit_idx = i
        self.stop_price = 0.0
        self.trail_active = False
        self.trail_stop = 0.0
        self._open_charge = 0


def sign(x):
    return 1 if x > 0 else (-1 if x < 0 else 0)