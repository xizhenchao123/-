# -*- coding: utf-8 -*-
"""技术指标：MA / EMA(MACD) / RSI / BOLL / ATR / 量价(放量增仓)。
仅采用业界公认的主流指标，便于回测中做多信号共振。
"""
import math


def sma(values, period):
    """简单移动平均，返回与 values 等长（前 period-1 个为 None）。"""
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def ema(values, period):
    """指数移动平均，返回等长列表。"""
    out = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (period + 1)
    prev = values[0]
    out[0] = prev
    for i in range(1, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def macd(close, fast=12, slow=26, mid=9):
    """返回 (DIF, DEA, MACD_hist)，等长列表，hist = DIF - DEA。"""
    ef = ema(close, fast)
    es = ema(close, slow)
    dif = [None] * len(close)
    for i in range(len(close)):
        if es[i] is not None and ef[i] is not None:
            dif[i] = ef[i] - es[i]
    dea = ema([d if d is not None else 0 for d in dif], mid)
    hist = [None] * len(close)
    for i in range(len(close)):
        if dif[i] is not None:
            hist[i] = dif[i] - dea[i]
    return dif, dea, hist


def rsi(close, period=6):
    """RSI，返回等长列表（含首元素哨兵，前部不可用置 None）。"""
    out = [None] * len(close)
    if len(close) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = close[i] - close[i - 1]
        gains += max(ch, 0)
        losses += max(-ch, 0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = _rsi_val(avg_g, avg_l)
    for i in range(period + 1, len(close)):
        ch = close[i] - close[i - 1]
        avg_g = (avg_g * (period - 1) + max(ch, 0)) / period
        avg_l = (avg_l * (period - 1) + max(-ch, 0)) / period
        out[i] = _rsi_val(avg_g, avg_l)
    return out


def _rsi_val(avg_g, avg_l):
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100.0 - 100.0 / (1.0 + rs)


def boll(close, period=20, std_mul=2.0):
    """返回 (mid, upper, lower)，等长列表。"""
    mid = sma(close, period)
    upper = [None] * len(close)
    lower = [None] * len(close)
    for i in range(len(close)):
        m = mid[i]
        if m is None:
            continue
        # 样本方差（总体）
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += (close[j] - m) ** 2
        sd = math.sqrt(s / period)
        upper[i] = m + std_mul * sd
        lower[i] = m - std_mul * sd
    return mid, upper, lower


def atr(bars, period=14):
    """真实波幅均值，返回等长列表。"""
    out = [None] * len(bars)
    if len(bars) < 2:
        return out
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # 首根 ATR 用 TR 平均近似
    seed = sum(trs[:period]) / period
    out[period] = seed
    for i in range(period, len(bars) - 1):
        # bars[i+1] 的 TR 是 trs[i]
        a_prev = out[i]
        tr_i = trs[i]
        # 前一指 ATR 对应 bars[i]，用 Wilder 平滑到 bars[i+1]
        cur = (a_prev * (period - 1) + tr_i) / period
        out[i + 1] = cur
    # 补充 period 前的位置（不参与信号，留 None 即可）
    return out


def volume_signal(bars, window=5):
    """量价信号：判放量 + 增仓。返回与 bars 等长列表，值为：
    +2 放量上涨且增仓（多头确认）
    +1 放量上涨 或 增仓上涨
     0 中性
    -1 放量下跌
    -2 放量下跌且减仓增空（空头确认）
    """
    out = []
    for i, b in enumerate(bars):
        if i < window:
            out.append(0)
            continue
        v_avg = sum(x["volume"] for x in bars[i - window:i]) / window
        oi_prev = bars[i - 1]["open_interest"]
        oi_change = b["open_interest"] - oi_prev
        chg = b["close"] - b["open"]
        vol_up = b["volume"] > v_avg * 1.2
        score = 0
        if vol_up:
            score += 1
        if oi_change > 0:      # 增仓
            score += 1
        elif oi_change < -0:   # 减仓
            score -= 1
        # 用方向修正
        if chg > 0:
            score = abs(score)
        elif chg < 0:
            score = -abs(score)
        out.append(score)
    return out