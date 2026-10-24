#!/usr/bin/env python3
"""
Dossier orchestrator — scaffolding utilities for company-dossier-build workflow.

Modes:
  migrate {TICKER}                  Copy legacy_source files from dossier_registry.json
                                    into the canonical 研究档案/ folder as the v1 baseline.
                                    No content rewriting — just file moves + _meta.json generation.

  prepare-refresh {TICKER} [SLOTS]  Create _pending/{timestamp}/ directory and emit
                                    a context-bundle JSON for the listed slots (default: all).
                                    The actual sub-skill invocation is handled by the
                                    orchestrator SKILL.md (Codex reads context, runs skills,
                                    writes outputs).

  finalize-refresh {TICKER} {TS}    After all sub-skill outputs have been written into
                                    _pending/{TS}/, write _meta.json and _diff_summary.md.

  accept {TICKER} [TS]              Move 研究档案/*.md + _meta.json into _history/{now}/,
                                    then move _pending/{TS}/*.md → 研究档案/.

  reject {TICKER} [TS]              Move _pending/{TS}/ → _pending/_rejected/{TS}/.

  status [TICKER]                   Print registry status (one ticker or all).

This script intentionally does NOT call sub-skills directly. Sub-skills (financial-analysis,
business-model-analysis, etc.) are invoked via Codex project Skills by the orchestrator SKILL.md.
This script just handles the file plumbing.

v3.1 (2026-07-30): added slot 04_战略决策.md (strategic-decision-analysis).
- Required node in the DAG (Tier 2.5: ←01/02/03, +05 reference), slow-refresh
  (catalyst-driven, own stale threshold 365d; quarterly Mode C doesn't rerun it).
- TRANSITION: complete/stale status, research-summary trigger and the briefing
  dashboard are computed over CORE_SLOTS (the 6 original slots) until the user
  finishes manually backfilling 04 for existing companies. Flip COMPLETE_BASIS
  below when backfill is done.
- 06/07 list 04 as a SOFT dependency: missing → OPTIONAL_MISSING in context
  bundle, downstream proceeds and notes the gap.
- finalize-refresh runs handoff_lint.py on 06/07/04 batch outputs (sentinel /
  required-section / row-cap checks); lint ERRORs mark the slot failed.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone, date
from pathlib import Path


# --------------------------------------------------------------------------
# Path configuration — works both inside cowork sandbox and on host filesystem.
# --------------------------------------------------------------------------
def detect_projects_root() -> Path:
    from tidestone_paths import PROJECTS_ROOT
    return PROJECTS_ROOT


PROJECTS_ROOT = detect_projects_root()
SYSTEM_DIR = PROJECTS_ROOT / "_system"
REGISTRY_PATH = SYSTEM_DIR / "dossier_registry.json"

CANONICAL_SLOTS = [
    "01_企业文化.md",
    "02_财务分析.md",
    "03_商业模式.md",
    "04_战略决策.md",  # v3.1: required node, slow-refresh (catalyst-driven)
    "05_股性分析.md",
    "06_财务预测.md",
    "07_估值分析.md",
]

# The 6 original slots. TRANSITION (2026-07-30): while the user manually backfills
# 04 for existing companies, completeness/staleness/HTML-trigger/briefing use
# CORE_SLOTS so 50 legacy companies don't all flip to "partial" overnight.
CORE_SLOTS = [s for s in CANONICAL_SLOTS if s != "04_战略决策.md"]
# Flip this to CANONICAL_SLOTS when 04 backfill is complete (one-line switch).
COMPLETE_BASIS = CANONICAL_SLOTS

# Soft dependencies: listed in SLOT_DEPENDENCIES but absence does not block the
# downstream slot — context bundle marks them OPTIONAL_MISSING instead of MISSING.
SOFT_DEP_SLOTS = set()  # New dossiers have no legacy transition exception.

SLOT_TO_SUB_SKILLS = {
    "01_企业文化.md": [
        "mission-vision-assessment",
        "leadership-assessment",
        "corporate-governance-assessment",
    ],
    "02_财务分析.md": ["financial-analysis"],
    "03_商业模式.md": ["business-model-analysis"],
    "05_股性分析.md": ["stock-character-analysis"],
    "06_财务预测.md": ["financial-forecast"],
    "07_估值分析.md": ["valuation-analysis"],
    "04_战略决策.md": ["strategic-decision-analysis"],
}

# DAG: slot -> list of slot names it depends on (read-context for the sub-skill)
SLOT_DEPENDENCIES = {
    "01_企业文化.md": [],
    "02_财务分析.md": [],
    "03_商业模式.md": ["02_财务分析.md"],
    "05_股性分析.md": [],
    "06_财务预测.md": [
        "01_企业文化.md",
        "02_财务分析.md",
        "03_商业模式.md",
        "04_战略决策.md",  # soft dep: H2 scenarios + H3 handoff table seed the forecast's 三情景
    ],
    "07_估值分析.md": [
        "05_股性分析.md",
        "06_财务预测.md",
        "04_战略决策.md",  # soft dep: H2 milestones + H4 positioning/anchor-switch hypothesis
    ],
    "04_战略决策.md": [
        "01_企业文化.md",
        "02_财务分析.md",
        "03_商业模式.md",
        "05_股性分析.md",  # reference-grade: historical market-reaction patterns for the decision ledger
    ],
}

# --------------------------------------------------------------------------
# Company portfolio — 单一真相源：_system/companies.json
# --------------------------------------------------------------------------
# 2026-08-01 分类重构第 3a 步。此处原先硬编码一份 52 行的 COMPANIES 列表，与
# portfolio_registry.md、文件系统三方各写各的，加一家公司要记住改三处。现在
# 统一从 companies.json 加载，那里也是 build_site.py 的板块来源。
#
# 四元组接口 (ticker, name, sector, folder) 保持不变，下游 scan_company_entry /
# rescan_one / prepare 全部无需改动。三点约定：
#   · name   取 name_cn，缺失才回落 name_en。company_name 会成为研究总结 HTML 的
#            文件名（见 prepare 的输出提示），中文优先与全库其余部分一致。
#   · sector 取 GICS 一级板块的**中文名**（"信息技术"），不取代码——registry 会被
#            人和 sub-skill 直接读，"45" 不可读。需要精确到 8 位 sub-industry 时
#            直接读 companies.json。
#   · folder 优先取 folder，回落 legacy_folder。第 5 步文件夹 ticker 化后只需把
#            companies.json 里的字段改名，这里不用动。
COMPANIES_PATH = SYSTEM_DIR / "companies.json"


def load_companies_list():
    """从 companies.json 读出 (ticker, name, sector, folder) 列表，保持文件内顺序。"""
    try:
        raw = COMPANIES_PATH.read_bytes()
    except FileNotFoundError:
        raise SystemExit(
            f"找不到 {COMPANIES_PATH}。\n"
            "分类重构第 3a 步（2026-08-01）起，公司名单与板块的真相源是这个文件；"
            "旧的 COMPANIES 硬编码列表已删除，备份见 dossier_orchestrator.py.bak_before_taxonomy_20260801。"
        )
    if b"\x00" in raw:          # FUSE 缓存偶发的 NUL 填充：读到就明确报错，不要静默解析失败
        raise SystemExit(f"{COMPANIES_PATH} 含 NUL 填充（FUSE 缓存现象），请在宿主机确认后重跑")
    data = json.loads(raw.decode("utf-8"))

    sector_names = data.get("gics_sector_names", {})
    rows = []
    for ticker, e in data["companies"].items():
        code = (e.get("gics") or {}).get("sector")
        if not code:
            raise SystemExit(f"companies.json 里 {ticker} 缺 gics.sector，补齐后再跑")
        folder = e.get("folder") or e.get("legacy_folder")
        if not folder:
            raise SystemExit(f"companies.json 里 {ticker} 既无 folder 也无 legacy_folder")
        name = e.get("name_cn") or e.get("name_en") or ticker
        rows.append((ticker, name, sector_names.get(code, f"未知板块 {code}"), folder))
    return rows


COMPANIES = load_companies_list()

# --------------------------------------------------------------------------
# Classification rules — order matters (most specific first).
# Each (pattern, slot) is checked against the lowercased full file path.
# --------------------------------------------------------------------------
RULES = [
    # strategy must match FIRST — most specific vocabulary, avoids leaking into 03/06
    (r"(战略决策|战略解码|核心战略|战略dna|strategic.{0,3}decision)", "04_战略决策.md"),
    # forecast must match BEFORE valuation so "财务预测核心假设" classifies as 06
    (r"(财务预测|forecast|预测核心假设|盈利预测|model.{0,3}update)", "06_财务预测.md"),
    # valuation patterns — DCF, 估值, 综合估值, 投资建议书, 内在价值 all go to 07
    (r"(dcf|估值分析|估值\s|valuation|内在价值|综合估值|投资建议书)", "07_估值分析.md"),
    (r"(股性分析|股性特征|历史股价|股价复盘|历史复盘|stock.{0,3}character|价格行为)", "05_股性分析.md"),
    (r"(商业模式|business.{0,3}model|业务分析|业务模式)", "03_商业模式.md"),
    (r"(财务分析|financial.{0,3}analysis|财务状况|财务综合|综合财务)", "02_财务分析.md"),
    (r"(企业文化|公司文化|使命愿景|leadership|领导力|governance|公司治理|mission.{0,5}vision)", "01_企业文化.md"),
]

CONTENT_EXTS = {".md", ".docx"}
EXCLUDE_PATH_SEGMENTS = ["wiki/", "wiki\\", "raw/", "raw\\", "财务数据/", "财务数据\\", "_meta.json", "研究档案/"]
EXCLUDE_FILENAME_PATTERNS = ["earnings", "transcript", "10-k", "10-q", "20-f", "8-k"]
EXCLUDE_DIR_NAMES = {"wiki", "raw", "earnings", "earnings report", "earnings call", "研究档案"}

STALE_THRESHOLD_DAYS = 120
# Per-slot override: strategy is a slow variable, refreshed on catalyst not calendar.
STALE_THRESHOLD_BY_SLOT = {"04_战略决策.md": 365}


def _slot_stale_threshold(slot: str) -> int:
    return STALE_THRESHOLD_BY_SLOT.get(slot, STALE_THRESHOLD_DAYS)


def _classify_file(filepath: Path) -> str | None:
    """Return canonical slot filename, or None if no match."""
    import re
    haystack = str(filepath).lower()
    for ex in EXCLUDE_PATH_SEGMENTS:
        if ex in haystack:
            return None
    for pat in EXCLUDE_FILENAME_PATTERNS:
        if pat in filepath.name.lower():
            return None
    if filepath.suffix.lower() not in CONTENT_EXTS:
        return None
    for pattern, slot in RULES:
        if re.search(pattern, haystack):
            return slot
    return None


def _get_file_mtime_date(filepath: Path) -> str | None:
    """Prefer filename date; fallback to mtime."""
    import re
    name = filepath.name
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", name)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except ValueError:
            pass
    m = re.search(r"(20\d{2})年(\d{1,2})月", name)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-01"
    try:
        return date.fromtimestamp(filepath.stat().st_mtime).isoformat()
    except Exception:
        return None


def approved_slot_errors(dossier: Path, slot: str, meta_docs=None) -> list[str]:
    """Only an accepted, intact canonical file is a formal research document.

    This new library has no legacy migration: materials, drafts and backups are
    never discovered by filename. The accepted hash also detects direct edits.
    """
    import hashlib
    if meta_docs is None:
        try:
            meta_docs = json.loads((dossier / "_meta.json").read_text(encoding="utf-8")).get("documents", {})
        except (OSError, ValueError, AttributeError):
            return ["缺少有效的正式接受记录"]
    if not isinstance(meta_docs, dict):
        return ["正式接受记录格式无效"]
    record = meta_docs.get(slot)
    if not isinstance(record, dict) or record.get("approval_status") != "approved":
        return ["该模块尚未被接受"]
    if not record.get("accepted_batch") or not record.get("approved_at") or not record.get("sha256"):
        return ["缺少已接受批次、接受时间或内容哈希"]
    path = dossier / slot
    if not path.is_file() or path.is_symlink():
        return ["正式模块缺失或不是本地常规文件"]
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError):
        return ["正式模块无法读取为 UTF-8"]
    if not text.strip() or "\x00" in text:
        return ["正式模块为空或含损坏字符"]
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        return ["正式模块与已接受内容哈希不符；直接修改不能视为已审阅"]
    return []


def scan_company_entry(ticker: str, name: str, sector: str, folder_rel: str) -> dict:
    """Scan only approved canonical slots; legacy filename discovery is disabled."""
    folder_abs = PROJECTS_ROOT / folder_rel
    folder_exists = folder_abs.exists()
    dossier_abs = folder_abs / "研究档案"
    today = date.today()
    try:
        meta_docs = json.loads((dossier_abs / "_meta.json").read_text(encoding="utf-8")).get("documents", {})
    except (OSError, ValueError, AttributeError):
        meta_docs = {}
    result_docs = {}
    for slot in CANONICAL_SLOTS:
        errors = approved_slot_errors(dossier_abs, slot, meta_docs)
        if errors:
            result_docs[slot] = {"exists": False, "legacy_source": None,
                                 "all_candidates": [], "shadowed_legacy": [],
                                 "integrity_errors": errors}
            continue
        record = meta_docs[slot]
        raw_lu = record.get("last_updated") or record.get("approved_at")
        lu = raw_lu[:10] if raw_lu else None
        try:
            age = (today - date.fromisoformat(lu)).days if lu else None
        except (TypeError, ValueError):
            age = None
        canon_rel = f"{folder_rel}/研究档案/{slot}"
        result_docs[slot] = {
            "exists": True, "last_updated": lu, "age_days": age,
            "is_stale": age is not None and age > _slot_stale_threshold(slot),
            # Retained key for source consumers; it can only point to a formal slot.
            "legacy_source": canon_rel, "canonical_path": canon_rel,
            "all_candidates": [canon_rel], "shadowed_legacy": [],
            "approval_status": "approved", "accepted_batch": record["accepted_batch"],
        }
    exists_count = sum(result_docs[s]["exists"] for s in COMPLETE_BASIS)
    stale_count = sum(bool(result_docs[s].get("is_stale")) for s in COMPLETE_BASIS)
    if not folder_exists:
        status = "folder_missing"
    elif exists_count == 0:
        status = "empty"
    elif exists_count == len(COMPLETE_BASIS):
        status = "stale" if stale_count else "complete"
    else:
        status = "partial"
    return {
        "ticker": ticker, "company_name": name, "sector": sector,
        "folder": folder_rel, "folder_exists": folder_exists,
        "dossier_path": f"{folder_rel}/研究档案", "dossier_status": status,
        "exists_count": exists_count, "documents": result_docs, "pending_reviews": [],
        "stale_threshold_days": STALE_THRESHOLD_DAYS,
    }


# Fields preserved across rescan (orchestrator-managed state)
PRESERVED_FIELDS = ["dossier_initialized", "dossier_initialized_at", "pending_reviews"]


def _merge_preserved(new_entry: dict, old_entry: dict | None) -> dict:
    """Copy persistent state from old entry into freshly-scanned entry,
    AND infer dossier_initialized from disk (presence of 研究档案/_meta.json) as backup.
    Disk truth wins over registry memory."""
    # Backup recovery: if 研究档案/_meta.json exists on disk, that company is initialized.
    dossier_meta = PROJECTS_ROOT / new_entry["dossier_path"] / "_meta.json"
    new_entry["dossier_initialized"] = any(d.get("exists") for d in new_entry["documents"].values())
    if new_entry["dossier_initialized"] and dossier_meta.exists():
        # Use file mtime as the init timestamp if registry didn't remember it
        try:
            new_entry.setdefault(
                "dossier_initialized_at",
                datetime.fromtimestamp(dossier_meta.stat().st_mtime, tz=timezone.utc).isoformat(),
            )
        except Exception:
            pass

    # Pull live pending_reviews state from disk too — _pending/{ts}/ that isn't _rejected/
    pending_root = PROJECTS_ROOT / new_entry["dossier_path"] / "_pending"
    if pending_root.exists():
        live_pending = []
        for batch in pending_root.iterdir():
            if not batch.is_dir() or batch.name.startswith("_"):
                continue
            # Skip EMPTY batch dirs: a real pending batch always holds _context_bundle.json
            # + slot files; an accepted batch is emptied, but on some mounts (FUSE) the
            # final rmdir is blocked ("Operation not permitted"), leaving a hollow {ts}/ dir.
            # Counting those as pending_reviews would resurrect already-accepted batches and
            # wrongly block future prepare-refresh. Treat empty dirs as not-pending.
            try:
                if not any(batch.iterdir()):
                    continue
            except Exception:
                continue
            # Read trigger from batch's _meta.json if present
            batch_meta = batch / "_meta.json"
            trigger = "unknown"
            if batch_meta.exists():
                try:
                    with open(batch_meta, encoding="utf-8") as f:
                        bm = json.load(f)
                    trigger = bm.get("trigger", "unknown")
                except Exception:
                    pass
            live_pending.append({"timestamp": batch.name, "trigger": trigger})
        new_entry["pending_reviews"] = live_pending
    else:
        new_entry.setdefault("pending_reviews", [])

    # Then layer on old_entry's fields (highest priority for older timestamps, etc.)
    if old_entry is not None:
        for field in PRESERVED_FIELDS:
            if field == "pending_reviews":
                # Disk wins for pending_reviews (already set above)
                continue
            if field in old_entry and old_entry[field] is not None and field not in new_entry:
                new_entry[field] = old_entry[field]

    return new_entry


def rescan_one(ticker: str, registry: dict | None = None, save: bool = True) -> dict:
    """Re-scan a single company's folder and merge into registry. Returns new entry."""
    spec = next((row for row in COMPANIES if row[0] == ticker), None)
    if spec is None:
        raise ValueError(f"Ticker {ticker} not in COMPANIES portfolio. Add it first.")
    if registry is None:
        registry = load_registry() if REGISTRY_PATH.exists() else {"schema_version": "1.0", "companies": []}

    new_entry = scan_company_entry(*spec)
    # Find existing entry
    idx = next((i for i, c in enumerate(registry["companies"]) if c["ticker"] == ticker), None)
    if idx is not None:
        old = registry["companies"][idx]
        new_entry = _merge_preserved(new_entry, old)
        registry["companies"][idx] = new_entry
    else:
        registry["companies"].append(new_entry)

    if save:
        save_registry(registry)
    return new_entry


