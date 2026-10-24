#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 口径修复：给 three_year_valuation_registry.json 补情景标签与待复核标记。

不改动任何既有 target_price_3y / target_multiple，只新增诊断字段。

口径说明
--------
三年目标价 = 目标年指标 × target_multiple（EV 型再减净负债）÷ 等效股数。
把 valuation_registry 的三情景价格按同一套指标/股数/净负债反算，就得到
"若该情景价在目标年实现所需的倍数"。因为指标固定，倍数与价格严格成正比，
所以档位判定既是倍数比较、也是价格比较。

判定规则
--------
正常：三年目标价 >= 基准情景价（三年比 12 个月多两年增长，理应更高）。
red  ：三年目标价 < 基准情景价 —— 两栏口径打架，必须用 07_估值分析 的
       基准倍数重算（本次 P0 只标记，不重算）。
amber：三年目标价 > 乐观情景价 —— 未必错，但要确认是业绩增长驱动，
       而不是退出倍数给得过松。

新增字段
--------
scenario_multiples : 三情景价折算到目标年指标上的隐含倍数
scenario_nearest   : 三年目标价在三情景阶梯上的位置
vs_base            : 三年目标价 ÷ 基准情景价（= 倍数之比）
base_scenario_price: 基准情景价（同期参照值，不是三年目标价）
needs_recheck / recheck_reason / recheck_level : 复核标记

用法: python annotate_three_year_registry.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from tidestone_paths import SYSTEM_DIR
SYSTEM = SYSTEM_DIR
THREE_YEAR_PATH = SYSTEM / "three_year_valuation_registry.json"
VALUATION_PATH = SYSTEM / "valuation_registry.json"

NEAREST_TOL = 0.08          # 与某档相差 8% 以内即归入该档
ANCHOR_STALE_DAYS = 30      # 锚点超过这个天数视为待复核
DIAG_FIELDS = ("scenario_multiples", "scenario_nearest", "vs_base",
               "base_scenario_price", "recheck_reason", "recheck_level")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def implied_multiple(price, entry):
    """把一个每股价格反算成隐含倍数（对齐本条的指标口径）。"""
    shares = entry.get("share_equivalent_b")
    metric = entry.get("metric_value_b")
    if not price or not shares or not metric:
        return None
    market_cap = price * shares
    if entry.get("valuation_type") == "ev":
        market_cap += entry.get("net_debt_b") or 0.0
    return market_cap / metric


def classify(mult, m_bear, m_base, m_bull):
    if mult is None or None in (m_bear, m_base, m_bull):
        return None
    ladder = sorted([("bear", m_bear), ("base", m_base), ("bull", m_bull)],
                    key=lambda x: x[1])
    for label, ref in ladder:
        if ref and abs(mult - ref) / ref <= NEAREST_TOL:
            return label
    if mult < ladder[0][1]:
        return "below_bear"
    if mult > ladder[-1][1]:
        return "above_bull"
    return "between"


def days_since(iso):
    if not iso:
        return None
    try:
        y, m, d = (int(x) for x in str(iso).split("-")[:3])
    except ValueError:
        return None
    return (date.today() - date(y, m, d)).days


def annotate(dry_run: bool = False) -> dict:
    three = load(THREE_YEAR_PATH)
    val = load(VALUATION_PATH).get("companies", {})
    companies = three.get("companies", {})

    stats = {"total": len(companies), "resolved": 0, "needs_recheck": 0,
             "red": [], "amber": [], "missing_scenarios": [], "stale_anchor": []}

    for ticker, entry in companies.items():
        for f in DIAG_FIELDS:
            entry.pop(f, None)

        scen = ((val.get(ticker) or {}).get("scenario_valuation") or {}).get("scenarios") or {}
        prices = {k: (scen.get(k) or {}).get("price") for k in ("bear", "base", "bull")}
        mults = {k: implied_multiple(p, entry) for k, p in prices.items()}
        target_mult = entry.get("target_multiple")

        reasons: list[str] = []
        level = None

        if all(v is not None for v in mults.values()):
            entry["scenario_multiples"] = {k: round(v, 3) for k, v in mults.items()}
            entry["base_scenario_price"] = prices["base"]
            nearest = classify(target_mult, mults["bear"], mults["base"], mults["bull"])
            if nearest:
                entry["scenario_nearest"] = nearest
                stats["resolved"] += 1
            if mults["base"] and target_mult:
                vs_base = target_mult / mults["base"]
                entry["vs_base"] = round(vs_base, 3)
                if vs_base < 0.98:
                    level = "red"
                    reasons.append(
                        f"三年目标价仅为基准情景价的 {vs_base:.0%}，两栏口径冲突，"
                        f"需按 07_估值分析 基准倍数重算"
                    )
                    stats["red"].append(ticker)
                elif nearest == "above_bull":
                    level = "amber"
                    reasons.append(
                        f"三年目标价高于乐观情景价（{vs_base:.2f}× 基准），"
                        f"需确认由业绩增长而非退出倍数支撑"
                    )
                    stats["amber"].append(ticker)
        elif entry.get("valuation_type") != "fixed":
            reasons.append("valuation_registry 缺三情景价，无法判定档位")
            stats["missing_scenarios"].append(ticker)

        if str(entry.get("source", "")).startswith("legacy_dashboard_migration"):
            reasons.append("倍数沿用旧看板迁移值，未经估值报告复核")

        age = days_since(entry.get("anchor_date"))
        if age is None:
            reasons.append("缺 anchor_date，无法判断锚点漂移")
            stats["stale_anchor"].append(ticker)
        elif age > ANCHOR_STALE_DAYS:
            reasons.append(f"锚点已过期 {age} 天")
            stats["stale_anchor"].append(ticker)

        entry["needs_recheck"] = bool(reasons)
        if reasons:
            entry["recheck_reason"] = reasons
            entry["recheck_level"] = level or "info"
            stats["needs_recheck"] += 1

    three["schema_version"] = 2
    three["updated_at"] = date.today().isoformat()
    three["note"] = (
        "三年目标价为研究锚；每日构建只更新现价，不自动改变目标价。"
        "scenario_* / vs_base / needs_recheck 由 annotate_three_year_registry.py 生成，"
        "用于暴露三年目标价与估值报告三情景的口径差异；"
        "base_scenario_price 是同期参照价，不是三年目标价。"
        "share_equivalent_b 需在拆股、ADS 比例变化或重大增发回购后复核。"
    )

    if not dry_run:
        THREE_YEAR_PATH.write_text(
            json.dumps(three, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    s = annotate(ap.parse_args().dry_run)
    print(f"总条目 {s['total']}｜已判定档位 {s['resolved']}｜待复核 {s['needs_recheck']}")
    print(f"红旗（低于基准情景价）: {', '.join(s['red']) or '无'}")
    print(f"黄旗（高于乐观情景价）: {', '.join(s['amber']) or '无'}")
    print(f"缺三情景价: {len(s['missing_scenarios'])} 家")
    print(f"锚点过期/缺失: {len(s['stale_anchor'])} 家")


if __name__ == "__main__":
    main()

