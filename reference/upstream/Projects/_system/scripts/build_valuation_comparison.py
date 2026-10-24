#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the all-company price target comparison dashboard.

Current prices come from the daily market-data CSV files. Twelve-month targets
come from valuation_registry.json. Three-year targets are fixed per-share values
stored in three_year_valuation_registry.json, migrated from the legacy market-cap
dashboard once and then maintained as research data.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

from site_chrome import head_links, page_open, page_close   # 2026-10-20 统一页头页脚（同目录）


BASE = Path(__file__).resolve().parents[2]
SYSTEM = BASE / "_system"
SRC = BASE / "基本面分析汇总"
MARKET_DATA = SYSTEM / "market_data"
COMPANIES_PATH = SYSTEM / "companies.json"
VALUATION_PATH = SYSTEM / "valuation_registry.json"
THREE_YEAR_PATH = SYSTEM / "three_year_valuation_registry.json"
OUTPUT_PATH = SRC / "组合三年估值看板.html"

TICKER_ALIASES = {"SATS": "ECHO"}
NUMERIC_SUFFIXES = {
    "002555": "002555.SZ",
    "300054": "300054.SZ",
    "300750": "300750.SZ",
    "301086": "301086.SZ",
    "601872": "601872.SH",
    "688362": "688362.SH",
    "920186": "920186.BJ",
}
SECTOR_ORDER = ["10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60"]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_ticker(raw: str | None) -> str | None:
    if not raw:
        return None
    ticker = raw.strip().upper()
    ticker = re.sub(r"\.(O|N)$", "", ticker)
    ticker = TICKER_ALIASES.get(ticker, ticker)
    return NUMERIC_SUFFIXES.get(ticker, ticker)


def currency_symbol(ticker: str, registry_entry: dict | None = None) -> str:
    code = (registry_entry or {}).get("currency")
    if code == "HKD" or ticker.endswith(".HK"):
        return "HK$"
    if code == "CNY" or re.search(r"\.(SZ|SH|BJ)$", ticker):
        return "¥"
    return "$"


def clean_target_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("**", "").strip()
    if not re.search(r"\d", text):
        return ""
    text = re.split(r"[（(]", text, maxsplit=1)[0].strip()
    text = re.split(r"\s*/\s*", text, maxsplit=1)[0].replace("/股", "").strip()
    text = text.replace("港元", "").replace("港币", "").replace("美元", "").replace("元", "").strip()
    return text


def target_number(value: object) -> float | None:
    text = clean_target_text(value).replace(",", "")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None
    if len(nums) >= 2 and re.search(r"\d\s*[-–—]\s*\d", text):
        return (nums[0] + nums[1]) / 2
    return nums[0]


def short_rating(value: object) -> str:
    text = str(value or "").strip()
    for label in ("强烈买入", "买入", "增持", "持有", "减持", "强烈卖出", "卖出", "研究中"):
        if label in text:
            return label
    if "BUY" in text.upper():
        return "买入"
    if "HOLD" in text.upper():
        return "持有"
    if "SELL" in text.upper():
        return "卖出"
    return "待评估"


def last_close(ticker: str) -> tuple[float | None, str | None]:
    path = MARKET_DATA / f"{ticker}.csv"
    if not path.exists():
        return None, None
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    for line in reversed(rows):
        parts = line.strip().split(",")
        if len(parts) >= 5 and parts[0] != "date":
            try:
                close = float(parts[4])
                if close > 0:
                    return close, parts[0]
            except ValueError:
                continue
    return None, None