def rescan_all(verbose: bool = False) -> dict:
    """Re-scan all companies. Preserves dossier_initialized + pending_reviews from previous registry."""
    old_registry = load_registry() if REGISTRY_PATH.exists() else None
    old_by_ticker = {c["ticker"]: c for c in (old_registry["companies"] if old_registry else [])}

    registry = {
        "schema_version": "1.0",
        "last_updated": date.today().isoformat(),
        "default_stale_threshold_days": STALE_THRESHOLD_DAYS,
        "scan_notes": "Re-scan with state preservation (dossier_initialized + pending_reviews retained).",
        "companies": [],
    }
    for ticker, name, sector, folder in COMPANIES:
        entry = scan_company_entry(ticker, name, sector, folder)
        entry = _merge_preserved(entry, old_by_ticker.get(ticker))
        registry["companies"].append(entry)
        if verbose:
            path_label = "✓" if entry["folder_exists"] else "✗"
            init = "✓" if entry.get("dossier_initialized") else " "
            print(f"[{ticker:10}] {entry['exists_count']}/{len(COMPLETE_BASIS)}  status={entry['dossier_status']:14}  folder={path_label}  init={init}")

    save_registry(registry)
    if verbose:
        print(f"\nWrote {REGISTRY_PATH}")
        counts = {}
        for c in registry["companies"]:
            counts[c["dossier_status"]] = counts.get(c["dossier_status"], 0) + 1
        print(f"Status: {counts}")

        # 正本优先之后，散落的旧文件不再影响判定，但它们留在公司目录里会让人误读
        # （以为那才是现行档案），也会在 migrate 时造成困惑。这里主动报出来。
        shadow = []
        for c in registry["companies"]:
            for slot, d in (c.get("documents") or {}).items():
                for old in (d.get("shadowed_legacy") or []):
                    shadow.append((c["ticker"], slot, old))
        no_canon = [(c["ticker"], slot)
                    for c in registry["companies"]
                    for slot, d in (c.get("documents") or {}).items()
                    if d.get("canonical_missing")]
        if shadow:
            by_tk = {}
            for tk, slot, old in shadow:
                by_tk.setdefault(tk, []).append(old)
            print(f"\n⚠️  {len(shadow)} 个散落旧文件已被正本盖过（不影响判定，建议归档）："
                  f"涉及 {len(by_tk)} 家")
            for tk, olds in sorted(by_tk.items()):
                print(f"   {tk}: {len(olds)} 个，例 {olds[0]}")
            print("   处理：python cleanup_projects.py --list  然后 --apply T3-3")
        if no_canon:
            print(f"\n⚠️  {len(no_canon)} 个模块还没有 研究档案/ 正本，仍在用散落旧文件："
                  f"{sorted({t for t, _ in no_canon})}")
            print("   处理：python _system/scripts/dossier_orchestrator.py migrate {TICKER}")
    return registry


