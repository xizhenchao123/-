# -*- coding: utf-8 -*-
"""鸡蛋期货量化仪表盘 · Flask 后端。

职责：
  · 启动/首次访问时加载长历史主力连续，计算一次完整状态并缓存。
  · /api/state    快速返回缓存状态（前端定时轮询用，不做网络抓取）。
  · /api/refresh  强制重建状态（可选先 fetch_history 拉最新日线）。
  · /api/rerun    重跑 run_long + walk_forward（较慢，输出文本缓存展示）。
  · 后台线程在交易时段平和收盘后自动核对数据、按需拉取更新。

运行：python app.py   → 本地 http://127.0.0.1:8501
"""
import os
import sys
import json
import time
import csv
import subprocess
import threading
from datetime import datetime, timezone, timedelta

# 北京时间 (UTC+8)
TZ_BJ = timezone(timedelta(hours=8))


def _now_bj():
    return datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M:%S")

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)   # 项目根（含 config.py / data / fetch_history.py）
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from flask import Flask, jsonify, request, render_template
import config as C
from indicators import sma, boll
from data import load_bars

# 缓存的全局状态（加锁）
STATE = {}
STATE_LOCK = threading.Lock()
ANALYSIS = {"run_long": "", "walk_forward": "", "updated": None, "running": False}

app = Flask(__name__)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _recompute():
    """重建行情/持仓状态缓存（快，不做大量检验）。"""
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

    # 尾部行情 + MA20 + 买卖点（用于前端 SVG 绘图）
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

    # 方向趋势判断（综合多信号）
    trend = _trend_verdict(strat, last["close"])

    # ---- 支撑 / 阻力位（基于真实价格）----
    rec = bars[-1]
    low20 = min(b["low"] for b in bars[-20:])
    high20 = max(b["high"] for b in bars[-20:])
    low60 = min(b["low"] for b in bars[-60:])
    ma20_now = ma20[-1]
    _bm, _bu, _bl = boll([b["close"] for b in bars], C.BOLL_PERIOD, C.BOLL_STD)
    boll_low = _bl[-1]
    cost_buy = C.COST_REF - C.COST_OVERSHOOT   # 物极必反买区
    levels = {
        # 名称: [价位, 类型]
        "压力": [round(high20, 0), "res"],
        "布林上轨": [round(_bu[-1], 0), "res"],
        "MA20": [round(ma20_now, 1), "mid"],
        "布林下轨": [round(boll_low, 1), "sup"],
        "支撑": [round(low20, 0), "sup"],
        "物极买区": [round(cost_buy, 0), "ext"],
    }
    # 买入点提示
    buy_notes = [
        "激进左侧：3650~3680 支撑带（近20日低点+布林下轨），跌破3650止损",
        "稳健右侧：站稳并收复 MA20(3787) 且共振分转正，才追多",
        "极值买区：<3520 触发物极必反，超跌博弈",
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
        "levels": levels,
        "buy_notes": buy_notes,
        "jd2611": _jd2611_analysis(),
        # 模拟盘
        "position": ({"dir": "多" if bt.dir == 1 else "空", "lots": bt.lots,
                      "entry": bt.entry_price, "stop": bt.stop_price,
                      "trail": bt.trail_active}
                     if bt.lots else None),
        "pending": pending,
        "last_trade": (bt.trades[-1] if bt.trades else None),
        # 尾部K线
        "tail": seq,
        "trend": trend,
        "params": {
            "TREND_MA": C.TREND_MA, "TREND_MA_MAJOR": C.TREND_MA_MAJOR,
            "SIGNAL_THRESHOLD": C.SIGNAL_THRESHOLD,
            "ATR_STOP_MULT": C.ATR_STOP_MULT, "TRAIL_STOP_TRIGGER": C.TRAIL_STOP_TRIGGER,
            "RISK_PER_TRADE": C.RISK_PER_TRADE, "MIN_TRADE_INTERVAL": C.MIN_TRADE_INTERVAL,
            "COST_REF": C.COST_REF,
        },
        "updated": _now_bj(),
    }
    return state


