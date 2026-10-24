#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive_old.py —— 把超过保留期的日期文件搬进 _system/_archive/{类别}/{YYYY-MM}/

用法（在任意位置跑都行，路径基准由脚本自身位置上溯三层得到 Projects 根）：

    python _system/scripts/archive_old.py                 # 只列清单，不动文件
    python _system/scripts/archive_old.py --apply         # 执行搬迁
    python _system/scripts/archive_old.py --days 60       # 换个保留期看看
    python _system/scripts/archive_old.py --undo-last     # 撤销最近一次搬迁

规则（与 _system/README.md「归档约定」一致）：
- 只处理**文件名里带 YYYY-MM-DD** 的文件，按文件名日期判断，不看 mtime。
  没有日期的一律跳过（README.md / SCHEMA.md / dashboard_template.html /
  render_dashboard.py / _data_status.json / registry_changelog.md 等都会被自动放过）。
- 保留期默认 31 天。超期的搬到 `_archive/{类别}/{YYYY-MM}/`，**是移动不是删除**。
- 同一个源目录可能拆到不同类别：`daily_briefing/` 里的 `briefing_data_*.json`
  归 `briefing_data/`，`*_daily_briefing.md` 归 `daily_briefing/`——沿用既有布局。
- 每次搬迁写一条 JSON 到 `_archive/_move_log.jsonl`（**日志放 _archive 里，
  不放在会被整体删除的目录**——2026-08-09 的教训：manifest 跟着 _to_delete 一起没了）。

