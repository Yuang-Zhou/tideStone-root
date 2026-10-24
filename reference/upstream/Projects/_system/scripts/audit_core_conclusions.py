#!/usr/bin/env python3
"""Audit whether company-level target prices and three-year valuations are extractable.

This script is deliberately read-only with respect to research dossiers and registries.
It writes generated audit views only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import date
from pathlib import Path


PENDING_TARGETS = {"", "待完成估值分析"}
TICKER_ALIASES = {"SATS": "ECHO"}
NUMERIC_SUFFIXES = {
    "002555": "002555.SZ",
    "920186": "920186.BJ",
    "688362": "688362.SH",
    "300054": "300054.SZ",
    "301086": "301086.SZ",
    "300750": "300750.SZ",
    "601872": "601872.SH",
}


def normalize_ticker(raw: str | None) -> str | None:
    if not raw:
        return None
    ticker = raw.strip().upper()
    ticker = re.sub(r"\.(O|N)$", "", ticker)
    ticker = TICKER_ALIASES.get(ticker, ticker)
    return NUMERIC_SUFFIXES.get(ticker, ticker)


def dossier_ticker(company_dir: Path, meta: dict | None) -> str | None:
    if meta and meta.get("ticker"):
        return normalize_ticker(str(meta["ticker"]))
    match = re.search(r"\(([^()]+)\)\s*$", company_dir.name)
    if match:
        return normalize_ticker(match.group(1))
    if re.fullmatch(r"[A-Za-z]{1,8}(?:\.[A-Za-z]{1,3})?", company_dir.name):
        return normalize_ticker(company_dir.name)
    return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


_DASHBOARD_DATA_RE = re.compile(r"const\s+DATA\s*=\s*(\[.*?\])\s*;", re.S)


def dashboard_tickers(path: Path) -> set[str]:
    """看板里「确实有三年目标价」的公司集合。

    2026-08-09 修复：原实现按行匹配 `^\\s*\\{n:'` 再抓 `t:'TICKER'`，那是**旧版看板**
    的 JS 对象格式。`build_valuation_comparison.py` 现在输出的是单行双引号 JSON：

        const DATA=[{"ticker":"300054.SZ","name":"鼎龙股份",...,"has_3y":true}];

    旧正则永远匹配不上 → 55 家全部 dashboard=False → 报告头部固定写「已有三年估值
    看板数据：0 家」，并给 50 家挂上「未进入三年估值看板」这个假问题。

    新实现解析 DATA 数组，只收 `has_3y` 为真的条目（"待补录"的不算进入看板）。
    保留旧格式解析作为兜底，便于回看历史版本的看板文件。
    """
    text = path.read_text(encoding="utf-8-sig")
    tickers: set[str] = set()

    match = _DASHBOARD_DATA_RE.search(text)
    if match:
        try:
            rows = json.loads(match.group(1))
        except json.JSONDecodeError:
            rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            # has_3y 缺失时回退到 target_3y 是否有值，兼容早期字段集
            has = row.get("has_3y")
            if has is None:
                has = row.get("target_3y") is not None
            if not has:
                continue
            ticker = normalize_ticker(row.get("ticker"))
            if ticker:
                tickers.add(ticker)
        if tickers:
            return tickers

    # 兜底：旧版看板的 JS 对象格式 {n:'名称', t:'TICKER', ...}
    for line in text.splitlines():
        if not re.match(r"^\s*\{n:'", line):
            continue
        m = re.search(r"\bt:'([^']+)'", line)
        if m:
            ticker = normalize_ticker(m.group(1))
            if ticker:
                tickers.add(ticker)
    return tickers


def classify(row: dict) -> tuple[str, list[str]]:
    issues: list[str] = []
    if row["folder_only"]:
        if row["ticker"] == "META":
            return "目录清理", ["疑似 Meta 重复/遗留目录"]
        return "未入库", ["公司目录未进入估值注册表"]

    if not row["research"]:
        issues.append("缺研究档案")
    if not row["forecast"]:
        issues.append("缺06财务预测")
    if not row["valuation"]:
        issues.append("缺07估值分析")
    if not row["target_usable"]:
        issues.append("目标价为空或待完成")
    if not row["dashboard"]:
        issues.append("未进入三年估值看板")
    if not row["structured_scenarios"]:
        issues.append("三情景未结构化")

    if all((row["forecast"], row["valuation"], row["target_usable"], row["dashboard"])):
        if row["structured_scenarios"]:
            return "可直接提取", issues
        return "可提取·需口径确认", issues
    if all((row["forecast"], row["valuation"], row["target_usable"])):
        return "可补三年估值", issues
    if row["valuation"] and row["target_usable"]:
        return "部分可提取", issues
    return "资料缺口", issues


def make_rows(projects: Path) -> list[dict]:
    registry_path = projects / "_system" / "valuation_registry.json"
    dashboard_path = projects / "基本面分析汇总" / "组合三年估值看板.html"
    registry = load_json(registry_path).get("companies", {})
    dashboard = dashboard_tickers(dashboard_path)

    # 2026-08-07 目录扁平化：公司目录不再按 `{N. 板块}/` 分桶，改为 companies/{TICKER} {中文名}/。
    # 原先这里是「遍历顶层数字前缀目录 → 从目录名括号里猜 ticker」，扁平化之后扫不到任何公司。
    # 现在直接以 companies.json 为准：ticker 是 key 不用猜，folder 由它声明，category 取 GICS 中文板块名。
    # folder_only 的语义随之收窄为「companies/ 下有目录但 companies.json 里没有」——即真正的孤儿目录，
    # 这正是 2026-08-07 查出迈瑞医疗的那个机制，保留。
    companies_path = projects / "_system" / "companies.json"
    companies_doc = load_json(companies_path)
    sector_names = companies_doc.get("gics_sector_names", {})
    company_entries = companies_doc.get("companies", {})

    folders_by_ticker: dict[str, dict] = {}
    folder_only: list[dict] = []
    declared_dirs: set[str] = set()

    for ticker, entry in company_entries.items():
        rel = entry.get("folder") or entry.get("legacy_folder")
        if not rel:
            continue
        declared_dirs.add(rel.replace("\\", "/"))
        company_dir = projects / rel.replace("/", os.sep)
        research_dir = company_dir / "研究档案"
        meta_path = research_dir / "_meta.json"
        meta = None
        if meta_path.exists():
            try:
                meta = load_json(meta_path)
            except (json.JSONDecodeError, UnicodeDecodeError):
                meta = None
        code = (entry.get("gics") or {}).get("sector")
        folders_by_ticker[normalize_ticker(ticker) or ticker] = {
            "ticker": normalize_ticker(ticker) or ticker,
            "company_folder": company_dir.name,
            "category": sector_names.get(code, "未知板块"),
            "folder": rel,
            "folder_exists": company_dir.is_dir(),
            "research": research_dir.exists(),
            "forecast": (research_dir / "06_财务预测.md").exists(),
            "valuation": (research_dir / "07_估值分析.md").exists(),
            "strategy": (research_dir / "04_战略决策.md").exists(),
            "meta": meta or {},
        }

    # 孤儿检测：companies/ 下存在、但 companies.json 没声明的目录
    flat_root = projects / "companies"
    if flat_root.is_dir():
        for d in sorted(p for p in flat_root.iterdir() if p.is_dir()):
            rel = d.relative_to(projects).as_posix()
            if rel not in declared_dirs:
                folder_only.append({
                    "ticker": None,
                    "company_folder": d.name,
                    "category": None,
                    "folder": rel,
                    "note": "目录存在但不在 companies.json —— 孤儿，需入库或归档",
                })

    rows: list[dict] = []
    for ticker, valuation_entry in registry.items():
        ticker = normalize_ticker(ticker) or ticker
        folder = folders_by_ticker.get(ticker, {})
        target = valuation_entry.get("target_price")
        target_text = "" if target is None else str(target).strip()
        documents = folder.get("meta", {}).get("documents", {})
        val_meta = documents.get("07_估值分析.md", {})
        row = {
            "ticker": ticker,
            "name": valuation_entry.get("name") or folder.get("company_folder") or ticker,
            "category": folder.get("category") or valuation_entry.get("sector") or "",
            "folder": folder.get("folder"),
            "research": bool(folder.get("research")),
            "forecast": bool(folder.get("forecast")),
            "valuation": bool(folder.get("valuation")),
            "strategy": bool(folder.get("strategy")),
            "target_price_raw": target,
            "target_usable": bool(target_text and target_text not in PENDING_TARGETS),
            "structured_scenarios": valuation_entry.get("scenario_valuation") is not None,
            "dashboard": ticker in dashboard,
            "valuation_updated": val_meta.get("last_updated"),
            "source_period": val_meta.get("source_period"),
            "folder_only": False,
        }
        row["status"], row["issues"] = classify(row)
        rows.append(row)

    for folder in folder_only:
        row = {
            "ticker": folder.get("ticker"),
            "name": folder["company_folder"],
            "category": folder["category"],
            "folder": folder["folder"],
            "research": folder["research"],
            "forecast": folder["forecast"],
            "valuation": folder["valuation"],
            "strategy": folder["strategy"],
            "target_price_raw": None,
            "target_usable": False,
            "structured_scenarios": False,
            "dashboard": False,
            "valuation_updated": None,
            "source_period": None,
            "folder_only": True,
        }
        row["status"], row["issues"] = classify(row)
        rows.append(row)

    return sorted(rows, key=lambda r: (r["category"], r["name"]))


def markdown_report(rows: list[dict], generated: str) -> str:
    registered = [r for r in rows if not r["folder_only"]]
    counts = Counter(r["status"] for r in rows)
    target_count = sum(r["target_usable"] for r in registered)
    dashboard_count = sum(r["dashboard"] for r in registered)
    scenario_count = sum(r["structured_scenarios"] for r in registered)

    lines = [
        "# 公司核心结论提取审计",
        "",
        f"> 生成日期：{generated}。本报告只审计覆盖情况，不修改任何研究结论或估值假设。",
        "",
        "## 总览",
        "",
        f"- 估值注册表公司：{len(registered)} 家",
        f"- 可用目标价：{target_count} 家",
        f"- 已有三年估值看板数据：{dashboard_count} 家",
        f"- 已结构化三情景估值：{scenario_count} 家",
        f"- 公司目录总数：{len(rows)} 个（含重复、遗留或未入库目录）",
        "",
        "| 状态 | 数量 | 含义 |",
        "|---|---:|---|",
    ]
    meanings = {
        "可直接提取": "目标价、三年估值及三情景均已有结构化来源",
        "可提取·需口径确认": "目标价和三年估值已有来源，但三情景或期限口径未完全结构化",
        "可补三年估值": "06/07及目标价齐全，可从报告补录三年估值",
        "部分可提取": "已有目标价/估值，但财务预测或三年估值链条不完整",
        "资料缺口": "缺少关键研究模块或有效目标价",
        "目录清理": "疑似重复或遗留目录",
        "未入库": "存在公司目录，但未进入估值注册表",
    }
    for status in meanings:
        if counts[status]:
            lines.append(f"| {status} | {counts[status]} | {meanings[status]} |")

    lines.extend([
        "",
        "## 公司明细",
        "",
        "| 公司 | 代码 | 状态 | 06预测 | 07估值 | 目标价 | 三年看板 | 三情景 | 主要问题 |",
        "|---|---|---|:---:|:---:|---|:---:|:---:|---|",
    ])
    for row in rows:
        target = str(row["target_price_raw"] or "—").replace("|", "\\|")
        if len(target) > 36:
            target = target[:35] + "…"
        issues = "；".join(row["issues"]) or "—"
        lines.append(
            f"| {row['name']} | {row['ticker'] or '—'} | {row['status']} | "
            f"{'✓' if row['forecast'] else '—'} | {'✓' if row['valuation'] else '—'} | "
            f"{target} | {'✓' if row['dashboard'] else '—'} | "
            f"{'✓' if row['structured_scenarios'] else '—'} | {issues} |"
        )

    lines.extend([
        "",
        "## 建议的数据治理顺序",
        "",
        "1. 先补录“可补三年估值”公司的结构化三年字段，不改变报告内判断。",
        "2. 将当前 HTML 中的 46 行三年估值迁移为独立结构化数据，再由网站读取生成。",
        "3. 为所有目标价增加 `horizon`、`as_of`、`method`，区分12个月目标价、当前公允价值和三年目标价。",
        "4. 最后处理资料缺口和重复目录，避免把不完整研究包装成可比较结论。",
        "",
        "## 口径说明",
        "",
        "- `可直接提取`不代表估值结论一定最新，只表示已有明确的数据来源。",
        "- `三年看板`当前仍是手工维护 HTML 数据，不是注册表字段。",
        "- `三情景`以 `valuation_registry.json` 中 `scenario_valuation` 是否存在为准。",
        "- 目标价原文保留，审计阶段不尝试从自由文本中猜测期限或货币。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    projects = args.projects.resolve()
    rows = make_rows(projects)
    output_dir = projects / "基本面分析汇总"
    json_path = output_dir / "公司核心结论提取审计.json"
    md_path = output_dir / f"公司核心结论提取审计_{args.date}.md"
    payload = {
        "schema_version": 1,
        "generated_at": args.date,
        "scope": "coverage_audit_only",
        "companies": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(markdown_report(rows, args.date), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "rows": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
