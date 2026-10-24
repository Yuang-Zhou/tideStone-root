#!/usr/bin/env python3
"""Re-extract a deliberately limited CAS statement dataset from saved official PDFs.

No network requests; no forecasts, valuation, or research conclusions. Outputs only
financials.json and validation.json next to this script. Requires pypdf.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

OUT = Path(__file__).resolve().parent
RAW = OUT.parents[1]
NUM = r"[-−]?\d+(?:,\d{3})*(?:\.\d+)?"

SPECS = {
    "annual_2023": {
        "title": "2023年年度报告", "published": "2024-03-16", "unit": "万元", "multiplier": 10000,
        "footer_offset": -1, "summary_page": 7, "summary_layout": "annual_2023",
        "current_period": ["2023-01-01", "2023-12-31"], "comparative_period": ["2022-01-01", "2022-12-31"],
        "balance_dates": ["2023-12-31", "2023-01-01"],
        "balance_date_note": "原表第二列为2023年1月1日；代表期初余额，未改写成2022年12月31日。",
        "sections": {"balance_sheet": [115, 117, "1、合并资产负债表", "2、母公司资产负债表"],
                     "income_statement": [119, 121, "3、合并利润表", "4、母公司利润表"],
                     "cash_flow_statement": [123, 125, "5、合并现金流量表", "6、母公司现金流量表"]},
        "url": "https://static.cninfo.com.cn/finalpage/2024-03-16/1219313047.PDF",
    },
    "annual_2024": {
        "title": "2024年年度报告", "published": "2025-03-15", "unit": "千元", "multiplier": 1000,
        "footer_offset": 0, "summary_page": 9, "summary_layout": "standard",
        "current_period": ["2024-01-01", "2024-12-31"], "comparative_period": ["2023-01-01", "2023-12-31"],
        "balance_dates": ["2024-12-31", "2023-12-31"],
        "sections": {"balance_sheet": [114, 116, "1、合并资产负债表", "2、母公司资产负债表"],
                     "income_statement": [119, 121, "3、合并利润表", "4、母公司利润表"],
                     "cash_flow_statement": [122, 124, "5、合并现金流量表", "6、母公司现金流量表"]},
        "url": "https://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF",
    },
    "annual_2025": {
        "title": "2025年年度报告", "published": "2026-03-10", "unit": "千元", "multiplier": 1000,
        "footer_offset": 0, "summary_page": 11, "summary_layout": "standard",
        "current_period": ["2025-01-01", "2025-12-31"], "comparative_period": ["2024-01-01", "2024-12-31"],
        "balance_dates": ["2025-12-31", "2024-12-31"],
        "sections": {"balance_sheet": [111, 113, "1、合并资产负债表", "2、母公司资产负债表"],
                     "income_statement": [116, 118, "3、合并利润表", "4、母公司利润表"],
                     "cash_flow_statement": [119, 121, "5、合并现金流量表", "6、母公司现金流量表"]},
        "url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
    },
    "interim_2026": {
        "title": "2026年半年度报告", "published": "2026-07-25", "unit": "千元", "multiplier": 1000,
        "footer_offset": 0, "summary_page": 7, "summary_layout": "standard",
        "current_period": ["2026-01-01", "2026-06-30"], "comparative_period": ["2025-01-01", "2025-06-30"],
        "balance_dates": ["2026-06-30", "2025-12-31"],
        "sections": {"balance_sheet": [72, 75, "1、合并资产负债表", "2、母公司资产负债表"],
                     "income_statement": [77, 79, "3、合并利润表", "4、母公司利润表"],
                     "cash_flow_statement": [80, 82, "5、合并现金流量表", "6、母公司现金流量表"]},
        "url": "https://static.cninfo.com.cn/finalpage/2026-07-25/1225441586.PDF",
    },
    "q3_2026": {
        "title": "2026年第三季度报告", "published": "2026-10-21", "unit": "千元", "multiplier": 1000,
        "footer_offset": 0, "summary_page": 1, "summary_layout": "quarterly",
        "current_period": ["2026-01-01", "2026-09-30"], "comparative_period": ["2025-01-01", "2025-09-30"],
        "balance_dates": ["2026-09-30", "2025-12-31"],
        "sections": {"balance_sheet": [5, 8, "1、合并资产负债表", "2、合并年初到报告期末利润表"],
                     "income_statement": [9, 11, "2、合并年初到报告期末利润表", "3、合并年初到报告期末现金流量表"],
                     "cash_flow_statement": [11, 12, "3、合并年初到报告期末现金流量表", "（二）"]},
        "url": "https://static.cninfo.com.cn/finalpage/2026-10-21/1225613175.PDF",
    },
}

FIELDS = {
    "balance_sheet": {
        "monetary_funds": "货币资金", "trade_receivables": "应收账款", "inventories": "存货",
        "current_assets": "流动资产合计", "noncurrent_assets": "非流动资产合计", "total_assets": "资产总计",
        "short_term_borrowings": "短期借款", "long_term_borrowings": "长期借款", "bonds_payable": "应付债券",
        "current_portion_of_noncurrent_liabilities": "一年内到期的非流动负债",
        "current_liabilities": "流动负债合计", "noncurrent_liabilities": "非流动负债合计",
        "total_liabilities": "负债合计", "parent_equity": "归属于母公司所有者权益合计",
        "minority_equity": "少数股东权益", "total_equity": "所有者权益合计",
    },
    "income_statement": {
        "revenue": "其中：营业收入", "cost_of_sales": "其中：营业成本", "selling_expenses": "销售费用",
        "research_and_development_expenses": "研发费用", "operating_profit": "三、营业利润",
        "profit_before_tax": "四、利润总额", "income_tax_expense": "减：所得税费用",
        "net_profit": "五、净利润", "net_profit_parent": "1.归属于母公司股东的净利润",
        "net_profit_minority": "2.少数股东损益",
    },
    "cash_flow_statement": {
        "operating_inflows": "经营活动现金流入小计", "operating_outflows": "经营活动现金流出小计",
        "operating_cash_flow": "经营活动产生的现金流量净额",
        "investing_inflows": "投资活动现金流入小计", "investing_outflows": "投资活动现金流出小计",
        "investing_cash_flow": "投资活动产生的现金流量净额",
        "cash_paid_for_long_lived_assets": "购建固定资产、无形资产和其他长期资产支付的现金",
        "financing_inflows": "筹资活动现金流入小计", "financing_outflows": "筹资活动现金流出小计",
        "financing_cash_flow": "筹资活动产生的现金流量净额",
        "fx_effect_on_cash": "四、汇率变动对现金及现金等价物的",
        "net_change_in_cash": "五、现金及现金等价物净增加额",
        "opening_cash_equivalents": "加：期初现金及现金等价物余额",
        "ending_cash_equivalents": "六、期末现金及现金等价物余额",
    },
}


def label_pattern(label):
    return r"\s*".join(re.escape(ch) for ch in label)


def dec(text):
    return Decimal(text.replace(",", "").replace("−", "-"))


def serialize_decimal(value):
    return format(value, "f")


def extract_reports():
    reports, missing = {}, []
    for rid, spec in SPECS.items():
        path = RAW / "OFFICIAL" / (rid + ".pdf")
        if not path.exists():
            missing.append({"source_id": rid, "reason": "原始PDF未到位"})
            continue
        reader = PdfReader(path)
        cache = {}
        def page(n):
            if n not in cache:
                cache[n] = reader.pages[n - 1].extract_text()
            return cache[n]
        if spec["title"] not in re.sub(r"\s+", "", page(1)):
            raise ValueError(f"Title mismatch: {rid}")
        report = {"source_id": rid, "title": "宁德时代新能源科技股份有限公司" + spec["title"],
                  "relative_path_from_raw": f"OFFICIAL/{rid}.pdf", "source_url": spec["url"],
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pdf_pages": len(reader.pages),
                  "announcement_date": spec["published"], "currency": "CNY", "accounting_basis": "CAS",
                  "scope": "合并", "raw_unit": spec["unit"], "raw_unit_cny_multiplier": spec["multiplier"],
                  "amount_precision_cny": 100 if spec["unit"] == "万元" else 1000,
                  "current_period": spec["current_period"], "comparative_period": spec["comparative_period"],
                  "balance_dates": spec["balance_dates"], "balance_date_note": spec.get("balance_date_note"),
                  "statements": {}, "summary_checks_input": {}}
        for section, (first, last, begin, end) in spec["sections"].items():
            chunks, active = [], False
            for n in range(first, last + 1):
                text = page(n)
                if not active:
                    start = re.search(label_pattern(begin), text)
                    if not start:
                        continue
                    text, active = text[start.end():], True
                stop = re.search(label_pattern(end), text)
                if stop:
                    text = text[:stop.start()]
                chunks.append((n, text))
                if stop:
                    break
            if not active:
                raise ValueError(f"Section header missing: {rid}/{section}")
            metrics = {}
            for metric, label in FIELDS[section].items():
                hits = []
                for n, text in chunks:
                    # Prevent matching '流动...' inside '非流动...' or a total
                    # inside a parent total; labels start at a physical text line.
                    pat = r"(?m)^\s*" + label_pattern(label) + r"[^0-9]{0,90}?(" + NUM + r")\s+(" + NUM + r")"
                    hits.extend((n, m) for m in re.finditer(pat, text))
                if len(hits) != 1:
                    missing.append({"source_id": rid, "statement": section, "metric": metric,
                                    "reason": f"exact row matches={len(hits)}; 未猜值"})
                    continue
                n, match = hits[0]
                vals = [match.group(1), match.group(2)]
                metrics[metric] = {"label": label, "raw_current": vals[0], "raw_comparative": vals[1],
                                   "current_cny": serialize_decimal(dec(vals[0]) * spec["multiplier"]),
                                   "comparative_cny": serialize_decimal(dec(vals[1]) * spec["multiplier"]),
                                   "pdf_page": n, "printed_page": n + spec["footer_offset"],
                                   "source_excerpt": re.sub(r"\s+", " ", match.group(0)).strip()}
            report["statements"][section] = metrics
        summary_text = re.sub(r"\s+", " ", page(spec["summary_page"]))
        labels = {"revenue": "营业收入", "net_profit_parent": "归属于上市公司股东的净利润",
                  "operating_cash_flow": "经营活动产生的现金流量净额"}
        for metric, label in labels.items():
            m = re.search(label_pattern(label), summary_text)
            if not m:
                missing.append({"source_id": rid, "summary_metric": metric, "reason": "摘要行未定位"})
                continue
            tail = summary_text[m.end():]
            # Capture just this numeric row, including quarterly '--' placeholders.
            row = re.match(r"[^0-9]{0,20}?((?:" + NUM + r"%?\s+|--\s+){1,8})", tail)
            if not row:
                missing.append({"source_id": rid, "summary_metric": metric, "reason": "摘要数字行未定位"})
                continue
            toks = re.findall(NUM + r"%?|--", row.group(1))
            layout = spec["summary_layout"]
            if layout == "quarterly":
                current, prior, yoy = toks[2], None, toks[3]
            elif layout == "annual_2023":
                current, prior, yoy = toks[0], toks[2], toks[3]
            else:
                current, prior, yoy = toks[0], toks[1], toks[2]
            if not yoy.endswith("%"):
                raise ValueError(f"Yoy column mismatch: {rid}/{metric}: {toks}")
            report["summary_checks_input"][metric] = {
                "raw_current": current, "raw_comparative": prior, "reported_yoy_percent": yoy[:-1],
                "pdf_page": spec["summary_page"], "printed_page": spec["summary_page"] + spec["footer_offset"],
                "source_excerpt": re.sub(r"\s+", " ", summary_text[m.start():m.end()] + row.group(0)).strip(),
                "period_note": "前三季累计，不是单独第三季" if layout == "quarterly" else "报告期累计"}
        reports[rid] = report
    return reports, missing


def validate(reports, missing):
    checks, suspects, rounding = [], [], []
    def record(cid, rid, lhs, rhs, tolerance, formula, refs, explained=None):
        diff = lhs - rhs
        status = "pass_exact" if not diff else ("pass_with_rounding" if abs(diff) <= tolerance else ("explained_difference" if explained else "fail"))
        item = {"id": cid, "source_id": rid, "status": status, "lhs": str(lhs), "rhs": str(rhs),
                "difference": str(diff), "tolerance": str(tolerance), "formula": formula, "source_pointers": refs}
        if explained:
            item["explanation"] = explained
        checks.append(item)
        if status == "pass_with_rounding":
            rounding.append(item)
        elif status == "fail":
            suspects.append(item)
    identities = [
        ("assets_equal_liabilities_plus_equity", "balance_sheet", "total_assets", ["total_liabilities", "total_equity"]),
        ("asset_subtotals", "balance_sheet", "total_assets", ["current_assets", "noncurrent_assets"]),
        ("liability_subtotals", "balance_sheet", "total_liabilities", ["current_liabilities", "noncurrent_liabilities"]),
        ("equity_subtotals", "balance_sheet", "total_equity", ["parent_equity", "minority_equity"]),
        ("profit_attribution", "income_statement", "net_profit", ["net_profit_parent", "net_profit_minority"]),
    ]
    for rid, report in reports.items():
        precision = Decimal(report["amount_precision_cny"])
        def value(section, name, col):
            return Decimal(report["statements"][section][name][col + "_cny"])
        def refs(section, names):
            return [{"file": report["relative_path_from_raw"], "sha256": report["sha256"],
                     "metric": n, "pdf_page": report["statements"][section][n]["pdf_page"]} for n in names]
        for col in ["current", "comparative"]:
            for cid, sec, lhsname, rhsnames in identities:
                if not all(n in report["statements"][sec] for n in [lhsname] + rhsnames):
                    continue
                record(cid + "/" + col, rid, value(sec, lhsname, col), sum(value(sec,n,col) for n in rhsnames),
                       precision * Decimal("1.5"), lhsname + " = " + " + ".join(rhsnames), refs(sec,[lhsname] + rhsnames))
            sec = "income_statement"
            names = ["profit_before_tax", "income_tax_expense", "net_profit"]
            if all(n in report["statements"][sec] for n in names):
                record("pretax_less_tax/" + col, rid, value(sec,"net_profit",col),
                       value(sec,"profit_before_tax",col) - value(sec,"income_tax_expense",col), precision * Decimal("1.5"),
                       "net_profit = profit_before_tax - income_tax_expense", refs(sec,names))
            sec = "cash_flow_statement"
            for group in ["operating", "investing", "financing"]:
                names = [group+"_inflows", group+"_outflows", group+"_cash_flow"]
                if all(n in report["statements"][sec] for n in names):
                    record(group+"_cash_subtotals/"+col, rid, value(sec,names[2],col), value(sec,names[0],col)-value(sec,names[1],col),
                           precision*Decimal("1.5"), names[2]+" = "+names[0]+" - "+names[1], refs(sec,names))
            names = ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "fx_effect_on_cash", "net_change_in_cash"]
            if all(n in report["statements"][sec] for n in names):
                record("cash_flow_bridge/"+col, rid, value(sec,names[-1],col),sum(value(sec,n,col) for n in names[:-1]),
                       precision*Decimal("2.5"), "net_change_in_cash = operating + investing + financing + fx",refs(sec,names))
            names = ["opening_cash_equivalents", "net_change_in_cash", "ending_cash_equivalents"]
            if all(n in report["statements"][sec] for n in names):
                record("cash_balance_bridge/"+col, rid,value(sec,names[2],col),value(sec,names[0],col)+value(sec,names[1],col),
                       precision*Decimal("1.5"),"ending_cash_equivalents = opening_cash_equivalents + net_change_in_cash",refs(sec,names))
        for metric, summary in report["summary_checks_input"].items():
            sec = "cash_flow_statement" if metric == "operating_cash_flow" else "income_statement"
            if metric not in report["statements"][sec]:
                continue
            rawmult = Decimal(report["raw_unit_cny_multiplier"])
            source_refs = refs(sec,[metric]) + [{"file":report["relative_path_from_raw"], "sha256":report["sha256"],"pdf_page":summary["pdf_page"],"table":"主要会计数据和财务指标"}]
            record("summary_current/"+metric,rid,value(sec,metric,"current"),dec(summary["raw_current"])*rawmult,
                   precision,"三表本期值 = 摘要本期值",source_refs)
            if summary["raw_comparative"] is not None:
                record("summary_yoy_base/"+metric,rid,value(sec,metric,"comparative"),dec(summary["raw_comparative"])*rawmult,
                       precision,"三表上年同期 = 摘要上年同期",source_refs)
            current, prior = value(sec,metric,"current"), value(sec,metric,"comparative")
            if prior:
                record("reported_yoy/"+metric,rid,(current/prior-1)*100,Decimal(summary["reported_yoy_percent"]),
                       Decimal("0.0051"),"(current / comparative - 1) * 100 = disclosed percentage (两位小数)",source_refs)
    # Consecutive annual reports: compare like periods, retaining revisions.
    for older,newer in [("annual_2023","annual_2024"),("annual_2024","annual_2025")]:
        if older not in reports or newer not in reports:
            continue
        a,b = reports[older],reports[newer]
        for sec in FIELDS:
            for metric in sorted(set(a["statements"][sec]) & set(b["statements"][sec])):
                x,y=a["statements"][sec][metric],b["statements"][sec][metric]
                explained = None
                if older == "annual_2023" and metric in ["cost_of_sales","selling_expenses"]:
                    expected_delta = Decimal("14911696000") * (1 if metric == "cost_of_sales" else -1)
                    if abs(Decimal(y["comparative_cny"]) - Decimal(x["current_cny"]) - expected_delta) <= Decimal("550"):
                        explained = "2024年报物理第162–163页：执行企业会计准则解释第18号，保证类质量保证费用追溯从销售费用重分类至营业成本；调整额14,911,696千元。已核差额在单位舍入容差内符合该金额；保留两版，不合并。"
                record("cross_report/"+older+"/"+metric,newer,Decimal(y["comparative_cny"]),Decimal(x["current_cny"]),
                       Decimal(a["amount_precision_cny"]+b["amount_precision_cny"])/2,
                       "后一年年报比较期 = 原年度年报本期（已做单位换算）",
                       [{"file":a["relative_path_from_raw"],"sha256":a["sha256"],"pdf_page":x["pdf_page"]},
                        {"file":b["relative_path_from_raw"],"sha256":b["sha256"],"pdf_page":y["pdf_page"]}],explained)
    # A visible discrepancy discovered while inspecting the source summaries is
    # quarantined outside the 40 monetary fields. Do not resolve it by guessing.
    supplementary = []
    if "annual_2023" in reports and "annual_2024" in reports:
        a,b = reports["annual_2023"], reports["annual_2024"]
        ar = PdfReader(RAW/a["relative_path_from_raw"])
        br = PdfReader(RAW/b["relative_path_from_raw"])
        ap = ar.pages[6].extract_text()
        bp = br.pages[8].extract_text()
        pattern = label_pattern("基本每股收益") + r"[^0-9]{0,20}?(" + NUM + r")\s+(" + NUM + r")"
        av,bv = re.search(pattern,ap),re.search(pattern,bp)
        if av and bv and dec(av.group(1)) != dec(bv.group(2)):
            item={"id":"supplementary/basic_eps_2023_cross_report", "metric":"basic_eps", "period":"2023",
                  "status":"needs_review", "scope":"outside_40_core_fields", "unit":"CNY/share",
                  "original_report_value":av.group(1),"later_comparative_value":bv.group(2),
                  "source_pointers":[{"file":a["relative_path_from_raw"],"sha256":a["sha256"],"pdf_page":7,"printed_page":6},
                                     {"file":b["relative_path_from_raw"],"sha256":b["sha256"],"pdf_page":9,"printed_page":9}],
                  "note":"现场读取两份原文摘要时发现，2023年原报该页已视觉确认。未在本轮核定差异原因或股数追溯，EPS未进入financials.json核心字段，后续研究前需单独复核。"}
            supplementary.append(item)
            suspects.append(item)
    return {"schema_version":1,"validation_scope":"有限三表核心字段机械勾稽，不是完整财务模型审计或投资判断",
            "counts":dict(Counter(x["status"] for x in checks)),"checks":checks,"suspect_metrics":suspects,
            "supplementary_observations":supplementary,
            "rounding_differences":rounding,"missing_fields":missing,
            "not_performed":["原始凭证或外部审计复核","78字段完整模型","分部和地区口径核验","EPS及股数追溯重述核对", "净利润至经营现金流补充资料逐项桥接", "现金等价物与货币资金受限项目逐项桥接", "2022年原始年报独立对照", "2026Q3单季三表提取"]}


def main():
    reports,missing=extract_reports()
    basis=RAW/"OFFICIAL/accounting_basis_2026.pdf"
    basis_metadata={"relative_path_from_raw":"OFFICIAL/accounting_basis_2026.pdf", "sha256":hashlib.sha256(basis.read_bytes()).hexdigest(),
                    "pdf_pages":[1,2],"note":"公告称自2025年年度财务报告开始统一采用中国企业会计准则；本数据包只使用A股CAS报表，不混用H股招股书IFRS历史数据。"} if basis.exists() else None
    dataset={"schema_version":1,"company":{"name":"宁德时代新能源科技股份有限公司","primary_ticker":"300750.SZ","other_listing":"03750.HK"},
             "as_of":"2026-10-24","purpose":"入库材料准备：有限三表基础摘录，非研究结论、预测或估值",
             "extraction_method":"pypdf读取本地PDF；固定合并报表范围与行名匹配；保留原值、币种、原单位、换算值及逐指标物理页码",
             "currency":"CNY","normalized_unit":"CNY元（十进制字符串）", "scope":"合并",
             "accounting_basis_source":basis_metadata,
             "coverage_notes":["最近三份年度报告为2023、2024、2025年报；2022年流量取自2023年报比较期。", "2023年报期初资产负债表日期保留为2023-01-01。", "2026年中期及前三季均为累计期间，未经审计。", "2023年原报以万元披露，2024年起所选报告以千元披露；原值不覆盖。", "2024年报执行准则解释18号追溯重分类2023年质保费用，成本及销售费用不可直接拼接。", "购建长期资产支付的现金仅为该报表行，不等同完整资本开支或自由现金流。", "货币资金与现金及现金等价物是不同定义，未将二者强行相等。"],
             "reports":reports,"missing_fields":missing,
             "preferred_observation_map":{"2022_flows":"annual_2023/comparative", "2022_closing_balance_proxy":"annual_2023/comparative (原表2023-01-01)",
                                          "2023":"annual_2024/comparative (营业成本/销售费用为追溯调整后)",
                                          "2024":"annual_2025/comparative","2025":"annual_2025/current","2026H1":"interim_2026/current","2026_9M":"q3_2026/current"}}
    validation=validate(reports,missing)
    for filename,obj in [("financials.json",dataset),("validation.json",validation)]:
        (OUT/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"reports":len(reports),"metrics_per_report":{r:sum(len(v) for v in x["statements"].values()) for r,x in reports.items()},
                      "counts":validation["counts"],"missing_fields":missing,"suspect_metrics":validation["suspect_metrics"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
