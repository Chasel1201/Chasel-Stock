"""
個股籌碼查詢 — 全市場資料抓取腳本
====================================
由 GitHub Actions 排程執行，跑在 GitHub 的伺服器上，不受瀏覽器 CORS 限制。

兩組資料來源（皆已用真實資料驗證過）：
  1. 大戶持股比／籌碼集中度：TDCC 集保結算所開放資料
     https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
     每週更新，一次回傳全市場所有證券的股權分散表（17個持股級距）。
     「大戶」定義（本工具採用的慣例，非TDCC官方名詞）：
     取級距15、16（不含級距17的加總列）之股數合計 ÷ 總股數，
     這是市場上常見「千張大戶」概念的近似算法，你可以依需要調整級距範圍。

  2. 外資持股比：臺灣證交所官方資料
     https://www.twse.com.tw/rwd/trading/fund/MI_QFIIS?date=YYYYMMDD&response=json&selectType=ALLBUT0999
     每交易日更新，回傳全市場「全體外資及陸資持股比率」。

輸出：stocks.json，格式為 {"證券代號": {"name":..., "concentration_pct":..., "foreign_holding_pct":...}}
"""

import csv
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))


def fetch_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url):
    return json.loads(fetch_text(url))


def build_concentration():
    """回傳 {股票代號: {"name":None,"concentration_pct":..., "date":...}}"""
    text = fetch_text("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5")
    text = text.lstrip("\ufeff")  # TDCC的CSV檔頭帶BOM字元，不移除會導致第一欄位名稱比對失敗
    reader = csv.DictReader(io.StringIO(text))

    per_stock = {}  # code -> {15: shares, 16: shares, 17: total}
    latest_date = None
    for row in reader:
        code = row.get("證券代號", "").strip()
        if not code:
            continue
        latest_date = row.get("資料日期", latest_date)
        tier = row.get("持股分級", "").strip()
        shares = int(row.get("股數", "0") or 0)
        if code not in per_stock:
            per_stock[code] = {}
        per_stock[code][tier] = shares

    result = {}
    for code, tiers in per_stock.items():
        total = tiers.get("17", 0)
        if total <= 0:
            continue
        big = tiers.get("15", 0) + tiers.get("16", 0)
        result[code] = {
            "concentration_pct": round(big / total * 100, 2),
            "concentration_date": latest_date,
        }
    return result


def build_foreign_holding():
    """回傳 {股票代號: {"name":..., "foreign_holding_pct":..., "date":...}}"""
    today = datetime.now(TAIPEI_TZ)
    # 外資持股資料若當天還沒發布，往前找最近幾天
    for delta in range(0, 6):
        d = today - timedelta(days=delta)
        date_str = d.strftime("%Y%m%d")
        url = (
            "https://www.twse.com.tw/rwd/trading/fund/MI_QFIIS"
            f"?date={date_str}&response=json&selectType=ALLBUT0999"
        )
        try:
            data = fetch_json(url)
        except Exception:
            continue
        if data.get("stat") != "OK" or not data.get("data"):
            continue

        fields = data["fields"]
        idx_code = fields.index("證券代號")
        idx_name = fields.index("證券名稱")
        idx_pct = fields.index("全體外資及陸資持股比率")

        result = {}
        for row in data["data"]:
            code = row[idx_code].strip()
            name = row[idx_name].strip()
            pct_str = str(row[idx_pct]).replace(",", "").strip()
            try:
                pct = float(pct_str)
            except ValueError:
                continue
            result[code] = {
                "name": name,
                "foreign_holding_pct": pct,
                "foreign_holding_date": date_str,
            }
        return result
    return {}


def main():
    print("抓取外資持股比…")
    foreign = build_foreign_holding()
    print(f"  取得 {len(foreign)} 檔股票的外資持股比")

    print("抓取大戶持股比／籌碼集中度…")
    concentration = build_concentration()
    print(f"  取得 {len(concentration)} 檔證券的籌碼集中度")

    merged = {}
    for code, info in foreign.items():
        merged[code] = dict(info)
    for code, info in concentration.items():
        if code in merged:
            merged[code].update(info)
        else:
            merged[code] = dict(info)

    output = {
        "generated_at": datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "stock_count": len(merged),
        "stocks": merged,
    }

    with open("stocks.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    print(f"stocks.json 已產生，共 {len(merged)} 檔股票")


if __name__ == "__main__":
    sys.exit(main())
