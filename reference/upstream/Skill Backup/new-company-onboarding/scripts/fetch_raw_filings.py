#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_raw_filings.py v1.0 — 新公司入库时预取定期报告原始文件到 {公司目录}/{TICKER} Wiki/raw/

用法:
    python fetch_raw_filings.py {TICKER} --out "{公司目录}/{TICKER} Wiki/raw" [--years 2] [--probe]

按 ticker 后缀路由市场：
    .SZ / .SH / .BJ  → A 股：东方财富公告接口（主）/ 深交所接口（.SZ 备）→ 年报 + 半年报
    .HK              → 港股：披露易 titleSearch → 年报 + 中期报告
    其他（裸代码）    → 美股：SEC EDGAR submissions → 10-K + 10-Q

只用标准库，Windows / Linux / 云端容器都能跑。
**巨潮 www.cninfo.com.cn 在多数受控网络里不可达，本脚本不依赖它。**

产出：
    raw/{EASTMONEY|SZSE|HKEX|SEC}/  下载到的文件
    raw/MANIFEST.md                 清单 + 失败项 + 需人工补充项

失败不中断：任何单个文件失败都记进 MANIFEST 的「自动预取失败项」，退出码仍为 0。
只有「一个渠道都没通」才返回退出码 1。
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse
from datetime import datetime

SCRIPT_VERSION = "1.0"
SEC_UA = "flyfish-research dbao0108@gmail.com"   # SEC 要求 User-Agent 带联系方式
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
TIMEOUT = 45


# ---------------------------------------------------------------- http

