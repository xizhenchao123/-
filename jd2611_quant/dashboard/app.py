# -*- coding: utf-8 -*-
"""鸡蛋期货量化仪表盘 · Flask 后端。"""
import os
import sys
import json
import time
import csv
import subprocess
import threading
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from flask import Flask, jsonify, render_template
import config as C
from indicators import sma, macd, rsi, boll
from data import load_bars

STATE = {}
STATE_LOCK = threading.Lock()
ANALYSIS = {"run_long": "", "walk_forward": "", "updated": None, "running": False}

BJ_TZ = timezone(timedelta(hours=8))

app = Flask(__name__)


def _now():
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _trend_verdict(bars, close, score_v=None, gate_str=None):
    """返回方向结论 dict。"""
    n = len(bars)
    if n < 60:
        return {"verdict": "数据不足", "label": "观望", "cls": "mut",
                "score": 0, "gate": "--", "summary": "数据不足",
                "close": close[-1] if close else 0}

    ma20 = sma(close, 20)[-1]
    ma60 = sma(close, 60)[-1]
    hist, dea, dif = macd(close)
    r6 = rsi(close, 6)[-1]
    trend = sma(close, C.TREND_MA)
    trend_major = sma(close, C.TREND_MA_MAJOR)

    mid_bear = close[-1] < ma60
    short_bull = close[-1] > ma20

    # 共振分
    score = 0
    ma5 = sma(close, 5)[-1]
    if ma5 > ma20:
        score += 2 if not mid_bear else 1
    else:
        score -= 2 if mid_bear else 1
    if hist[-1] > 0 and dif[-1] > dea[-1]:
        score += 2
    elif hist[-1] < 0 and dif[-1] < dea[-1]:
        score -= 2
    if r6 < 30:
        score += 1
    elif r6 > 70:
        score -= 1
    if not mid_bear:
        score += 1
    else:
        score -= 1

    if score >= 3:
        verdict, cls = "看多", "up"
    elif score <= -3:
        verdict, cls = "看空", "dn"
    elif score >= 1:
        verdict, cls = "偏多", "up"
    elif score <= -1:
        verdict, cls = "偏空", "dn"
    else:
        verdict, cls = "震荡观望", "mut"

    gate = gate_str or (
        "多头结构" if trend[-1] > trend_major[-1] else
        "空头结构" if trend[-1] < trend_major[-1] else "结构不明"
    )

    # 一句话依据
    notes = []
    if mid_bear:
        notes.append(f"价在中周期均线下方")
    else:
        notes.append(f"价站上中周期均线")
    if hist[-1] > 0:
        notes.append("MACD红柱扩大")
    else:
        notes.append("MACD绿柱")
    if r6 > 70:
        notes.append(f"RSI{round(r6,0)}超买")
    elif r6 < 30:
        notes.append(f"RSI{round(r6,0)}超卖")
    else:
        notes.append(f"RSI{round(r6,0)}中性")
    if score >= 3 or score <= -3:
        notes.append("多信号共振→方向" + ("一致" if abs(score) >= 4 else "偏强"))

    return {
        "verdict": verdict,
        "label": "看空" if verdict in ("偏空", "看空") else ("看多" if verdict in ("偏多", "看多") else "观望"),
        "cls": cls,
        "score": score,
        "close": close[-1],
        "gate": gate,
        "summary": "；".join(notes),
        "ma20": round(ma20, 1),
        "rsi6": round(r6, 1),
        "macd_hist": round(hist[-1], 1) if hist[-1] else 0,
        "mid_bear": mid_bear,
        "short_bull": short_bull,
    }


