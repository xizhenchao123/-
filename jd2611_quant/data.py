# -*- coding: utf-8 -*-
"""数据加载：读取 JD2611 日线 CSV，返回结构化的 bar 列表。
如需刷新数据，可用通达信 MCP 的 tdx_kline 拉取最新 K 线后回写本 CSV。
"""
import csv
import os

BAR_KEYS = ["date", "open", "high", "low", "close", "volume", "open_interest"]


def load_bars(path):
    """读取 CSV 为 list[dict]，字段见 BAR_KEYS。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"数据文件不存在: {path}")
    bars = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "open_interest": float(row["open_interest"]),
            })
    return bars