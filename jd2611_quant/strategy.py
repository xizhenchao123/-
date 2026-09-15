# -*- coding: utf-8 -*-
"""策略层：多信号共振 + 傅海棠交易纪律。

傅海棠思路融入：
  1. 顺应大势（趋势门控）：只顺中周期趋势方向入场，逆势信号一律观望；
     回调不改变持仓，避免被次要波动扫出（漏斗式拒绝逆势）。
  2. 物极必反：价格显著跌破预设成本锚 + 超卖时，视为「物极」，给多头额外权重。
  3. 不扛单（硬止损）：由回测引擎按 ATR 铁律止损执行，见 backtest.py。
  4. 看对拿住（移动止损）：盈利达标后启用移动止损跟踪大趋势，见 backtest.py。

信号计分（多信号共振）：
  均线交叉、MACD 金叉死叉、RSI 超卖/强势、布林位置、量价(放量增仓)。
  分值达到 SIGNAL_THRESHOLD 且通过趋势门控，才生成入场信号。
"""
from config import (
    MA_SHORT, MA_LONG, TREND_MA, TREND_MA_MAJOR,
    MACD_SHORT, MACD_LONG, MACD_MID,
    RSI_PERIOD, BOLL_PERIOD, BOLL_STD,
    VOL_WINDOW, SIGNAL_THRESHOLD,
    COST_REF, COST_OVERSHOOT,
    MIN_OI, ENTRY_REQUIRE_CROSS,
)
from indicators import sma, macd, rsi, boll, volume_signal


class Strategy:
    def __init__(self, bars, cfg=None):
        self.bars = bars
        self.cfg = cfg or {}
        self.close = [b["close"] for b in bars]
        self.n = len(bars)
        self._build()

    def _build(self):
        c = self.close
        self.ma_s = sma(c, MA_SHORT)
        self.ma_l = sma(c, MA_LONG)
        self.ma_t = sma(c, TREND_MA)
        self.ma_major = sma(c, TREND_MA_MAJOR)
        self.dif, self.dea, self.hist = macd(c, MACD_SHORT, MACD_LONG, MACD_MID)
        self.rsi6 = rsi(c, RSI_PERIOD)
        self.boll_m, self.boll_u, self.boll_l = boll(c, BOLL_PERIOD, BOLL_STD)
        self.volsig = volume_signal(self.bars, VOL_WINDOW)
        self.score = [None] * self.n
        self.break_dir = [0] * self.n   # 结构突破方向：+1 均线金叉或MACD金叉；-1 死叉；0 无
        self.gate = [0] * self.n      # 趋势门控：+1 允许多，-1 允许多空，0 观望
        self.signal = [0] * self.n    # 入场方向：+1 / -1 / 0
        self.last_signal = 0
        self._compute_scores()
        self._apply_entries()

    def _compute_scores(self):
        for i in range(self.n):
            if self.ma_s[i] is None or self.ma_l[i] is None:
                continue
            ok_ma = (self.ma_s[i - 1] is not None and self.ma_l[i - 1] is not None)
            s = 0.0
            # --- 均线 ---
            cross_hi = ok_ma and self.ma_s[i - 1] <= self.ma_l[i - 1] and self.ma_s[i] > self.ma_l[i]
            cross_lo = ok_ma and self.ma_s[i - 1] >= self.ma_l[i - 1] and self.ma_s[i] < self.ma_l[i]
            if cross_hi:
                s += 2
                self.break_dir[i] = 1
            elif cross_lo:
                s -= 2
                self.break_dir[i] = -1
            elif self.ma_s[i] > self.ma_l[i]: s += 0.5
            elif self.ma_s[i] < self.ma_l[i]: s -= 0.5
            # --- MACD ---
            d, e = self.dif[i], self.dea[i]
            if d is not None and e is not None:
                prev_ok = self.dif[i - 1] is not None and self.dea[i - 1] is not None
                gc = prev_ok and self.dif[i - 1] <= self.dea[i - 1] and d > e
                dc = prev_ok and self.dif[i - 1] >= self.dea[i - 1] and d < e
                if gc:
                    s += 2
                    if self.break_dir[i] == 0:
                        self.break_dir[i] = 1
                elif dc:
                    s -= 2
                    if self.break_dir[i] == 0:
                        self.break_dir[i] = -1
                if d > 0: s += 0.5
                else: s -= 0.5
            # --- RSI ---
            r = self.rsi6[i]
            if r is not None:
                prev_r = self.rsi6[i - 1]
                if prev_r is not None and prev_r < 30 and r >= prev_r:  # 超卖回升
                    s += 1.5
                elif r > 50: s += 0.5
                elif r < 30: s -= 0.5
            # --- 布林 ---
            bm = self.boll_m[i]
            if bm is not None:
                if self.close[i] > bm: s += 0.5
                else: s -= 0.5
            # --- 量价 ---
            s += self.volsig[i]
            self.score[i] = s

    def _apply_entries(self):
        """双趋势门控 + 流动性过滤 + 结构突破主触发 + 阈值，生成入场方向。

        傅海棠"顺应大势"落地为双重过滤：
          ① 中周期门控（TREND_MA）+ ② 大趋势门控（TREND_MA_MAJOR，若可用），
        价格位于两层同侧才做单，把夹在均线之间的震荡 whipsaw 全部滤掉。
        另：上市初期/流动性不足（持仓量 < MIN_OI）不开新仓——那是噪声行情。
        """
        for i in range(self.n):
            s = self.score[i]
            c = self.close[i]
            mt = self.ma_t[i]
            if s is None or mt is None:
                self.gate[i] = 0
                continue
            oi = self.bars[i]["open_interest"]
            # 流动性过滤：持仓量过低（上市初期/不活跃）→ 观望
            if oi < MIN_OI:
                self.gate[i] = 0
                continue

            major = self.ma_major[i]
            # 双门控：中周期 + 大趋势同侧
            up = c > mt and (major is None or c > major)
            dn = c < mt and (major is None or c < major)
            if not up and not dn:
                self.gate[i] = 0
                continue

            self.gate[i] = 1 if up else -1
            brk = self.break_dir[i]
            if ENTRY_REQUIRE_CROSS and brk == 0:
                # 没有结构突破，不给入场
                continue
            if up:
                # 多头须有向上突破（金叉方向一致）；"物极必反"超跌反抽例外
                if brk >= 0:
                    if s >= SIGNAL_THRESHOLD:
                        self.signal[i] = 1
                else:
                    # 向下突破但价格已极低 + 超卖 → 物极必反多头
                    r = self.rsi6[i]
                    if (r is not None and r < 30 and c < COST_REF - COST_OVERSHOOT
                            and s + 2 >= SIGNAL_THRESHOLD):
                        self.signal[i] = 1
            else:
                if brk <= 0 and s <= -SIGNAL_THRESHOLD:
                    self.signal[i] = -1


def signals_of(strategy):
    """透出每根 bar 的方向信号，便于回测引擎消费。"""
    return strategy.signal