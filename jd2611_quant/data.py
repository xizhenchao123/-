# -*- coding: utf-8 -*-
"""数据加载工具。"""
import csv
import os


def load_bars(path):
    """从 CSV 加载 OHLCV + open_interest 数据，返回 list[dict]。"""
    bars = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "date": row["date"].strip(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(float(row.get("volume", 0))),
                "open_interest": int(float(row.get("open_interest", 0))),
            })
    return bars