# -*- coding: utf-8 -*-
"""探测 v2：确认鸡蛋主力连续接口。"""
import akshare as ak
import pandas as pd
pd.set_option("display.max_columns", None)

def show(name, df):
    if df is None:
        return
    try: n = len(df)
    except: n = "?"
    print(f"[OK] {name} rows={n} cols={list(df.columns)}")
    print(df.head(2).to_string()); print(df.tail(2).to_string()); print("-"*54)

try:
    dfm = ak.futures_display_main_sina()
    show("display_main_sina(前20)", dfm.head(20))
except Exception as e:
    print("[FAIL] display:", type(e).__name__, str(e)[:120]); print("-"*54)

try:
    df = ak.futures_main_sina(symbol="JD0", start_date="20140101", end_date="20260915")
    show("futures_main_sina JD0", df)
except Exception as e:
    print("[FAIL] main_sina JD0:", type(e).__name__, str(e)[:180]); print("-"*54)

try:
    df = ak.futures_hist_em(symbol="鸡蛋主连", period="daily",
                            start_date="20140101", end_date="20260915")
    show("futures_hist_em 鸡蛋主连", df)
except Exception as e:
    print("[FAIL] hist_em 鸡蛋主连:", type(e).__name__, str(e)[:180]); print("-"*54)