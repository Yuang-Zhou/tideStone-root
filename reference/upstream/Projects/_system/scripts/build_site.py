# -*- coding: utf-8 -*-
"""
一键刷新研究网站：
  1. 读取「基本面分析汇总」里的所有研究总结 HTML
  2. 用 _system/companies.json 的 GICS 板块、_system/valuation_registry.json 的目标价、
     和 _system/market_data/<ticker>.csv 的最新收盘价，生成导航首页 index.html
     （每张卡显示 目标价 / 现价 / 上行空间）
  3. 把首页 + 所有报告整理进 website_deploy 文件夹（待上传 Cloudflare）
本脚本位于 _system/scripts/，路径基准 BASE 由文件位置上溯三层得到 Projects 根。
双击 _system/刷新网站本地预览.bat 即可运行（该 bat 会先 cd 回 Projects 根；只建不推）。

用法
----
    python3 build_site.py                    正常构建（按 GICS 板块分组）
    python3 build_site.py --dump-map         只打印「报告名 → 板块 → ticker」，不写任何文件

2026-07-31 分类重构第 2 步的三处关键改动
----------------------------------------
  1. 板块来源从 valuation_registry.sector（自定义 6 桶）改为 companies.json 的 gics.sector

2026-09-11 分组细化
------------------
板块大节内再按 GICS 四级子行业（gics.sub_industry）分小节，仅当该板块 >= SUBGROUP_MIN
家公司时才分——信息技术一个节挤 20+ 家、其余节只有 1 家，两头都不好看。
子行业中文名来自 companies.json 的 gics_sub_industry_names；查不到名字不会中断构建，
会显示成「未命名子行业 {代码}」，肉眼就能发现该补表了。
  2. 删掉 MANUAL 硬编码补丁（宁德时代/招商轮船/直觉机器）—— companies.json 里已有正式归属
  3. **匹配不上的报告直接抛错，不再静默归入「9. 其他公司」** —— 这是本次改动的核心。
     旧逻辑下归错类的页面看起来完全正常，无法察觉。

2026-08-09 清理
--------------
旧逻辑（`===== LEGACY =====` 段、`match_legacy` 的静默兜底、`MANUAL_LEGACY`、
`LEGACY_ORDER`）与 `--legacy` 开关已全部删除。它们是第 2 步做新旧双输出 diff 用的，
验收早已完成；留着的风险是哪天被误传参数，就又走回「归错类但页面看着正常」的老路。
分类重构前的旧对比方式已随 .bak 一并清理（2026-08-09），不再可回看。
"""
import json, os, re, sys, html, shutil, subprocess
from site_chrome import head_links, page_open, page_close   # 2026-10-20 统一页头页脚（同目录）
from collections import defaultdict

# 本文件位于 _system/scripts/，向上三层才是 Projects 根目录
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "基本面分析汇总")
COMPANIES = os.path.join(BASE, "_system", "companies.json")
REG = os.path.join(BASE, "_system", "valuation_registry.json")
MD = os.path.join(BASE, "_system", "market_data")
OUT = os.path.join(BASE, "website_deploy", "public")   # 站点文件目录（git 仓库 website_deploy 的子目录）

# 站点图标（2026-09-16）：图片文件常驻 website_deploy/public/（favicon.svg / favicon-32.png / apple-touch-icon.png / logo.svg），
# 清理旧 html 时不会被删。首页直接写进模板；从 基本面分析汇总/ 复制过来的子页面由 inject_favicon() 注入 <head>。
FAVICON_TAGS = (
    '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n'
    '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">\n'
    '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
)


RS_OVERRIDE = ('<style>/* site skin */body{background:var(--paper);margin:0;padding:0;'
               'font-family:var(--font);font-size:14.5px;line-height:1.7}</style>\n')