def _recompute():
    """重建行情/持仓状态缓存。"""
    bars = load_bars(os.path.join(PROJ, "data", "jd_main_hist.csv"))
    import strategy as STRAT
    from backtest import Backtest

    strat = STRAT.Strategy(bars)
    bt = Backtest(bars, strat.signal)
    bt.run()

    n = len(bars)
    last = bars[-1]
    prev = bars[-2] if n > 1 else last
    chg = (last["close"] - prev["close"]) / prev["close"] if prev["close"] else 0.0
    pending = None
    if bt.lots == 0 and strat.signal[-1] != 0:
        if (n - 1 - bt.last_exit_idx) >= C.MIN_TRADE_INTERVAL:
            pending = {"dir": "多" if strat.signal[-1] == 1 else "空",
                       "date": last["date"]}

    # 尾部行情
    tail_n = 220
    tail = bars[-tail_n:]
    ma20 = sma([b["close"] for b in bars], 20)[-tail_n:]
    seq = []
    mark_set = {(t["entry_date"]): "long" if t["direction"] == "多" else "short"
                for t in bt.trades}
    for i, b in enumerate(tail):
        seq.append({"date": b["date"], "o": b["open"], "h": b["high"],
                    "l": b["low"], "c": b["close"],
                    "ma20": None if ma20[i] is None else round(ma20[i], 1),
                    "mark": mark_set.get(b["date"], None)})

    # 趋势判断
    c_list = [b["close"] for b in bars]
    tr = _trend_verdict(bars, c_list)

    # 水平价位
    n20, n60 = 20, 60
    hi20 = max(b["high"] for b in bars[-n20:])
    lo20 = min(b["low"] for b in bars[-n20:])
    mid_b, up_b, low_b = boll(c_list, 20, 2)
    levels = {
        "boll_up": round(up_b[-1], 0) if up_b[-1] else 0,
        "boll_mid": round(mid_b[-1], 0) if mid_b[-1] else 0,
        "boll_low": round(low_b[-1], 0) if low_b[-1] else 0,
        "hi20": round(hi20, 0), "lo20": round(lo20, 0),
        "ma20": round(ma20[-1], 0) if ma20[-1] else 0,
        "extreme_buy": round(lo20 * 0.965, 0),
    }
    buy_notes = [
        f"激进左侧：{round(lo20,0)}~{round(up_b[-1] if up_b[-1] else 0,0)} 支撑带",
        f"稳健右侧：收复 MA20({round(ma20[-1] if ma20[-1] else 0,0)}) 且共振转正",
        f"极值买区：< {levels['extreme_buy']} 触发物极必反",
    ]

    state = {
        "date": last["date"],
        "close": last["close"],
        "prev_close": prev["close"],
        "chg_pct": round(chg * 100, 2),
        "oi": last["open_interest"],
        "vol": last["volume"],
        "n_bars": n,
        "trade_count": len(bt.trades),
        "equity_final": round(bt.equity[-1], 0),
        "eq_total_pct": round(bt.equity[-1] / C.INITIAL_CAPITAL - 1, 4),
        "position": ({"dir": "多" if bt.dir == 1 else "空", "lots": bt.lots,
                      "entry": bt.entry_price, "stop": bt.stop_price,
                      "trail": bt.trail_active}
                     if bt.lots else None),
        "pending": pending,
        "last_trade": (bt.trades[-1] if bt.trades else None),
        "tail": seq,
        "trend": tr,
        "levels": levels,
        "buy_notes": buy_notes,
        "jd2611": _jd2611_analysis(),
        "params": {
            "TREND_MA": C.TREND_MA, "TREND_MA_MAJOR": C.TREND_MA_MAJOR,
            "SIGNAL_THRESHOLD": C.SIGNAL_THRESHOLD,
            "ATR_STOP_MULT": C.ATR_STOP_MULT, "TRAIL_STOP_TRIGGER": C.TRAIL_STOP_TRIGGER,
            "RISK_PER_TRADE": C.RISK_PER_TRADE, "MIN_TRADE_INTERVAL": C.MIN_TRADE_INTERVAL,
            "COST_REF": C.COST_REF,
        },
        "updated": _now(),
    }
    return state


def refresh_state(do_fetch=False):
    global STATE
    if do_fetch:
        try:
            subprocess.run([sys.executable, "fetch_history.py"], timeout=90, capture_output=True)
        except Exception as e:
            print("fetch_history 失败:", e)
        try:
            _fetch_jd2611()
        except Exception as e:
            print("fetch JD2611 失败:", e)
    with STATE_LOCK:
        STATE = _recompute()
    return STATE


def _fetch_jd2611():
    """拉取 JD2611 个券日线。"""
    import akshare as ak
    df = ak.futures_zh_daily_sina(symbol="JD2611")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    out = os.path.join(PROJ, "data", "jd2611_raw.csv")
    df.to_csv(out, index=False)


def _jd2611_analysis():
    """对 JD2611 个券做专项分析。"""
    import pandas as pd
    fp = os.path.join(PROJ, "data", "jd2611_raw.csv")
    if not os.path.exists(fp):
        return None
    try:
        df = pd.read_csv(fp)
        df = df.sort_values("date").reset_index(drop=True)
        df = df.dropna(subset=["close"]).reset_index(drop=True)
        if len(df) < 30:
            return None
        c = df["close"].tolist()
        ma20 = sma(c, 20)[-1]
        ma60 = sma(c, 60)[-1]
        hist, dea, dif = macd(c)
        hist, dif, dea = hist[-1], dif[-1], dea[-1]
        r6 = rsi(c, 6)[-1]
        r14 = rsi(c, 14)[-1]
        bm, bu, bl = boll(c, 20, 2)
        last = df.iloc[-1]
        close = float(last["close"])
        prev = float(df.iloc[-2]["close"])
        chg = (close - prev) / prev
        # ATR14
        tr = []
        for i in range(len(df)):
            h, l = df["high"].iloc[i], df["low"].iloc[i]
            pc = df["close"].iloc[i - 1] if i > 0 else h
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr14 = sum(tr[-14:]) / 14
        hi20 = df["high"].tail(20).max()
        lo20 = df["low"].tail(20).min()
        hb = df["close"].tail(120).max()
        lb = df["close"].tail(120).min()

        mid_bear = close < ma60
        if mid_bear:
            verdict, cls = "偏空", "dn"
        elif hist > 0 and r6 > 40:
            verdict, cls = "偏多", "up"
        else:
            verdict, cls = "震荡观望", "mut"

        notes = []
        if mid_bear:
            notes.append("价格位于中周期均线(MA60)下方，中期偏弱")
        else:
            notes.append("价格站上中周期均线，中期转强")
        notes.append("MACD" + ("红柱，动能偏多" if hist > 0 else "绿柱，动能偏空"))
        ma5 = sma(c, 5)[-1]
        notes.append("短均线" + ("多头排列" if ma5 > ma20 else "空头排列"))

        return {
            "via_date": str(last["date"]),
            "close": round(close, 0),
            "prev_close": round(prev, 0),
            "chg_pct": round(chg * 100, 2),
            "n_bars": int(len(df)),
            "ma5": round(ma5, 0),
            "ma10": round(sma(c, 10)[-1], 0),
            "ma20": round(ma20, 0),
            "ma60": round(ma60, 0),
            "atr": round(atr14, 0),
            "dif": round(dif, 1) if dif else 0,
            "dea": round(dea, 1) if dea else 0,
            "hist": round(hist, 1) if hist else 0,
            "macd_bull": hist > 0 if hist else False,
            "rsi6": round(r6, 1) if r6 else 0,
            "rsi14": round(r14, 1) if r14 else 0,
            "boll_up": round(bu[-1], 0) if bu[-1] else 0,
            "boll_mid": round(bm[-1], 0) if bm[-1] else 0,
            "boll_low": round(bl[-1], 0) if bl[-1] else 0,
            "hi20": round(hi20, 0),
            "lo20": round(lo20, 0),
            "hi120": round(hb, 0),
            "lo120": round(lb, 0),
            "pct_from_high": round((close / hb - 1) * 100, 1),
            "verdict": verdict,
            "cls": cls,
            "mid_bear": mid_bear,
            "summary": "；".join(notes),
        }
    except Exception as e:
        print("JD2611 分析失败:", e)
        return None


