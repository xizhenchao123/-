# -*- coding: utf-8 -*-
"""把通达信 tdx_kline 的 persisted 输出转换成标准 CSV。
用法：python build_csv_from_mcp.py <persisted_txt> <输出csv>
从 MCP 返回文本中定位 '详细K线数据:' 后的 JSON，提取 Rows 写出
date,open,high,low,close,volume,open_interest。
"""
import sys
import json


def extract_rows(path):
    # persisted 文件把 MCP 的 JSON 字符串转义后存储，需先解码一层转义
    with open(path, encoding="utf-8") as f:
        text = f.read()
    ridx = text.find("Rows")
    if ridx < 0:
        raise SystemExit("未找到 Rows")
    start = text.find("[", ridx)
    if start < 0:
        raise SystemExit("未找到 Rows 数组起点")
    # 找到配对 ]（引号内跳过）
    depth = 0
    i = start
    in_str = False
    while i < len(text):
        c = text[i]
        if c == '"':
            if not in_str:
                in_str = True
            elif text[i - 1] != "\\":
                in_str = False
        elif not in_str:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        i += 1
    blob = text[start:end]
    blob = blob.replace('\\"', '"').replace("\\n", "\n")
    obj = json.JSONDecoder().raw_decode(blob)[0]
    return obj


def main():
    src, dst = sys.argv[1], sys.argv[2]
    rows = extract_rows(src)
    lines = ["date,open,high,low,close,volume,open_interest"]
    for r in rows:
        lines.append(",".join([
            r["Data"],
            f"{float(r['Open']):.1f}", f"{float(r['High']):.1f}",
            f"{float(r['Low']):.1f}", f"{float(r['Close']):.1f}",
            f"{float(r['Volume']):.0f}", f"{float(r['VolInStock']):.0f}",
        ]))
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已写入 {dst} 共 {len(rows)} 根（{rows[0]['Data']} ~ {rows[-1]['Data']}）")


if __name__ == "__main__":
    main()