def skin_research(html_text):
    """研究总结页（skill 生成的自包含 HTML）套统一外框：head 加 site.css，body 内容包进顶栏/页脚。
    页面自带样式不动，只在 site.css 的 .rs-wrap 规则里盖外框和几处颜色。已套过的原样返回。"""
    if 'class="site-top"' in html_text:
        return html_text
    m = re.search(r"<head[^>]*>", html_text, flags=re.I)
    if not m:
        return html_text
    html_text = html_text[:m.end()] + "\n" + head_links() + html_text[m.end():]
    i = html_text.lower().rfind("</head>")
    if i >= 0:
        html_text = html_text[:i] + RS_OVERRIDE + html_text[i:]
    mb = re.search(r"<body[^>]*>", html_text, flags=re.I)
    me = html_text.lower().rfind("</body>")
    if mb and me > mb.end():
        html_text = (html_text[:mb.end()] + "\n" + page_open("research", "", main_class="rs-wrap")
                     + html_text[mb.end():me] + page_close("研究总结由七个分析模块汇总生成，结论带时效，以档案版本日期为准。")
                     + html_text[me:])
    return html_text


def skin_paper(html_text):
    """模拟盘看板（paper_portfolio.py 生成，自带一套样式）套统一外框：换掉其 <style>，内容包进顶栏/页脚。"""
    if 'class="site-top"' in html_text:
        return html_text
    html_text = re.sub(r"<style>.*?</style>", "", html_text, count=1, flags=re.S | re.I)
    m = re.search(r"<head[^>]*>", html_text, flags=re.I)
    if m:
        html_text = html_text[:m.end()] + "\n" + head_links() + html_text[m.end():]
    mb = re.search(r"<body[^>]*>", html_text, flags=re.I)
    me = html_text.lower().rfind("</body>")
    if mb and me > mb.end():
        html_text = (html_text[:mb.end()] + "\n" + page_open("paper", "", main_class="site-main pp-wrap")
                     + html_text[mb.end():me] + page_close("模拟盘为纸面组合，按收盘价成交、不计手续费与滑点，每日自动更新。")
                     + html_text[me:])
    return html_text


def inject_favicon(html_text):
    """给子页面 <head> 补 favicon 标签；已有 rel="icon" 或找不到 <head> 就原样返回。"""
    if 'rel="icon"' in html_text or "rel='icon'" in html_text:
        return html_text
    m = re.search(r"<head[^>]*>", html_text, flags=re.I)
    if not m:
        return html_text
    return html_text[:m.end()] + "\n" + FAVICON_TAGS + html_text[m.end():]
DASHBOARD_BUILDER = os.path.join(BASE, "_system", "scripts", "build_valuation_comparison.py")
BRIEFING_BUILDER = os.path.join(BASE, "_system", "scripts", "build_briefing.py")   # 2026-10-20：每日简报 → public/briefing/
BRIEFING_SRC = os.path.join(BASE, "_system", "daily_briefing")

# 策略模拟盘（2026-10-03）：「低估+增长」纸面组合看板由 paper_portfolio.py（流水线 [3/8]）生成，
# 这里只负责搬上站。站上文件名用策略名 value-growth，内部目录仍叫 paper_portfolio（paper = 纸面/模拟盘）。
# 看板或摘要缺失时首页不显示该卡片、也不复制页面——模拟盘不是发布的必要条件，不能因它阻断建站。
PAPER_DIR = os.path.join(BASE, "_system", "paper_portfolio")
PAPER_DASHBOARD = os.path.join(PAPER_DIR, "dashboard.html")
PAPER_SUMMARY = os.path.join(PAPER_DIR, "summary_latest.json")
PAPER_PAGE = "value-growth.html"
PAPER_BACKLINK = ('<div style="margin:0 0 10px;font-size:13px"><a href="/" '
                  'style="color:inherit;opacity:.7;text-decoration:none">← 基本面研究 · 汇总</a></div>\n')


def paper_available():
    return os.path.isfile(PAPER_DASHBOARD)


VALUATION_SUMMARY = os.path.join(BASE, "_system", "valuation_comparison_summary.json")   # build_valuation_comparison.py 写

ICON_BARS = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 20h18"/><path d="M6 16V9"/>'
             '<path d="M11 16V5"/><path d="M16 16v-6"/><path d="M21 16V8"/></svg>')
ICON_LINE = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 17l5-6 4 4 5-8 4 5"/></svg>')
ICON_DOC = ('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="3" width="16" height="18" rx="2"/>'
            '<path d="M8 8h8"/><path d="M8 12h8"/><path d="M8 16h5"/></svg>')


