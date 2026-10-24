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
                                    orchestrator SKILL.md (claude reads context, runs skills,
                                    writes outputs).

  finalize-refresh {TICKER} {TS}    After all sub-skill outputs have been written into
                                    _pending/{TS}/, write _meta.json and _diff_summary.md.

  accept {TICKER} [TS]              Move 研究档案/*.md + _meta.json into _history/{now}/,
                                    then move _pending/{TS}/*.md → 研究档案/.

  reject {TICKER} [TS]              Move _pending/{TS}/ → _pending/_rejected/{TS}/.

  status [TICKER]                   Print registry status (one ticker or all).

This script intentionally does NOT call sub-skills directly. Sub-skills (financial-analysis,
business-model-analysis, etc.) are invoked via Claude's Skill tool by the orchestrator SKILL.md.
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
    """Try sandbox mount first (current + legacy), then user home. Sandbox mounts are
    per-session so we glob /sessions/*/mnt/Projects rather than hard-coding."""
    import glob

    candidates = []
    # Current/known sandbox mounts (may include other sessions; first accessible wins)
    for p in sorted(glob.glob("/sessions/*/mnt/Projects")):
        candidates.append(Path(p))
    # Cowork mount where the connected folder is a parent of Projects
    # (e.g. 连接的是 Documents\Claude → 挂成 /sessions/*/mnt/Claude/Projects)
    for p in sorted(glob.glob("/sessions/*/mnt/*/Projects")):
        candidates.append(Path(p))
    # Cowork mount: mnt/ itself is the Projects root (no /Projects subdirectory)
    for p in sorted(glob.glob("/sessions/*/mnt")):
        mp = Path(p)
        if (mp / "_system").exists():  # confirm it's really a Projects root
            candidates.append(mp)
    # Host filesystem fallbacks
    candidates.append(Path.home() / "Documents" / "Claude" / "Projects")
    candidates.append(Path("C:/Users/dbao0/Documents/Claude/Projects"))

    for c in candidates:
        try:
            if c.exists():
                return c
        except PermissionError:
            # Another session's mount we can't see — skip silently.
            continue
    raise FileNotFoundError(f"Could not locate Projects root. Tried: {candidates}")


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
COMPLETE_BASIS = CORE_SLOTS

# Soft dependencies: listed in SLOT_DEPENDENCIES but absence does not block the
# downstream slot — context bundle marks them OPTIONAL_MISSING instead of MISSING.
SOFT_DEP_SLOTS = {"04_战略决策.md"}

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
    if not rows:
        raise SystemExit("companies.json 的 companies 为空")
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


def scan_company_entry(ticker: str, name: str, sector: str, folder_rel: str) -> dict:
    """Fresh scan of one company's folder. Does NOT preserve persistent state."""
    folder_abs = PROJECTS_ROOT / folder_rel
    docs = {slot: {"exists": False, "candidates": []} for slot in CANONICAL_SLOTS}
    folder_exists = folder_abs.exists()
    today = date.today()

    if folder_exists:
        for root, dirs, files in os.walk(folder_abs):
            rootp = Path(root)
            if any(part.lower() in EXCLUDE_DIR_NAMES for part in rootp.parts):
                continue
            for fname in files:
                fp = rootp / fname
                slot = _classify_file(fp)
                if slot is None:
                    continue
                rel = fp.relative_to(PROJECTS_ROOT)
                mtime_date = _get_file_mtime_date(fp)
                docs[slot]["candidates"].append({
                    "path": str(rel).replace("\\", "/"),
                    "last_updated": mtime_date,
                })

    # ------------------------------------------------------------------
    # CANONICAL FIRST (2026-08-09)
    #
    # 以前的顺序是反的：先用上面 os.walk 找到的散落旧文件填 result_docs，
    # canonical overlay 只在「该模块 legacy 候选为空」时才生效。于是只要公司目录里
    # 还留着一个能被 _classify_file 认出的旧文件（不限根目录——研究结果/、分析结果/、
    # 分析/、战略解码/ 这些旧目录同样算），registry 认的就是它而不是 研究档案/ 正本。
    #
    # 2026-08-09 实测：13 家公司 37 个模块被遮挡，其中 22 个的正本更新——
    # BA 差 98 天（registry 认 4-23，正本 7-30）、PDD 差 116 天、3690.HK 差 97 天。
    # 「PDD/美团/GRAL 研究欠账 150 天」的印象有一半就是这么来的。
    #
    # 现在：研究档案/{slot}.md 存在就一律以它为准，日期取 _meta.json 的 last_updated
    # （没有才回落到 mtime）。散落的旧文件降级为 shadowed_legacy，只做提示、不参与判定。
    # ------------------------------------------------------------------
    dossier_abs = folder_abs / "研究档案"
    meta_docs = {}
    meta_path = dossier_abs / "_meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta_docs = json.load(f).get("documents", {})
        except Exception:
            meta_docs = {}

    def _entry(slot_name: str, path_rel: str, lu, legacy: list) -> dict:
        try:
            age = (today - date.fromisoformat(lu)).days if lu else None
        except Exception:
            age = None
        return {
            "exists": True,
            "last_updated": lu,
            "age_days": age,
            "is_stale": age is not None and age > _slot_stale_threshold(slot_name),
            "legacy_source": path_rel,
            "all_candidates": [path_rel] + [c for c in legacy if c != path_rel],
            "shadowed_legacy": [c for c in legacy if c != path_rel],
        }

    result_docs = {}
    for slot in CANONICAL_SLOTS:
        cands = sorted(docs[slot]["candidates"],
                       key=lambda x: x["last_updated"] or "", reverse=True)
        legacy_paths = [c["path"] for c in cands]
        slot_file = dossier_abs / slot

        if slot_file.exists():
            # 正本优先
            raw_lu = (meta_docs.get(slot) or {}).get("last_updated")
            lu = raw_lu[:10] if raw_lu else _get_file_mtime_date(slot_file)
            canon_rel = f"{folder_rel}/研究档案/{slot}"
            result_docs[slot] = _entry(slot, canon_rel, lu, legacy_paths)
        elif cands:
            # 没有正本才回落到散落旧文件（迁移前的老公司）
            chosen = cands[0]
            result_docs[slot] = _entry(slot, chosen["path"],
                                       chosen["last_updated"], legacy_paths)
            result_docs[slot]["canonical_missing"] = True
        else:
            result_docs[slot] = {"exists": False, "legacy_source": None}

    # TRANSITION: status computed over COMPLETE_BASIS (currently the 6 core slots)
    # so companies awaiting manual 04 backfill stay "complete".
    total_slots = len(COMPLETE_BASIS)
    exists_count = sum(1 for s in COMPLETE_BASIS if result_docs[s]["exists"])
    stale_count = sum(1 for s in COMPLETE_BASIS if result_docs[s].get("is_stale"))
    if not folder_exists:
        status = "folder_missing"
    elif exists_count == 0:
        status = "empty"
    elif exists_count == total_slots and stale_count == 0:
        status = "complete"
    elif exists_count == total_slots and stale_count > 0:
        status = "stale"
    else:
        status = "partial"

    return {
        "ticker": ticker,
        "company_name": name,
        "sector": sector,
        "folder": folder_rel,
        "folder_exists": folder_exists,
        "dossier_path": f"{folder_rel}/研究档案",
        "dossier_status": status,
        "exists_count": exists_count,
        "documents": result_docs,
        "pending_reviews": [],
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
    if dossier_meta.exists():
        new_entry["dossier_initialized"] = True
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
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


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

    2. All 6 slots are now complete  →  print instruction for Claude to
       invoke research-summary skill immediately in the current session.
    """
    now = datetime.now(timezone.utc).isoformat()

    # 0. 04 accepted → downstream 06/07 should realign to the new strategy scenarios.
    #    This is a REMINDER, never automatic (user decides when to rerun).
    if "04_战略决策.md" in batch_slot_files:
        print(
            f"\n  ⚠️ [提示] 04_战略决策.md 已更新——战略三情景变了，预测分叉点应重新对齐。"
            f"\n     建议随后重跑：prepare-refresh {ticker} --slots 06_财务预测.md 07_估值分析.md --trigger catalyst"
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
            f"\n     python3 _system/scripts/sync_valuations.py drain {ticker}"
            f"\n     （从 07 §4.8 登记块提取 评级/目标价/区间/切换路标 → valuation_registry.json"
            f" → portfolio_registry.md → check → 出队）"
        )

    # 2. Research summary — print instruction for Claude to act on immediately.
    # (No queue file: research-summary requires Claude intelligence and should
    # run in the current session, not wait until the next scanner run.)
    # Research-summary HTML trigger fires on the 6 core slots (transition semantics).
    # A batch touching ONLY 04 doesn't regenerate the HTML (summary has 6 sections).
    all_slots_present = all(
        company["documents"].get(slot, {}).get("exists") for slot in COMPLETE_BASIS
    )
    batch_touches_core = any(s in batch_slot_files for s in CORE_SLOTS)
    if all_slots_present and batch_touches_core:
        dossier_abs = str(PROJECTS_ROOT / company["dossier_path"])
        print(
            f"\n  📋 [NEXT STEP — 请立即执行] 研究档案 6 槽全部就位，"
            f"请调用 research-summary skill 生成研究总结 HTML：\n"
            f"     档案目录：{dossier_abs}\n"
            f"     输出目标：基本面分析汇总/{company['company_name']}_{datetime.now().strftime('%Y-%m-%d')}_研究总结.html\n"
            f"     （生成后无需其他操作，10:00 的每日更新任务会自动把 HTML 打包到网站）"
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
    # Step 0: auto-rescan this single company to refresh legacy_source paths.
    # Prevents the bug where registry has a stale path because a file moved
    # between scan and migrate. Set skip_rescan=True only for debugging.
    if not skip_rescan:
        print(f"[migrate {ticker}] rescanning folder first (to refresh legacy_source paths)...")
        rescan_one(ticker, save=True)

    reg = load_registry()
    company = find_company(reg, ticker)
    dd = dossier_dir(company)
    dd.mkdir(parents=True, exist_ok=True)

    print(f"[migrate {ticker}] dossier_dir={dd}")

    meta_path = dd / "_meta.json"
    existing_meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            existing_meta = json.load(f)
    # 迁移单个缺失模块时保留其他模块既有的审批状态、来源周期、备注和历史信息。
    documents_meta = dict(existing_meta.get("documents", {}))
    migrated = 0  # successfully copied
    skipped_existing = 0  # source already is the canonical file
    skipped_no_source = 0  # legacy_source is None — genuine miss
    failed_missing = 0  # legacy_source exists in registry but file not on disk — BUG
    failed_slots: list[str] = []

    for slot in CANONICAL_SLOTS:
        doc_info = company["documents"].get(slot, {})
        if not doc_info.get("exists"):
            print(f"  {slot}: SKIP (no legacy source)")
            if slot not in documents_meta:
                documents_meta[slot] = {
                    "last_updated": None,
                    "source_period": None,
                    "trigger": "pending_initial_build",
                    "approval_status": "missing",
                    "sub_skills_used": SLOT_TO_SUB_SKILLS[slot],
                    "legacy_source": None,
                }
            skipped_no_source += 1
            continue

        src_rel = doc_info["legacy_source"]
        src_abs = PROJECTS_ROOT / src_rel
        if not src_abs.exists():
            print(f"  {slot}: ❌ ERROR — legacy source missing on disk: {src_rel}")
            documents_meta[slot] = {
                "last_updated": None,
                "source_period": None,
                "trigger": "migration_failed",
                "approval_status": "failed",
                "error_message": f"legacy_source path missing on disk: {src_rel}",
                "sub_skills_used": SLOT_TO_SUB_SKILLS[slot],
                "legacy_source": src_rel,
            }
            failed_missing += 1
            failed_slots.append(slot)
            continue

        # Preserve original extension (.md or .docx) for migration — content not converted.
        # The canonical slot name uses .md; if source is .docx, we save it alongside with
        # _meta.json noting the format.
        target = dd / slot
        target_docx = dd / slot.replace(".md", ".docx")
        # Migration only fills missing canonical slots. A newer legacy candidate must never
        # overwrite an already-canonical research document (DUOL 07 incident, 2026-08-05).
        if target.exists() or target_docx.exists():
            print(f"  {slot}: KEEP (canonical target already exists)")
            skipped_existing += 1
            continue
        if src_abs.suffix.lower() == ".docx":
            shutil.copy2(src_abs, target_docx)
            # Also write a placeholder .md noting the docx exists
            placeholder_title = slot.replace(".md", "")
            placeholder = (
                "# " + placeholder_title + "\n\n"
                "> 内容存于同目录 `" + target_docx.name + "`（迁移自 .docx 文件，未做格式转换）。\n"
                "> 下次 refresh 时由 orchestrator 写入 markdown。\n\n"
                "**来源:** `" + src_rel + "`\n"
            )
            target.write_text(placeholder, encoding="utf-8")
            print(f"  {slot}: COPIED .docx + placeholder.md from {src_rel}")
        else:
            shutil.copy2(src_abs, target)
            print(f"  {slot}: COPIED from {src_rel}")

        documents_meta[slot] = {
            "last_updated": doc_info.get("last_updated"),
            "source_period": None,
            "trigger": "migration_from_legacy",
            "approval_status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "sub_skills_used": SLOT_TO_SUB_SKILLS[slot],
            "legacy_source": src_rel,
            "session_id": None,
        }
        migrated += 1

    meta = dict(existing_meta)
    meta.update({
        "schema_version": existing_meta.get("schema_version", "1.0"),
        "ticker": ticker,
        "company_name": company["company_name"],
        "sector": company["sector"],
        "documents": documents_meta,
    })
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    if failed_missing == 0:
        company["dossier_initialized"] = True
        company["dossier_initialized_at"] = datetime.now(timezone.utc).isoformat()
    save_registry(reg)

    total = migrated + skipped_existing + skipped_no_source + failed_missing
    status_emoji = "OK" if failed_missing == 0 else "FAIL"
    print(f"\n[{status_emoji}] [migrate {ticker}] SUMMARY")
    print(f"   migrated (copied to 研究档案/):  {migrated}/{total}")
    print(f"   kept (already canonical):       {skipped_existing}/{total}")
    print(f"   skipped (no legacy source):     {skipped_no_source}/{total}")
    failed_label = ", ".join(failed_slots) if failed_slots else ""
    print(f"   FAILED (path missing on disk):  {failed_missing}/{total}" + (f"  <- {failed_label}" if failed_label else ""))
    print(f"   meta.json:                       {dd / '_meta.json'}")
    if failed_missing > 0:
        print(f"\n[migrate {ticker}] Had {failed_missing} failure(s). Likely cause: file moved/renamed between scan and migrate.")
        print(f"   Resolution: locate the missing file(s) or run `rescan {ticker}` then `migrate {ticker}` again.")
        sys.exit(1)


# --------------------------------------------------------------------------
# Mode: prepare-refresh
# --------------------------------------------------------------------------
def cmd_prepare_refresh(ticker, slots, trigger="manual"):
    reg = load_registry()
    company = find_company(reg, ticker)
    dd = dossier_dir(company)
    if not dd.exists():
        print(f"ERROR: dossier folder doesn't exist. Run `migrate {ticker}` first.")
        sys.exit(1)
    ts = now_ts()
    pending = dd / "_pending" / ts
    pending.mkdir(parents=True, exist_ok=True)
    # Default = all 7 slots (04 is a required node — full builds include strategy).
    # Quarterly/catalyst routines use explicit --slots (Mode C) and skip 04 naturally.
    slots = slots or CANONICAL_SLOTS
    print(f"[prepare-refresh {ticker}] _pending/{ts}/")
    print(f"  Slots to refresh: {slots}")

    context_bundle = {
        "ticker": ticker,
        "company_name": company["company_name"],
        "sector": company["sector"],
        "dossier_dir": str(dd.relative_to(PROJECTS_ROOT)),
        "pending_dir": str(pending.relative_to(PROJECTS_ROOT)),
        "timestamp": ts,
        "trigger": trigger,
        "slots": [],
    }
    for slot in slots:
        deps = SLOT_DEPENDENCIES[slot]
        dep_paths = []
        for dep in deps:
            dep_path = dd / dep
            if dep_path.exists():
                dep_paths.append(str(dep_path.relative_to(PROJECTS_ROOT)))
            elif dep in slots:
                dep_paths.append(f"PENDING_IN_BATCH: {pending.relative_to(PROJECTS_ROOT)}/{dep}")
            elif dep in SOFT_DEP_SLOTS:
                # Soft upstream (04 during transition): downstream proceeds, notes the gap.
                dep_paths.append(f"OPTIONAL_MISSING: {dep}")
            else:
                dep_paths.append(f"MISSING: {dep}")
        context_bundle["slots"].append({
            "slot": slot,
            "sub_skills": SLOT_TO_SUB_SKILLS[slot],
            "dependencies": deps,
            "dependency_paths": dep_paths,
            "output_path": str((pending / slot).relative_to(PROJECTS_ROOT)),
            "status": "pending",
        })
    bundle_path = pending / "_context_bundle.json"
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(context_bundle, f, ensure_ascii=False, indent=2)
    print(f"\n[prepare-refresh {ticker}] context bundle -> {bundle_path}")
    print(f"Timestamp for finalize-refresh: {ts}")


# --------------------------------------------------------------------------
# Mode: finalize-refresh
# --------------------------------------------------------------------------
def cmd_finalize_refresh(ticker, ts):
    reg = load_registry()
    company = find_company(reg, ticker)
    dd = dossier_dir(company)
    pending = dd / "_pending" / ts
    if not pending.exists():
        print(f"ERROR: pending batch not found: {pending}")
        sys.exit(1)
    bundle_path = pending / "_context_bundle.json"
    if not bundle_path.exists():
        print(f"ERROR: context bundle missing")
        sys.exit(1)
    with open(bundle_path, encoding="utf-8") as f:
        bundle = json.load(f)

    documents_meta = {}
    diff_lines = [
        f"# {ticker} 待审档案 — {ts}",
        f"",
        f"**触发:** {bundle.get('trigger', 'manual')}",
        f"**生成时间:** {ts}",
        f"",
        f"## 各档案变更概览",
        f"",
    ]
    for slot_info in bundle["slots"]:
        slot = slot_info["slot"]
        output_path = pending / slot
        if not output_path.exists():
            print(f"WARNING: expected output not found: {output_path}")
            documents_meta[slot] = {
                "last_updated": None,
                "trigger": bundle.get("trigger", "manual"),
                "approval_status": "failed",
                "error_message": "Sub-skill output file not written",
                "sub_skills_used": slot_info["sub_skills"],
            }
            diff_lines.append(f"### {slot}\n\nGENERATION FAILED\n")
            continue
        # v3.1: handoff lint (sentinel / required sections / row caps) for 06/07/04.
        # Lint ERRORs mark the slot failed (file exists but is truncated/malformed).
        lint_errors, lint_warnings = [], []
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import handoff_lint  # noqa: PLC0415
            lint_errors, lint_warnings = handoff_lint.lint_file(output_path, slot)
        except ImportError:
            print(f"  ⚠️ handoff_lint.py 不可用，跳过 {slot} 的交接块校验")
        for w in lint_warnings:
            print(f"  ⚠️ LINT WARN [{slot}] {w}")
        if lint_errors:
            for e in lint_errors:
                print(f"  ❌ LINT ERROR [{slot}] {e}")
            documents_meta[slot] = {
                "last_updated": None,
                "trigger": bundle.get("trigger", "manual"),
                "approval_status": "failed",
                "error_message": "handoff lint failed: " + "; ".join(lint_errors),
                "sub_skills_used": slot_info["sub_skills"],
            }
            diff_lines.append(f"### {slot}\n\nHANDOFF LINT FAILED: {'; '.join(lint_errors)}\n")
            continue

        new_size = output_path.stat().st_size
        new_lines = sum(1 for _ in open(output_path, encoding="utf-8"))
        current = dd / slot
        if current.exists():
            old_size = current.stat().st_size
            old_lines = sum(1 for _ in open(current, encoding="utf-8"))
            diff_lines.append(
                f"### {slot}\n\n- old: {old_lines} lines / {old_size:,} bytes\n"
                f"- new: {new_lines} lines / {new_size:,} bytes\n"
                f"- sub-skills: {', '.join(slot_info['sub_skills'])}\n"
            )
        else:
            diff_lines.append(
                f"### {slot}\n\n- old: none (first generation)\n"
                f"- new: {new_lines} lines / {new_size:,} bytes\n"
                f"- sub-skills: {', '.join(slot_info['sub_skills'])}\n"
            )
        documents_meta[slot] = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "source_period": None,
            "trigger": bundle.get("trigger", "manual"),
            "approval_status": "pending",
            "sub_skills_used": slot_info["sub_skills"],
            "session_id": None,
        }

    meta = {
        "schema_version": "1.0",
        "ticker": ticker,
        "company_name": company["company_name"],
        "sector": company["sector"],
        "batch_timestamp": ts,
        "trigger": bundle.get("trigger", "manual"),
        "documents": documents_meta,
    }
    with open(pending / "_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    diff_path = pending / "_diff_summary.md"
    diff_path.write_text("\n".join(diff_lines), encoding="utf-8")

    if "pending_reviews" not in company:
        company["pending_reviews"] = []
    company["pending_reviews"].append({"timestamp": ts, "trigger": bundle.get("trigger", "manual")})
    save_registry(reg)
    print(f"[finalize-refresh {ticker}] _meta.json + _diff_summary.md written")
    print(f"  Review: cat '{diff_path}'")
    print(f"  Accept: python3 dossier_orchestrator.py accept {ticker} {ts}")


# --------------------------------------------------------------------------
# Mode: accept
# --------------------------------------------------------------------------
def cmd_accept(ticker, ts=None):
    """Partial-replace semantics: only slots present in _pending/{ts}/ are replaced.
    Slots NOT in pending stay as-is in 研究档案/. _meta.json is merged (not overwritten)."""
    reg = load_registry()
    company = find_company(reg, ticker)
    dd = dossier_dir(company)
    pending_root = dd / "_pending"
    if not pending_root.exists():
        print(f"ERROR: no pending batches for {ticker}")
        sys.exit(1)
    if ts is None:
        batches = sorted([p.name for p in pending_root.iterdir() if p.is_dir() and not p.name.startswith("_")])
        if not batches:
            print(f"ERROR: no pending batches")
            sys.exit(1)
        ts = batches[-1]
        print(f"[accept {ticker}] auto-selected latest batch: {ts}")
    batch = pending_root / ts
    if not batch.exists():
        print(f"ERROR: batch not found: {batch}")
        sys.exit(1)

    archive_ts = now_ts()
    history = dd / "_history" / archive_ts

    # Identify which slots are in this batch
    batch_slot_files: dict[str, Path] = {}  # slot.md -> source file in batch
    for item in batch.iterdir():
        if not item.is_file():
            continue
        if item.name in CANONICAL_SLOTS:
            batch_slot_files[item.name] = item
        elif item.name.replace(".docx", ".md") in CANONICAL_SLOTS:
            # .docx companion file — pair with the canonical .md slot
            slot_md = item.name.replace(".docx", ".md")
            batch_slot_files[slot_md] = item  # actual file is .docx but registered under .md slot key

    print(f"[accept {ticker}] batch contains slots: {sorted(batch_slot_files.keys())}")

    if not batch_slot_files:
        print(f"ERROR: no canonical slot files found in batch {ts}")
        sys.exit(1)

    # Load current _meta.json (may not exist for fresh dossiers)
    current_meta_path = dd / "_meta.json"
    current_meta = {"documents": {}}
    if current_meta_path.exists():
        with open(current_meta_path, encoding="utf-8") as f:
            current_meta = json.load(f)

    # Load batch's _meta.json
    batch_meta_path = batch / "_meta.json"
    batch_meta = {"documents": {}}
    if batch_meta_path.exists():
        with open(batch_meta_path, encoding="utf-8") as f:
            batch_meta = json.load(f)

    history.mkdir(parents=True, exist_ok=True)

    # Step 1: archive only the slots being REPLACED (and any companion .docx of those slots)
    for slot_md in batch_slot_files.keys():
        current_md = dd / slot_md
        current_docx = dd / slot_md.replace(".md", ".docx")
        if current_md.exists():
            shutil.move(str(current_md), str(history / current_md.name))
            print(f"  Archived -> _history/{archive_ts}/{current_md.name}")
        if current_docx.exists():
            shutil.move(str(current_docx), str(history / current_docx.name))
            print(f"  Archived -> _history/{archive_ts}/{current_docx.name}")

    # Step 2: promote each slot file from batch into 研究档案/
    for slot_md, src in batch_slot_files.items():
        target = dd / src.name  # preserve original extension (.md or .docx)
        shutil.move(str(src), str(target))
        print(f"  Promoted <- _pending/{ts}/{src.name}")

    # Step 3: archive diff_summary + context_bundle + batch _meta.json (none go to 研究档案/)
    for fname in ("_diff_summary.md", "_context_bundle.json", "_meta.json"):
        src = batch / fname
        if src.exists():
            shutil.move(str(src), str(history / ("batch_" + fname if fname == "_meta.json" else fname)))

    # Step 4: merge _meta.json — for each accepted slot, write the batch entry as approved.
    # For slots not in batch, keep the current entry untouched.
    merged_documents = dict(current_meta.get("documents", {}))
    for slot in batch_slot_files.keys():
        batch_slot = batch_meta.get("documents", {}).get(slot, {})
        merged_documents[slot] = {
            "last_updated": batch_slot.get("last_updated") or datetime.now(timezone.utc).isoformat(),
            "source_period": batch_slot.get("source_period"),
            "trigger": batch_slot.get("trigger", "manual"),
            "approval_status": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "sub_skills_used": batch_slot.get("sub_skills_used", SLOT_TO_SUB_SKILLS.get(slot, [])),
            "legacy_source": None,  # no longer relevant — content was orchestrator-generated
            "session_id": batch_slot.get("session_id"),
        }
    merged_meta = {
        "schema_version": "1.0",
        "ticker": ticker,
        "company_name": company["company_name"],
        "sector": company["sector"],
        "documents": merged_documents,
    }
    with open(current_meta_path, "w", encoding="utf-8") as f:
        json.dump(merged_meta, f, ensure_ascii=False, indent=2)
    print(f"  Updated _meta.json: {len(batch_slot_files)} slot(s) marked approved (others preserved)")

    # Step 5: cleanup empty pending batch dir
    if batch.exists():
        # Remove if empty (or only contains hidden files)
        try:
            remaining = list(batch.iterdir())
            if not remaining:
                batch.rmdir()
        except Exception:
            pass

    company["pending_reviews"] = [pr for pr in company.get("pending_reviews", []) if pr.get("timestamp") != ts]
    if company.get("dossier_initialized") is not True:
        company["dossier_initialized"] = True
        company["dossier_initialized_at"] = datetime.now(timezone.utc).isoformat()
    save_registry(reg)

    # Auto-refresh central freshness index: accept promotes new files + writes the
    # dossier-folder _meta.json, but does NOT propagate the new last_updated/age_days/
    # is_stale into dossier_registry.json. Re-scan this ticker so the index reflects
    # the just-accepted refresh (no more manual `rescan {TICKER}` after accept).
    try:
        rescan_one(ticker, registry=reg)
        print(f"  Auto-rescanned dossier_registry.json: {ticker} freshness dates refreshed")
    except Exception as e:
        print(f"  ⚠️ auto-rescan failed ({e}); run `rescan {ticker}` manually to refresh dates")

    # Automation pending queues: write entries for the daily scanner to consume.
    # - 07 accepted → scanner extracts rating/target/zones → updates valuation_registry.json
    # - all 6 slots present → scanner generates research-summary HTML
    # After rescan_one above, company entry in reg is already fresh.
    fresh_company = find_company(reg, ticker)
    _handle_accept_automation(ticker, batch_slot_files, fresh_company)

    # 三年估值覆盖闸门：07 落盘后，三年估值注册表必须有对应条目，否则该公司会在
    # 组合三年估值看板上永远显示"待补录"。历史上这张表只有一次性 migrate 一个写入口，
    # 新建档案不会写它——这里把缺口在 accept 当下就喊出来，而不是等半年后看板上发现。
    if "07_估值分析.md" in batch_slot_files:
        _warn_missing_three_year_target(ticker)

    print(f"\n[accept {ticker}] done. {len(batch_slot_files)} slot(s) replaced; {len(CANONICAL_SLOTS) - len(batch_slot_files)} preserved.")


# --------------------------------------------------------------------------
# 三年估值覆盖闸门
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Mode: reject
# --------------------------------------------------------------------------
def cmd_reject(ticker, ts=None):
    reg = load_registry()
    company = find_company(reg, ticker)
    dd = dossier_dir(company)
    pending_root = dd / "_pending"
    if ts is None:
        batches = sorted([p.name for p in pending_root.iterdir() if p.is_dir() and not p.name.startswith("_")])
        if not batches:
            print(f"ERROR: no pending batches")
            sys.exit(1)
        ts = batches[-1]
    batch = pending_root / ts
    rejected = pending_root / "_rejected" / ts
    rejected.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(batch), str(rejected))
    company["pending_reviews"] = [pr for pr in company.get("pending_reviews", []) if pr.get("timestamp") != ts]
    save_registry(reg)
    print(f"[reject {ticker} {ts}] moved to _pending/_rejected/{ts}/")


# --------------------------------------------------------------------------
# Mode: status
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Mode: rescan
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Mode: briefing-snippet — emit JSON for daily-briefing dashboard integration.
# Output shape:
#   {
#     "dossiers": { pending_review: [], stale: [], partial: [], summary: {} },
#     "companies_dossier": { "V": {...}, "PLTR": {...}, ... }
#   }
# Caller merges into briefing_data.json:
#   - top-level dossiers field (for the new dashboard panel)
#   - each companies[i].dossier from companies_dossier[ticker]
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Mode: audit
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
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
    main()