安全：目标已存在同名文件时跳过并报告，不覆盖。
"""
import argparse
import datetime
import json
import os
import re
import shutil
from pathlib import Path

from tidestone_paths import PROJECTS_ROOT
ROOT = PROJECTS_ROOT      # _system/scripts/ → _system/ → Projects/
SYSTEM = ROOT / "_system"
ARCHIVE = SYSTEM / "_archive"
LOG = ARCHIVE / "_move_log.jsonl"

DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")

# 源目录 → 分类函数（返回 _archive 下的类别名；返回 None 表示不归档）
def _daily_briefing_cat(name: str):
    if name.startswith("briefing_data_"):
        return "briefing_data"
    if name.endswith("_daily_briefing.md"):
        return "daily_briefing"
    return "daily_briefing"          # 该目录下其余带日期的产物，跟简报同类

SOURCES = [
    ("_system/daily_briefing",        _daily_briefing_cat),
    ("_system/scan_log",              lambda n: "scan_log"),
    ("_system/market_data/fetch_log", lambda n: "fetch_log"),
    ("_system/position_advice",       lambda n: "position_advice"),
    ("_system/positions",             lambda n: "positions"),
]


# ── .bak 手工备份 ────────────────────────────────────────────
# 来源：几乎全部是 Claude 会话在改注册表/脚本前顺手留的 `xxx.bak_{日期}_{事由}`，
# 没有任何代码会再读它们，也没有任何代码会清理它们 —— 所以会一直堆积。
# 规则：超过 BAK_DAYS 天的搬进 _archive/backups/{YYYY-MM}/（按 mtime，文件名里的日期格式不统一）。
# 例外：脚本自动维护、每次覆盖的固定名备份不动 —— 它永远只有一份，搬走了下次又会生成。
BAK_DAYS = 3
BAK_KEEP = {"valuation_registry.json.bak_before_drain"}   # sync_valuations.py drain 自动覆写


def scan_bak(bak_days: int):
    cut = datetime.datetime.now() - datetime.timedelta(days=bak_days)
    plan = []
    for dp, dn, fn in os.walk(SYSTEM):
        d = Path(dp)
        if d == ARCHIVE or ARCHIVE in d.parents:
            dn[:] = []
            continue
        for f in fn:
            if ".bak" not in f or f in BAK_KEEP:
                continue
            p = d / f
            mt = datetime.datetime.fromtimestamp(p.stat().st_mtime)
            if mt >= cut:
                continue
            plan.append((p, ARCHIVE / "backups" / mt.strftime("%Y-%m") / f, p.stat().st_size))
    return plan


def scan(days: int, bak_days: int = BAK_DAYS):
    cut = datetime.date.today() - datetime.timedelta(days=days)
    plan, skipped_nodate = scan_bak(bak_days), []
    for rel, catfn in SOURCES:
        d = ROOT / rel
        if not d.is_dir():
            continue
        for f in sorted(os.listdir(d)):
            p = d / f
            if not p.is_file():
                continue
            m = DATE_RE.search(f)
            if not m:
                skipped_nodate.append(f"{rel}/{f}")
                continue
            try:
                fd = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                skipped_nodate.append(f"{rel}/{f}")
                continue
            if fd >= cut:
                continue
            cat = catfn(f)
            if not cat:
                continue
            dest = ARCHIVE / cat / fd.strftime("%Y-%m") / f
            plan.append((p, dest, p.stat().st_size))
    return plan, skipped_nodate, cut


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def cmd_list(days: int, bak_days: int = BAK_DAYS):
    plan, skipped, cut = scan(days, bak_days)
    print("保留期 %d 天 → 文件名日期早于 %s 的归档；.bak 备份超过 %d 天的一并归档\n" % (days, cut, bak_days))
    if not plan:
        print("没有超期文件，已经是干净的。")
    bycat = {}
    for src, dst, size in plan:
        bycat.setdefault(dst.parent.relative_to(ARCHIVE).as_posix(), []).append((src, size))
    for cat in sorted(bycat):
        items = bycat[cat]
        print("  → _archive/%-26s %3d 个 / %6.2f MB" %
              (cat, len(items), sum(s for _, s in items) / 1048576))
        for src, _ in items[:3]:
            print("        %s" % rel(src))
        if len(items) > 3:
            print("        … 还有 %d 个" % (len(items) - 3))
    if plan:
        print("\n合计 %d 个 / %.2f MB" % (len(plan), sum(s for _, _, s in plan) / 1048576))
        print("执行：python _system/scripts/archive_old.py --apply")
    if skipped:
        print("\n跳过（文件名无日期，永不归档）%d 个：" % len(skipped))
        for s in skipped:
            print("    %s" % s)


def cmd_apply(days: int, bak_days: int = BAK_DAYS):
    plan, _, cut = scan(days, bak_days)
    if not plan:
        print("没有超期文件，无需操作。")
        return
    moved, conflict = [], []
    for src, dst, _ in plan:
        if dst.exists():
            conflict.append(rel(dst))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append({"from": rel(src), "to": rel(dst)})
    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, "days": days, "moved": moved},
                            ensure_ascii=False) + "\n")
    print("已归档 %d 个文件 → _archive/" % len(moved))
    bycat = {}
    for m in moved:
        bycat.setdefault("/".join(m["to"].split("/")[2:4]), 0)
        bycat["/".join(m["to"].split("/")[2:4])] += 1
    for k in sorted(bycat):
        print("    %-30s %3d" % (k, bycat[k]))
    if conflict:
        print("\n⚠️ %d 个目标位置已有同名文件，已跳过（不覆盖）：" % len(conflict))
        for c in conflict:
            print("    %s" % c)
    print("\n记录写入 %s" % rel(LOG))
    print("撤销：python _system/scripts/archive_old.py --undo-last")


def cmd_undo_last():
    if not LOG.exists():
        print("没有归档记录。")
        return
    lines = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        print("没有归档记录。")
        return
    entry = json.loads(lines[-1])
    n = 0
    for m in reversed(entry["moved"]):
        src, dst = ROOT / m["to"], ROOT / m["from"]
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            n += 1
    LOG.write_text("\n".join(lines[:-1]) + ("\n" if lines[:-1] else ""), encoding="utf-8")
    print("已还原 %d 个文件（撤销 %s 那次归档）" % (n, entry["ts"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=31, help="保留期天数，默认 31")
    ap.add_argument("--apply", action="store_true", help="真的执行搬迁")
    ap.add_argument("--undo-last", action="store_true", help="撤销最近一次归档")
    ap.add_argument("--bak-days", type=int, default=BAK_DAYS,
                    help=".bak 手工备份保留天数，默认 %d" % BAK_DAYS)
    a = ap.parse_args()
    if a.undo_last:
        cmd_undo_last()
    elif a.apply:
        cmd_apply(a.days, a.bak_days)
    else:
        cmd_list(a.days, a.bak_days)


if __name__ == "__main__":
    main()