def entry_card(href, icon, title, value, unit, desc, link):
    return (f'      <a class="entry" href="{href}">\n'
            f'        <div class="eh">{icon}{title}</div>\n'
            f'        <div class="ev">{value} <span class="eu">{unit}</span></div>\n'
            f'        <div class="ed">{desc}</div>\n'
            f'        <div class="el">{link} →</div>\n'
            f'      </a>\n')


def valuation_card():
    """首页目标价对比入口卡；摘要 json 缺失时用通用文案。"""
    value, unit, desc = "71", "家公司", "现价 · 研究目标价 · 三年目标价与年化回报"
    try:
        with open(VALUATION_SUMMARY, encoding="utf-8") as fh:
            sm = json.load(fh)
        value, unit = str(sm["rows"]), "家公司"
        desc = (f"现价 · 研究目标价 · 三年目标价与年化回报。口径红旗 "
                f'<b class="neg">{sm["red_rows"]}</b> 家待复核')
    except Exception:
        value, unit = "", "现价 · 目标价 · 三年回报"
    return entry_card("组合三年估值看板.html", ICON_BARS, "公司目标价对比", value, unit, desc, "打开对比表")


def paper_card():
    """首页模拟盘入口卡片；摘要读不到时只显示标题和说明。"""
    if not paper_available():
        return ""
    value, unit, desc = "", "纸面组合", "等权 · 按收盘价成交 · 每日自动更新"
    try:
        with open(PAPER_SUMMARY, encoding="utf-8") as fh:
            sm = json.load(fh)
        value = f'<span class="{"pos" if sm["ret"] >= 0 else "neg"}">{sm["ret"] * 100:+.2f}%</span>'
        unit = "净值"
        parts = []
        if sm.get("bm_ret") is not None:
            parts.append(f"同期 SPX {sm['bm_ret'] * 100:+.2f}%")
        parts.append(f"{sm['holds']} 只持仓")
        parts.append(f"截至 {sm['asof']}")
        desc = " · ".join(parts) + "。纸面组合，非交易建议"
    except Exception:
        pass
    return entry_card(PAPER_PAGE, ICON_LINE, "低估+增长 策略模拟盘", value, unit, html.escape(desc, quote=False), "查看持仓与净值")


def briefing_card():
    """首页每日简报入口卡片；没有任何简报 md 时不显示。"""
    try:
        dates = sorted(f[:10] for f in os.listdir(BRIEFING_SRC) if re.match(r"^\d{4}-\d{2}-\d{2}_daily_briefing\.md$", f))
    except OSError:
        dates = []
    if not dates:
        return ""
    desc = f"共 {len(dates)} 份 · 市场脉搏、催化剂、技术信号、动作建议。每日扫描自动生成"
    return entry_card("briefing/index.html", ICON_DOC, "投资组合每日简报", dates[-1][5:], "最新一期", desc, "读今天的简报")


# ==========================================================================
# 新逻辑：companies.json 为板块真相源
# ==========================================================================
def load_companies():
    """
    返回 (entries, sector_names, sub_names)。
    entries = {ticker: {name_cn, name_en, sector, sub, target_price}}

    sector = GICS 一级代码（2 位），决定页面大节；
    sub    = GICS 四级子行业代码（8 位），决定大节内的小节（见 render 的 SUBGROUP_MIN）。
    """
    d = json.load(open(COMPANIES, encoding="utf-8"))
    sector_names = d.get("gics_sector_names", {})
    sub_names = d.get("gics_sub_industry_names", {})

    targets = {}
    try:
        for tk, c in json.load(open(REG, encoding="utf-8"))["companies"].items():
            if isinstance(c, dict):
                targets[tk] = c.get("target_price") or ""
    except Exception as e:
        print("  ! 读不到估值注册表，目标价将留空：", e)

    entries = {}
    for tk, e in d["companies"].items():
        sec = e.get("gics", {}).get("sector")
        if not sec:
            raise SystemExit("companies.json 里 %s 缺 gics.sector，先补齐再跑" % tk)
        entries[tk] = {
            "name_cn": e.get("name_cn") or "",
            "name_en": e.get("name_en") or "",
            "sector": sec,
            "sub": e.get("gics", {}).get("sub_industry") or "",
            "target_price": targets.get(tk, ""),
        }
    return entries, sector_names, sub_names


