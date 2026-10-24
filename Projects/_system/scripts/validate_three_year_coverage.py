#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验：有 07_估值分析 的公司，三年估值注册表里必须有对应条目。

背景：three_year_valuation_registry.json 历史上只有一个写入口——2026-06-30 那次
`build_valuation_comparison.py --migrate`。此后 new-company-onboarding 建新公司、
company-dossier-build 跑完整档案，都不会往这张表写任何东西，于是新建档案的公司
在看板上永远显示"待补录"。本脚本把这个缺口变成显式告警。

用法:
  python validate_three_year_coverage.py            # 报告缺口，退出码 0
  python validate_three_year_coverage.py --strict   # 有缺口即退出码 1
  python validate_three_year_coverage.py --ticker MU --strict   # 只查一家

豁免：_system/three_year_coverage_waivers.json
  {"WAIVERS": {"TSM": "07 只做到 FY2027，需先延展预测"}}
豁免只是"已知且已决定暂不补"，仍会打印，只是不触发失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tidestone_paths import SYSTEM_DIR
SYSTEM = SYSTEM_DIR
PROJECTS = SYSTEM.parent
COMPANIES_PATH = SYSTEM / "companies.json"
THREE_YEAR_PATH = SYSTEM / "three_year_valuation_registry.json"
WAIVERS_PATH = SYSTEM / "three_year_coverage_waivers.json"
VALUATION_SLOT = "07_估值分析.md"


def load(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check(ticker_filter: str | None = None) -> dict:
    companies = load(COMPANIES_PATH).get("companies", {})
    entries = load(THREE_YEAR_PATH).get("companies", {})
    # 条目存在但 target_price_3y 为空，等同于没有三年目标价——看板照样显示"待补录"。
    registered = {t for t, e in entries.items() if (e or {}).get("target_price_3y") is not None}
    hollow = {t for t in entries if t not in registered}
    waivers = load(WAIVERS_PATH).get("WAIVERS", {})

    gaps, waived, ok, no_valuation = [], [], [], []
    for ticker, company in companies.items():
        if ticker_filter and ticker != ticker_filter:
            continue
        folder = company.get("folder") or company.get("path")
        if not folder:
            continue
        has_valuation = (PROJECTS / folder / "研究档案" / VALUATION_SLOT).exists()
        if not has_valuation:
            no_valuation.append(ticker)
        elif ticker in registered:
            ok.append(ticker)
        elif ticker in hollow and ticker not in waivers:
            gaps.append(f"{ticker}（条目存在但 target_price_3y 为空）")
        elif ticker in waivers:
            waived.append((ticker, waivers[ticker]))
        else:
            gaps.append(ticker)
    return {"gaps": gaps, "waived": waived, "ok": ok, "no_valuation": no_valuation}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="有未豁免缺口时退出码 1")
    ap.add_argument("--ticker", help="只校验单家公司")
    args = ap.parse_args()

    r = check(args.ticker)
    print(f"三年估值覆盖校验：已登记 {len(r['ok'])}｜缺口 {len(r['gaps'])}｜"
          f"已豁免 {len(r['waived'])}｜无 07 估值分析 {len(r['no_valuation'])}")
    for ticker, reason in r["waived"]:
        print(f"  [豁免] {ticker} —— {reason}")
    for ticker in r["gaps"]:
        print(f"  [缺口] {ticker} 有 {VALUATION_SLOT} 但三年估值注册表无可用条目 —— "
              f"请补 three_year_valuation_registry.json，或写进 {WAIVERS_PATH.name} 说明原因")
    if r["gaps"] and args.strict:
        sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()