def now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")


# --------------------------------------------------------------------------
# Automation pending queues — written by cmd_accept, consumed by scanner
# --------------------------------------------------------------------------
PENDING_VALUATION_SYNC = SYSTEM_DIR / "pending_valuation_sync.json"


def _enqueue_pending(path: Path, entry: dict) -> None:
    """Append (or replace) an entry in a pending queue JSON file.
    Deduplicates by ticker so a repeated accept doesn't pile up."""
    existing: list = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f).get("pending", [])
        except Exception:
            existing = []
    ticker = entry.get("ticker")
    existing = [e for e in existing if e.get("ticker") != ticker]  # dedup
    existing.append(entry)
    atomic_dump_json(
        {"pending": existing, "updated_at": datetime.now(timezone.utc).isoformat()},
        path, indent=2,
    )


def _handle_accept_automation(ticker: str, batch_slot_files: dict, company: dict) -> None:
    """Trigger automated follow-up steps after accept.

    1. 07_估值分析.md was accepted  →  pending_valuation_sync.json
       Scanner will read the file, extract rating/target/zones, update
       valuation_registry.json, then run sync_valuations.py apply.

    2. All 7 slots are now complete  →  print instruction for Codex to
       invoke research-summary skill immediately in the current session.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Same-batch downstream modules already consumed the strategy handoff.
    if "04_战略决策.md" in batch_slot_files:
        outstanding = [s for s in ("06_财务预测.md", "07_估值分析.md") if s not in batch_slot_files]
        if outstanding:
            print(
                f"\n  📌 [提示] 04_战略决策.md 已更新，以下模块未在同批覆盖，需核对新战略交接："
                f"\n     python3 scripts/tidestone.py prepare {ticker} --slots {' '.join(outstanding)} --trigger catalyst"
            )

    # 1. Valuation sync queue (consumed by daily scanner Step 0a)
    if "07_估值分析.md" in batch_slot_files:
        slot07_rel = f"{company['dossier_path']}/07_估值分析.md"
        _enqueue_pending(
            PENDING_VALUATION_SYNC,
            {"ticker": ticker, "slot07_path": slot07_rel, "added_at": now},
        )
        print(
            f"\n  ✅ 已入队 pending_valuation_sync.json"
            f"\n  📌 [请执行] 队列不会自己消费，请跑："
            f"\n     python3 scripts/tidestone.py sync {ticker}"
            f"\n     （从同一已接受 07 提取普通估值与三年登记块；两者均通过才出队，缺失保留待补）"
        )

    # 2. Research summary — print instruction for Codex to act on immediately.
    # (No queue file: research-summary requires Codex analysis and should
    # run in the current session, not wait until the next scanner run.)
    # Every accepted module can affect the seven-module summary.
    all_slots_present = all(
        company["documents"].get(slot, {}).get("exists") for slot in COMPLETE_BASIS
    )
    batch_touches_core = any(s in batch_slot_files for s in CANONICAL_SLOTS)
    if all_slots_present and batch_touches_core:
        dossier_abs = str(PROJECTS_ROOT / company["dossier_path"])
        summary_stem = str(Path(dossier_abs).parent / f"研究总结_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}")
        print(
            f"\n  📋 [NEXT STEP — 请立即执行] 研究档案 7 模块全部就位，"
            f"请调用 research-summary skill 生成研究总结 Markdown 与 HTML：\n"
            f"     档案目录：{dossier_abs}\n"
            f"     输出目标：{summary_stem}.md 与 {summary_stem}.html\n"
            f"     登记：python3 scripts/register_summary.py {ticker} --markdown '{summary_stem}.md' --html '{summary_stem}.html'\n"
            f"     登记后：python3 scripts/ops.py build"
        )


def load_registry() -> dict:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def atomic_dump_json(obj, path: Path, indent: int = 2):
    """原子写 JSON：先写同目录 .tmp，fsync，再 os.replace 覆盖目标。
    FUSE 挂载下 open(w) 会立即把目标截断为 0 字节再流式写入，进程/桥接
    中断即留下截断文件（2026-07-14 甲骨文、2026-07-15 TEAM 两次事故）。
    原子写保证目标要么是旧的完整文件、要么是新的完整文件，绝不出现半截。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_registry(reg: dict):
    reg["last_updated"] = date.today().isoformat()
    atomic_dump_json(reg, REGISTRY_PATH, indent=2)