def norm_name(s):
    """归一化用于匹配：去空格/逗号/句点/连字符，拉丁字母转小写。"""
    return re.sub(r"[\s,.\-—－·]", "", s or "").lower()


def build_index(entries):
    """预建匹配索引：{归一化名 -> [ticker, ...]}，含 ticker 本身、中文名、英文名。"""
    idx = defaultdict(list)
    for tk, e in entries.items():
        for key in (tk, e["name_cn"], e["name_en"]):
            if key:
                idx[norm_name(key)].append(tk)
    return idx


def match(name, entries, idx):
    """
    报告文件名里的公司名 -> ticker。三级匹配，全部失败则返回 None（由调用方抛错）。
      1) 精确命中 ticker / 中文名 / 英文名
      2) 前缀命中（"Microsoft" -> "Microsoft Corporation"）
      3) 无
    命中多家时视为歧义，直接抛错——宁可停下也不要归错。
    """
    n = norm_name(name)

    hits = sorted(set(idx.get(n, [])))
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise SystemExit("报告名 %r 同时命中 %s，请改报告文件名或 companies.json 的名称字段" % (name, hits))

    pref = sorted({tk for tk, e in entries.items()
                   for key in (e["name_cn"], e["name_en"])
                   if key and norm_name(key).startswith(n)})
    if len(pref) == 1:
        return pref[0]
    if len(pref) > 1:
        raise SystemExit("报告名 %r 前缀命中多家 %s，请补全报告文件名以消歧" % (name, pref))
    return None


# ==========================================================================
# 通用工具
# ==========================================================================
def clean_target(tp):
    """从注册表杂乱的目标价字段里抽出干净的数字，如 '$485（…）' -> '$485'"""
    if not tp:
        return ""
    t = tp.split("（")[0].split("(")[0].replace("*", "").strip()
    t = re.split(r"\s*/\s*", t)[0].strip().replace("/股", "").strip()
    return t


# 中文货币词 → 符号。"港元" / "美元" 必须排在 "元" 前面，否则会被 "元" 先吃掉。
CURRENCY_WORDS = [("港元", "HK$"), ("港币", "HK$"), ("美元", "$"), ("元", "¥")]
HAS_SYMBOL_RE = re.compile(r"^[~约]?\s*(HK\$|US\$|\$|¥|￥)")


def normalize_target(t, cur):
    """
    把目标价统一成「货币符号 + 数字」，与同一张卡上的现价同侧。

    2026-08-03 新增。`valuation_registry` 里目标价是自由文本，各条写法不一：
        '62 元'  '278港元'  '96'  '$60.50'  '~$21'  '¥36.6'  '$280-290'  '待完成估值分析'
    结果卡片上出现「目标 62 元 / 现价 ¥68.68」这种混搭；更麻烦的是港股的 '96' / '107'
    完全没有单位，光看数字分不清港元还是美元。

    规则：中文货币词换成符号；已有符号的原样保留（US$ / ￥ 统一成 $ / ¥）；
    裸数字补上 currency(ticker) 给出的符号；不含数字的占位文本（如"待完成估值分析"）
    返回空串——宁可不显示目标价，也不要在卡片上摆一句话。
    """
    if not t:
        return ""
    t = t.strip()
    for word, sym in CURRENCY_WORDS:
        if word in t:
            t = (sym + t.replace(word, "").strip()).strip()
            break
    if not re.search(r"\d", t):
        return ""
    if HAS_SYMBOL_RE.match(t):
        return t.replace("US$", "$").replace("￥", "¥")
    m = re.match(r"^([~约]?)\s*(.*)$", t)
    return (m.group(1).replace("约", "~") + cur + m.group(2)).strip()


def to_num(s):
    """从带符号的字符串里取出数字，如 '~$43.5' -> 43.5"""
    if not s:
        return None
    m = re.search(r"[\d.]+", s.replace(",", ""))
    return float(m.group()) if m else None