def close_near(ticker: str, as_of: str) -> tuple[float | None, str | None]:
    path = MARKET_DATA / f"{ticker}.csv"
    if not path.exists():
        return None, None
    candidates: list[tuple[str, float]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                close = float(row["close"])
                if close > 0:
                    candidates.append((row["date"], close))
            except (KeyError, TypeError, ValueError):
                continue
    if not candidates:
        return None, None
    before = [x for x in candidates if x[0] <= as_of]
    chosen = before[-1] if before else candidates[0]
    return chosen[1], chosen[0]


def parse_js_number(line: str, key: str) -> float | None:
    match = re.search(rf"(?:^|,)\s*{re.escape(key)}\s*:\s*(null|-?\d+(?:\.\d+)?)", line)
    if not match or match.group(1) == "null":
        return None
    return float(match.group(1))


def parse_js_string(line: str, key: str) -> str | None:
    match = re.search(rf"(?:^|,)\s*{re.escape(key)}\s*:\s*'([^']*)'", line)
    return match.group(1) if match else None


def explicit_snapshot_price(text: str) -> float | None:
    patterns = [
        r"(?:现价|当前股价)\s*(?:约|~)?\s*(?:HK\$|US\$|\$|¥|￥)?\s*(\d+(?:\.\d+)?)",
        r"(?:现价|当前股价)\s*(\d+(?:\.\d+)?)\s*港元",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def migrate_legacy_dashboard(source: Path, output: Path, snapshot_date: str) -> dict:
    """Migrate legacy market-cap rows into fixed per-share three-year targets."""
    text = source.read_text(encoding="utf-8-sig")
    companies: dict[str, dict] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("{n:'"):
            continue
        ticker = normalize_ticker(parse_js_string(line, "t"))
        if not ticker:
            continue
        current_cap = parse_js_number(line, "cur")
        metric_value = parse_js_number(line, "d")
        multiple = parse_js_number(line, "mult")
        net_debt = parse_js_number(line, "nd") or 0.0
        fixed = parse_js_number(line, "fixed")
        valuation_type = parse_js_string(line, "mt") or "equity"
        if valuation_type == "fixed":
            target_cap = fixed
        elif metric_value is not None and multiple is not None:
            target_cap = metric_value * multiple - net_debt if valuation_type == "ev" else metric_value * multiple
        else:
            target_cap = None
        catalyst = parse_js_string(line, "cat") or ""
        anchor_price = explicit_snapshot_price(catalyst)
        anchor_source = "报告摘要中的现价"
        anchor_date = None
        if anchor_price is None:
            anchor_price, anchor_date = close_near(ticker, snapshot_date)
            anchor_source = f"本地行情 {anchor_date or snapshot_date}"
        shares_b = current_cap / anchor_price if current_cap and anchor_price else None
        target_price_3y = target_cap / shares_b if target_cap is not None and shares_b else None
        companies[ticker] = {
            "name": parse_js_string(line, "n") or ticker,
            "target_year": 2028,
            "valuation_method": parse_js_string(line, "m") or "",
            "valuation_type": valuation_type,
            "metric_value_b": metric_value,
            "target_multiple": multiple,
            "net_debt_b": net_debt,
            "target_market_cap_b": target_cap,
            "share_equivalent_b": shares_b,
            "target_price_3y": target_price_3y,
            "currency_symbol": parse_js_string(line, "ccy") or "$",
            "anchor_market_cap_b": current_cap,
            "anchor_price": anchor_price,
            "anchor_price_source": anchor_source,
            "anchor_date": anchor_date,
            "source": "legacy_dashboard_migration",
        }
    payload = {
        "schema_version": 1,
        "updated_at": date.today().isoformat(),
        "target_horizon": "2028E",
        "note": "三年目标价为研究锚；每日构建只更新现价，不自动改变目标价。share_equivalent_b需在拆股、ADS比例变化或重大增发回购后复核。",
        "companies": companies,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


ZONE_BUY = ("强烈买入", "买入", "增持")
ZONE_SELL = ("减持", "卖出", "强烈卖出")


def parse_zones(zones: object) -> list[tuple[str, float, float]]:
    """把 valuation_registry 的 zones 文本解析成 (标签, 下限, 上限)。

    先剥掉括号注释和分号后的补充说明——它们常含 ">20%" 之类的百分比，
    会被误读成区间方向。
    """
    parsed: list[tuple[str, float, float]] = []
    for zone in zones or []:
        label = str((zone or {}).get("label") or "").strip()
        text = re.sub(r"[（(][^）)]*[）)]", "", str((zone or {}).get("range") or ""))
        text = re.split(r"[；;]", text)[0].replace(",", "")
        text = text.replace("≤", "<=").replace("≥", ">=").replace("–", "-").replace("—", "-")
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
        if not nums:
            continue
        if re.search(r"^\s*<", text) or "以下" in text or "低于" in text:
            parsed.append((label, float("-inf"), nums[0]))
        elif re.search(r"^\s*>", text) or "以上" in text or "高于" in text:
            parsed.append((label, nums[0], float("inf")))
        elif len(nums) >= 2:
            parsed.append((label, min(nums[:2]), max(nums[:2])))
    return parsed


def zone_for_price(zones: object, price: float | None) -> str | None:
    if price is None:
        return None
    for label, lo, hi in parse_zones(zones):
        if lo <= price <= hi:
            return label
    return None


def zone_conflict(zone: str | None) -> str | None:
    """三年目标价仍落在今天的买入区间——说明三年目标价明显偏低，需复核。

    反向（三年目标价高过减持/卖出区）是正常现象：zones 是近期操作带，
    三年目标价本就应当高于它，因此不作为红旗。
    """
    if zone and any(k in zone for k in ZONE_BUY):
        return f"三年目标价仍落在{zone}——三年后价格还在今天的买入区间内"
    return None


def cagr(target: float | None, base: float | None) -> float | None:
    if not target or not base or target <= 0 or base <= 0:
        return None
    return (target / base) ** (1 / 3) - 1


def fmt_price(value: float | None, symbol: str) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    digits = 2 if value < 1000 else 1
    number = f"{value:,.{digits}f}".rstrip("0").rstrip(".")
    return f"{symbol}{number}"


def build_rows() -> tuple[list[dict], str | None]:
    companies_data = load_json(COMPANIES_PATH)
    valuation_data = load_json(VALUATION_PATH).get("companies", {})
    three_year_data = load_json(THREE_YEAR_PATH).get("companies", {}) if THREE_YEAR_PATH.exists() else {}
    sector_names = companies_data.get("gics_sector_names", {})
    rows: list[dict] = []
    latest_dates: list[str] = []
    for ticker, company in companies_data.get("companies", {}).items():
        ticker = normalize_ticker(ticker) or ticker
        valuation = valuation_data.get(ticker, {})
        three_year = three_year_data.get(ticker, {})
        price, price_date = last_close(ticker)
        if price_date:
            latest_dates.append(price_date)
        symbol = currency_symbol(ticker, valuation)
        target_12m = target_number(valuation.get("target_price"))
        target_3y = three_year.get("target_price_3y")
        try:
            target_3y = float(target_3y) if target_3y is not None else None
        except (TypeError, ValueError):
            target_3y = None
        upside_12m = target_12m / price - 1 if price and target_12m else None
        total_3y = target_3y / price - 1 if price and target_3y else None
        cagr_3y = cagr(target_3y, price)

        anchor_price = three_year.get("anchor_price")
        try:
            anchor_price = float(anchor_price) if anchor_price is not None else None
        except (TypeError, ValueError):
            anchor_price = None
        anchor_drift = price / anchor_price - 1 if price and anchor_price else None
        cagr_from_anchor = cagr(target_3y, anchor_price)

        base_price = three_year.get("base_scenario_price")
        try:
            base_price = float(base_price) if base_price is not None else None
        except (TypeError, ValueError):
            base_price = None
        base_cagr_3y = cagr(base_price, price)
        vs_base = three_year.get("vs_base")
        nearest = three_year.get("scenario_nearest")

        rating_short = short_rating(valuation.get("rating"))
        zone_3y = zone_for_price(valuation.get("zones"), target_3y)

        flags: list[dict] = []
        if target_3y and target_12m and target_3y < target_12m:
            flags.append({"level": "red", "label": "倒挂",
                          "title": "三年目标价低于研究目标价——模型隐含先涨后跌"})
        if vs_base is not None and vs_base < 0.98:
            flags.append({"level": "red", "label": "低于基准",
                          "title": f"三年目标价仅为基准情景价的 {vs_base:.0%}"})
        if nearest == "above_bull":
            flags.append({"level": "amber", "label": "超乐观档",
                          "title": "三年目标价高于乐观情景价，需确认由业绩增长支撑"})
        if anchor_drift is not None and abs(anchor_drift) > 0.20:
            flags.append({"level": "amber", "label": "锚点漂移",
                          "title": f"现价较锚点 {anchor_drift:+.0%}，三年回报已被入场价吃掉一部分"})
        conflict = zone_conflict(zone_3y)
        if conflict:
            flags.append({"level": "red", "label": "仍在买入区", "title": conflict})

        sector_code = str(company.get("gics", {}).get("sector") or "")
        rows.append({
            "ticker": ticker,
            "name": company.get("name_cn") or company.get("name_en") or valuation.get("name") or ticker,
            "name_en": company.get("name_en") or "",
            "sector_code": sector_code,
            "sector": sector_names.get(sector_code, "其他"),
            "price": price,
            "price_text": fmt_price(price, symbol),
            "price_date": price_date,
            "target_12m": target_12m,
            "target_12m_text": fmt_price(target_12m, symbol),
            "target_12m_raw": valuation.get("target_price") or "",
            "upside_12m": upside_12m,
            "target_3y": target_3y,
            "target_3y_text": fmt_price(target_3y, symbol),
            "total_3y": total_3y,
            "cagr_3y": cagr_3y,
            "target_year": three_year.get("target_year"),
            "method": three_year.get("valuation_method") or "",
            "anchor_price": anchor_price,
            "anchor_price_text": fmt_price(anchor_price, symbol),
            "anchor_date": three_year.get("anchor_date") or "",
            "anchor_drift": anchor_drift,
            "cagr_from_anchor": cagr_from_anchor,
            "base_price": base_price,
            "base_price_text": fmt_price(base_price, symbol),
            "base_cagr_3y": base_cagr_3y,
            "vs_base": vs_base,
            "scenario_nearest": nearest or "",
            "zone_3y": zone_3y or "",
            "flags": flags,
            "needs_recheck": bool(three_year.get("needs_recheck")),
            "recheck_level": three_year.get("recheck_level") or "",
            "recheck_reason": three_year.get("recheck_reason") or [],
            "rating": rating_short,
            "rating_raw": valuation.get("rating") or "",
            "currency": symbol,
            "has_3y": target_3y is not None,
        })
    order = {code: index for index, code in enumerate(SECTOR_ORDER)}
    rows.sort(key=lambda r: (order.get(r["sector_code"], 999), r["name"]))
    return rows, max(latest_dates) if latest_dates else None


def json_for_script(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build_html(rows: list[dict], latest_date: str | None) -> str:
    coverage_12m = sum(r["target_12m"] is not None for r in rows)
    coverage_3y = sum(r["target_3y"] is not None for r in rows)
    red_rows = sum(any(f["level"] == "red" for f in r["flags"]) for r in rows)
    recheck_rows = sum(r["needs_recheck"] for r in rows)
    dates = sorted({r["price_date"] for r in rows if r["price_date"]})
    price_asof = latest_date or "无行情"
    data_json = json_for_script(rows)
    # 2026-10-20：给首页入口卡的摘要（build_site.py 读）
    try:
        (BASE / "_system" / "valuation_comparison_summary.json").write_text(json.dumps({
            "rows": len(rows), "coverage_12m": coverage_12m, "coverage_3y": coverage_3y,
            "red_rows": red_rows, "recheck_rows": recheck_rows, "price_asof": price_asof}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print("  ! 摘要 json 写入失败（不影响看板）:", e)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公司目标价对比</title>
{head_links()}<style>
/* 2026-10-20：颜色改走 site.css 的变量，本页只留布局 */
:root{{--bg:var(--paper);--green:var(--up);--green-bg:var(--up-bg);--red:var(--down);--red-bg:var(--down-bg);--amber:var(--warn);--amber-bg:var(--warn-bg);--navy:var(--accent);--shadow:none}}
.page{{font-size:14px;line-height:1.5}} .eyebrow{{margin-bottom:6px}}
.lede{{color:var(--muted);font-size:14px;margin:6px 0 0;max-width:760px}}
.hero{{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;margin-bottom:25px}} .asof{{text-align:right;color:var(--muted);font-size:12px;white-space:nowrap}} .asof strong{{display:block;color:var(--ink);font-size:14px;margin-bottom:2px}}
.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}} .stat{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px 20px}}
.stat .k{{color:var(--muted);font-size:12px}} .stat .v{{font-size:28px;font-weight:700;line-height:1.1;margin-top:4px}} .stat .s{{font-size:11px;color:var(--muted);margin-top:1px}}
.controls{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:10px 12px;margin-bottom:12px}}
input,select,button{{font:inherit}} input,select{{border:1px solid var(--line);background:var(--panel);border-radius:8px;padding:8px 12px;color:var(--ink)}} input[type=search]{{background:var(--bg)}} input{{width:240px}} select{{min-width:150px}} button{{border:0;background:transparent;color:var(--accent);padding:8px 10px;cursor:pointer}} button:hover{{color:var(--accent-dark)}}
.result{{margin-left:auto;color:var(--muted);font-size:12px}} .table-shell{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);overflow:auto;max-height:72vh}}
table{{width:100%;border-collapse:separate;border-spacing:0;min-width:1360px}} th{{position:sticky;top:0;z-index:3;background:var(--bg);color:var(--muted);font-size:12px;font-weight:600;text-align:right;padding:11px 14px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}}
th:first-child{{left:0;z-index:5;text-align:left}} td{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} td:first-child{{position:sticky;left:0;z-index:2;background:var(--panel);text-align:left;min-width:220px}} tbody tr:hover td{{background:var(--bg)}} tbody tr:hover td:first-child{{background:var(--bg)}}
.company{{font-weight:720;font-size:14px}} .meta{{color:var(--muted);font-size:11px;margin-top:2px}}
td:first-child .company,td:first-child .meta{{max-width:212px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} .sector{{display:inline-block;padding:1px 8px;border-radius:10px;border:1px solid var(--line);color:var(--muted);font-size:12px}}
.price{{font-weight:760;font-size:15px}} .subnum{{font-size:11px;color:var(--muted);margin-top:2px}} .metric{{display:flex;justify-content:flex-end;align-items:center;gap:8px}} .pill{{display:inline-flex;align-items:center;justify-content:center;min-width:60px;padding:2px 7px;border-radius:6px;font-size:12px;font-weight:700}}
.positive{{color:var(--green)}} .negative{{color:var(--red)}} .pill.positive{{background:var(--green-bg)}} .pill.negative{{background:var(--red-bg)}} .pill.neutral{{background:var(--bg);color:var(--muted)}}
.rating{{font-size:12px;font-weight:700}} .rating.buy{{color:var(--green)}} .rating.sell{{color:var(--red)}} .rating.hold{{color:var(--amber)}} .missing{{color:var(--muted)}} .method{{max-width:160px;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:12px}}
.flags{{margin-top:4px;display:flex;gap:4px;justify-content:flex-end;flex-wrap:wrap}} .flag{{font-size:11px;font-weight:600;padding:1px 6px;border-radius:5px;cursor:help}} .flag.red{{background:var(--red-bg);color:var(--red)}} .flag.amber{{background:var(--amber-bg);color:var(--amber)}}
.note{{margin-top:14px;color:var(--muted);font-size:12px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}} details{{max-width:900px}} summary{{cursor:pointer;color:var(--ink);font-weight:650}} .back{{color:var(--accent);text-decoration:none;white-space:nowrap}}
@media(max-width:800px){{td:first-child{{min-width:0;padding-left:10px;padding-right:8px}}td:first-child .company,td:first-child .meta{{max-width:124px}}.meta .en{{display:none}}.page{{padding:0}}.hero{{align-items:flex-start;flex-direction:column}}.asof{{text-align:left}}.stats{{grid-template-columns:repeat(2,1fr)}}.controls{{align-items:stretch}}input,select{{width:100%;min-width:0}}.result{{margin-left:0}}.table-shell{{max-height:none}}.note{{flex-direction:column}}}}
</style>
</head>
<body>
{page_open("valuation", f"现价更新至 {html.escape(price_asof)}")}<div class="page">
<section class="hero"><div><div class="eyebrow">Investment research · valuation</div><h1>公司目标价对比</h1><p class="lede">把现价、研究目标价与2028E三年目标价放在同一张表里。先看每股价格与回报，再按需展开估值方法。</p></div><div class="asof"><strong>现价更新至 {html.escape(price_asof)}</strong>每日构建自动读取本地收盘价</div></section>
<section class="stats"><div class="stat"><div class="k">覆盖公司</div><div class="v">{len(rows)}</div><div class="s">同一张表统一比较</div></div><div class="stat"><div class="k">研究目标价</div><div class="v">{coverage_12m}</div><div class="s">来自估值注册表</div></div><div class="stat"><div class="k">三年目标价</div><div class="v">{coverage_3y}</div><div class="s">固定研究锚，不随股价漂移</div></div><div class="stat"><div class="k">口径红旗</div><div class="v" style="color:var(--red)">{red_rows}</div><div class="s">共 {recheck_rows} 家待复核 · 行情 {html.escape(price_asof)}</div></div></section>
<section class="controls"><input id="search" type="search" placeholder="搜索公司或代码…" aria-label="搜索公司或代码"><select id="sector" aria-label="筛选行业"><option value="">全部行业</option></select><select id="coverage" aria-label="筛选数据完整度"><option value="">全部数据状态</option><option value="complete">三年目标价完整</option><option value="missing">三年目标价待补</option><option value="flagged">仅看有红旗的</option><option value="recheck">仅看待复核</option></select><button id="reset" type="button">重置</button><span class="result" id="result"></span></section>
<div class="table-shell"><table><thead><tr><th data-sort="name">公司</th><th data-sort="sector">行业</th><th data-sort="price">现价</th><th data-sort="target_12m">研究目标价</th><th data-sort="upside_12m">目标空间</th><th data-sort="target_3y">三年目标价</th><th data-sort="total_3y">三年总回报</th><th data-sort="cagr_3y">三年 CAGR</th><th data-sort="cagr_from_anchor">锚点起算 CAGR</th><th data-sort="base_cagr_3y">基准情景价</th><th data-sort="rating">评级</th><th data-sort="method">三年估值锚</th></tr></thead><tbody id="body"></tbody></table></div>
<div class="note"><details><summary>口径与局限</summary><p>“研究目标价”保留估值注册表中的主目标，期限尚未全部标准化，因此页面称研究目标价而非统一宣称12个月目标价。“三年目标价”由原三年隐含市值换算为每股价格，基于迁移时的等效股数；拆股、ADS比例变化、重大增发或回购后必须复核。未完成三年估值的公司显示“待补录”，不从自由文本猜测。</p>
<p><strong>为什么“目标空间”和“三年 CAGR”会打架：</strong>两栏来自不同注册表、不同日期、不同倍数假设，不可交叉解读。决策请以三年 CAGR 为准，并先看该行的档位标签与红旗。<strong>倒挂</strong>＝三年目标价低于研究目标价（模型隐含先涨后跌）；<strong>低于基准</strong>＝三年目标价低于估值报告的基准情景价；<strong>超乐观档</strong>＝高于乐观情景价，需确认由业绩增长而非退出倍数支撑；<strong>锚点漂移</strong>＝现价较三年锚点已偏离 20% 以上，三年回报被入场价吃掉一部分；<strong>仍在买入区</strong>＝三年目标价仍落在今天的买入区间内，即三年后价格还没走出你现在认为便宜的位置。</p>
<p><strong>“锚点起算 CAGR”</strong>是按设定三年目标价当天的价格买入所能得到的年化，与按今天价格买入的“三年 CAGR”并列，用来区分“标的变差”与“入场价变贵”。<strong>“基准情景价”</strong>是估值报告基准档的价格，与三年目标价不同期，只作参照下限——正常情况下三年目标价应高于它。</p></details><a class="back" href="index.html">返回研究首页 →</a></div>
</div>
{page_close("三年目标价为固定研究锚；「锚点漂移」表示现价已偏离建锚时价格超过阈值，回报口径需复核。")}<script>
const DATA={data_json};
const $=s=>document.querySelector(s); let sortKey='cagr_3y',sortDir=-1;
const pct=v=>v==null?'—':`${{v>=0?'+':''}}${{(v*100).toFixed(1)}}%`;
const cls=v=>v==null?'neutral':v>=0?'positive':'negative';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const ratingClass=r=>/买入|增持/.test(r)?'buy':/卖出|减持/.test(r)?'sell':'hold';
const SCEN={{bear:'悲观档',base:'基准档',bull:'乐观档',below_bear:'低于悲观',above_bull:'超乐观档',between:'档间'}};
const scenLabel=k=>SCEN[k]||k;
const driftTxt=d=>`<span class="${{d>=0?'negative':'positive'}}">${{d>=0?'+':''}}${{(d*100).toFixed(0)}}%</span>`;
function flagHtml(r){{if(!r.flags||!r.flags.length)return '';return `<div class="flags">`+r.flags.map(f=>`<span class="flag ${{f.level}}" title="${{esc(f.title)}}">${{esc(f.label)}}</span>`).join('')+`</div>`}}
function cellMetric(price,value){{return `<div class="metric"><span class="price ${{value==null?'missing':''}}">${{esc(price)}}</span>${{value==null?'':`<span class="pill ${{cls(value)}}">${{pct(value)}}</span>`}}</div>`}}
function render(){{const q=$('#search').value.trim().toLowerCase(),sector=$('#sector').value,cov=$('#coverage').value;let rows=DATA.filter(r=>(!q||`${{r.name}} ${{r.name_en}} ${{r.ticker}}`.toLowerCase().includes(q))&&(!sector||r.sector===sector)&&(!cov||(cov==='complete'?r.has_3y:cov==='missing'?!r.has_3y:cov==='flagged'?(r.flags||[]).some(f=>f.level==='red'):r.needs_recheck)));rows.sort((a,b)=>{{let x=a[sortKey],y=b[sortKey];if(x==null)x=sortDir<0?-Infinity:Infinity;if(y==null)y=sortDir<0?-Infinity:Infinity;return typeof x==='string'?sortDir*x.localeCompare(y,'zh'):sortDir*(x-y)}});$('#body').innerHTML=rows.map(r=>`<tr><td><div class="company">${{esc(r.name)}}</div><div class="meta">${{esc(r.ticker)}}${{r.name_en&&r.name_en!==r.name?'<span class="en"> · '+esc(r.name_en)+'</span>':''}}</div></td><td><span class="sector">${{esc(r.sector)}}</span></td><td><div class="price">${{esc(r.price_text)}}</div><div class="subnum">${{esc(r.price_date||'无行情')}}</div></td><td title="${{esc(r.target_12m_raw)}}"><div class="price ${{r.target_12m==null?'missing':''}}">${{esc(r.target_12m_text)}}</div></td><td><span class="pill ${{cls(r.upside_12m)}}">${{pct(r.upside_12m)}}</span></td><td><div class="price ${{r.target_3y==null?'missing':''}}">${{r.target_3y==null?'待补录':esc(r.target_3y_text)}}</div><div class="subnum">${{r.target_year?r.target_year+'E':'—'}}${{r.scenario_nearest?' · '+scenLabel(r.scenario_nearest):''}}</div>${{flagHtml(r)}}</td><td><span class="pill ${{cls(r.total_3y)}}">${{pct(r.total_3y)}}</span></td><td><span class="price ${{cls(r.cagr_3y)}}">${{pct(r.cagr_3y)}}</span></td><td title="锚点价 ${{esc(r.anchor_price_text)}}（${{esc(r.anchor_date||'无日期')}}）——按当时价格买入的三年 CAGR"><span class="price ${{cls(r.cagr_from_anchor)}}">${{pct(r.cagr_from_anchor)}}</span><div class="subnum">${{r.anchor_price==null?'无锚点':esc(r.anchor_price_text)+' '+(r.anchor_drift==null?'':driftTxt(r.anchor_drift))}}</div></td><td title="基准情景价三年化，仅作参照——它与三年目标价不同期"><div class="price ${{r.base_price==null?'missing':''}}">${{r.base_price==null?'—':esc(r.base_price_text)}}</div><div class="subnum">${{r.base_cagr_3y==null?'三情景待补':'参照 CAGR '+pct(r.base_cagr_3y)}}</div></td><td title="${{esc(r.rating_raw)}}"><span class="rating ${{ratingClass(r.rating)}}">${{esc(r.rating)}}</span></td><td><div class="method" title="${{esc(r.method)}}">${{esc(r.method||'待补录')}}</div></td></tr>`).join('');$('#result').textContent=`${{rows.length}} 家公司`;}}
[...new Set(DATA.map(r=>r.sector))].sort((a,b)=>a.localeCompare(b,'zh')).forEach(s=>{{const o=document.createElement('option');o.value=o.textContent=s;$('#sector').appendChild(o)}});
document.querySelectorAll('th[data-sort]').forEach(th=>th.addEventListener('click',()=>{{const k=th.dataset.sort;if(sortKey===k)sortDir*=-1;else{{sortKey=k;sortDir=k==='name'||k==='sector'||k==='rating'||k==='method'?1:-1}}render()}}));
['search','sector','coverage'].forEach(id=>$('#'+id).addEventListener(id==='search'?'input':'change',render));$('#reset').addEventListener('click',()=>{{$('#search').value='';$('#sector').value='';$('#coverage').value='';sortKey='cagr_3y';sortDir=-1;render()}});render();
</script></body></html>'''


def refresh_annotations() -> None:
    """构建前刷新三年注册表的情景标签与复核标记，保证红旗与最新估值口径同步。"""
    try:
        from annotate_three_year_registry import annotate
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            from annotate_three_year_registry import annotate
        except ImportError:
            print("警告：未找到 annotate_three_year_registry，沿用注册表中的既有标记", file=sys.stderr)
            return
    annotate()


def build() -> dict:
    if not THREE_YEAR_PATH.exists():
        raise SystemExit(f"缺少三年估值数据：{THREE_YEAR_PATH}")
    refresh_annotations()
    rows, latest_date = build_rows()
    OUTPUT_PATH.write_text(build_html(rows, latest_date), encoding="utf-8")
    return {
        "output": str(OUTPUT_PATH),
        "companies": len(rows),
        "with_current_price": sum(r["price"] is not None for r in rows),
        "with_research_target": sum(r["target_12m"] is not None for r in rows),
        "with_three_year_target": sum(r["target_3y"] is not None for r in rows),
        "price_asof": latest_date,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--migrate", action="store_true", help="migrate the legacy dashboard into the three-year registry")
    parser.add_argument("--snapshot-date", default="2026-06-30")
    parser.add_argument("--source", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    if args.migrate:
        payload = migrate_legacy_dashboard(args.source, THREE_YEAR_PATH, args.snapshot_date)
        print(json.dumps({"migrated": len(payload["companies"]), "output": str(THREE_YEAR_PATH)}, ensure_ascii=False))
        return
    print(json.dumps(build(), ensure_ascii=False))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
