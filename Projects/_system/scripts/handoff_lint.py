#!/usr/bin/env python3
"""
handoff_lint — 交接块（Handoff Block）机器校验 v1（2026-07-30，dossier schema v3.1 §2.5）

校验目标：防截断（哨兵行）、防漏写（必备字段）、防臃肿（行数上限）。

规则（v1）：
  04_战略决策.md   ERROR: 哨兵 <!-- HANDOFF-END 缺失（=文件截断或漏写交接块）
                   ERROR: "## 交接块" 章节缺失；H1-H5 小节缺失
                   WARN : H2 情景行数 != 3；H3 数据行 > 12；H4 数据行 > 5；
                          交接块总行数 > 45（含表格线的宽松预算）
  06_财务预测.md   WARN : "三情景分歧驱动表" 标题缺失（旧版格式，建议刷新）
  07_估值分析.md   WARN : 4.8 valuation_registry 登记块的 ```json 缺失或 JSON 解析失败

设计说明：v1 对 04 从严（新格式从第一天就守住），对 06/07 只 WARN（存量格式渐进迁移）。
行数超限先 WARN，跑顺一两家后可把 STRICT_ROWCAP 改 True 升级为 ERROR。

用法：
  python3 _system/scripts/handoff_lint.py {file.md}                # 按文件名自动识别 slot
  python3 _system/scripts/handoff_lint.py {file.md} --slot 04_战略决策.md
  python3 _system/scripts/handoff_lint.py --batch {pending_dir}    # 校验批次内 06/07/04
有 ERROR 时退出码 1；仅 WARN 退出码 0。
也可被 dossier_orchestrator.py import，调用 lint_file(path, slot) -> (errors, warnings)。
"""

import argparse
import json
import re
import sys
from pathlib import Path

STRICT_ROWCAP = False  # 跑顺后改 True：行数超限从 WARN 升级为 ERROR

SENTINEL_RE = re.compile(r"<!--\s*HANDOFF-END\s+v(\d+)\s*-->")
H_SECTIONS = ["H1", "H2", "H3", "H4", "H5"]
ROW_CAPS = {"H2": 3, "H3": 12, "H4": 5}  # 数据行上限（H2 为恰好 3）
BLOCK_TOTAL_CAP = 45  # 交接块总行数宽松预算（非空行）


def _table_data_rows(lines):
    """Count markdown table data rows (pipe rows excluding header + separator)."""
    pipe_rows = [l for l in lines if l.strip().startswith("|")]
    if len(pipe_rows) <= 2:
        return 0
    return len(pipe_rows) - 2  # minus header row + |---| separator


def _split_h_sections(block_lines):
    """Map H1..H5 -> list of lines in that subsection."""
    sections, current = {}, None
    for line in block_lines:
        m = re.match(r"###\s+(H[1-5])\b", line.strip())
        if m:
            current = m.group(1)
            sections[current] = []
        elif current:
            sections[current].append(line)
    return sections


def lint_07(text):
    errors, warnings = [], []
    if not SENTINEL_RE.search(text):
        errors.append("哨兵行 `<!-- HANDOFF-END v1 -->` 缺失 —— 文件被截断，或交接块漏写")
    m = re.search(r"^##\s*交接块", text, re.MULTILINE)
    if not m:
        errors.append("`## 交接块` 章节缺失")
        return errors, warnings  # 后续检查无意义

    block = text[m.start():]
    end = SENTINEL_RE.search(block)
    if end:
        block = block[: end.end()]
    block_lines = [l for l in block.splitlines() if l.strip()]

    sections = _split_h_sections(block_lines)
    for h in H_SECTIONS:
        if h not in sections:
            errors.append(f"交接块小节 ### {h} 缺失")

    for h, cap in ROW_CAPS.items():
        if h not in sections:
            continue
        rows = _table_data_rows(sections[h])
        if h == "H2" and rows != 3:
            msg = f"H2 战略三情景应恰好 3 行数据，实际 {rows} 行"
            (errors if STRICT_ROWCAP else warnings).append(msg)
        elif h != "H2" and rows > cap:
            msg = f"{h} 数据行 {rows} 超上限 {cap} —— 按重要性挤掉一行再加新的"
            (errors if STRICT_ROWCAP else warnings).append(msg)

    if len(block_lines) > BLOCK_TOTAL_CAP:
        msg = f"交接块共 {len(block_lines)} 非空行，超过预算 {BLOCK_TOTAL_CAP} —— 论证移回正文，块内只留结论+指针"
        (errors if STRICT_ROWCAP else warnings).append(msg)

    if re.search(r"概率加权", block):
        errors.append("交接块内出现\"概率加权\"字样 —— 加权增量 EV 属战略层内部参考，禁止进入交接块传给下游")
    return errors, warnings


def lint_05(text):
    warnings = []
    if not re.search(r"三情景分歧驱动表", text):
        warnings.append("未找到\"三情景分歧驱动表\"标题 —— 旧版格式？建议按新版 financial-forecast skill 刷新")
    return [], warnings


def lint_06(text):
    warnings = []
    blocks = re.findall(r"```json\s*(.*?)```", text, re.DOTALL)
    reg = [b for b in blocks if "scenario_valuation" in b]
    if not reg:
        warnings.append("未找到含 scenario_valuation 的 ```json 登记块（4.8 节）")
    else:
        try:
            json.loads(reg[-1])
        except Exception as e:
            warnings.append(f"4.8 登记块 JSON 解析失败：{e}")
    return [], warnings


LINTERS = {
    "04_战略决策.md": lint_07,
    "06_财务预测.md": lint_05,
    "07_估值分析.md": lint_06,
}


def lint_file(path, slot=None):
    """Return (errors, warnings). Unknown slots lint as no-op."""
    path = Path(path)
    slot = slot or path.name
    linter = LINTERS.get(slot)
    if linter is None:
        return [], []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"无法读取文件：{e}"], []
    return linter(text)


def _report(path, errors, warnings):
    for e in errors:
        print(f"  ❌ ERROR [{Path(path).name}] {e}")
    for w in warnings:
        print(f"  ⚠️  WARN  [{Path(path).name}] {w}")
    if not errors and not warnings:
        print(f"  ✅ OK    [{Path(path).name}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", help="单个 md 文件路径")
    ap.add_argument("--slot", default=None, help="显式指定 slot 名（默认按文件名识别）")
    ap.add_argument("--batch", default=None, help="批次目录（_pending/{ts}/），校验其中的 06/07/04")
    args = ap.parse_args()

    all_errors = 0
    if args.batch:
        batch = Path(args.batch)
        for slot in LINTERS:
            f = batch / slot
            if f.exists():
                errs, warns = lint_file(f, slot)
                _report(f, errs, warns)
                all_errors += len(errs)
    elif args.target:
        errs, warns = lint_file(args.target, args.slot)
        _report(args.target, errs, warns)
        all_errors += len(errs)
    else:
        ap.error("需要 target 文件或 --batch 目录")

    sys.exit(1 if all_errors else 0)


if __name__ == "__main__":
    main()

