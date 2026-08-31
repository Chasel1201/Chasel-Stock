"""
台指選擇權籌碼動向 — GitHub Actions 資料抓取腳本
====================================================
由 GitHub Actions（排程機器人）執行，不是在使用者瀏覽器裡執行，
所以不受瀏覽器 CORS 限制——這點跟 Google Apps Script 版本原理相同。

執行後會在專案根目錄產生 data.json，GitHub Pages 的網頁
（index.html）會讀取這份「同一個網站裡的」json 檔案，
瀏覽器讀取同網站的檔案不受跨網域限制，這才是資料能顯示出來的關鍵。

欄位名稱已於對話中用真實回傳資料核對過（2026/08/28 實測），
包含修正後的正確欄位：
- ContractCode 是中文全名「臺指選擇權」，不是代碼"TXO"
- CallPut 在三大法人資料集裡是英文"CALL"/"PUT"（大寫）
- CallPut 在大額交易人資料集裡是中文"買權"/"賣權"
兩個資料集欄位命名習慣不同，程式裡分開處理。
"""

import json
import sys
from datetime import datetime, timezone, timedelta
import urllib.request

BASE = "https://openapi.taifex.com.tw/v1"
TAIPEI_TZ = timezone(timedelta(hours=8))


def fetch_json(path):
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_rows(rows, date_key="Date"):
    if not rows:
        return None, []
    dates = sorted({r.get(date_key) for r in rows if r.get(date_key)})
    if not dates:
        return None, rows
    latest = dates[-1]
    return latest, [r for r in rows if r.get(date_key) == latest]


def to_num(x, default=0.0):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return default


def build_put_call_ratio():
    rows = fetch_json("PutCallRatio")
    latest, today_rows = latest_rows(rows)
    if not today_rows:
        return {"status": "error", "message": "無資料"}
    r = today_rows[0]
    oi_ratio = to_num(r.get("PutCallOIRatio%"))
    vol_ratio = to_num(r.get("PutCallVolumeRatio%"))
    if oi_ratio >= 110:
        bias = "bearish"
        note = "偏悲觀（賣權未平倉相對偏多）"
    elif oi_ratio <= 70:
        bias = "bullish"
        note = "偏樂觀（買權未平倉相對偏多）"
    else:
        bias = "neutral"
        note = "中性，無明顯籌碼傾向"
    return {
        "status": "ok",
        "date": latest,
        "oi_ratio": oi_ratio,
        "vol_ratio": vol_ratio,
        "bias": bias,
        "note": note,
    }


def build_institutional():
    rows = fetch_json("MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate")
    latest, today_rows = latest_rows(rows)
    if not today_rows:
        return {"status": "error", "message": "無資料"}

    call_net, put_net = 0.0, 0.0
    for r in today_rows:
        code = str(r.get("ContractCode", ""))
        if "臺指選擇權" not in code:
            continue
        net = r.get("OpenInterest(Net)")
        if net is None:
            net = to_num(r.get("OpenInterest(Long)")) - to_num(r.get("OpenInterest(Short)"))
        else:
            net = to_num(net)
        cp = str(r.get("CallPut", "")).upper()
        if cp == "CALL":
            call_net += net
        elif cp == "PUT":
            put_net += net

    if call_net > 0 and put_net < 0:
        bias = "bullish"
        note = "三大法人籌碼偏多方"
    elif call_net < 0 and put_net > 0:
        bias = "bearish"
        note = "三大法人籌碼偏空方"
    else:
        bias = "neutral"
        note = "三大法人籌碼方向不明確"

    return {
        "status": "ok",
        "date": latest,
        "call_net": call_net,
        "put_net": put_net,
        "bias": bias,
        "note": note,
    }


def build_large_traders():
    rows = fetch_json("OpenInterestOfLargeTradersOptions")
    latest, today_rows = latest_rows(rows)
    if not today_rows:
        return {"status": "error", "message": "無資料"}

    call_buy = call_sell = put_buy = put_sell = 0.0
    for r in today_rows:
        name = str(r.get("ContractName", "")) + str(r.get("Contract", ""))
        if "臺指" not in name and "TXO" not in name:
            continue
        cp = str(r.get("CallPut", ""))
        b10 = to_num(r.get("Top10Buy"))
        s10 = to_num(r.get("Top10Sell"))
        if "買" in cp:
            call_buy += b10
            call_sell += s10
        elif "賣" in cp:
            put_buy += b10
            put_sell += s10

    call_skew = call_buy - call_sell
    put_skew = put_buy - put_sell

    if call_skew > 0 and put_skew < 0:
        bias = "bullish"
        note = "十大交易人籌碼偏多"
    elif call_skew < 0 and put_skew > 0:
        bias = "bearish"
        note = "十大交易人籌碼偏空"
    else:
        bias = "neutral"
        note = "十大交易人籌碼方向不明確"

    return {
        "status": "ok",
        "date": latest,
        "call_skew": call_skew,
        "put_skew": put_skew,
        "bias": bias,
        "note": note,
        "coverage_note": "此數字加總臺指選擇權所有到期別（週選+月選），非單獨本週選",
    }


def weekly_contract_hint():
    now = datetime.now(TAIPEI_TZ)
    wd = now.weekday()  # Monday=0 ... Sunday=6
    if wd in (0, 1):
        return "本週週三選即將到期，適合作為主力收租/調節部位"
    if wd == 2:
        return "今日為週三選結算日，收盤後可轉往下週週三選，留意今晚夜盤是否需加開週五選"
    if wd == 3:
        return "今晚為全週夜盤成交量最高時段，建議優先評估週五選因應"
    if wd == 4:
        return "今日為週五選結算日，盤中以了結/調整既有部位為主"
    return "假日無交易，可利用此時間覆核下週建倉規劃"


def main():
    result = {
        "generated_at": datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "weekly_hint": weekly_contract_hint(),
    }

    try:
        result["put_call_ratio"] = build_put_call_ratio()
    except Exception as e:
        result["put_call_ratio"] = {"status": "error", "message": str(e)}

    try:
        result["institutional"] = build_institutional()
    except Exception as e:
        result["institutional"] = {"status": "error", "message": str(e)}

    try:
        result["large_traders"] = build_large_traders()
    except Exception as e:
        result["large_traders"] = {"status": "error", "message": str(e)}

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("data.json 已產生：")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
