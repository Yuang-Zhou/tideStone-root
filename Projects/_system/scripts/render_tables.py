#!/usr/bin/env python3
"""
render_tables.py — 把 financials.json 渲染成第 0b 步的数据底座 Markdown 表。

用法:
    python3 render_tables.py path/to/financials.json [--years 5] [--unit 1e6] > tables.md

字段名按 references/data-contract.md（fetch_edgar_financials.py v0.2）。
底稿字段名变了改 FIELDS，不改 SKILL.md。
缺的数一律输出 n/a，不猜、不当 0。53 周年份列头加 53w。
"""
import argparse
import json
import sys

# 指标名 → 底稿 annual 字段。改这里适配新版底稿。
FIELDS = {
    "revenue": "revenue", "cogs": "cost_of_revenue", "rnd": "rnd_expense", "sga": "sga_expense",
    "da": "depreciation_amortization", "impairment": "impairment", "restructuring": "restructuring",
    "op_income": "operating_income", "int_exp": "interest_expense", "int_inc": "interest_income",
    "pretax": "pretax_income", "tax": "income_tax", "net_income": "net_income", "sbc": "sbc",
    "shares_diluted": "shares_diluted",
    "cash": "cash_and_equivalents", "sti": "short_term_investments", "ar": "accounts_receivable",
    "inventory": "inventory", "ppe": "ppe_net", "rou": "operating_lease_rou", "goodwill": "goodwill",
    "intangibles": "intangibles", "total_assets": "total_assets", "ap": "accounts_payable",
    "accrued": "accrued_liabilities", "employee_liab": "employee_liabilities",
    "prepaid": "prepaid_and_other_current", "deferred_rev": "deferred_revenue",
    "std": "short_term_debt", "ltd": "long_term_debt",
    "ol_cur": "operating_lease_liab_current", "ol_nc": "operating_lease_liab_noncurrent",
    "fl_cur": "finance_lease_liab_current", "fl_nc": "finance_lease_liab_noncurrent",
    "equity": "total_equity", "cfo": "cfo", "capex": "capex", "taxes_paid": "income_taxes_paid",
}
CAPALLOC = {"fcf": "fcf", "acq": "acquisitions", "nci": "payments_to_nci", "buyback": "buyback",
            "dividend": "dividends_paid", "net_debt_repay": "net_debt_repayment"}


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Book:
    def __init__(self, data, n_years, unit):
        self.d = data
        self.unit = unit
        self.annual = data.get("annual", {})
        self.ttm = data.get("ttm", {}) or {}
        self.capalloc = data.get("capital_allocation", {}) or {}
        years = sorted({y for m in self.annual.values() for y in m})
        self.years = years[-n_years:]
        self.prev = years[-n_years - 1] if len(years) > n_years else None
        w53 = set(data.get("meta", {}).get("week53_years", []) or [])
        self.headers = [f"{y} 53w" if y in w53 else y for y in self.years] + ["TTM"]

    # --- 取数：一律返回 None 表示缺 ---
    def a(self, key, year):
        f = FIELDS.get(key, key)
        v = self.annual.get(f, {}).get(year)
        return None if v is None else v

    def t(self, key):
        f = FIELDS.get(key, key)
        for bucket in ("flow", "instant"):
            v = (self.ttm.get(bucket) or {}).get(f)
            if v is not None:
                return v
        return None

    def ca(self, key, year):
        f = CAPALLOC.get(key, key)
        row = self.capalloc.get(year) if isinstance(self.capalloc, dict) else None
        if row is None and isinstance(self.capalloc, list):
            row = next((r for r in self.capalloc if str(r.get("year")) == str(year)), None)
        return None if row is None else row.get(f)

    # --- 行构造 ---
    def row_a(self, key, ttm=True):
        vals = [self.a(key, y) for y in self.years]
        vals.append(self.t(key) if ttm else None)
        return vals

    def row_ca(self, key):
        return [self.ca(key, y) for y in self.years] + [None]


