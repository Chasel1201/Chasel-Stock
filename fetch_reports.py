"""
太空人 Chasel 盤後短線報告 / 波段報告 — 產生腳本
==============================================
由 GitHub Actions 每個交易日盤後執行。只用證交所、櫃買中心的免費公開盤後資料。

流程：
  1. 抓當天上市＋上櫃個股日 K（開高低收量），併入 reports_data/ohlc.json（保留近 130 個交易日）
  2. 對每一檔普通股計算報告，輸出 flow/reports/<代號>.json
  3. 輸出 flow/reports/index.json（搜尋框用的清單）

補歷史（第一次使用或資料中斷時）：
  python fetch_reports.py --backfill 120     # 往回補約 120 個交易日

計算細節見程式碼。
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta

from fetch_flow import TAIPEI_TZ, fetch_json, load_companies, num, pick

HIST_FILE = os.path.join("reports_data", "ohlc.json")
OUT_DIR = os.path.join("flow", "reports")
KEEP_DAYS = 130


# ---------------------------------------------------------------- 資料
def to_ymd(raw):
    """民國 1151020 / 115/10/20 / 西元 20261020 / 2026-10-20 → '20261020'"""
    s = str(raw or "").replace("/", "").replace("-", "").strip()
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3]) + 1911}{s[3:]}"
    if len(s) == 8 and s.isdigit():
        return s
    return None


def bar(o, h, l, c, v_shares):
    o, h, l, c, v = num(o), num(h), num(l), num(c), num(v_shares)
    if None in (o, h, l, c) or c <= 0 or h <= 0 or l <= 0:
        return None
    return [o, h, l, c, int(round((v or 0) / 1000))]


def today_quotes():
    """回傳 {date: {code: (name, mkt, bar)}}"""
    out = {}
    rows = fetch_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
    for r in rows:
        code = str(pick(r, "Code", "證券代號") or "").strip()
        d = to_ymd(pick(r, "Date", "日期"))
        b = bar(pick(r, "OpeningPrice", "開盤價"), pick(r, "HighestPrice", "最高價"),
                pick(r, "LowestPrice", "最低價"), pick(r, "ClosingPrice", "收盤價"),
                pick(r, "TradeVolume", "成交股數"))
        if code and d and b:
            out.setdefault(d, {})[code] = (str(pick(r, "Name", "證券名稱") or "").strip(), "上市", b)
    print(f"  上市今日行情 {sum(len(v) for v in out.values())} 筆")
    try:
        rows = fetch_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes")
        n = 0
        for r in rows:
            code = str(pick(r, "SecuritiesCompanyCode", "代號", "Code") or "").strip()
            d = to_ymd(pick(r, "Date", "日期"))
            b = bar(pick(r, "Open", "開盤"), pick(r, "High", "最高"), pick(r, "Low", "最低"),
                    pick(r, "Close", "收盤"), pick(r, "TradingShares", "TradeVolume", "成交股數"))
            if code and d and b:
                out.setdefault(d, {})[code] = (str(pick(r, "CompanyName", "名稱", "Name") or "").strip(), "上櫃", b)
                n += 1
        print(f"  上櫃今日行情 {n} 筆")
    except Exception as e:
        print(f"  [警告] 上櫃今日行情失敗：{e}")

    # 備援：OpenAPI 常比較晚更新。若今天是交易日、已過 14:30，但 OpenAPI 還是舊資料，
    # 改從證交所／櫃買的每日收盤行情頁抓今天的資料（這兩個來源通常 15:00 前後就有）
    now = datetime.now(TAIPEI_TZ)
    today = now.strftime("%Y%m%d")
    if now.weekday() < 5 and now.hour * 60 + now.minute >= 14 * 60 + 30:
        have = out.get(today, {})
        if sum(1 for v in have.values() if v[1] == "上市") < 500:
            try:
                q = hist_twse(today)
                print(f"  [備援] 上市今日行情改用每日收盤行情頁：{len(q)} 筆")
                for code, val in q.items():
                    out.setdefault(today, {})[code] = val
            except Exception as e:
                print(f"  [備援] 上市每日收盤行情頁失敗：{e}")
        if sum(1 for v in out.get(today, {}).values() if v[1] == "上櫃") < 300:
            q = hist_tpex(today)
            print(f"  [備援] 上櫃今日行情改用每日收盤行情頁：{len(q)} 筆")
            for code, val in q.items():
                out.setdefault(today, {})[code] = val
    return out


def get_raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8-sig", errors="replace"))


def parse_table(fields, data, code_keys, name_keys, o_k, h_k, l_k, c_k, v_k, mkt, out):
    idx = {f.strip(): i for i, f in enumerate(fields)}

    def col(keys):
        for k in keys:
            for f, i in idx.items():
                if f == k or k in f:
                    return i
        return None
    ci, ni, oi, hi, li, cl, vi = (col(code_keys), col(name_keys), col(o_k), col(h_k), col(l_k), col(c_k), col(v_k))
    if None in (ci, oi, hi, li, cl, vi):
        return 0
    n = 0
    for row in data:
        b = bar(row[oi], row[hi], row[li], row[cl], row[vi])
        code = str(row[ci]).strip()
        if b and code:
            out[code] = (str(row[ni]).strip() if ni is not None else "", mkt, b)
            n += 1
    return n


def hist_twse(ymd):
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json"
    j = get_raw(url)
    out = {}
    tables = j.get("tables") or []
    for k in j:  # 舊格式 fields9 / data9
        if k.startswith("fields") and ("data" + k[6:]) in j:
            tables.append({"fields": j[k], "data": j["data" + k[6:]]})
    for t in tables:
        f = t.get("fields") or []
        if any("證券代號" in x for x in f) and any("收盤價" in x for x in f):
            parse_table(f, t.get("data") or [], ["證券代號"], ["證券名稱"], ["開盤價"], ["最高價"],
                        ["最低價"], ["收盤價"], ["成交股數"], "上市", out)
    return out


def hist_tpex(ymd):
    y, m, d = ymd[:4], ymd[4:6], ymd[6:]
    out = {}
    urls = [
        f"https://www.tpex.org.tw/www/zh-tw/afterTrading/otc?date={y}%2F{m}%2F{d}&type=EW&response=json",
        f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&d={int(y) - 1911}/{m}/{d}&se=EW&o=json",
    ]
    for url in urls:
        try:
            j = get_raw(url)
        except Exception as e:
            print(f"    櫃買 {ymd} 來源失敗：{e}")
            continue
        tables = j.get("tables") or []
        if j.get("aaData"):
            tables.append({"fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數"],
                           "data": j["aaData"]})
        for t in tables:
            f = t.get("fields") or []
            parse_table(f, t.get("data") or [], ["代號"], ["名稱"], ["開盤"], ["最高"], ["最低"],
                        ["收盤"], ["成交股數"], "上櫃", out)
        if out:
            break
    return out


def load_hist():
    if os.path.exists(HIST_FILE):
        with open(HIST_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"stocks": {}}


def merge(hist, ymd, quotes):
    st = hist["stocks"]
    for code, (name, mkt, b) in quotes.items():
        s = st.setdefault(code, {"n": name, "m": mkt, "r": []})
        if name:
            s["n"] = name
        s["m"] = mkt
        rows = [r for r in s["r"] if r[0] != ymd]
        rows.append([ymd] + b)
        rows.sort(key=lambda r: r[0])
        s["r"] = rows


def trim(hist):
    dates = sorted({r[0] for s in hist["stocks"].values() for r in s["r"]})
    keep = set(dates[-KEEP_DAYS:])
    for code in list(hist["stocks"]):
        s = hist["stocks"][code]
        s["r"] = [r for r in s["r"] if r[0] in keep]
        if not s["r"]:
            del hist["stocks"][code]
    return dates[-1] if dates else None


def save_hist(hist):
    os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
    with open(HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))


def backfill(hist, days):
    have = {r[0] for s in hist["stocks"].values() for r in s["r"]}
    d = datetime.now(TAIPEI_TZ).date()
    got, tried = 0, 0
    while got < days and tried < int(days * 1.6) + 10:
        d -= timedelta(days=1)
        tried += 1
        if d.weekday() >= 5:
            continue
        ymd = d.strftime("%Y%m%d")
        if ymd in have:
            got += 1
            continue
        try:
            q = hist_twse(ymd)
        except Exception as e:
            print(f"  {ymd} 上市失敗：{e}")
            q = {}
        time.sleep(3.5)
        if not q:
            print(f"  {ymd} 無上市資料（休市）")
            continue
        o = hist_tpex(ymd)
        time.sleep(2.5)
        q.update(o)
        merge(hist, ymd, q)
        got += 1
        print(f"  {ymd} 補入 上市 {len(q) - len(o)}、上櫃 {len(o)}")


# ---------------------------------------------------------------- 計算
def tick(p):
    if p < 10: return 0.01
    if p < 50: return 0.05
    if p < 100: return 0.1
    if p < 500: return 0.5
    if p < 1000: return 1.0
    return 5.0


def rt(x):
    """依台股升降單位四捨五入"""
    t = tick(x)
    v = round(round(x / t) * t, 2)
    return int(v) if v == int(v) else v


def ma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None


def kd(h, l, c, n=9):
    k = d = 50.0
    for i in range(len(c)):
        hh, ll = max(h[max(0, i - n + 1):i + 1]), min(l[max(0, i - n + 1):i + 1])
        rsv = (c[i] - ll) / (hh - ll) * 100 if hh > ll else 50.0
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
    return k, d


def band(h, l, c, i):
    if i < 2:
        return None
    m = (h[i] + l[i] + h[i - 1] + l[i - 1] + 2 * c[i - 1] + h[i - 2] + l[i - 2]) / 8
    w = ((h[i] - l[i]) + 2 * (h[i - 1] - l[i - 1]) + (h[i - 2] - l[i - 2])) / 8
    return m - w, m + w


def state(cl, b):
    if b is None: return "—"
    if cl > b[1]: return "盤堅"
    if cl < b[0]: return "盤跌"
    return "盤整"


ARROW = {"盤堅": "▲", "盤跌": "▼", "盤整": "─", "—": ""}


def weekly(rows):
    wk = {}
    for r in rows:
        dt = datetime.strptime(r[0], "%Y%m%d").date()
        key = dt.isocalendar()[:2]
        w = wk.setdefault(key, [r[1], r[2], r[3], r[4]])
        w[1], w[2], w[3] = max(w[1], r[2]), min(w[2], r[3]), r[4]
    return [wk[k] for k in sorted(wk)]


def report(code, s):
    rows = s["r"]
    if len(rows) < 3:
        return None
    o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]
    c = [r[4] for r in rows]; v = [r[5] for r in rows]
    i = len(rows) - 1
    C, H, L = c[i], h[i], l[i]
    prev = c[i - 1]
    chg = C - prev
    pct = chg / prev * 100 if prev else 0.0

    # 支撐壓力
    P = (H + L + C) / 3
    R1, S1 = 2 * P - L, 2 * P - H

    # 盤堅盤跌
    b, pb = band(h, l, c, i), band(h, l, c, i - 1)
    st, pst = state(C, b), state(c[i - 1], pb)

    # 短線箱（10 日）
    n10 = min(10, len(rows))
    hi10, lo10 = max(h[-n10:]), min(l[-n10:])
    bh10 = hi10 - lo10
    box = [lo10 - 0.382 * bh10, lo10, hi10, hi10 + 0.382 * bh10]
    pos10 = (C - lo10) / bh10 if bh10 > 0 else 0.5

    # 量
    pv = v[-6:-1]
    vol5 = sum(pv) / len(pv) if pv else 0
    vr = v[i] / vol5 if vol5 else None

    # 均線、KD
    m5, m12, m30, m20, m60 = ma(c, 5), ma(c, 12), ma(c, 30), ma(c, 20), ma(c, 60)
    K, D = kd(h, l, c)
    pK, pD = kd(h[:-1], l[:-1], c[:-1]) if len(c) > 1 else (K, D)

    # 多方強度
    if H > L:
        daypos = (C - L) / (H - L)
    else:
        daypos = 1.0 if chg > 0 else 0.0 if chg < 0 else 0.5
    checks = []
    if m5: checks.append(C > m5)
    if m5 and m12: checks.append(m5 > m12)
    if m12 and m30: checks.append(m12 > m30)
    align = sum(checks) / len(checks) if checks else 0.5
    strength = (K / 100 + daypos + pos10 + align) / 4 * 100

    # 資金動能
    last = list(range(max(1, i - 4), i + 1))
    tot = sum(v[j] for j in last)
    upv = sum(v[j] for j in last if c[j] > c[j - 1])
    money = upv / tot * 100 if tot else 0.0

    # ---------- 短線文字 ----------
    f = rt
    rev = []
    if st == "盤堅":
        lead = f"由{pst}轉為盤堅，" if pst in ("盤整", "盤跌") else ""
        rev.append(f"{lead}收盤 {f(C)} 站上盤堅 {f(b[1])}，屬盤堅格局。")
        rev.append(f"未來兩個交易日若有一日收盤站上續強點 {f(R1)}，強勢可望延續；若未站上，可能先回到盤整。")
    elif st == "盤跌":
        lead = f"由{pst}轉為盤跌，" if pst in ("盤整", "盤堅") else ""
        rev.append(f"{lead}收盤 {f(C)} 跌破盤跌 {f(b[0])}，屬盤跌格局。")
        rev.append(f"未來兩個交易日若收盤回到 {f(b[0])} 之上，跌勢可望止穩；若未回到，留意續弱。")
    elif b:
        rev.append(f"收盤 {f(C)} 位於盤跌盤堅區間 [{f(b[0])} – {f(b[1])}] 內，屬盤整。")
        rev.append(f"向上站穩 {f(b[1])} 轉為盤堅，跌破 {f(b[0])} 轉為盤跌。")

    tech = []
    if C >= hi10 and bh10 > 0:
        tech.append(f"收盤位於近 10 日高點區，突破箱頂 {f(hi10)} 後若能守穩三日，下一觀察位 {f(box[3])}。")
    elif pos10 >= 0.7:
        tech.append(f"股價位於股票箱上半部（箱內位置 {pos10 * 100:.0f}%），須有效突破箱頂 {f(hi10)} 並守穩三日，才有機會挑戰上延 {f(box[3])}。")
    elif pos10 <= 0.3:
        tech.append(f"股價位於股票箱下半部（箱內位置 {pos10 * 100:.0f}%），留意箱底 {f(lo10)} 是否守住，跌破則下一觀察位 {f(box[0])}。")
    else:
        tech.append(f"股價位於股票箱中段（箱內位置 {pos10 * 100:.0f}%），箱頂 {f(hi10)}、箱底 {f(lo10)} 為上下觀察位。")
    if vr is not None:
        if chg > 0 and vr < 0.7:
            tech.append(f"今日上漲但量縮（量比 {vr:.2f}），隔日需觀察能否帶量延續。")
        elif chg > 0 and vr >= 1.5:
            tech.append(f"今日帶量上漲（量比 {vr:.2f}），買盤積極。")
        elif chg < 0 and vr >= 1.5:
            tech.append(f"今日帶量下跌（量比 {vr:.2f}），賣壓較重。")
        elif chg < 0 and vr < 0.7:
            tech.append(f"今日量縮回檔（量比 {vr:.2f}），賣壓有限。")
    tech.append(f"隔日收盤若跌破支撐 {f(S1)}，短線轉弱；站上壓力 {f(R1)}，延續強勢。")
    if pK <= pD and K > D:
        tech.append(f"KD 黃金交叉（K {K:.1f} / D {D:.1f}）。")
    elif pK >= pD and K < D:
        tech.append(f"KD 死亡交叉（K {K:.1f} / D {D:.1f}）。")
    if K >= 80:
        tech.append("K 值位於 80 以上高檔區，留意短線過熱。")
    elif K <= 20:
        tech.append("K 值位於 20 以下低檔區，留意短線超跌。")

    # ---------- 波段（20 日） ----------
    n20 = min(20, len(rows))
    hi20, lo20 = max(h[-n20:]), min(l[-n20:])
    bh20 = hi20 - lo20
    pos20 = (C - lo20) / bh20 if bh20 > 0 else 0.5
    target = hi20 + bh20
    m20p = sum(c[-25:-5]) / 20 if len(c) >= 25 else None
    slope = (m20 - m20p) if (m20 and m20p) else None
    if m20 and m5 and slope is not None:
        if C > m5 > m20 and slope > 0: trend = "強"
        elif C > m20 and slope > 0: trend = "偏強"
        elif C < m5 < m20 and slope < 0: trend = "弱"
        elif C < m20 and slope < 0: trend = "偏弱"
        else: trend = "整理"
    else:
        trend = "資料不足"
    wk = weekly(rows)
    wb = None
    if len(wk) >= 3:
        wh = [x[1] for x in wk]; wl = [x[2] for x in wk]; wc = [x[3] for x in wk]
        wb = band(wh, wl, wc, len(wk) - 1)
    wst = state(C, wb)
    ret20 = (C / c[-n20] - 1) * 100 if c[-n20] else 0

    # 波段績效：收盤由下往上站上盤堅後 10 日報酬
    rets = []
    for j in range(3, len(c) - 10):
        bj, bjp = band(h, l, c, j), band(h, l, c, j - 1)
        if bj and bjp and c[j] > bj[1] and c[j - 1] <= bjp[1]:
            rets.append((c[j + 10] / c[j] - 1) * 100)
    perf = {"n": len(rets), "avg": round(sum(rets) / len(rets), 2) if rets else None,
            "win": round(sum(1 for x in rets if x > 0) / len(rets) * 100, 1) if rets else None}

    sw = []
    sw.append(f"近 {n20} 日區間 [{f(lo20)} – {f(hi20)}]，目前位於 {pos20 * 100:.0f}% 位置，近 {n20} 日漲跌 {ret20:+.2f}%。")
    if trend != "資料不足":
        sw.append(f"中期趨勢{('屬' if trend in ('強', '弱') else '')}{trend}：收盤 {f(C)}、MA5 {m5:.2f}、MA20 {m20:.2f}，MA20 {'上彎' if slope > 0 else '下彎' if slope < 0 else '走平'}。")
    if C >= hi20:
        sw.append(f"收盤創近 {n20} 日新高，若續強，等幅目標 {f(target)}；波段防守參考 MA20 {f(m20) if m20 else '—'}。")
    else:
        sw.append(f"向上須突破 {n20} 日高點 {f(hi20)}，突破後等幅目標 {f(target)}；跌破 {f(lo20)} 則波段轉弱。")
    if wb:
        sw.append(f"週線盤跌盤堅 [{f(wb[0])} – {f(wb[1])}]，目前屬週線{wst}。")
    if perf["n"] >= 3:
        sw.append(f"過去約 {len(rows)} 個交易日中，同類轉強訊號出現 {perf['n']} 次，之後平均報酬 {perf['avg']:+.2f}%，上漲機率 {perf['win']:.0f}%。")
    else:
        sw.append("歷史轉強訊號次數不足，波段績效暫不統計。")

    r2 = lambda x: round(x, 2) if x is not None else None
    return {
        "code": code, "name": s["n"], "mkt": s["m"], "date": rows[i][0],
        "o": o[i], "h": H, "l": L, "c": C, "chg": r2(chg), "pct": r2(pct),
        "vol": v[i], "vol5": int(round(vol5)), "vr": r2(vr),
        "short": {
            "pivot": [f(S1), f(P), f(R1)], "key": f(R1),
            "band": [f(b[0]), f(b[1])] if b else None, "state": st, "arrow": ARROW[st],
            "pband": [f(pb[0]), f(pb[1])] if pb else None, "pstate": pst,
            "box": [f(x) for x in box],
            "strength": round(strength, 2), "money": round(money, 2),
            "ma": [r2(m5), r2(m12), r2(m30)], "kd": [round(K, 2), round(D, 2)],
            "rev": rev, "tech": tech,
        },
        "swing": {
            "n": n20, "box": [f(lo20), f(hi20)], "pos": round(pos20 * 100, 1), "target": f(target),
            "guard": f(m20) if m20 else None, "trend": trend, "ret": round(ret20, 2),
            "wband": [f(wb[0]), f(wb[1])] if wb else None, "wstate": wst,
            "perf": perf, "ma": [r2(m5), r2(m20), r2(m60)], "text": sw,
        },
        "days": len(rows),
    }


def write_reports(hist, comp):
    os.makedirs(OUT_DIR, exist_ok=True)
    index, n = [], 0
    for code, s in hist["stocks"].items():
        if code not in comp:  # 只做普通股
            continue
        try:
            rep = report(code, s)
        except Exception as e:
            print(f"  [警告] {code} 計算失敗：{e}")
            continue
        if not rep:
            continue
        with open(os.path.join(OUT_DIR, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, separators=(",", ":"))
        index.append([code, s["n"], s["m"]])
        n += 1
    index.sort()
    latest = max((s["r"][-1][0] for s in hist["stocks"].values() if s["r"]), default="")
    mdates = {}
    for code, s in hist["stocks"].items():
        if code in comp and s["r"]:
            mdates[s["m"]] = max(mdates.get(s["m"], ""), s["r"][-1][0])
    with open(os.path.join(OUT_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"date": latest, "dates": mdates, "generated_at": datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                   "stocks": index}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"報告已產生 {n} 檔，最新資料日 {latest}")
    return n


def main():
    args = sys.argv[1:]
    hist = load_hist()
    if "--backfill" in args:
        days = int(args[args.index("--backfill") + 1]) if len(args) > args.index("--backfill") + 1 else 120
        print(f"補歷史資料 {days} 個交易日…")
        backfill(hist, days)
    if "--no-today" not in args:
        print("抓取今日盤後行情…")
        try:
            for d, q in today_quotes().items():
                merge(hist, d, q)
        except Exception as e:
            print(f"[警告] 今日行情抓取失敗：{e}")
    latest = trim(hist)
    if not latest:
        print("[錯誤] 沒有任何歷史資料")
        return 1
    save_hist(hist)
    print("抓取公司基本資料…")
    comp = load_companies()
    if len(comp) < 500:
        print("[錯誤] 公司基本資料不足，這次不更新報告")
        return 1
    return 0 if write_reports(hist, comp) > 500 else 1


if __name__ == "__main__":
    sys.exit(main())
