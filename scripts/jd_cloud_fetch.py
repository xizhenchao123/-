# -*- coding: utf-8 -*-
"""
jd_cloud_fetch.py — v17.28 云端轻量抓取（GitHub Actions 定时任务专用）
=====================================================================
只抓两样（~1KB 轻量包，不含K线——页面K线走内置新浪实时源）：
  ① 鸡蛋现货价   生意社口径（元/500kg → 页面用 元/斤），futures_spot_price 按日全品种过滤 JD，
                 自动回退最近 7 个自然日找有数据的交易日，取最近两个交易日（今日价 + 前值）。
  ② 饲料成本锚   玉米主力连续(C0) + 豆粕主力连续(M0) 最新收盘（10 天新鲜度校验），
                 料价 = 62%玉米 + 28%豆粕 + 10%预混(4.2元/kg)，costPerJin = 料价 × 2.3斤料/斤蛋 ÷ 2。

输出：仓库根目录 jd_cloud_feed.json ——
  { "fetchedAt": ..., "spot": {today, yest, auto:{date,prevDate,source,domContract}}, "feed": {...} }
由本 workflow 自提交进仓库；GitHub Pages 线上版在本地 jd_latest.json 缺失时
fetch 此包，复用页面内 applySpotAuto / applyFeedAuto 自动回填（人工录入优先）。

与本地生产脚本 jd_fetch_akshare.py 的关系：fetch_spot / fetch_feed_cost /
with_timeout / retry 逻辑原样复用（同一数据源、同一公式、同一容错）。
计划：交易日（周一~周五）北京时间 09:20 / 10:30 / 13:20 / 15:10 各跑一次。
"""
import json
import os
import sys
import time
import threading

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jd_cloud_feed.json")

FETCH_TIMEOUT = 60  # 单步取数硬超时（秒），防止接口挂起导致任务卡死