# ---- Flask routes ----
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with STATE_LOCK:
        if not STATE:
            refresh_state()
    return jsonify([STATE])


@app.route("/api/refresh")
def api_refresh():
    refresh_state(do_fetch=request and request.args.get("fetch", "0") == "1")
    return jsonify([STATE])


@app.route("/api/rerun")
def api_rerun():
    if ANALYSIS["running"]:
        return jsonify({"status": "already running"})
    ANALYSIS["running"] = True
    for name, cmd in [("run_long", [sys.executable, "run_long.py"]),
                      ("walk_forward", [sys.executable, "walk_forward.py"])]:
        try:
            r = subprocess.run(cmd, timeout=1200, capture_output=True, text=True)
            ANALYSIS[name] = (r.stdout or r.stderr)[-4000:]
        except Exception as e:
            ANALYSIS[name] = f"失败: {e}"
    ANALYSIS["updated"] = _now()
    ANALYSIS["running"] = False
    refresh_state(do_fetch=False)
    return jsonify({"status": "done"})


# ---- 后台自动更新线程 ----
def _background():
    last_check = ""
    while True:
        now = datetime.now(BJ_TZ)
        today = now.strftime("%Y-%m-%d")
        # 盘中每 10 分钟刷新数据（09:00-11:30, 13:30-15:00）
        in_market = False
        wd = now.weekday()
        if wd < 5:  # 周一到周五
            hm = now.hour * 100 + now.minute
            if (900 <= hm <= 1130) or (1330 <= hm <= 1500):
                in_market = True
        # 收盘后 16:30 做一次完整流程
        do_full = (today != last_check and now.hour == 16 and now.minute >= 30)
        if in_market:
            try:
                refresh_state(do_fetch=True)
                print(f"[bg] {_now()} 盘中数据刷新完成")
            except Exception as e:
                print(f"[bg] 盘中刷新失败: {e}")
            time.sleep(600)
        elif do_full:
            last_check = today
            try:
                refresh_state(do_fetch=True)
                print(f"[bg] {_now()} 数据已更新，开始跑样本外检验…")
                # 加回测
                ANALYSIS["running"] = True
                for name, cmd in [("run_long", [sys.executable, "run_long.py"]),
                                  ("walk_forward", [sys.executable, "walk_forward.py"])]:
                    try:
                        r = subprocess.run(cmd, timeout=1200, capture_output=True, text=True)
                        ANALYSIS[name] = (r.stdout or r.stderr)[-4000:]
                    except Exception as e:
                        ANALYSIS[name] = f"失败: {e}"
                ANALYSIS["updated"] = _now()
                ANALYSIS["running"] = False
                refresh_state(do_fetch=False)
                print(f"[bg] {_now()} 收盘流程完成")
            except Exception as e:
                print(f"[bg] 收盘更新失败: {e}")
            time.sleep(600)
        else:
            time.sleep(120)


def start_bg():
    t = threading.Thread(target=_background, daemon=True)
    t.start()


if __name__ == "__main__":
    # 首次加载数据
    jd_csv = os.path.join(PROJ, "data", "jd_main_hist.csv")
    if not os.path.exists(jd_csv):
        print("首次运行，拉取数据…")
        subprocess.run([sys.executable, "fetch_history.py"])
        _fetch_jd2611()
    with STATE_LOCK:
        STATE = _recompute()
    start_bg()
    app.run(host="0.0.0.0", port=8501, debug=False, use_reloader=False)