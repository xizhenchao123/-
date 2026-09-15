# -*- coding: utf-8 -*-
"""获取鸡蛋期货(JD)主力连续长历史日线并保存为 CSV。
数据源：akshare futures_main_sina(symbol="JD0")，2014-01-02 至今。

主力连续 = 按成交量/持仓量在各到期合约间滚动切换的缝合序列，价格单位为元/500公斤，
与各合约相同；切换点存在轻微价差，属连续行情正常现象，这里不做复权(back-adjust)。

用法：python fetch_history.py
输出：data/jd_main_hist.csv（date,open,high,low,close,volume,open_interest）
"""
import os
import akshare as ak

OUT = os.path.join("data", "jd_main_hist.csv")


def main():
    df = ak.futures_main_sina(symbol="JD0", start_date="20140101",
                              end_date="22220101")
    df["date"] = df["日期"].astype(str).str[:10]
    out = df[["date", "开盘价", "最高价", "最低价", "收盘价", "成交量", "持仓量"]].copy()
    out.columns = ["date", "open", "high", "low", "close", "volume", "open_interest"]
    out = out.dropna(subset=["close"]).sort_values("date")
    out.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"已保存 → {OUT}  共 {len(out)} 根  ({out['date'].iloc[0]} ~ {out['date'].iloc[-1]})")
    print(out.head(3).to_string())
    print(out.tail(3).to_string())


if __name__ == "__main__":
    main()