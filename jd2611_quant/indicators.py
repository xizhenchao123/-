# -*- coding: utf-8 -*-
import math


def sma(data, n):
    res = [None] * len(data)
    for i in range(len(data)):
        if i < n - 1:
            continue
        s = 0.0
        for j in range(i - n + 1, i + 1):
            s += data[j]
        res[i] = s / n
    return res


def ema(data, n):
    k = 2.0 / (n + 1)
    res = [None] * len(data)
    for i, v in enumerate(data):
        if i == 0:
            res[i] = v
        else:
            res[i] = res[i - 1] + k * (v - res[i - 1])
    return res


def macd(data, fast=12, slow=26, sig=9):
    e_fast = ema(data, fast)
    e_slow = ema(data, slow)
    dif = [None] * len(data)
    for i in range(len(data)):
        if e_fast[i] is None or e_slow[i] is None:
            dif[i] = None
        else:
            dif[i] = e_fast[i] - e_slow[i]
    dea = ema([d if d is not None else 0 for d in dif], sig)
    hist = [None] * len(data)
    for i in range(len(data)):
        if dif[i] is not None and dea[i] is not None:
            hist[i] = (dif[i] - dea[i]) * 2
    return hist, dea, dif


def rsi(data, n):
    res = [None] * len(data)
    for i in range(len(data)):
        if i < n:
            continue
        gain, loss = 0.0, 0.0
        for j in range(i - n + 1, i + 1):
            d = data[j] - data[j - 1]
            if d > 0:
                gain += d
            else:
                loss -= d
        if loss == 0:
            res[i] = 100.0
        else:
            rs = gain / n / (loss / n)
            res[i] = 100 - 100 / (1 + rs)
    return res


def boll(data, n, k=2):
    mid = sma(data, n)
    up = [None] * len(data)
    low = [None] * len(data)
    for i in range(len(data)):
        if mid[i] is None:
            continue
        s = 0.0
        cnt = 0
        for j in range(max(0, i - n + 1), i + 1):
            s += (data[j] - mid[i]) ** 2
            cnt += 1
        std = math.sqrt(s / cnt)
        up[i] = mid[i] + k * std
        low[i] = mid[i] - k * std
    return mid, up, low


def atr(bars, n):
    """ATR from list-of-dict bars with high/low/close."""
    res = [None] * len(bars)
    tr_arr = [None] * len(bars)  # 存储逐笔 TR
    for i in range(len(bars)):
        if i == 0:
            tr = bars[i]["high"] - bars[i]["low"]
        else:
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
        tr_arr[i] = tr
        if i < n - 1:
            res[i] = None
            continue
        s = 0.0
        for j in range(i - n + 1, i + 1):
            s += tr_arr[j]
        res[i] = s / n
    return res