def with_timeout(fn, seconds=FETCH_TIMEOUT):
    """守护线程硬超时：接口挂起时在 seconds 秒后放弃，不让进程无限等待"""
    box = {}

    def runner():
        try:
            box["ok"] = fn()
        except Exception as e:
            box["err"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(seconds)
    if "err" in box:
        raise box["err"]
    if "ok" not in box:
        raise TimeoutError(f"取数超时({seconds}s)")
    return box["ok"]


def retry(fn, n=3, wait=2):
    """网络容错重试"""
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(wait)
    raise last


def fetch_spot():
    """鸡蛋现货价（生意社口径，元/500kg）：futures_spot_price(date) 按日全品种查询，
    过滤 symbol==JD；自动回退最近 7 个自然日找有数据的交易日（周末/节假日无数据）。
    取最近两个有数据的交易日，今日价 + 前一交易日价。失败返回 None。"""
    import akshare as ak, datetime, warnings
    try:
        today = datetime.date.today()
        rows = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for back in range(10):  # v17.29: 7→10 天。10/7 事故诱因：长假第 8 天窗口滑出最近交易日
                day = today - datetime.timedelta(days=back)
                if back == 0 and day.weekday() >= 5:
                    continue  # 今天是周末，直接从周五开始找
                ds = day.strftime("%Y%m%d")
                try:
                    df = with_timeout(lambda: ak.futures_spot_price(ds), 30)
                except Exception:
                    continue
                if df is None or len(df) == 0:
                    continue
                jd = df[df["symbol"] == "JD"]
                if len(jd) == 0:
                    continue
                r = jd.iloc[0]
                rows.append({
                    "date": ds,
                    "spotPrice": float(r["spot_price"]),
                    "domContract": str(r["dominant_contract"]),
                })
                if len(rows) >= 2:
                    break
        if not rows:
            return None
        cur = rows[0]
        cur["prevSpotPrice"] = rows[1]["spotPrice"] if len(rows) >= 2 else None
        cur["prevDate"] = rows[1]["date"] if len(rows) >= 2 else None
        cur["source"] = "生意社(AKShare futures_spot_price)"
        return cur
    except Exception as e:
        print(f"   ⚠️ 现货抓取失败: {e}", flush=True)
        return None


def fetch_feed_cost():
    """饲料成本锚：玉米主力连续(C0) + 豆粕主力连续(M0) 日线最新收盘价。
    料价 = 62%玉米 + 28%豆粕 + 10%预混料（4.2元/kg 固定估算）；
    costPerJin = 料价 × 2.3斤料/斤蛋 ÷ 2（元/kg → 元/斤）。失败返回 None。"""
    import akshare as ak, datetime
    try:
        def latest_close(sym):
            df = with_timeout(lambda: ak.futures_main_sina(symbol=sym), 30)
            last = df.iloc[-1]
            d = str(last["日期"]).replace("-", "")
            # 数据新鲜度校验：与北京时间相差超过 10 个自然日视为源停更/陈旧
            dt = datetime.datetime.strptime(d, "%Y%m%d")
            now_bj = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
            if (now_bj - dt).days > 10:
                raise ValueError(f"{sym} 最新数据日期 {d} 距今 {(now_bj - dt).days} 天，疑似数据源停更")
            return float(last["收盘价"]), d
        corn, cornD = latest_close("C0")
        meal, mealD = latest_close("M0")
        if not corn or not meal:
            return None
        premix = 4.2  # 元/kg 预混料固定估算
        cornKg, mealKg = corn / 1000.0, meal / 1000.0  # 元/吨 → 元/kg
        feedPrice = cornKg * 0.62 + mealKg * 0.28 + premix * 0.10  # 元/kg 料价
        costPerJin = feedPrice * 2.3 / 2  # 2.3斤料/斤蛋，元/kg→元/斤 ÷2
        print(f"   🌽 饲料成本线：玉米{corn:.0f} 豆粕{meal:.0f} → 料价{feedPrice:.2f}元/kg → 成本{costPerJin:.2f}元/斤蛋", flush=True)
        return {
            "corn": round(corn, 1), "cornDate": cornD,
            "meal": round(meal, 1), "mealDate": mealD,
            "feedPrice": round(feedPrice, 3),
            "costPerJin": round(costPerJin, 3),
            "date": max(cornD, mealD),
            "source": "新浪主力连续(AKShare futures_main_sina)",
        }
    except Exception as e:
        print(f"   ⚠️ 饲料成本抓取失败: {e}", flush=True)
        return None


def spot_cloud(spot):
    """生产 spot 字段 → 页面 applySpotAuto 契约：元/500kg ÷1000 = 元/斤"""
    if not spot:
        return None
    return {
        "today": round(spot["spotPrice"] / 1000.0, 3),
        "yest": round(spot["prevSpotPrice"] / 1000.0, 3) if spot.get("prevSpotPrice") else None,
        "auto": {
            "date": spot["date"],
            "prevDate": spot.get("prevDate"),
            "source": spot.get("source", ""),
            "domContract": spot.get("domContract", ""),
        },
    }


def main():
    print("☁️ [jd-cloud] 拉取 鸡蛋现货 + 饲料成本 ...", flush=True)
    spot = fetch_spot()
    if spot:
        chgTxt = "无前值"
        if spot.get("prevSpotPrice"):
            chg = (spot["spotPrice"] - spot["prevSpotPrice"]) / spot["prevSpotPrice"] * 100
            chgTxt = f"{chg:+.1f}%"
        print(f"   🥚 现货价 {spot['spotPrice']} 元/500kg（{spot['date']}，较前日 {chgTxt}）", flush=True)
    feed = fetch_feed_cost()

    if not spot and not feed:
        print("❌ 现货与饲料双双失败，放弃本次更新（线上保留旧包）", flush=True)
        sys.exit(1)

    out = {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "spot": spot_cloud(spot),
        "feed": feed,
    }

    # v17.29 修复（2026-10-08 事故复盘）：单边失败时沿用旧包字段，防止好数据被 null 覆盖。
    # 事故机理：10/7 早 7 天回看窗口滑出 9/30 → spot=None 照常写包 → family 组包模板重建 → 种子回退丢失。
    # 原则：抓不到的沿用旧值，绝不写 null 抹掉已有好数据；仅双双失败才放弃本轮（sys.exit(1)）。
    if out["spot"] is None or out["feed"] is None:
        old = None
        try:
            with open(OUT, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = None
        if out["spot"] is None:
            old_spot = (old or {}).get("spot")
            if isinstance(old_spot, dict) and old_spot.get("today"):
                out["spot"] = old_spot
                print(f"   ↩️ 现货本轮抓取失败，沿用旧包现货（{old_spot.get('auto', {}).get('date', '?')}）", flush=True)
        if out["feed"] is None:
            old_feed = (old or {}).get("feed")
            if isinstance(old_feed, dict) and old_feed.get("costPerJin"):
                out["feed"] = old_feed
                print(f"   ↩️ 饲料本轮抓取失败，沿用旧包饲料锚（{old_feed.get('date', '?')}）", flush=True)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"💾 已写入 {OUT}", flush=True)


if __name__ == "__main__":
    main()
