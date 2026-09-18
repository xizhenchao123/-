# -*- coding: utf-8 -*-
"""回测引擎 —— 逐笔回测、以损定仓、硬止损、移动止损。"""
import config as C
from indicators import atr


class Backtest:
    def __init__(self, bars, signal):
        self.bars = bars
        self.signal = signal
        self.n = len(bars)
        # 状态变量
        self.dir = 0  # 1 多  -1 空  0 空仓
        self.lots = 0
        self.entry_price = 0.0
        self.entry_idx = -1
        self.stop_price = 0.0
        self.trail_active = False
        self.last_exit_idx = -1
        # 记录
        self.equity = [C.INITIAL_CAPITAL] * self.n  # 时间序列净值
        self.trades = []
        # ATR
        self.atr_arr = atr(bars, 14)

    def run(self):
        eq = C.INITIAL_CAPITAL
        for i in range(1, self.n):
            prev = self.bars[i - 1]
            bar = self.bars[i]
            atr_v = self.atr_arr[i] if self.atr_arr[i] else 0

            # --- 持仓期间检查 ---
            if self.lots > 0:
                # 硬止损
                if self.dir == 1 and bar["low"] <= self.stop_price:
                    exit_price = min(bar["open"], self.stop_price)
                    self._close(i, exit_price, "hard_stop")
                elif self.dir == -1 and bar["high"] >= self.stop_price:
                    exit_price = max(bar["open"], self.stop_price)
                    self._close(i, exit_price, "hard_stop")
                # 移动止损
                elif self.trail_active and not self._check_trail(i, bar):
                    pass  # _check_trail 内部会 close
                # 信号反向
                elif self.signal[i] != 0 and self.signal[i] != self.dir:
                    self._close(i, bar["open"], "signal_reverse")

            # --- 开仓逻辑（空仓时检查信号） ---
            if self.lots == 0 and self.signal[i] != 0:
                # 冷却期检查
                if (i - self.last_exit_idx) < C.MIN_TRADE_INTERVAL:
                    pass  # 不开仓
                else:
                    self._open(i, bar["open"], atr_v)

            # 更新净值
            eq = self._calc_equity(i)
            self.equity[i] = eq

    def _open(self, idx, price, atr_v):
        risk_per_unit = atr_v * C.ATR_STOP_MULT if atr_v > 0 else atr_v
        risk_total = C.INITIAL_CAPITAL * C.RISK_PER_TRADE
        lots = max(1, int(risk_total / (risk_per_unit * C.COST_REF["multiplier"]))) if risk_per_unit > 0 else 1

        self.dir = self.signal[idx]
        self.lots = lots
        self.entry_price = price
        self.entry_idx = idx
        self.trail_active = False
        if atr_v > 0:
            if self.dir == 1:
                self.stop_price = price - atr_v * C.ATR_STOP_MULT
            else:
                self.stop_price = price + atr_v * C.ATR_STOP_MULT
        else:
            self.stop_price = price

    def _close(self, idx, price, reason):
        if self.lots == 0 or self.dir == 0:
            return
        pnl_per_unit = (price - self.entry_price) * self.dir
        pnl_total = pnl_per_unit * self.lots * C.COST_REF["multiplier"] - C.COST_REF["commission"] * 2
        self.trades.append({
            "entry_date": self.bars[self.entry_idx]["date"],
            "exit_date": self.bars[idx]["date"],
            "direction": "多" if self.dir == 1 else "空",
            "lots": self.lots,
            "entry": round(self.entry_price, 1),
            "exit": round(price, 1),
            "pnl": round(pnl_total, 0),
            "reason": reason,
        })
        self.last_exit_idx = idx
        self.dir = 0
        self.lots = 0
        self.stop_price = 0.0
        self.trail_active = False

    def _check_trail(self, idx, bar):
        if not self.trail_active or self.lots == 0:
            return True
        atr_v = self.atr_arr[idx] if self.atr_arr[idx] else 0
        trail_dist = atr_v * C.TRAIL_STOP_ATR if atr_v > 0 else 0
        if self.dir == 1:
            new_stop = bar["high"] - trail_dist
            if new_stop > self.stop_price:
                self.stop_price = new_stop
            if bar["low"] <= self.stop_price:
                exit_price = min(bar["open"], self.stop_price)
                self._close(idx, exit_price, "move_stop")
                return False
        else:
            new_stop = bar["low"] + trail_dist
            if new_stop < self.stop_price:
                self.stop_price = new_stop
            if bar["high"] >= self.stop_price:
                exit_price = max(bar["open"], self.stop_price)
                self._close(idx, exit_price, "move_stop")
                return False
        return True

    def _calc_equity(self, idx):
        eq = C.INITIAL_CAPITAL
        for t in self.trades:
            eq += t["pnl"]
        if self.lots > 0:
            cur_price = self.bars[idx]["close"]
            pnl = (cur_price - self.entry_price) * self.dir * self.lots * C.COST_REF["multiplier"]
            eq += pnl
        return eq