def refresh_state(do_fetch=False):
    global STATE
    if do_fetch:
        try:
            subprocess.run([sys.executable, "fetch_history.py"], timeout=90,
                           capture_output=True)
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
    """拉取/刷新 JD2611 个券日线到 data/jd2611_raw.csv（与主力连续相互独立）。"""
    import akshare as ak
    df = ak.futures_zh_daily_sina(symbol="JD2611")
    df = df.rename(columns={c: c.lower() for c in df.columns})
    out = os.path.join(PROJ, "data", "jd2611_raw.csv")
    df.to_csv(out, index=False)


def _jd2611_analysis():
    """对 JD2611 个券做专项方向/走势分析（独立于主力连续）。"""
    try:
        import pandas as pd
        from indicators import macd, rsi
    except Exception:
        return None
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
        bm, bu, bl = boll([b for b in c], 20, 2)
        last = df.iloc[-1]
        close = float(last["close"])
        prev = float(df.iloc[-2]["close"])
        chg = (close - prev) / prev
        # 手动 ATR14
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

        # 方向判定（与主力逻辑对齐的双周期）
        mid_bear = close < ma60
        short_bull = ma20 and c[-1] and sma(c, 5)[-1] > ma20
        if mid_bear and not (short_bull and hist > 0):
            verdict, cls = "偏空", "dn"
        elif not mid_bear and (short_bull or hist > 0):
            verdict, cls = "偏多", "up"
        else:
            verdict, cls = "震荡观望", "mut"
        quotes = {
            "via_date": str(last["date"]),
            "close": round(close, 0),
            "prev_close": round(prev, 0),
            "chg_pct": round(chg * 100, 2),
            "n_bars": int(len(df)),
            "ma5": round(sma(c, 5)[-1], 0),
            "ma10": round(sma(c, 10)[-1], 0),
            "ma20": round(ma20, 0),
            "ma60": round(ma60, 0),
            "atr": round(atr14, 0),
            "dif": round(dif, 1), "dea": round(dea, 1), "hist": round(hist, 1),
            "macd_bull": hist > 0,
            "rsi6": round(r6, 1), "rsi14": round(r14, 1),
            "boll_up": round(bu[-1], 0), "boll_mid": round(bm[-1], 0),
            "boll_low": round(bl[-1], 0),
            "hi20": round(hi20, 0), "lo20": round(lo20, 0),
            "hi120": round(hb, 0), "lo120": round(lb, 0),
            "verdict": verdict, "cls": cls,
            "mid_bear": mid_bear, "short_bull": short_bull,
            "pct_from_high": round((close / hb - 1) * 100, 1),
        }
        # 一句话依据
        note = []
        if mid_bear:
            note.append("价格仍在中周期均线(MA60)下方，中期偏弱")
        else:
            note.append("价格站上中周期均线，中期转强")
        if hist > 0:
            note.append("MACD红柱，动能偏多")
        else:
            note.append("MACD绿柱，动能偏空")
        note.append("短均线" + ("多头排列" if sma(c, 5)[-1] > ma20 else "空头排列"))
        quotes["summary"] = "；".join(note)
        return quotes
    except Exception as e:
        print("JD2611 分析失败:", e)
        return None