def find_company(reg: dict, ticker: str) -> dict:
    for c in reg["companies"]:
        if c["ticker"] == ticker:
            return c
    raise ValueError(f"Ticker {ticker} not found in dossier_registry.json")


def dossier_dir(company: dict) -> Path:
    return PROJECTS_ROOT / company["dossier_path"]


# --------------------------------------------------------------------------
# Mode: migrate — copy legacy_source files into canonical 研究档案/.
# Auto-rescans the company's folder first to avoid stale legacy_source paths.
# Exits non-zero if any legacy_source exists in registry but is missing on disk.
# --------------------------------------------------------------------------
def cmd_migrate(ticker: str, skip_rescan: bool = False):
    raise ValueError("本地全新研究库禁止迁入既有研究结论；请用 tidestone.py add/material/prepare 建档")



def _warn_missing_three_year_target(ticker: str) -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_three_year_coverage import check
    except Exception as e:                                    # 校验器缺失不应阻断 accept
        print(f"  ⚠️ 三年估值覆盖校验不可用（{e}）")
        return
    result = check(ticker)
    if any(str(g).startswith(ticker) for g in result["gaps"]):
        print(f"\n  ⚠️ {ticker} 已接受 07_估值分析，但 three_year_valuation_registry.json 无可用条目。")
        print(f"     不补的话该公司在组合三年估值看板上会显示「待补录」。")
        print(f"     补录：写 _system/three_year_valuation_registry.json（目标年指标 / 基准倍数 / 净负债 / 等效股数）")
        print(f"     或豁免：写 _system/three_year_coverage_waivers.json 说明为什么暂时补不了")
    elif any(t == ticker for t, _ in result["waived"]):
        print(f"  ℹ️ {ticker} 三年估值缺口已在 three_year_coverage_waivers.json 中豁免")