def last_close(tk):
    """读取 <ticker>.csv 最后一行有效收盘价；最后一行若被写一半则自动回退。返回 (收盘价, 日期)"""
    if not tk:
        return None, None
    for cand in [tk, re.sub(r"\.(N|O)$", "", tk)]:
        p = os.path.join(MD, cand + ".csv")
        if os.path.exists(p):
            try:
                rows = open(p, encoding="utf-8").read().splitlines()
            except Exception:
                return None, None
            for line in reversed(rows):
                c = line.strip().split(",")
                if len(c) >= 5 and c[0] != "date":
                    try:
                        close = float(c[4])
                        if close > 0:
                            return close, c[0]
                    except ValueError:
                        continue
    return None, None


def currency(tk):
    if not tk:
        return "$"
    if tk.endswith(".HK"):
        return "HK$"
    if re.search(r"\.(SZ|SH|BJ)$", tk):
        return "¥"
    return "$"


def fmt_price(v):
    return ("%.2f" % v).rstrip("0").rstrip(".")


def report_files():
    return [f for f in os.listdir(SRC)
            if f.endswith(".html") and "看板" not in f and f != "index.html"]


def split_filename(f):
    m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})_研究总结\.html", f)
    return (m.group(1), m.group(2)) if m else (f.replace(".html", ""), "")


# ==========================================================================
# 收集记录
# ==========================================================================
def collect():
    """返回 (recs, order, sector_label, sub_label)。label(code) -> 展示名。"""
    entries, sector_names, sub_names = load_companies()
    idx = build_index(entries)
    recs, unmatched = [], []
    for f in report_files():
        name, date = split_filename(f)
        tk = match(name, entries, idx)
        if tk is None:
            unmatched.append((name, f))
            continue
        e = entries[tk]
        # 展示名一律取 companies.json，不取文件名——否则同一家公司写法不同就会裂成两张卡
        recs.append(_rec(e["name_cn"] or e["name_en"] or name, date, f,
                         e["sector"], e["target_price"], tk, e["sub"]))

    if unmatched:
        lines = "\n".join("    %-28s  ← %s" % (n, f) for n, f in unmatched)
        raise SystemExit(
            "以下研究报告在 _system/companies.json 里找不到对应公司，已中止构建：\n"
            + lines
            + "\n\n处理方式（择一）：\n"
              "  · 报告名写错 → 改「基本面分析汇总」里的文件名\n"
              "  · 公司确实在库 → 补 companies.json 里该公司的 name_cn / name_en\n"
              "  · 公司不在库 → 跑「新公司入库」把它加进 companies.json\n"
              "旧版本会把它们静默归入「9. 其他公司」，页面看起来正常但归类是错的；现在改为中止。"
        )

    order = sorted({r["sector"] for r in recs})
    return (recs, order,
            lambda s: sector_names.get(s, "未知板块 " + s),
            lambda c: sub_names.get(c, "未命名子行业 " + c) if c else "未分类")


def _rec(name, date, f, sec, tp, tk, sub=""):
    cur = currency(tk)
    target = normalize_target(clean_target(tp), cur)
    px, pdate = last_close(tk)
    tnum = to_num(target)
    return dict(name=name, date=date, file=f, sector=sec, sub=sub, ticker=tk,
                target=target, price=px, pdate=pdate, cur=cur,
                upside=(tnum / px - 1) * 100 if (tnum and px) else None)


def dedupe(recs):
    """
    同一家公司多份报告：最新的做主卡，其余进「历史」。

    2026-08-01 修正：按 **ticker** 分组，不再按报告文件名里的公司名。
    旧写法下「Microsoft」和「Microsoft Corporation」两个文件名会裂成两张 MSFT 卡，
    首页因此把 40 家显示成 41 家。`r["ticker"] or r["name"]` 里的 or 分支现在走不到了
    （collect 匹配不上会直接抛错），留着只是防御。
    """
    bycomp = defaultdict(list)
    for r in recs:
        bycomp[r["ticker"] or r["name"]].append(r)
    items = []
    for _, rs in bycomp.items():
        rs.sort(key=lambda x: x["date"], reverse=True)
        p = rs[0]
        p["older"] = rs[1:]
        items.append(p)
    return items


# ==========================================================================
# 渲染
# ==========================================================================
# 一个板块里公司少于这个数就不分子行业小节——否则会出现一串「某某 1」的孤儿标题，
# 比 21 家挤在一起还难看。2026-09-11 加。
SUBGROUP_MIN = 6