def _trend_verdict(strat, price):
    """综合多信号给出一句话方向趋势判断。

    依据（全部来自策略层已算好的指标）：
      · gate   趋势门控（+1 多头结构 / -1 空头结构 / 0 观望）
      · score  多信号共振分（>0 偏多，<0 偏空）
      · ma_s|ma_l  短期均线排列（多头/空头排列）
      · hist   MACD 柱（红/绿）
      · rsi6   强弱
    """
    i = -1
    c, gate, score = price, strat.gate[i], strat.score[i]
    ma_s, ma_l = strat.ma_s[i], strat.ma_l[i]
    hist, rsi = strat.hist[i], strat.rsi6[i]
    macd_bull = hist is not None and hist > 0
    ma_bull = ma_s is not None and ma_l is not None and ma_s > ma_l

    def _r(v, nd=1):
        return None if v is None else round(v, nd)

    score_v = _r(score)
    lines = []
    if gate == 1:
        if (score_v is not None and score_v >= 5) or (ma_bull and macd_bull):
            verdict, label, cls = "强多头", "看多", "up"
            lines.append("价在均线上方(多头结构)，多信号分强，MACD红柱")
        else:
            verdict, label, cls = "偏多", "看多", "up"
            lines.append("价在均线上方(多头结构)，但共振分/动能一般")
    elif gate == -1:
        if (score_v is not None and score_v <= -5) or (not ma_bull and not macd_bull):
            verdict, label, cls = "强空头", "看空", "dn"
            lines.append("价在均线下方(空头结构)，多信号分偏空，MACD绿柱")
        else:
            verdict, label, cls = "偏空", "看空", "dn"
            lines.append("价在均线下方(空头结构)，但下跌动能有限")
    else:
        if score_v is not None and score_v > 1.5:
            verdict, label, cls = "震荡偏多", "观望", "up"
        elif score_v is not None and score_v < -1.5:
            verdict, label, cls = "震荡偏空", "观望", "dn"
        else:
            verdict, label, cls = "震荡观望", "观望", "mut"
        lines.append("价格夹在均线间(无趋势门控)，建议观望")
    if macd_bull:
        lines.append("MACD红柱扩大")
    else:
        lines.append("MACD绿柱")
    if ma_bull:
        lines.append("短均线在长均线上方(多头排列)")
    else:
        lines.append("短均线在长均线下方(空头排列)")
    return {
        "verdict": verdict,
        "label": label,
        "cls": cls,
        "score": score_v,
        "close": c,
        "gate": "多头结构" if gate == 1 else ("空头结构" if gate == -1 else "观望"),
        "ma5": _r(ma_s, 0), "ma20": _r(ma_l, 0),
        "ma_bull": ma_bull,
        "macd_bull": macd_bull,
        "macd_hist": _r(hist),
        "rsi6": _r(rsi),
        "summary": "；".join(lines),
    }


# ---- 后台自动更新线程 ----
# 盘中实时：鸡蛋仅日盘（无夜盘）。北京时间 09:00-11:30 / 13:30-15:00 内每 10 分钟
#           拉一次最新数据并刷新缓存，供开盘时即时看趋势。
# 收盘后  ：每日 16:30 后做一次完整 fetch + 全样本回测 + Walk-Forward（保留原逻辑）。
def _in_session(t):
    """t=北京时间分钟数，是否处于鸡蛋日盘交易时段。"""
    morning = (540 <= t <= 615) or (630 <= t <= 690)   # 09:00-10:15, 10:30-11:30
    afternoon = 810 <= t <= 900                          # 13:30-15:00
    return morning or afternoon


