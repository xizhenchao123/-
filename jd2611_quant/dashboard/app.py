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
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(ROOT)   # 项目根（含 config.py / data / fetch_history.py）
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from flask import Flask, jsonify, request, render_template
import config as C
from indicators import sma
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
        # 模拟盘
        "position": ({"dir": "多" if bt.dir == 1 else "空", "lots": bt.lots,
                      "entry": bt.entry_price, "stop": bt.stop_price,
                      "trail": bt.trail_active}
                     if bt.lots else None),
        "pending": pending,
        "last_trade": (bt.trades[-1] if bt.trades else None),
        # 尾部K线
        "tail": seq,
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
            subprocess.run([sys.executable, "fetch_history.py"], timeout=90,
                           capture_output=True)
        except Exception as e:
            print("fetch_history 失败:", e)
    with STATE_LOCK:
        STATE = _recompute()
    return STATE


# ---- 后台自动更新线程：每天收盘后将新数据并入缓存 ----
def _background():
    last_check = ""
    while True:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != last_check and datetime.now().hour >= 16:
            last_check = today
            try:
                refresh_state(do_fetch=True)
                print(f"[bg] {_now()} 已核对/更新今日数据")
            except Exception as e:
                print(f"[bg] 更新失败: {e}")
        time.sleep(600)


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


if __name__ == "__main__":
    # 启动时立即算一次
    try:
        refresh_state(do_fetch=False)
        print("[startup] 状态已加载")
    except Exception as e:
        print("[startup] 加载失败:", e)
    threading.Thread(target=_background, daemon=True).start()
    app.run(host="127.0.0.1", port=8501, debug=False)