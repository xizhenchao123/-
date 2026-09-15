# -*- coding: utf-8 -*-
"""把通达信 MCP 拉取到的最新 K 线并入主 CSV，并做去重、按日期排序。
用法：
  1) 用通达信期货 MCP 调用 tdx_kline(code="JD2611", setcode=29, period=4, wantNum=500)，
     将返回的 Rows 逐行写成 data/raw_update.csv（表头同主表：
     date,open,high,low,close,volume,open_interest）。
  2) python refresh_data.py
     脚本会把 raw_update 与主表合并：同一日期以 raw 为准（保留最新复权/最新合约数据），
     按日期升序写回 data/jd2611_daily.csv，并删除 raw_update.csv 临时文件。
"""
import os
import csv

import config as C

MAIN = C.DATA_CSV
RAW = os.path.join("data", "raw_update.csv")


def read(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows[r["date"]] = {
                "date": r["date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"] or 0),
                "open_interest": float(r.get("open_interest", 0) or 0),
            }
    return rows


def main():
    if not os.path.exists(RAW):
        print("未找到 data/raw_update.csv，跳过本次更新。")
        return
    merged = read(MAIN)
    merged.update(read(RAW))  # raw 覆盖同日期
    ordered = sorted(merged.values(), key=lambda r: r["date"])
    with open(MAIN, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low",
                                          "close", "volume", "open_interest"])
        w.writeheader()
        w.writerows(ordered)
    os.remove(RAW)
    print(f"合并完成：主表现有 {len(ordered)} 根日线，最新日期 {ordered[-1]['date']}。")
    print("随后请运行：python main.py && python visualize.py && python sensitivity.py")


if __name__ == "__main__":
    main()