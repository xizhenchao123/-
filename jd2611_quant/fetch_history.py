# -*- coding: utf-8 -*-
"""拉取鸡蛋主力连续(JD0)日线，追加到 data/jd_main_hist.csv。"""
import os
import sys
import akshare as ak
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "jd_main_hist.csv")


def fetch_append(symbol="JD0"):
    df = ak.futures_zh_daily_sina(symbol=symbol)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    df["date"] = df["date"].astype(str).str[:10]
    df = df.sort_values("date").drop_duplicates(subset=["date"]).reset_index(drop=True)
    print(f"  新浪返回 {len(df)} 根，日期 {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

    if os.path.exists(OUT):
        old = pd.read_csv(OUT)
        old["date"] = old["date"].astype(str).str[:10]
        combined = pd.concat([old, df]).drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
        added = len(combined) - len(old)
        print(f"  原缓存 {len(old)} 根，新增 {added} 根，合计 {len(combined)} 根")
    else:
        combined = df
        print(f"  首次拉取，共 {len(combined)} 根")

    combined.to_csv(OUT, index=False)
    print(f"  已保存 → {OUT}")
    return combined


if __name__ == "__main__":
    fetch_append()