def render(items, recs, order, label, sub_label):
    sectors = defaultdict(list)
    for it in items:
        sectors[it["sector"]].append(it)

    latest_report = max([r["date"] for r in recs if r["date"]] or ["—"])
    price_dates = [r["pdate"] for r in recs if r["pdate"]]
    price_asof = max(price_dates) if price_dates else "—"

    def card(it):
        tp_chip = f'<span class="tp">目标 {html.escape(it["target"])}</span>' if it["target"] else ""
        px_chip = f'<span class="px">现价 {it["cur"]}{fmt_price(it["price"])}</span>' if it["price"] else ""
        if it["upside"] is not None:
            cls = "pos" if it["upside"] >= 0 else "neg"
            up_chip = f'<span class="up {cls}">空间 {it["upside"]:+.1f}%</span>'
        else:
            up_chip = ""
        older = ""
        if it["older"]:
            links = " · ".join(f'<a class="old" href="{html.escape(o["file"])}">{o["date"]}</a>' for o in it["older"])
            older = f'<span class="older">历史: {links}</span>'
        return f'''        <div class="card">
          <a class="cardmain" href="{html.escape(it['file'])}">
            <span class="cname">{html.escape(it['name'])}</span>
            <span class="meta">{tp_chip}{px_chip}</span>
            <span class="meta2">{up_chip}<span class="date">研究 {it['date']}</span></span>
          </a>
          {older}
        </div>\n'''

    def grid(rows):
        return f'''      <div class="grid">
{rows}      </div>\n'''

    cards = ""
    for s in order:
        if s not in sectors:
            continue
        members = sectors[s]
        body = ""
        if len(members) >= SUBGROUP_MIN:
            # 按子行业分小节：公司多的排前面，同数量按代码排，顺序才稳定
            subs = defaultdict(list)
            for it in members:
                subs[it["sub"]].append(it)
            for code in sorted(subs, key=lambda c: (-len(subs[c]), c)):
                rows = "".join(card(it) for it in sorted(subs[code], key=lambda x: x["name"]))
                body += f'''      <h3 class="sub">{html.escape(sub_label(code))} <span class="cnt2">{len(subs[code])}</span></h3>
''' + grid(rows)
        else:
            body = grid("".join(card(it) for it in sorted(members, key=lambda x: x["name"])))
        # 2026-10-20：板块改为可折叠（<details>），默认收起；顶部「全部展开/收起」按钮见 .toolbar
        cards += f'''    <details class="sec">
      <summary><h2>{html.escape(label(s))} <span class="cnt">{len(members)}</span><span class="chev" aria-hidden="true"></span></h2></summary>
      <div class="secbody">
{body}      </div>
    </details>\n'''

    page = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>基本面研究 · 汇总</title>
{head_links()}<style>
  /* 首页专属：入口卡 + 板块折叠列表 + 公司卡片。颜色一律用 site.css 的变量 */
  .entries{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:28px}}
  .entry{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:20px 22px;display:flex;flex-direction:column;gap:10px;color:var(--ink);text-decoration:none}}
  .entry:hover{{border-color:var(--accent);text-decoration:none;color:var(--ink)}}
  .entry .eh{{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:600;color:var(--ink)}}
  .entry .eh svg{{color:var(--brand);flex:none}}
  .entry .ev{{font-size:30px;font-weight:700;line-height:1.1}}
  .entry .eu{{font-size:14px;font-weight:500;color:var(--muted)}}
  .entry .ed{{font-size:13px;color:var(--muted)}}
  .entry .el{{font-size:13px;color:var(--accent);font-weight:600;margin-top:2px}}
  .toolbar{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 12px}}
  .toolbar .hint{{color:var(--muted);font-size:13px}}
  .toolbar .btns{{margin-left:auto;display:flex;gap:8px}}
  .secs{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}}
  .sec{{border-bottom:1px solid var(--line)}}
  .sec:last-child{{border-bottom:0}}
  .sec summary{{list-style:none;cursor:pointer;user-select:none}}
  .sec summary::-webkit-details-marker{{display:none}}
  .sec h2{{font-size:15px;font-weight:600;margin:0;padding:14px 18px;display:flex;align-items:center;gap:10px}}
  .sec summary:hover h2{{color:var(--accent)}}
  .sec[open] h2{{color:var(--accent);background:var(--paper);border-bottom:1px solid var(--line)}}
  .sec .chev{{margin-left:auto;width:8px;height:8px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:transform .15s}}
  .sec[open] .chev{{transform:rotate(45deg);border-color:var(--accent)}}
  .secbody{{padding:16px 18px 20px}}
  .cnt{{font-size:12px;font-weight:600;color:var(--muted);background:var(--paper);border-radius:10px;padding:1px 8px}}
  .sec[open] .cnt{{background:var(--panel)}}
  .sub{{font-size:13px;font-weight:600;color:var(--muted);margin:14px 0 10px;display:flex;align-items:center;gap:8px}}
  .secbody h3.sub:first-of-type{{margin-top:0}}
  .cnt2{{font-size:11px;font-weight:600;color:var(--muted);border:1px solid var(--line);border-radius:9px;padding:0 6px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
  .card{{border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px;display:flex;flex-direction:column;gap:6px;transition:border-color .15s}}
  .card:hover{{border-color:var(--accent)}}
  .cardmain{{text-decoration:none;color:var(--ink);display:flex;flex-direction:column;gap:6px}}
  .cardmain:hover{{text-decoration:none;color:var(--ink)}}
  .cname{{font-weight:600;font-size:15px}}
  .meta{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px}}
  .meta2{{display:flex;align-items:center;gap:8px;font-size:12px}}
  .tp{{color:var(--accent);font-weight:600;white-space:nowrap}}
  .px{{color:var(--muted);white-space:nowrap}}
  .up{{font-weight:700;white-space:nowrap;border-radius:6px;padding:1px 7px}}
  .up.pos{{color:var(--up);background:var(--up-bg)}}
  .up.neg{{color:var(--down);background:var(--down-bg)}}
  .date{{color:var(--muted)}}
  .older{{font-size:12px;color:var(--muted)}}
  @media (max-width:860px){{.entries{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
{page_open("home", f"现价更新至 {price_asof} 收盘")}
    <div class="titlebar">
      <div class="eyebrow">Flyfish Capital · Research</div>
      <h1>基本面研究 · 汇总</h1>
      <div class="lede">{len(items)} 家公司 · {len([s for s in order if s in sectors])} 个 GICS 板块 · 研究更新至 {latest_report}</div>
    </div>
    <div class="entries">
{valuation_card()}{paper_card()}{briefing_card()}    </div>
    <div class="toolbar">
      <h2>按 GICS 板块</h2>
      <span class="hint">点板块标题展开／收起</span>
      <div class="btns">
        <button type="button" class="btn" onclick="document.querySelectorAll('details.sec').forEach(function(d){{d.open=true}})">全部展开</button>
        <button type="button" class="btn" onclick="document.querySelectorAll('details.sec').forEach(function(d){{d.open=false}})">全部收起</button>
      </div>
    </div>
    <div class="secs">
{cards}    </div>
{page_close("「目标价」为各报告当时的估算（带假设与时效）；「空间」= 目标价 ÷ 现价 − 1，正值表示现价低于目标价。现价取自本地行情数据，可能非实时。")}</body>
</html>'''
    return page, sectors


# ==========================================================================
# 主流程
# ==========================================================================
def build(dump_map=False):
    if not os.path.isdir(SRC):
        raise SystemExit("找不到「基本面分析汇总」文件夹，脚本是否放在 Projects 根目录？")

    recs, order, label, sub_label = collect()
    items = dedupe(recs)

    if dump_map:
        # 只输出映射，供 diff。稳定排序，与是否写文件无关。
        for it in sorted(items, key=lambda x: x["name"]):
            print("%-28s\t%s\t%s" % (it["name"], label(it["sector"]), it["ticker"] or "-"))
        return

    # 目标价对比页必须在复制部署文件前重建，确保现价来自当日行情。
    subprocess.run([sys.executable, DASHBOARD_BUILDER], check=True)
    # 每日简报页面（public/briefing/）。扫描器在本流水线之后才出当天简报，
    # 当天上站靠 推送简报.bat 单独再跑一次；这里保证首页卡片指向的目录页存在。
    subprocess.run([sys.executable, BRIEFING_BUILDER], check=True)

    page, sectors = render(items, recs, order, label, sub_label)

    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                      # 只清旧 html，保留 .git/.gitignore/wrangler 等
        if f.endswith(".html"):
            os.remove(os.path.join(OUT, f))
    for f in os.listdir(SRC):
        if f.endswith(".html") and f != "index.html":
            with open(os.path.join(SRC, f), encoding="utf-8") as fh:
                sub = fh.read()
            # 2026-10-20：研究总结页套统一外框；其他（目标价对比）只补 favicon
            with open(os.path.join(OUT, f), "w", encoding="utf-8") as fh:
                fh.write(skin_research(sub) if f.endswith("研究总结.html") else inject_favicon(sub))
    if paper_available():
        with open(PAPER_DASHBOARD, encoding="utf-8") as fh:
            sub = fh.read()
        with open(os.path.join(OUT, PAPER_PAGE), "w", encoding="utf-8") as fh:
            fh.write(skin_paper(sub))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)

    deploy_files = set(os.listdir(OUT))
    hrefs = re.findall(r'href="([^"]+)"', page)
    # 2026-09-16：站点图标用根相对路径（/favicon.svg），校验时去掉开头的 "/" 再比对
    # 2026-10-20：简报链接带子目录（briefing/index.html），改为按实际路径存在性校验
    missing = [h for h in hrefs if not h.startswith("http")
               and not os.path.exists(os.path.join(OUT, *h.lstrip("/").split("/")))]
    priced = sum(1 for it in items if it["price"])
    nopx = [it["name"] for it in items if not it["price"]]

    build_failed = bool(nopx or missing)
    print("=" * 52)
    print("  %s" % ("构建失败，禁止发布！" if build_failed else "刷新完成！"))
    # 注册表里有、但页面上没有的公司。
    # 2026-09-11 加：build_site 的中止条件一直只管「报告找不到公司」（归错类的老毛病），
    # 反过来「公司没有报告」是完全静默的——于是 registry 64 家、站上 56 家，
    # 差额不写在任何地方，只能靠人自己数出来。这不是错误（没做完研究本来就不该上站），
    # 但必须可见，否则会被误读成分类漏了公司。
    all_tickers = set(load_companies()[0])
    on_site = {it["ticker"] for it in items}
    offsite = sorted(all_tickers - on_site)

    print("  公司数: %d / 注册表 %d    现价命中: %d/%d    页面文件: %d"
          % (len(items), len(all_tickers), priced, len(items), len(deploy_files)))
    for s in order:
        if s in sectors:
            print("    - %s: %d" % (label(s), len(sectors[s])))
    if offsite:
        print("  · 未上站 %d 家（无研究总结 HTML，属正常）: %s"
              % (len(offsite), "、".join(offsite)))
    if nopx:
        print("  ! 无现价的公司: %s" % "、".join(nopx))
    if missing:
        print("  ! 有链接对应的文件缺失:", missing)
    else:
        print("  所有导航链接都已校验通过。")
    print("=" * 52)
    print("  站点文件目录: %s" % OUT)
    if not build_failed:
        print("  接下来由 daily_pipeline.bat（每日自动）或「手动推送上线.bat」执行 git push，成功后触发 Cloudflare 部署。")
    else:
        print("  本次不会执行 git push。")
    print("=" * 52)

    # 发布链路依赖退出码。关键内容不完整时必须非零退出，不能只打印警告后继续 push。
    if build_failed:
        problems = []
        if nopx:
            problems.append("无现价: " + "、".join(nopx))
        if missing:
            problems.append("缺链接文件: " + "、".join(missing))
        raise SystemExit("构建产物未通过发布校验；已禁止 push。" + "；".join(problems))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--legacy" in sys.argv:
        raise SystemExit("--legacy 已于 2026-08-09 删除。旧逻辑（自定义 6 桶 + 静默兜底）"
                         "已不存在；分类重构前的旧对比方式已随 .bak 于 2026-08-09 清理。")
    build(dump_map="--dump-map" in sys.argv)
