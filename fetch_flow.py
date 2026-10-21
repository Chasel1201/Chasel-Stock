"""
太空人 Chasel 盤後雷達 — 資料抓取腳本
=====================================
由 GitHub Actions 每個交易日盤後執行，輸出 flow/flow.json 給 flow/index.html 讀取。
只用免費公開資料：

  1. 上市個股日成交：證交所 OpenAPI  /v1/exchangeReport/STOCK_DAY_ALL
  2. 上櫃個股日成交：櫃買中心 OpenAPI /v1/tpex_mainboard_daily_close_quotes
  3. 上市公司基本資料（產業別、發行股數）：證交所 OpenAPI /v1/opendata/t187ap03_L
  4. 上櫃公司基本資料（產業別、發行股數）：櫃買中心 OpenAPI /v1/mopsfin_t187ap03_O

計算方式：
  - 周轉率 = 當日成交股數 ÷ 已發行普通股數 × 100
  - 產業漲跌幅 = 產業內個股依成交值加權的平均漲跌幅
  - 資金占比變化(pp) = 今日該產業成交值占全市場比重 − 前一交易日比重
    （前一日比重存在 flow/history.json，所以第一次執行時 pp 會是空的，第二個交易日起才有）
  - 細產業分組讀取 sub_industries.json（可自行編輯）
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))
OUT_DIR = "flow"
OUT_FILE = os.path.join(OUT_DIR, "flow.json")
HIST_FILE = os.path.join(OUT_DIR, "history.json")

# 強勢股條件
TURNOVER_MIN = 10.0     # 周轉率 %
VOLUME_MIN = 10000      # 張
CHANGE_MIN = 3.0        # 漲幅 %

TWSE_INDUSTRY = {
    "01": "水泥", "02": "食品", "03": "塑膠", "04": "紡織纖維", "05": "電機機械",
    "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙", "10": "鋼鐵", "11": "橡膠",
    "12": "汽車", "14": "建材營造", "15": "航運", "16": "觀光餐旅", "17": "金融保險",
    "18": "貿易百貨", "19": "綜合", "20": "其他", "21": "化學", "22": "生技醫療",
    "23": "油電燃氣", "24": "半導體", "25": "電腦週邊", "26": "光電", "27": "通信網路",
    "28": "電子零組件", "29": "電子通路", "30": "資訊服務", "31": "其他電子",
    "32": "文化創意", "33": "農業科技", "34": "電子商務", "35": "綠能環保",
    "36": "數位雲端", "37": "運動休閒", "38": "居家生活", "91": "存託憑證",
}


# ---------- 抓資料 ----------
def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8-sig", errors="replace"))


def pick(row, *keys):
    """欄位名稱容錯：依序嘗試多個可能的欄位名，找不到時用『包含關鍵字』比對。"""
    for k in keys:
        if k in row and str(row[k]).strip() != "":
            return row[k]
    for k in keys:
        for rk in row:
            if k in rk and str(row[rk]).strip() != "":
                return row[rk]
    return None


def num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").replace("X", "").strip()
    if s in ("", "--", "---", "----", "除權", "除息", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def industry_name(raw):
    if raw is None:
        return "其他"
    s = str(raw).strip()
    if s in TWSE_INDUSTRY:
        return TWSE_INDUSTRY[s]
    if s.zfill(2) in TWSE_INDUSTRY:
        return TWSE_INDUSTRY[s.zfill(2)]
    for suffix in ("工業", "業"):
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            s = s[: -len(suffix)]
    return s.replace("電腦及週邊設備", "電腦週邊").replace("其他電子", "其他電子") or "其他"


def load_companies():
    """回傳 {代號: {"ind": 產業名, "shares": 發行股數}}"""
    comp = {}
    sources = [
        ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "上市"),
        ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", "上櫃"),
    ]
    for url, mkt in sources:
        try:
            rows = fetch_json(url)
        except Exception as e:
            print(f"  [警告] {mkt}公司基本資料抓取失敗：{e}")
            continue
        n = 0
        for r in rows:
            code = pick(r, "公司代號", "SecuritiesCompanyCode", "CompanyCode", "Code")
            if not code:
                continue
            code = str(code).strip()
            shares = num(pick(r, "已發行普通股數或TDR原股發行股數", "IssueShares", "已發行普通股數", "發行股數"))
            ind = industry_name(pick(r, "產業別", "SecuritiesIndustryCode", "IndustryCode", "Industry"))
            comp[code] = {"ind": ind, "shares": shares}
            n += 1
        print(f"  {mkt}公司基本資料 {n} 筆")
    return comp


def load_quotes():
    """回傳 list of dict：code,name,mkt,close,chg,pct,vol(張),val(億),date"""
    out = []
    date_seen = None

    # 上市
    try:
        rows = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        for r in rows:
            code = str(pick(r, "Code", "證券代號") or "").strip()
            close = num(pick(r, "ClosingPrice", "收盤價"))
            chg = num(pick(r, "Change", "漲跌價差"))
            vol = num(pick(r, "TradeVolume", "成交股數"))
            val = num(pick(r, "TradeValue", "成交金額"))
            date_seen = date_seen or pick(r, "Date", "日期")
            if not code or close is None or vol is None:
                continue
            out.append(dict(code=code, name=str(pick(r, "Name", "證券名稱") or "").strip(), mkt="上市",
                            close=close, chg=chg or 0.0, vol_sh=vol, val=val or 0.0))
        print(f"  上市行情 {len(rows)} 筆")
    except Exception as e:
        print(f"  [警告] 上市行情抓取失敗：{e}")

    # 上櫃
    try:
        rows = fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
        for r in rows:
            code = str(pick(r, "SecuritiesCompanyCode", "代號", "Code") or "").strip()
            close = num(pick(r, "Close", "收盤"))
            chg = num(pick(r, "Change", "漲跌"))
            vol = num(pick(r, "TradingShares", "TradeVolume", "成交股數"))
            val = num(pick(r, "TransactionAmount", "TradeValue", "成交金額"))
            date_seen = date_seen or pick(r, "Date", "日期")
            if not code or close is None or vol is None:
                continue
            out.append(dict(code=code, name=str(pick(r, "CompanyName", "名稱", "Name") or "").strip(), mkt="上櫃",
                            close=close, chg=chg or 0.0, vol_sh=vol, val=val or 0.0))
        print(f"  上櫃行情 {len(rows)} 筆")
    except Exception as e:
        print(f"  [警告] 上櫃行情抓取失敗：{e}")

    return out, date_seen


def norm_date(raw):
    """支援民國 1151020 / 115/10/20 與西元 20261020，回傳 2026/10/20。"""
    if raw:
        s = str(raw).replace("/", "").replace("-", "").strip()
        try:
            if len(s) == 7:
                return f"{int(s[:3]) + 1911}/{s[3:5]}/{s[5:7]}"
            if len(s) == 8:
                return f"{s[:4]}/{s[4:6]}/{s[6:8]}"
        except ValueError:
            pass
    return datetime.now(TAIPEI_TZ).strftime("%Y/%m/%d")


# ---------- 計算 ----------
def main():
    print("抓取公司基本資料…")
    comp = load_companies()
    print("抓取盤後行情…")
    quotes, raw_date = load_quotes()
    data_date = norm_date(raw_date)

    # 只保留普通股（有公司基本資料者），排除 ETF、權證、債券
    stocks = []
    for q in quotes:
        c = comp.get(q["code"])
        if not c:
            continue
        prev = q["close"] - q["chg"]
        q["pct"] = round(q["chg"] / prev * 100, 2) if prev > 0 else 0.0
        q["vol"] = int(round(q["vol_sh"] / 1000))
        q["val_e"] = q["val"] / 1e8
        q["ind"] = c["ind"]
        q["turn"] = round(q["vol_sh"] / c["shares"] * 100, 2) if c.get("shares") else None
        stocks.append(q)
    print(f"  有效普通股 {len(stocks)} 檔，資料日期 {data_date}")
    if len(stocks) < 500:
        print("[錯誤] 有效個股太少，可能是資料源格式變動或尚未更新，這次不覆寫 flow.json")
        return 1

    total_val = sum(s["val_e"] for s in stocks) or 1.0

    # 大盤廣度
    def bucket(p):
        if p >= 9.5: return 0
        if p > 5: return 1
        if p > 2: return 2
        if p > 0: return 3
        if p == 0: return 4
        if p > -2: return 5
        if p > -5: return 6
        if p > -9.5: return 7
        return 8
    dist = [0] * 9
    for s in stocks:
        dist[bucket(s["pct"])] += 1
    up = sum(dist[:4]); dn = sum(dist[5:])

    # 歷史（前一交易日的資金占比）
    hist = {}
    if os.path.exists(HIST_FILE):
        try:
            with open(HIST_FILE, encoding="utf-8") as f:
                hist = json.load(f)
        except Exception:
            hist = {}
    prev_days = sorted(d for d in hist if d < data_date)
    prev = hist[prev_days[-1]] if prev_days else {}

    def agg(members):
        val = sum(m["val_e"] for m in members)
        if val <= 0:
            return None
        pct = sum(m["pct"] * m["val_e"] for m in members) / val
        return round(val, 2), round(pct, 2)

    # 大產業
    by_ind = {}
    for s in stocks:
        by_ind.setdefault(s["ind"], []).append(s)
    big, share_big = [], {}
    for ind, mem in by_ind.items():
        a = agg(mem)
        if not a or ind in ("存託憑證",):
            continue
        share = a[0] / total_val * 100
        share_big[ind] = round(share, 3)
        p = prev.get("big", {}).get(ind)
        upn = sum(1 for m in mem if m["pct"] > 0); dnn = sum(1 for m in mem if m["pct"] < 0)
        lead = max(mem, key=lambda m: (m["pct"], m["val_e"]))
        big.append(dict(n=ind, amt=a[0], chg=a[1], share=round(share, 2),
                        pp=round(share - p, 2) if p is not None else None,
                        up=upn, dn=dnn, fl=len(mem) - upn - dnn,
                        lead=f"{lead['code']} {lead['name']}", lead_pct=lead["pct"]))
    big.sort(key=lambda d: -d["amt"])

    # 細產業
    with open("sub_industries.json", encoding="utf-8") as f:
        cfg = json.load(f)
    idx = {s["code"]: s for s in stocks}
    sub, share_sub = [], {}
    for g in cfg["groups"]:
        mem = [idx[c] for c in g["codes"] if c in idx]
        a = agg(mem)
        if not a:
            continue
        share = a[0] / total_val * 100
        share_sub[g["name"]] = round(share, 3)
        p = prev.get("sub", {}).get(g["name"])
        sub.append(dict(n=g["name"], lane=g["lane"], amt=a[0], chg=a[1], share=round(share, 2),
                        pp=round(share - p, 2) if p is not None else None,
                        members=[f"{m['code']} {m['name']}" for m in mem]))

    # 強勢股
    def row(s):
        return dict(code=s["code"], name=s["name"], mkt=s["mkt"], ind=s["ind"], close=s["close"],
                    chg=s["chg"], pct=s["pct"], vol=s["vol"], val=round(s["val_e"], 2), turn=s["turn"])
    cand = [s for s in stocks if s["turn"] is not None and s["turn"] >= 5 and s["vol"] >= 3000]
    cand.sort(key=lambda s: -s["turn"])
    picks = [row(s) for s in cand[:80]]

    out = {
        "date": data_date,
        "generated_at": datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "criteria": {"turn": TURNOVER_MIN, "vol": VOLUME_MIN, "pct": CHANGE_MIN},
        "breadth": {"up": up, "down": dn, "flat": dist[4], "total": len(stocks), "dist": dist},
        "total_val": round(total_val, 2),
        "lanes": cfg["lanes"],
        "big": big,
        "sub": sub,
        "stocks": picks,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    hist[data_date] = {"big": share_big, "sub": share_sub}
    for d in sorted(hist)[:-30]:  # 只留最近 30 個交易日
        hist.pop(d)
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))

    n_pass = sum(1 for s in picks if s["turn"] >= TURNOVER_MIN and s["vol"] >= VOLUME_MIN and s["pct"] >= CHANGE_MIN)
    print(f"flow.json 已產生：大產業 {len(big)}、細產業 {len(sub)}、候選股 {len(picks)}、達標強勢股 {n_pass}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