def _background():
    last_close = ""
    last_live_min = -999   # 上次盘中实时刷新时刻（分钟）
    last_live_day = ""
    while True:
        bj_now = datetime.now(TZ_BJ)
        today = bj_now.strftime("%Y-%m-%d")
        t = bj_now.hour * 60 + bj_now.minute

        # 跨天重置盘中计时
        if today != last_live_day:
            last_live_day = today
            last_live_min = -999

        try:
            # 1) 盘中实时刷新：交易时段内每 10 分钟拉最新价 + 重算趋势
            if _in_session(t) and (t - last_live_min) >= 10:
                last_live_min = t
                refresh_state(do_fetch=True)
                print(f"[bg-live] {_now_bj()} 盘中实时刷新(价 {STATE.get('close')})")
            # 2) 收盘后：每日 16:30 后完整重跑一次
            elif today != last_close and bj_now.hour >= 16 and bj_now.minute >= 30:
                last_close = today
                refresh_state(do_fetch=True)
                print(f"[bg] {_now_bj()} 已核对/更新今日数据，开始重跑样本外检验…")
                ANALYSIS["running"] = True
                for name, cmd in [("run_long", [sys.executable, "run_long.py"]),
                                  ("walk_forward", [sys.executable, "walk_forward.py"])]:
                    try:
                        r = subprocess.run(cmd, timeout=1200, capture_output=True, text=True)
                        ANALYSIS[name] = (r.stdout or r.stderr)[-4000:]
                    except Exception as e:
                        ANALYSIS[name] = f"失败: {e}"
                ANALYSIS["updated"] = _now_bj()
                ANALYSIS["running"] = False
                print(f"[bg] {_now_bj()} 样本外检验完成")
                # 刷新行情缓存
                refresh_state(do_fetch=False)
        except Exception as e:
            print(f"[bg] 更新失败: {e}")
        time.sleep(300)   # 每 5 分钟检查一次（盘中每 10 分钟拉一次）


@app.route("/")
def index():
    with STATE_LOCK:
        ready = bool(STATE)
    if not ready:
        threading.Thread(target=lambda: refresh_state(do_fetch=False), daemon=True).start()
    return render_template("index.html")


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.route("/api/state")
def api_state():
    with STATE_LOCK:
        if not STATE:
            refresh_state(False)
        return jsonify(STATE, ANALYSIS)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    body = request.get_json(silent=True) or {}
    do_fetch = bool(body.get("fetch", False))
    s = refresh_state(do_fetch=do_fetch)
    return jsonify({"ok": True, "updated": s["updated"]})


@app.route("/api/rerun", methods=["POST"])
def api_rerun():
    if ANALYSIS["running"]:
        return jsonify({"ok": False, "msg": "检验已在运行，请稍候"}), 409
    def _run():
        ANALYSIS["running"] = True
        for name, path, cmd in [("run_long", "run_long.py", [sys.executable, "run_long.py"]),
                                ("walk_forward", "walk_forward.py", [sys.executable, "walk_forward.py"])]:
            try:
                r = subprocess.run(cmd, timeout=1200, capture_output=True, text=True)
                ANALYSIS[name] = (r.stdout or r.stderr)[-4000:]
            except Exception as e:
                ANALYSIS[name] = f"失败: {e}"
        ANALYSIS["updated"] = _now()
        ANALYSIS["running"] = False
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "msg": "已开始重跑样本外检验"})


@app.route("/api/analysis")
def api_analysis():
    return jsonify(ANALYSIS)


@app.route("/api/schedule")
def api_schedule():
    """返回定时任务状态（计算 next_run 等信息）。"""
    bj_now = datetime.now(TZ_BJ)
    # cron: 30 16 * * * → 每天 16:30 北京时间
    target_h, target_m = 16, 30
    today_run = bj_now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
    if bj_now.hour < target_h or (bj_now.hour == target_h and bj_now.minute < target_m):
        next_run = today_run
    else:
        # 明天
        tomorrow = bj_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        next_run = tomorrow.replace(hour=target_h, minute=target_m, second=0)
    return jsonify({
        "name": "JD2611鸡蛋量化每日回测",
        "status": "Active",
        "cron": "30 16 * * *",
        "next_run": next_run.strftime("%Y-%m-%d %H:%M (北京时间)"),
        "last_run": ANALYSIS.get("updated", None) or "尚未执行",
        "description": "每日16:30自动拉取数据 → 全样本回测 → Walk-Forward → 刷新仪表盘",
    })


if __name__ == "__main__":
    # 启动时立即算一次
    try:
        refresh_state(do_fetch=False)
        print("[startup] 状态已加载")
    except Exception as e:
        print("[startup] 加载失败:", e)
    threading.Thread(target=_background, daemon=True).start()
    app.run(host="0.0.0.0", port=8501, debug=False)