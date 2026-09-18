# -*- coding: utf-8 -*-
"""策略 —— 多信号共振 + 傅海棠趋势门控 / 物极必反。"""
import config as C
from indicators import sma, macd, rsi, atr


class Strategy:
    def __init__(self, bars):
        self.bars = bars
        self.close = [b["close"] for b in bars]
        self.signal = [0] * len(bars)
        self._compute()

    def _compute(self):
        n = len(self.bars)
        if n < 60:
            return

        ma5 = sma(self.close, 5)
        ma10 = sma(self.close, 10)
        ma20 = sma(self.close, 20)
        ma30 = sma(self.close, 30)
        ma60 = sma(self.close, C.TREND_MA_MAJOR)
        hist, dea, dif = macd(self.close)
        r6 = rsi(self.close, 6)
        r14 = rsi(self.close, 14)
        atr_arr = atr(self.bars, 14)

        trend_ma = sma(self.close, C.TREND_MA)
        trend_ma_major = sma(self.close, C.TREND_MA_MAJOR)

        for i in range(n):
            c = self.close[i]
            if any(x is None for x in [ma20[i], ma60[i], hist[i], r6[i], r14[i]]):
                continue

            score = 0

            # 1) 趋势门控（傅海棠）：中周期 > 大周期 = 多头结构
            trend_bull = trend_ma[i] > trend_ma_major[i]
            trend_bear = trend_ma[i] < trend_ma_major[i]

            # 2) 均线系统
            if ma5[i] > ma10[i] > ma20[i]:
                score += 2 if trend_bull else 1
            elif ma5[i] < ma10[i] < ma20[i]:
                score -= 2 if trend_bear else 1

            # 3) MACD
            if hist[i] > 0 and dif[i] > dea[i]:
                score += 2
            elif hist[i] < 0 and dif[i] < dea[i]:
                score -= 2

            # 4) RSI 超买/超卖
            if r6[i] < 30 and trend_bull:
                score += 1  # 多头回调超卖 = 买入机会
            elif r6[i] > 70 and trend_bear:
                score -= 1  # 空头反弹超买 = 卖出机会
            elif r6[i] < 25:
                score += 1  # 极值超卖
            elif r6[i] > 75:
                score -= 1  # 极值超买

            # 5) 布林位置
            ma20_v = ma20[i]
            if c > ma20_v * 1.03 and trend_bull:
                score += 1
            elif c < ma20_v * 0.97 and trend_bear:
                score -= 1

            # 6) 物极必反（傅海棠）：大幅偏离成本/均线
            if ma60[i] and c < ma60[i] * 0.90:
                score += 2  # 严重超跌 = 极值买入
            elif ma60[i] and c > ma60[i] * 1.10:
                score -= 2  # 严重超涨 = 极值卖出

            if score >= C.SIGNAL_THRESHOLD:
                self.signal[i] = 1
            elif score <= -C.SIGNAL_THRESHOLD:
                self.signal[i] = -1
            else:
                self.signal[i] = 0