def add(*xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def sub(a, b):
    return None if a is None or b is None else a - b


def div(a, b):
    return None if a is None or b in (None, 0) else a / b


def fmt_money(v, unit):
    """Keep sub-unit amounts visible; displayed zero means an actual zero."""
    if v is None:
        return "n/a"
    scaled = v / unit
    if scaled == 0:
        return "0"
    text = f"{scaled:,.2f}".rstrip("0").rstrip(".")
    return f"{scaled:.3g}" if text in ("0", "-0") else text


def strict_add(*values):
    """Required coverage inputs: absence is not evidence of a zero liability."""
    return None if any(v is None for v in values) else sum(values)


def current_debt_tag(book, year, value):
    """Use period/value provenance; a field name alone does not resolve debt scope."""
    records = [r for r in book.d.get("records", []) or []
               if isinstance(r, dict) and r.get("metric") == "short_term_debt"]
    if records:
        if year is None:
            matches = [r for r in records if r.get("period_end") == book.ttm.get("period_end")]
        else:
            matches = [r for r in records if str(r.get("period_end", "")).startswith(str(year))
                       and str(r.get("form", "")).startswith(("10-K", "20-F", "40-F"))]
        tags = {r.get("tag") for r in matches if r.get("value") == value}
    else:
        tags = book.d.get("meta", {}).get("tag_map", {}).get("short_term_debt", [])
        tags = {tags} if isinstance(tags, str) else set(tags)
    return next(iter(tags)) if len(tags) == 1 else None


def current_obligations(book, long_term_due):
    """metrics.md: current borrowings + current long-term principal + current leases.

    The fetcher mixes non-equivalent tags into short_term_debt. DebtCurrent and
    IFRS CurrentBorrowings already include current long-term principal; adding
    debt_due_1y again would double count. ShortTermBorrowings needs that addition.
    LongTermDebtCurrent (including its capital-lease variant) lacks separate
    short-term borrowings, so this renderer cannot establish a complete total.
    """
    values, gaps = [], []
    rows = zip(book.years + [None], book.row_a("std"), long_term_due,
               book.row_a("ol_cur"), book.row_a("fl_cur"))
    for year, current, due, operating, finance in rows:
        tag = current_debt_tag(book, year, current)
        if tag in ("DebtCurrent", "CurrentBorrowings", "CurrentInterestbearingLoansAndBorrowings"):
            principal = current
        elif tag == "ShortTermBorrowings":
            principal = strict_add(current, due)
        else:
            principal = None
        total = strict_add(principal, operating, finance)
        if total is None:
            gaps.append(str(year) if year is not None else "TTM")
        values.append(total)
    return values, gaps


def fmt_pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def fmt_x(v):
    return "n/a" if v is None else f"{v:.1f}x"


def fmt_days(v):
    return "n/a" if v is None else f"{v:.0f}"


def table(title, headers, rows, fmt, unit=None):
    out = [f"**{title}**", "", "| 科目 | " + " | ".join(headers) + " |",
           "| :-- |" + " --: |" * len(headers)]
    for name, vals, f in rows:
        f = f or fmt
        cells = [f(v, unit) if f is fmt_money else f(v) for v in vals]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def pairwise(vals, prev_val):
    """逐年增速。prev_val 是 FY-6，用来填第一列。"""
    seq = [prev_val] + vals
    out = []
    for i in range(1, len(seq)):
        a, b = seq[i], seq[i - 1]
        out.append(None if a is None or b in (None, 0) else a / b - 1)
    return out


def avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def render(data, n_years=5, unit=1e6):
    b = Book(data, n_years, unit)
    H = b.headers
    Y = b.years
    meta = data.get("meta", {})
    cur = meta.get("unit", meta.get("currency", "USD"))
    lines = [f"取数日 {meta.get('fetched_at', 'n/a')} · TTM 截止 {b.ttm.get('period_end', 'n/a')} · "
             f"单位 {cur} 百万（股本：百万股）· 由 render_tables.py 生成，未改数\n"]

    # 表 1 利润表
    rev = b.row_a("revenue")
    cogs = b.row_a("cogs")
    gp = [sub(r, c) for r, c in zip(rev, cogs)]
    opi = b.row_a("op_income")
    ni = b.row_a("net_income")
    da = b.row_a("da")
    one_off = [add(i, r) for i, r in zip(b.row_a("impairment"), b.row_a("restructuring"))]
    int_net = [sub(e, i) for e, i in zip(b.row_a("int_exp"), b.row_a("int_inc"))]
    pretax = b.row_a("pretax")
    other = [None if o is None or n is None or p is None else p - (o - n) for o, n, p in zip(opi, int_net, pretax)]
    growth = pairwise(rev[:-1], b.a("revenue", b.prev) if b.prev else None) + [None]
    t1 = [("收入", rev, None), ("收入增速", growth, fmt_pct), ("营业成本", cogs, None), ("毛利", gp, None),
          ("研发", b.row_a("rnd"), None), ("销售管理", b.row_a("sga"), None), ("折旧摊销", da, None),
          ("减值 / 重组", one_off, None), ("营业利润", opi, None), ("利息支出（净）", int_net, None),
          ("其他损益", other, None), ("税前利润", pretax, None), ("所得税", b.row_a("tax"), None),
          ("净利润", ni, None), ("SBC", b.row_a("sbc"), None), ("稀释股本", b.row_a("shares_diluted"), None)]
    lines.append(table("表 1 利润表（精简）", H, t1, fmt_money, unit))

    # 表 2 资产负债表
    cash = [add(c, s) for c, s in zip(b.row_a("cash"), b.row_a("sti"))]
    ar, inv, ppe = b.row_a("ar"), b.row_a("inventory"), b.row_a("ppe")
    gw, intang, ta = b.row_a("goodwill"), b.row_a("intangibles"), b.row_a("total_assets")
    ap, dr = b.row_a("ap"), b.row_a("deferred_rev")
    debt = [add(*xs) for xs in zip(b.row_a("std"), b.row_a("ltd"), b.row_a("ol_cur"), b.row_a("ol_nc"),
                                   b.row_a("fl_cur"), b.row_a("fl_nc"))]
    eq = b.row_a("equity")
    teq = [None if e is None else e - (g or 0) - (i or 0) for e, g, i in zip(eq, gw, intang)]
    t2 = [("现金 + 短期投资", cash, None), ("应收账款", ar, None), ("存货", inv, None), ("固定资产净值", ppe, None),
          ("使用权资产", b.row_a("rou"), None), ("商誉", gw, None), ("无形资产", intang, None), ("总资产", ta, None),
          ("应付账款", ap, None), ("递延收入", dr, None), ("有息负债（含租赁）", debt, None),
          ("股东权益", eq, None), ("有形权益", teq, None)]
    lines.append(table("表 2 资产负债表（期末，精简）", H, t2, fmt_money, unit))

    # 表 3 现金流量表
    cfo, capex = b.row_a("cfo"), b.row_a("capex")
    fcf = b.row_ca("fcf")
    if all(v is None for v in fcf):
        fcf = [sub(c, abs(x) if x is not None else None) for c, x in zip(cfo, capex)]
    capex = [abs(x) if x is not None else None for x in capex]  # 底稿 capex 为正数（支付额），统一按正数展示
    ma = [add(a_, n_) for a_, n_ in zip(b.row_ca("acq"), b.row_ca("nci"))]
    t3 = [("经营现金流", cfo, None), ("资本开支", capex, None), ("自由现金流", fcf, None), ("并购", ma, None),
          ("回购", b.row_ca("buyback"), None), ("分红", b.row_ca("dividend"), None),
          ("净还债", b.row_ca("net_debt_repay"), None), ("实付所得税", b.row_a("taxes_paid"), None)]
    lines.append(table("表 3 现金流量表（精简）", H, t3, fmt_money, unit))

    # 表 4 比率
    def ratio(num, den):
        return [div(n, d) for n, d in zip(num, den)]

    def days(bal, flow):
        out = []
        for i in range(len(Y)):
            prev_bal = bal[i - 1] if i > 0 else None
            out.append(div(avg(bal[i], prev_bal), flow[i]) and div(avg(bal[i], prev_bal), flow[i]) * 365)
        return out + [None]

    ebitda = [add(o, d_) for o, d_ in zip(opi, da)]
    net_debt = [sub(d_, c) for d_, c in zip(debt, cash)]
    nd_ebitda = []
    for nd, e in zip(net_debt, ebitda):
        if nd is None or e in (None, 0) or e < 0:
            nd_ebitda.append(None)
        else:
            nd_ebitda.append(nd / e)
    int_exp = b.row_a("int_exp")
    ar_d, inv_d, ap_d = days(ar, rev), days(inv, cogs), days(ap, cogs)
    ccc = [None if a_ is None or i_ is None or p_ is None else a_ + i_ - p_ for a_, i_, p_ in zip(ar_d, inv_d, ap_d)]
    nwc = [None if a_ is None and i_ is None else (a_ or 0) + (i_ or 0) + (p_ or 0) - (ap_ or 0) - (ac or 0) - (el or 0) - (d_ or 0)
           for a_, i_, p_, ap_, ac, el, d_ in zip(ar, inv, b.row_a("prepaid"), ap, b.row_a("accrued"), b.row_a("employee_liab"), dr)]
    t4 = [("毛利率", ratio(gp, rev), fmt_pct), ("营业利润率", ratio(opi, rev), fmt_pct), ("净利率", ratio(ni, rev), fmt_pct),
          ("经营现金流 / 净利润", ratio(cfo, ni), fmt_x), ("自由现金流 / 收入", ratio(fcf, rev), fmt_pct),
          ("资本开支 / 收入", ratio([abs(x) if x is not None else None for x in capex], rev), fmt_pct),
          ("固定资产 / 总资产", ratio(ppe, ta), fmt_pct),
          ("应收天数", ar_d, fmt_days), ("存货天数", inv_d, fmt_days), ("应付天数", ap_d, fmt_days), ("现金转换周期", ccc, fmt_days),
          ("经营性营运资金 / 收入", ratio(nwc, rev), fmt_pct),
          ("净负债 / EBITDA", [("净现金" if nd is not None and nd < 0 else x) for nd, x in zip(net_debt, nd_ebitda)],
           lambda v: v if isinstance(v, str) else fmt_x(v)),
          ("利息覆盖（营业利润/利息支出）", ratio(opi, int_exp), fmt_x),
          ("商誉 + 无形 / 总资产", ratio([add(g, i) for g, i in zip(gw, intang)], ta), fmt_pct),
          ("SBC / 经营现金流", ratio(b.row_a("sbc"), cfo), fmt_pct)]
    lines.append(table("表 4 关键比率速览（ROIC 按 metrics.md 另算；一次性未剔除）", H, t4, fmt_pct))

    # 表 5 一次性候选
    lines.append("**表 5 一次性项目候选（模型核性质后填正式表）**\n")
    lines.append("| 财年 | 科目 | 金额 | 性质 | 剔除？ | 来源 |\n| :-- | :-- | --: | :-- | :-- | :-- |")
    found = False
    # 其他损益只在超过当年营业利润 2% 时才算候选，避免把零碎项当一次性
    for y, imp, rs, oth, o in zip(Y, b.row_a("impairment")[:-1], b.row_a("restructuring")[:-1], other[:-1], opi[:-1]):
        thresh = abs(o) * 0.02 if o else 0
        for name, v in (("减值", imp), ("重组", rs), ("其他损益", oth)):
            if v is not None and abs(v) > 0 and (name != "其他损益" or abs(v) > thresh):
                found = True
                lines.append(f"| {y} | {name} | {fmt_money(v, unit)} | 待核 | 待定 | 底稿 |")
    for r in data.get("records", []) or []:
        if isinstance(r, dict) and r.get("restated"):
            found = True
            lines.append(f"| {r.get('fy', r.get('year', ''))} | {r.get('metric', r.get('tag', ''))} 重述 | "
                         f"{fmt_money(r.get('value'), unit)}（原 {fmt_money(r.get('prior_value'), unit)}） | 待核 | 待定 | records |")
    if not found:
        lines.append("| — | 未发现候选 | | | | |")
    lines.append("")

    # 表 6 体检补充（fetch v0.4.0 字段；缺则 n/a）
    def ra(key):
        # TTM 时点数只在最近财年也有该指标时才用，避免底稿把多年前最后一次申报当"最新"
        annual_vals = [b.annual.get(key, {}).get(y) for y in Y]
        ttm_val = (b.ttm.get("instant") or {}).get(key) if annual_vals[-1] is not None else None
        return annual_vals + [ttm_val]
    due = {k: ra(k) for k in ("debt_due_1y", "debt_due_y2", "debt_due_y3", "debt_due_y4", "debt_due_y5", "debt_due_after_y5")}
    due_total = [add(*vals) for vals in zip(*due.values())]
    due_3y = [add(a_, b_, c_) for a_, b_, c_ in zip(due["debt_due_1y"], due["debt_due_y2"], due["debt_due_y3"])]
    debt_due_1y, coverage_gaps = current_obligations(b, due["debt_due_1y"])
    # Missing cash/investments cannot be silently omitted from the numerator.
    coverage_cash = [strict_add(c, i) for c, i in zip(b.row_a("cash"), b.row_a("sti"))]
    cash_cov = [div(c, d_) for c, d_ in zip(coverage_cash, debt_due_1y)]
    cur_ratio = ratio(ra("current_assets"), ra("current_liabilities"))
    quick = [div(sub(ca_, i_), cl) if ca_ is not None and cl not in (None, 0) else None
             for ca_, i_, cl in zip(ra("current_assets"), [x or 0 for x in inv], ra("current_liabilities"))]
    bad_debt = ratio(ra("allowance_doubtful_accounts"), [add(a_, al) for a_, al in zip(ar, ra("allowance_doubtful_accounts"))])
    inv_res = ratio(ra("inventory_reserve"), [add(i_, r_) for i_, r_ in zip(inv, ra("inventory_reserve"))])
    dep_rate = ratio(da, ra("ppe_gross"))
    dta = ratio(ra("deferred_tax_assets"), ta)
    int_paid_cov = ratio(cfo, b.row_a("interest_paid"))
    t6 = [("流动比率", cur_ratio, fmt_x), ("速动比率", quick, fmt_x),
          ("现金+短投 / 1 年内到期债务（含流动租赁）", cash_cov, fmt_x),
          ("1 年内到期债务（含流动租赁）", debt_due_1y, fmt_money),
          ("长期债务 1 年内到期本金（不含租赁）", due["debt_due_1y"], fmt_money), ("3 年内到期占比（本金）", ratio(due_3y, due_total), fmt_pct),
          ("经营现金流 / 利息实付", int_paid_cov, fmt_x),
          ("坏账准备 / 应收总额", bad_debt, fmt_pct), ("存货跌价准备 / 存货总额", inv_res, fmt_pct),
          ("折旧率（折旧摊销 / 固定资产原值）", dep_rate, fmt_pct), ("递延税资产 / 总资产", dta, fmt_pct),
          ("受限现金", ra("restricted_cash"), fmt_money)]
    lines.append(table("表 6 体检补充（偿债 / 流动性 / 资产质量；到期分布来自 10-K 附注 XBRL）", H, t6, fmt_pct, unit))

    if coverage_gaps:
        lines.append("**一年内偿债口径待核**：" + "、".join(coverage_gaps) +
                     " 的完整到期债务或流动租赁数据不足，覆盖率填 n/a。"
                     " short_term_debt 可能只含长期借款流动部分，或已含融资租赁；"
                     "不能与 debt_due_1y 机械相加。须按 records/tag_map 和原始附注核清短期借款、"
                     "一年内到期长期本金及两类流动租赁；未披露不视为零。\n")

    missing = meta.get("missing_metrics") or []
    if missing:
        lines.append("**底稿缺失指标（不是 0）**：" + "、".join(map(str, missing)) + "\n")
    checks = data.get("checks") or []
    failed = [c for c in checks if isinstance(c, dict) and c.get("pass") is False]
    if failed:
        lines.append("**勾稽未过**：" + "；".join(f"{c.get('check', c.get('name', '?'))} {c.get('year', '')}（差 {c.get('diff_pct', '?')}%）" for c in failed) + "\n")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--unit", type=float, default=1e6)
    a = p.parse_args()
    sys.stdout.write(render(load(a.path), a.years, a.unit))


if __name__ == "__main__":
    main()