def _get(url, headers=None, timeout=TIMEOUT, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                      # noqa: BLE001
            last = e
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise last


def _post_json(url, payload, headers=None, timeout=TIMEOUT):
    h = {"User-Agent": BROWSER_UA, "Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _safe(name):
    """文件名去掉 Windows 非法字符。"""
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip()[:120]


# ---------------------------------------------------------------- A 股

# 只要正文定期报告，排除摘要 / 英文版 / 更正后重发以外的噪音
_A_YEAR = re.compile(r"(\d{4})\s*年年度报告$")
_A_HALF = re.compile(r"(\d{4})\s*年半年度报告$")
_A_Q1 = re.compile(r"(\d{4})\s*年第一季度报告$")
_A_Q3 = re.compile(r"(\d{4})\s*年第三季度报告$")


def _a_classify(title):
    t = re.sub(r"^[^:：]{2,12}[:：]", "", title).strip()      # 去掉 "阳光电源:" 前缀
    t = t.replace("（", "(").replace("）", ")")
    if "摘要" in t or "英文" in t or "English" in t:
        return None, None
    for pat, kind in ((_A_YEAR, "年报"), (_A_HALF, "半年报"), (_A_Q1, "一季报"), (_A_Q3, "三季报")):
        m = pat.match(t)
        if m:
            return kind, m.group(1)
    return None, None


def list_a_eastmoney(code6, pages=3):
    """东方财富定期报告列表。f_node=1 = 财务报告。"""
    out = []
    for pg in range(1, pages + 1):
        u = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
             "?sr=-1&page_size=50&page_index=%d&ann_type=A&client_source=web"
             "&stock_list=%s&f_node=1&s_node=0" % (pg, code6))
        j = json.loads(_get(u, {"User-Agent": BROWSER_UA,
                                "Referer": "https://data.eastmoney.com/notices/"}).decode("utf-8", "ignore"))
        lst = ((j.get("data") or {}).get("list")) or []
        if not lst:
            break
        for a in lst:
            kind, period = _a_classify(a.get("title") or "")
            if not kind:
                continue
            out.append({"title": a.get("title"), "date": (a.get("notice_date") or "")[:10],
                        "kind": kind, "period": period, "art_code": a.get("art_code")})
    return out


def resolve_eastmoney_pdf(art_code):
    u = ("https://np-cnotice-stock.eastmoney.com/api/content/ann?art_code=%s"
         "&client_source=web&page_index=1" % art_code)
    j = json.loads(_get(u, {"User-Agent": BROWSER_UA,
                            "Referer": "https://data.eastmoney.com/notices/"}).decode("utf-8", "ignore"))
    d = j.get("data") or {}
    return d.get("attach_url") or d.get("attach_url_web")


def list_a_szse(code6, pages=2):
    """深交所定期报告（仅 .SZ）。bigCategoryId 010301 = 定期报告。"""
    out = []
    for pg in range(1, pages + 1):
        j = _post_json("https://www.szse.cn/api/disc/announcement/annList?random=0.1",
                       {"seDate": ["", ""], "stock": [code6], "channelCode": ["fixed_disc"],
                        "bigCategoryId": ["010301"], "pageSize": 30, "pageNum": pg},
                       {"Referer": "https://www.szse.cn/disclosure/listed/fixed/index.html",
                        "X-Request-Type": "ajax"})
        rows = j.get("data") or []
        if not rows:
            break
        for a in rows:
            kind, period = _a_classify(a.get("title") or "")
            if not kind:
                continue
            out.append({"title": a.get("title"), "date": (a.get("publishTime") or "")[:10],
                        "kind": kind, "period": period,
                        "url": "https://disc.static.szse.cn/download" + (a.get("attachPath") or "")})
    return out


# ---------------------------------------------------------------- 港股

def _hk_stock_id(code4):
    t = _get("https://www1.hkexnews.hk/search/prefix.do?callback=c&lang=ZH&type=A&name=%s&market=SEHK" % code4
             ).decode("utf-8", "ignore")
    m = re.search(r"\{.*\}", t, re.S)
    info = (json.loads(m.group(0)).get("stockInfo") or []) if m else []
    return info[0]["stockId"] if info else None


def _hk_date(s):
    """披露易给的是 DD/MM/YYYY HH:MM，统一成 YYYY-MM-DD。"""
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else (s or "")[:10]


def list_hk(code4, years):
    sid = _hk_stock_id(code4)
    if not sid:
        raise RuntimeError("披露易查不到 stockId：%s" % code4)
    to = datetime.now().strftime("%Y%m%d")
    frm = "%d0101" % (datetime.now().year - years - 1)
    out = []
    for t1, kind in (("40000", "年报"), ("40100", "中期报告")):
        u = ("https://www1.hkexnews.hk/search/titleSearchServlet.do?sortDir=0&sortByOptions=DateTime"
             "&category=0&market=SEHK&stockId=%s&documentType=-1&fromDate=%s&toDate=%s"
             "&title=&searchType=0&t1code=%s&t2Gcode=-2&t2code=-2&rowRange=100&lang=ZH"
             % (sid, frm, to, t1))
        j = json.loads(_get(u).decode("utf-8", "ignore"))
        res = j.get("result")
        rows = json.loads(res) if isinstance(res, str) and res not in ("null", "") else (res or [])
        for a in rows:
            d = _hk_date(a.get("DATE_TIME") or "")
            out.append({"title": a.get("TITLE") or a.get("NEWS_TITLE"),
                        "date": d, "kind": kind, "period": d[:4],
                        "url": "https://www1.hkexnews.hk" + (a.get("FILE_LINK") or "")})
    return out


# ---------------------------------------------------------------- 美股

def list_us(ticker, years):
    tk = json.loads(_get("https://www.sec.gov/files/company_tickers.json", {"User-Agent": SEC_UA}))
    cik = None
    for v in tk.values():
        if (v.get("ticker") or "").upper() == ticker.upper():
            cik = int(v["cik_str"]); break
    if cik is None:
        raise RuntimeError("EDGAR 查不到 CIK：%s" % ticker)
    sub = json.loads(_get("https://data.sec.gov/submissions/CIK%010d.json" % cik, {"User-Agent": SEC_UA}))
    rec = sub["filings"]["recent"]
    want = {"10-K": "年报", "20-F": "年报", "40-F": "年报", "10-Q": "季报"}
    out = []
    for i in range(len(rec["form"])):
        f = rec["form"][i]
        if f not in want:
            continue
        acc = rec["accessionNumber"][i].replace("-", "")
        doc = rec["primaryDocument"][i]
        if not doc:
            continue
        out.append({"title": "%s %s" % (f, rec["reportDate"][i]), "date": rec["filingDate"][i],
                    "kind": want[f], "period": (rec["reportDate"][i] or "")[:4],
                    "url": "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (cik, acc, doc),
                    "form": f})
    return out, cik


# ---------------------------------------------------------------- 主流程

def pick(items, years, quarterly=False):
    """每类各取最近 N 份，按日期倒序。A 股季报默认不取（信息密度低、体量大）。"""
    quota = {"年报": years, "半年报": years, "中期报告": years, "季报": years * 2}
    if quarterly:
        quota.update({"一季报": years, "三季报": years})
    seen, out = {}, []
    for it in sorted(items, key=lambda x: x.get("date") or "", reverse=True):
        k = it["kind"]
        if seen.get(k, 0) >= quota.get(k, 0):
            continue
        seen[k] = seen.get(k, 0) + 1
        out.append(it)
    return out


def download(items, outdir, headers, failures):
    os.makedirs(outdir, exist_ok=True)
    done = []
    for it in items:
        url = it.get("url")
        if not url:
            failures.append("%s —— 拿不到下载直链" % it["title"]); continue
        ext = ".pdf" if ".pdf" in url.lower() else (".htm" if ".htm" in url.lower() else ".bin")
        fn = _safe("%s_%s_%s" % (it["kind"], it.get("period") or it["date"], it["date"])) + ext
        path = os.path.join(outdir, fn)
        if os.path.exists(path) and os.path.getsize(path) > 20000:
            it["file"] = fn; it["skipped"] = True; done.append(it); continue
        try:
            blob = _get(url, headers, timeout=120)
            if len(blob) < 5000:
                raise RuntimeError("响应只有 %d 字节，多半是反爬拦截页而不是正文" % len(blob))
            with open(path, "wb") as fh:
                fh.write(blob)
            it["file"] = fn; it["bytes"] = len(blob); done.append(it)
        except Exception as e:                      # noqa: BLE001
            failures.append("%s —— %s: %s" % (it["title"], type(e).__name__, str(e)[:120]))
        time.sleep(0.4)
    return done


MANIFEST_TAIL = """
## 未能自动获取（需人工补充）

- Earnings call transcript / 业绩说明会记录：公司 IR 页面、交易所互动易、SeekingAlpha
- 管理层路演、专访、深度访谈
- 分析师日 / Investor Day 材料
- 券商深度报告（如需）
"""


def write_manifest(raw_dir, ticker, market, channel, got, failures):
    lines = ["# %s 原始材料清单" % ticker, "",
             "预取时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
             "市场：%s　　渠道：%s　　脚本：fetch_raw_filings.py v%s" % (market, channel, SCRIPT_VERSION), "",
             "| 文件 | 类型 | 报告期 | 披露日 | 来源 URL |", "|---|---|---|---|---|"]
    for it in got:
        lines.append("| %s/%s | %s | %s | %s | %s |"
                     % (channel, it.get("file", "—"), it["kind"], it.get("period") or "—",
                        it.get("date") or "—", it.get("url") or "—"))
    if not got:
        lines.append("| （无） | | | | |")
    lines.append("")
    lines.append("## 自动预取失败项")
    lines.append("")
    if failures:
        lines += ["- %s" % f for f in failures]
    else:
        lines.append("（无）")
    lines.append(MANIFEST_TAIL)
    p = os.path.join(raw_dir, "MANIFEST.md")
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--out", required=True, help="公司的 raw 目录，如 '.../{TICKER} Wiki/raw'")
    ap.add_argument("--years", type=int, default=2, help="每类报告各取几份，默认 2")
    ap.add_argument("--quarterly", action="store_true", help="A 股同时取一季报/三季报（默认只取年报+半年报）")
    ap.add_argument("--probe", action="store_true", help="只列清单不下载")
    a = ap.parse_args()

    t = a.ticker.strip().upper()
    raw = a.out
    os.makedirs(raw, exist_ok=True)
    failures, got, channel = [], [], None

    if t.endswith((".SZ", ".SH", ".BJ")):
        market, code = "A股", t.split(".")[0]
        items = []
        try:
            items = list_a_eastmoney(code); channel = "EASTMONEY"
        except Exception as e:                      # noqa: BLE001
            failures.append("东方财富列表失败：%s" % str(e)[:120])
        if not items and t.endswith(".SZ"):
            try:
                items = list_a_szse(code); channel = "SZSE"
            except Exception as e:                  # noqa: BLE001
                failures.append("深交所列表失败：%s" % str(e)[:120])
        items = pick(items, a.years, a.quarterly)
        if channel == "EASTMONEY":
            for it in items:
                try:
                    it["url"] = resolve_eastmoney_pdf(it["art_code"])
                except Exception as e:              # noqa: BLE001
                    failures.append("%s 取直链失败：%s" % (it["title"], str(e)[:80]))
        hdr = {"User-Agent": BROWSER_UA, "Referer": "https://data.eastmoney.com/notices/"} \
            if channel == "EASTMONEY" else {"User-Agent": BROWSER_UA, "Referer": "https://www.szse.cn/"}

    elif t.endswith(".HK"):
        market, channel = "港股", "HKEX"
        code = t.split(".")[0].zfill(5)
        try:
            items = pick(list_hk(code, a.years), a.years)
        except Exception as e:                      # noqa: BLE001
            failures.append("披露易列表失败：%s" % str(e)[:120]); items = []
        hdr = {"User-Agent": BROWSER_UA}

    else:
        market, channel = "美股", "SEC"
        try:
            items, cik = list_us(t, a.years)
            items = pick(items, a.years)
        except Exception as e:                      # noqa: BLE001
            failures.append("EDGAR 列表失败：%s" % str(e)[:120]); items = []
        hdr = {"User-Agent": SEC_UA}

    if a.probe:
        for it in items:
            print("  %-6s %-8s %s  %s" % (it["kind"], it.get("period"), it.get("date"), (it.get("url") or "")[:90]))
        print("[probe] %s / %s：候选 %d 份，失败 %d 条" % (market, channel, len(items), len(failures)))
        for f in failures:
            print("  [FAIL]", f)
        return 0

    got = download(items, os.path.join(raw, channel), hdr, failures) if items else []
    mp = write_manifest(raw, t, market, channel or "—", got, failures)

    print("[fetch_raw_filings v%s] %s %s → %s" % (SCRIPT_VERSION, t, market, channel))
    for it in got:
        print("  OK   %s %s (%s)" % (it["kind"], it.get("file"),
                                     "已存在跳过" if it.get("skipped") else "%.1f MB" % (it.get("bytes", 0) / 1048576.0)))
    for f in failures:
        print("  FAIL %s" % f)
    print("  清单：%s" % mp)
    if not got:
        print("  [WARN] 一份都没拿到——渠道可能在当前网络不可达，去 MANIFEST 看失败原因，或换个能联网的机器跑")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