def cmd_status(ticker=None):
    reg = load_registry()
    print(f"{'ticker':12} {'dossier_status':14} {'init':5} {'pending':8} docs")
    print("-" * 80)
    for c in reg["companies"]:
        if ticker and c["ticker"] != ticker:
            continue
        init = "Y" if c.get("dossier_initialized") else "."
        pending = len(c.get("pending_reviews", []))
        slot_status = "".join(["+" if c["documents"].get(s, {}).get("exists") else "." for s in CANONICAL_SLOTS])
        print(f"{c['ticker']:12} {c['dossier_status']:14} {init:5} {pending:<8} {slot_status}")

def cmd_rescan(ticker=None):
    if ticker is None:
        rescan_all(verbose=True)
    else:
        entry = rescan_one(ticker, save=True)
        init = "Y" if entry.get("dossier_initialized") else "."
        print(f"[rescan {ticker}] status={entry['dossier_status']}  exists={entry['exists_count']}/{len(COMPLETE_BASIS)}  init={init}")
        for slot in CANONICAL_SLOTS:
            d = entry["documents"][slot]
            if d.get("exists"):
                print(f"  {slot}: {d['legacy_source']}")
            else:
                print(f"  {slot}: (no legacy source)")

def cmd_briefing_snippet(stale_days: int = 120):
    reg = load_registry()
    today = date.today()

    pending_review = []
    stale_list = []
    partial_list = []
    missing_strategy = []  # v3.1: initialized companies still awaiting manual 04 backfill
    per_company = {}
    summary = {"total": 0, "complete": 0, "partial": 0, "empty": 0, "stale": 0,
               "pending_review": 0, "not_initialized": 0, "missing_strategy": 0}

    for c in reg["companies"]:
        ticker = c["ticker"]
        dd = PROJECTS_ROOT / c["dossier_path"]
        meta_path = dd / "_meta.json"
        summary["total"] += 1
        initialized = bool(c.get("dossier_initialized"))
        if not initialized:
            summary["not_initialized"] += 1

        # Compute slot-by-slot age and aggregate stats
        slot_ages: dict[str, int | None] = {}
        slot_status_chars = []
        max_age = 0
        slot_states: dict[str, str] = {}
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {"documents": {}}
            for slot in CORE_SLOTS:  # dashboard slot string stays 6 chars; 04 tracked separately below
                sm = meta.get("documents", {}).get(slot, {})
                status = sm.get("approval_status", "missing")
                slot_states[slot] = status
                last = sm.get("last_updated")
                age = None
                if status == "approved" and last:
                    try:
                        # last is sometimes a date YYYY-MM-DD, sometimes full ISO
                        ldate = date.fromisoformat(last[:10])
                        age = (today - ldate).days
                        max_age = max(max_age, age)
                    except Exception:
                        pass
                slot_ages[slot] = age
                # slot_status_chars: + if approved & fresh, ~ if approved but stale, . otherwise
                if status == "approved":
                    if age is not None and age > stale_days:
                        slot_status_chars.append("~")
                    else:
                        slot_status_chars.append("+")
                elif status == "missing":
                    slot_status_chars.append(".")
                elif status == "failed":
                    slot_status_chars.append("!")
                else:
                    slot_status_chars.append("?")
        else:
            for slot in CORE_SLOTS:
                slot_ages[slot] = None
                slot_status_chars.append(".")
                slot_states[slot] = "missing"

        # Pending reviews from registry (mirrors disk via rescan)
        prs = c.get("pending_reviews", [])
        has_pending = len(prs) > 0
        latest_pending_ts = prs[-1]["timestamp"] if has_pending else None
        latest_pending_trigger = prs[-1].get("trigger") if has_pending else None

        # Approved-slot count
        approved = sum(1 for s in slot_states.values() if s == "approved")

        # Stale slot list
        stale_slots = [
            s for s in CORE_SLOTS
            if slot_states[s] == "approved" and slot_ages[s] is not None and slot_ages[s] > stale_days
        ]

        # 04 strategy slot: tracked as a separate backfill list, never flips status.
        has_strategy = bool(
            (dd / "04_战略决策.md").exists()
            or c.get("documents", {}).get("04_战略决策.md", {}).get("exists")
        )

        # Per-company dossier object
        per_company[ticker] = {
            "initialized": initialized,
            "has_strategy": has_strategy,
            "exists_count": approved,
            "max_age_days": max_age if max_age > 0 else None,
            "slot_status": "".join(slot_status_chars),
            "has_pending": has_pending,
            "pending_batch_ts": latest_pending_ts,
            "pending_trigger": latest_pending_trigger,
            "stale_slots": stale_slots,
            "dossier_path": c["dossier_path"],
        }

                # Bucket counters
        if initialized and not has_strategy:
            missing_strategy.append({"ticker": ticker, "name": c["company_name"], "sector": c["sector"]})

        if not initialized and approved == 0:
            summary["empty"] += 1
        elif approved == len(CORE_SLOTS) and not stale_slots:
            summary["complete"] += 1
        elif approved < len(CORE_SLOTS):
            summary["partial"] += 1
        elif stale_slots:
            summary["stale"] += 1

        if has_pending:
            summary["pending_review"] += 1
            headline = None
            if latest_pending_ts:
                diff_path = dd / "_pending" / latest_pending_ts / "_diff_summary.md"
                if diff_path.exists():
                    try:
                        with open(diff_path, encoding="utf-8") as f:
                            headline = f.readline().strip().lstrip("#").strip()
                    except Exception:
                        pass
            pending_review.append({
                "ticker": ticker,
                "name": c["company_name"],
                "sector": c["sector"],
                "batch_ts": latest_pending_ts,
                "trigger": latest_pending_trigger,
                "headline": headline,
                "diff_summary_path": str((dd / "_pending" / latest_pending_ts / "_diff_summary.md").relative_to(PROJECTS_ROOT)) if latest_pending_ts else None,
            })

        if stale_slots:
            stale_list.append({
                "ticker": ticker,
                "name": c["company_name"],
                "sector": c["sector"],
                "max_age_days": max_age,
                "stale_slots": stale_slots,
            })

        if initialized and approved < len(CORE_SLOTS):
            missing = [s for s in CORE_SLOTS if slot_states[s] != "approved"]
            partial_list.append({
                "ticker": ticker,
                "name": c["company_name"],
                "sector": c["sector"],
                "missing_slots": missing,
                "exists_count": approved,
            })

    summary["missing_strategy"] = len(missing_strategy)
    snippet = {
        "dossiers": {
            "summary": summary,
            "pending_review": pending_review,
            "stale": stale_list,
            "partial": partial_list,
            "missing_strategy": missing_strategy,
            "stale_threshold_days": stale_days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "companies_dossier": per_company,
    }
    print(json.dumps(snippet, ensure_ascii=False, indent=2))

def cmd_audit():
    reg = load_registry()
    problems = []
    ok = []
    for c in reg["companies"]:
        ticker = c["ticker"]
        dd = PROJECTS_ROOT / c["dossier_path"]
        meta_path = dd / "_meta.json"
        if not meta_path.exists():
            if c["dossier_status"] != "empty":
                problems.append((ticker, ["no _meta.json (not migrated yet)"]))
            continue  # fix 2026-07-30: 缺 _meta.json 时必须跳过，否则下面 open() 抛 FileNotFoundError 中断整个 audit
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        company_issues = []
        approved_count = 0
        for slot in CANONICAL_SLOTS:
            slot_meta = meta["documents"].get(slot, {})
            status = slot_meta.get("approval_status", "missing")
            md_exists = (dd / slot).exists()
            docx_exists = (dd / slot.replace(".md", ".docx")).exists()
            any_file = md_exists or docx_exists
            reg_slot = c["documents"].get(slot, {})  # old registries may lack the 04 key until next rescan
            if status == "approved":
                if slot in CORE_SLOTS:
                    approved_count += 1  # 04 audited for disk consistency but not counted as core
                if not any_file:
                    company_issues.append(f"{slot}: meta='approved' BUT no file on disk")
            elif status == "missing":
                if reg_slot.get("exists"):
                    company_issues.append(f"{slot}: meta='missing' but rescan finds " + str(reg_slot.get('legacy_source')))
            elif status == "failed":
                company_issues.append(f"{slot}: prior migration failed")
        if company_issues:
            problems.append((ticker, company_issues))
        else:
            ok.append((ticker, approved_count))
    print(f"=== Clean: {len(ok)} companies ===")
    for t, n in ok:
        print(f"  {t}: {n}/{len(CORE_SLOTS)} core approved (+04 optional during transition)")
    print(f"\n=== Problems: {len(problems)} companies ===")
    for t, issues in problems:
        print(f"  {t}:")
        for line in issues:
            print(f"    - {line}")
    if problems:
        sys.exit(1)

def cmd_prepare_refresh(ticker, slots, trigger="manual"):
    import local_workflow as local
    result = local.prepare(sys.modules[__name__], ticker, slots, trigger)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def cmd_finalize_refresh(ticker, ts):
    import local_workflow as local
    result = local.finalize(sys.modules[__name__], ticker, ts)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["batch_status"] != "ready_for_review":
        raise SystemExit(1)
    return result


def cmd_accept(ticker, ts=None, reason="用户明确接受"):
    import local_workflow as local
    result = local.accept(sys.modules[__name__], ticker, ts, reason)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def cmd_reject(ticker, ts=None, reason="用户退回，待修订"):
    import local_workflow as local
    result = local.reject(sys.modules[__name__], ticker, ts, reason)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mig = sub.add_parser("migrate", help="Copy legacy_source files into canonical 研究档案/. Auto-rescans first.")
    p_mig.add_argument("ticker")

    p_prep = sub.add_parser("prepare-refresh", help="Create _pending/{ts}/ and emit context bundle")
    p_prep.add_argument("ticker")
    p_prep.add_argument("--slots", nargs="*", default=None)
    p_prep.add_argument("--trigger", default="manual")

    p_fin = sub.add_parser("finalize-refresh", help="Write _meta.json + _diff_summary.md after sub-skill outputs land")
    p_fin.add_argument("ticker")
    p_fin.add_argument("timestamp")

    p_acc = sub.add_parser("accept", help="Move _pending/{ts}/ slots -> 研究档案/ (partial-replace semantics)")
    p_acc.add_argument("ticker")
    p_acc.add_argument("timestamp", nargs="?", default=None)

    p_rej = sub.add_parser("reject", help="Move _pending/{ts}/ -> _pending/_rejected/")
    p_rej.add_argument("ticker")
    p_rej.add_argument("timestamp", nargs="?", default=None)

    p_stat = sub.add_parser("status", help="Print registry status")
    p_stat.add_argument("ticker", nargs="?", default=None)

    p_resc = sub.add_parser("rescan", help="Re-scan folder(s) and update registry")
    p_resc.add_argument("ticker", nargs="?", default=None)

    p_aud = sub.add_parser("audit", help="Cross-check _meta.json approvals vs disk")

    p_brf = sub.add_parser("briefing-snippet", help="Emit JSON for daily-briefing dashboard")
    p_brf.add_argument("--stale-days", type=int, default=120)

    args = parser.parse_args()

    if args.cmd == "migrate":
        cmd_migrate(args.ticker)
    elif args.cmd == "prepare-refresh":
        cmd_prepare_refresh(args.ticker, args.slots, args.trigger)
    elif args.cmd == "finalize-refresh":
        cmd_finalize_refresh(args.ticker, args.timestamp)
    elif args.cmd == "accept":
        cmd_accept(args.ticker, args.timestamp)
    elif args.cmd == "reject":
        cmd_reject(args.ticker, args.timestamp)
    elif args.cmd == "status":
        cmd_status(args.ticker)
    elif args.cmd == "rescan":
        cmd_rescan(args.ticker)
    elif args.cmd == "audit":
        cmd_audit()
    elif args.cmd == "briefing-snippet":
        cmd_briefing_snippet(args.stale_days)


if __name__ == "__main__":
    from local_workflow import lock
    with lock():
        main()

