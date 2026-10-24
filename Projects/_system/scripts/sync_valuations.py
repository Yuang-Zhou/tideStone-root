r"""
sync_valuations.py — 评级/估值区间/目标价的单一事实源同步工具
=============================================================

背景：估值数据原本同时活在两处——`portfolio_registry.md`（每日扫描消费）与各公司
`研究档案/07_估值分析.md`（dossier accept 产出），靠人工同步，已出现陈旧
（例：TCOM 2026-06-11 现价 $48 vs 注册表买入区 <$80，区间疑陈旧）。

本工具引入 `_system/valuation_registry.json` 作为评级/区间/目标价的**单一事实源**：

    07_估值分析.md accept 后 → 人工/skill 更新 JSON → apply 写回 registry md
    registry md 永远是 JSON 的"生成视图"（估值字段部分），手改 md 会被 check 抓出

用法（在 Projects 根目录下）：
    python3 _system/scripts/sync_valuations.py extract [--force]
        从 portfolio_registry.md 解析全部公司的估值字段 → 初建/重建 JSON。
        JSON 已存在时需 --force（防止误覆盖已修订的事实源）。

    python3 _system/scripts/sync_valuations.py check
        重新解析 md，与 JSON 逐家比对 rating / target_price / zones。
        一致 → exit 0；有差异 → 列出差异，exit 1。
        ⚠️ dossier accept 后、以及每周例行审计时必须跑。

    python3 _system/scripts/sync_valuations.py drain [{TICKER} ...] [--dry-run]
        消费 _system/pending_valuation_sync.json 队列（dossier accept 07 后由
        orchestrator 写入）：从每家 07_估值分析.md 的「§4.8 valuation_registry 登记块」
        提取 rating/target_price/zones/scenario_valuation → 写 JSON 事实源 → apply
        → check → 出队。只有成功的条目出队，失败的留队等人工。
        ⚠️ accept 07 之后应跑本模式；2026-07-30 之前该队列无消费端（写入端存在、
        没有任何代码读取），是 registry 陈旧的系统性成因。

    python3 _system/scripts/sync_valuations.py apply {TICKER} [{TICKER2} ...]
    python3 _system/scripts/sync_valuations.py apply --all
        把 JSON 中的 rating / zones / target 写回 registry md 对应条目
        （只替换 Rating 行 + Valuation 块，其余字段不动）。写回前自动备份
        registry 到 _system/portfolio_registry.backup.md（固定文件名，每次覆盖，只保留最近一份）。

FUSE 提示：本脚本读 registry 时自动剥离 NUL 填充并告警。若运行环境是 Cowork
sandbox 且 registry 刚被 Read/Write 工具修改过，bash 视角可能陈旧——重要操作
（apply）前建议先在宿主机或确认缓存一致后执行。
"""
import json
import math
import hashlib
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """原子写文本：写同目录 .tmp → fsync → os.replace 覆盖目标。
    防止 Cowork sandbox FUSE 下 write_text 直接截断写导致的半截文件
    （甲骨文 2026-07-14 / TEAM+601872+300750 2026-07-15 系列截断的根因）。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

SCRIPT_DIR = Path(__file__).resolve().parent
from tidestone_paths import PROJECTS_ROOT
ROOT = PROJECTS_ROOT
REGISTRY = ROOT / "_system" / "portfolio_registry.md"
JSON_PATH = ROOT / "_system" / "valuation_registry.json"

HEADING_RE = re.compile(r"^### (\S+) — (.*)$")
SECTOR_RE = re.compile(r"^## (\d+\..*)$")
FIELD_RE = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
ZONE_RE = re.compile(r"^  - (.+?)[:：]\s*(.*)$")      # 兼容 ASCII/中文冒号
ZONE_PLAIN_RE = re.compile(r"^  - (.*)$")             # Valuation 块内无冒号的注释行，原样保留


# --------------------------------------------------------------------------
# 2026-08-0X 分类重构第 3b 步：sector 的真相源改为 _system/companies.json。
# 原先靠解析 portfolio_registry.md 的 `## 1. SaaS软件` 这类标题拿 sector，
# 而第 3b 步会把那些标题整个删掉（板块不再由文件结构承载）。
# 注意：sector 不参与 check 的比对（check 只看 rating/target_price/status/zones），
# 所以这个改动不会影响 check 的判定结果。
# --------------------------------------------------------------------------
COMPANIES_JSON = ROOT / "_system" / "companies.json"


def load_sector_map():
    """{ticker: GICS 一级板块中文名}。与 dossier_orchestrator 的取值口径保持一致。"""
    raw = COMPANIES_JSON.read_bytes()
    if b"\x00" in raw:
        print("⚠️ companies.json 含 NUL 填充（FUSE 缓存陈旧迹象）", file=sys.stderr)
        raw = raw.replace(b"\x00", b"")
    data = json.loads(raw.decode("utf-8"))
    names = data.get("gics_sector_names", {})
    out = {}
    for tk, e in data["companies"].items():
        code = (e.get("gics") or {}).get("sector")
        out[tk] = names.get(code, f"未知板块 {code}") if code else None
    return out


SECTOR_MAP = load_sector_map()


def read_registry_text():
    data = REGISTRY.read_bytes()
    if b"\x00" in data:
        print("⚠️ registry 含 NUL 填充（FUSE 缓存陈旧迹象），已剥离；建议核实数据新鲜度", file=sys.stderr)
        data = data.replace(b"\x00", b"")
    return data.decode("utf-8", errors="replace")


def parse_registry():
    """解析 md → {ticker: entry}。entry 含 name/sector/status/currency/rating/zones/target_price/heading_line"""
    text = read_registry_text()
    lines = text.splitlines()
    companies = {}
    sector = None
    cur = None          # 当前公司条目
    in_valuation = False

    for i, line in enumerate(lines, 1):
        m = SECTOR_RE.match(line)
        if m:
            sector = m.group(1).strip()
            continue
        m = HEADING_RE.match(line)
        if m:
            ticker = m.group(1).strip()
            cur = {
                "name": m.group(2).strip(),
                "sector": SECTOR_MAP.get(ticker),   # 3b：不再取 `## 板块` 标题
                "status": None,
                "currency": None,
                "rating": None,
                "zones": [],
                "target_price": None,
                "heading_line": i,
            }
            companies[ticker] = cur
            in_valuation = False
            continue
        if cur is None:
            continue
        m = FIELD_RE.match(line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            in_valuation = (key == "Valuation")
            if key == "Status":
                cur["status"] = val
            elif key == "Currency":
                cur["currency"] = val
            elif key == "Rating":
                cur["rating"] = val
            continue
        if in_valuation:
            m = ZONE_RE.match(line)
            if m:
                label, val = m.group(1).strip(), m.group(2).strip()
                if "目标价" in label:
                    cur["target_price"] = val
                else:
                    cur["zones"].append({"label": label, "range": val})
                continue
            m = ZONE_PLAIN_RE.match(line)
            if m:
                # 无冒号的注释行（如"当前价 $32.74…隐含 25.9x"），原样保留以便 apply 写回保真
                cur["zones"].append({"label": None, "range": m.group(1).strip()})
                continue
            if line.startswith("    "):
                continue  # 更深缩进的延续行，跳过但不退出块
            if line.strip():
                in_valuation = False  # 仅遇到非缩进内容时退出 Valuation 块
    return companies


def load_json():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(companies, note):
    doc = {
        "schema_version": 1,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": note,
        "_convention": (
            "本文件是评级/估值区间/目标价的单一事实源。07_估值分析 accept 后先改这里，"
            "再跑 sync_valuations.py apply 写回 portfolio_registry.md。"
            "直接手改 registry md 的估值字段会被 check 模式抓出。"
        ),
        "companies": companies,
    }
    tmp = JSON_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    tmp.replace(JSON_PATH)


def strip_meta(entry):
    """比对时忽略行号等非事实字段"""
    return {k: v for k, v in entry.items() if k != "heading_line"}


def cmd_extract(force=False):
    if JSON_PATH.exists() and not force:
        print(f"❌ {JSON_PATH.name} 已存在。它是事实源，重建请加 --force（会丢弃 JSON 中未写回 md 的修订）")
        sys.exit(1)
    companies = parse_registry()
    problems = [t for t, e in companies.items()
                if not e["rating"] or not e["target_price"] or not e["zones"]]
    save_json(companies, f"extract 自 portfolio_registry.md（{len(companies)} 家）")
    print(f"✅ 已生成 {JSON_PATH.name}：{len(companies)} 家公司")
    for t in problems:
        e = companies[t]
        print(f"  ⚠️ {t}: rating={'有' if e['rating'] else '缺'} "
              f"target={'有' if e['target_price'] else '缺'} zones={len(e['zones'])} —— 请人工核对")
    if not problems:
        print("  全部条目 rating / target / zones 解析完整")


def cmd_check():
    doc = load_json()
    md = parse_registry()
    json_companies = doc["companies"]
    diffs = []
    for t in sorted(set(md) | set(json_companies)):
        if t not in json_companies:
            diffs.append(f"{t}: 只在 md 中存在（JSON 缺失 → 新公司入库后未 extract/更新 JSON？）")
            continue
        if t not in md:
            diffs.append(f"{t}: 只在 JSON 中存在（md 被删/改名？）")
            continue
        a, b = strip_meta(json_companies[t]), strip_meta(md[t])
        for key in ("rating", "target_price", "status", "currency"):
            if a.get(key) != b.get(key):
                diffs.append(f"{t}.{key}: JSON={a.get(key)!r} ≠ md={b.get(key)!r}")
        if a.get("zones") != b.get("zones"):
            diffs.append(f"{t}.zones: JSON {len(a.get('zones') or [])} 档 ≠ md {len(b.get('zones') or [])} 档（或内容不同）")
    if diffs:
        print(f"❌ JSON 与 registry md 有 {len(diffs)} 处差异：")
        for d in diffs:
            print(f"  - {d}")
        print("\n处理：以 JSON 为准 → `apply {TICKER}` 写回 md；以 md 为准 → 手工改 JSON 后再 check。")
        sys.exit(1)
    print(f"✅ 一致：{len(json_companies)} 家公司的 rating / target / zones / status / currency 与 md 完全一致")


def cmd_apply(tickers):
    doc = load_json()
    json_companies = doc["companies"]
    md = parse_registry()
    if tickers == ["--all"]:
        tickers = [t for t in json_companies if t in md]
    text = read_registry_text()
    lines = text.splitlines()

    # 备份（固定文件名，每次覆盖，只保留最近一份）
    backup = REGISTRY.with_name("portfolio_registry.backup.md")
    atomic_write_text(backup, text)

    applied = []
    for t in tickers:
        if t not in json_companies or t not in md:
            print(f"  ⚠️ 跳过 {t}（JSON 或 md 中不存在）")
            continue
        e = json_companies[t]
        start = md[t]["heading_line"]  # 1-based heading 行
        # 在该条目范围内（到下一个 ### / ## / 文件尾）定位 Rating 行和 Valuation 块
        end = len(lines)
        for j in range(start, len(lines)):
            if lines[j].startswith("### ") or lines[j].startswith("## "):
                end = j
                break
        new_block = []
        replaced_rating = replaced_val = False
        j = start
        while j < end:
            line = lines[j]
            if re.match(r"^- \*\*(Status|Currency):\*\*", line):
                key='status' if line.startswith('- **Status:') else 'currency'
                new_block.append(f"- **{key.title()}:** {e.get(key, '')}")
                j += 1
                continue
            if re.match(r"^- \*\*Rating:\*\*", line):
                new_block.append(f"- **Rating:** {e['rating']}")
                replaced_rating = True
                j += 1
                continue
            if re.match(r"^- \*\*Valuation:\*\*", line):
                new_block.append("- **Valuation:**")
                for z in e["zones"]:
                    if z.get("label"):
                        new_block.append(f"  - {z['label']}: {z['range']}")
                    else:
                        new_block.append(f"  - {z['range']}")
                if e.get("target_price"):
                    new_block.append(f"  - 情景目标价: {e['target_price']}")
                replaced_val = True
                j += 1
                while j < end and (ZONE_PLAIN_RE.match(lines[j]) or lines[j].startswith("    ")):
                    j += 1
                continue
            new_block.append(line)
            j += 1
        lines[start:end] = new_block
        # 行号变了，重新解析后续条目位置
        md = {tk: {**v} for tk, v in parse_md_lines(lines).items()}
        applied.append(f"{t}（Rating {'✓' if replaced_rating else '✗'} / Valuation {'✓' if replaced_val else '✗'}）")

    atomic_write_text(REGISTRY, "\n".join(lines) + "\n")
    print(f"✅ 已写回 {len(applied)} 家：{'; '.join(applied)}")
    print(f"   备份：{backup.name}")
    print("   提醒：在 Cowork sandbox 中写回后，bash 视角的 registry 可能缓存陈旧；扫描端按 MANDATORY Step 0.2b 处理。")


def parse_md_lines(lines):
    """对已在内存中的行做与 parse_registry 相同的解析（apply 中途重定位用）"""
    companies = {}
    sector = None
    for i, line in enumerate(lines, 1):
        m = SECTOR_RE.match(line)
        if m:
            sector = m.group(1).strip()
            continue
        m = HEADING_RE.match(line)
        if m:
            _tk = m.group(1).strip()
            companies[_tk] = {"heading_line": i, "sector": SECTOR_MAP.get(_tk)}   # 3b
    return companies



# ---------------------------------------------------------------------------
# drain：消费 pending_valuation_sync.json（2026-07-30 新增）
# ---------------------------------------------------------------------------
# 背景：dossier_orchestrator.py 在 07_估值分析.md 被 accept 时会把 {ticker, slot07_path}
# 写进 _system/pending_valuation_sync.json，并提示"下次扫描器运行时自动提取并同步"。
# 但在 2026-07-30 之前，全库没有任何代码读取该队列——写入端存在、消费端缺失，
# 队列只进不出，那句提示是空承诺。META/LLY 均靠人工同步，疑为 TCOM 区间陈旧的同源成因。
# 本模式补上消费端：队列 → 从每家 07 提取登记块 → 写 JSON 事实源 → apply → check → 出队。
#
# 提取优先级：
#   1) 07 的 "### 4.8 valuation_registry 登记块" 后第一个 ```json 块（机器可读契约，首选）
#   2) 该 JSON 缺 rating/zones 时，回退到结论表格抓取（标签容错，兼容历史 07 格式）
#   3) 仍抓不到 → 该条报错并留在队列，不猜、不写

PENDING_SYNC = ROOT / "_system" / "pending_valuation_sync.json"
_INCOMPLETE_BLOCKS = {}

_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.S)
_ZONE_LABELS = {
    "buy": ("买入区", "买入区间"),
    "hold": ("持有区", "持有区间"),
    "sell": ("卖出区", "卖出区间", "卖出/减持区", "卖出/减持区间", "减持/卖出区", "减持/卖出区间", "减持区"),
}
_RATING_LABELS = ("投资评级", "评级")
_WEIGHTED_BAN = ("概率加权", "加权目标价")


def _table_rows(md_text):
    """把所有 markdown 表格行解析成 (标签, 值) —— 标签去掉粗体/空白"""
    rows = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        label = cells[0].replace("**", "").replace("*", "").strip()
        value = cells[1].strip()
        if not label or set(label) <= set("-: "):
            continue
        rows.append((label, value))
    return rows


def _extract_registry_payload(md_text, ticker):
    """从 07_估值分析.md 提取 registry 载荷。返回 (payload, warnings)；失败抛 ValueError。"""
    warnings = []
    payload = {}

    payload = _named_registry_payload(md_text, "valuation_registry")
    if not payload:
        raise ValueError("未找到 '### 4.8 valuation_registry 登记块' 或其后的 ```json 块")

    if "target_price" not in payload:
        raise ValueError("登记块缺 target_price")
    if "scenario_valuation" not in payload:
        warnings.append("登记块缺 scenario_valuation（事件分诊将无切换路标可比对）")

    # rating / zones：只认登记块里的值。
    # 结论表格的单元格带大量解释性文字（"持有（Hold）—— 安全边际 +11.9%，落在…"），
    # 抓过来会把 registry 现有的精炼值覆盖成一句话，属于降级。
    # 因此缺就跳过该字段（保留 registry 现值）+ 告警，绝不用表格值覆盖。
    rows = _table_rows(md_text)
    for field, labels in (("rating", _RATING_LABELS), ("zones", tuple(sum(_ZONE_LABELS.values(), ())))):
        if field in payload:
            continue
        seen = [lb for lb, v in rows if lb in labels and v]
        hint = f"（结论表格里有「{seen[0]}」行，但表格值含解释性文字，不适合直接入库）" if seen else ""
        warnings.append(
            f"登记块缺 {field} → 本次不同步该字段，registry 保留现值{hint}。"
            f"请在 07 的「### 4.8 valuation_registry 登记块」JSON 中补上 {field}"
        )

    for banned in _WEIGHTED_BAN:
        if banned in str(payload.get("target_price", "")):
            raise ValueError(f"target_price 含禁用表述「{banned}」（registry 硬规则：禁止概率加权价）")

    return payload, warnings


THREE_YEAR_PATH = ROOT / "_system" / "three_year_valuation_registry.json"


def _named_registry_payload(text, registry_name):
    """Do not accidentally read the ordinary JSON from the three-year heading."""
    heading = re.search(r"(?m)^#{1,6}\s+(?:[0-9]+(?:\.[0-9]+)*\s+)?" +
                        re.escape(registry_name) + r" 登记块[^\n]*$", text)
    if not heading:
        raise ValueError(f"未找到 {registry_name} 登记块")
    tail = text[heading.end():]
    next_heading = re.search(r"(?m)^#{1,6}\s+", tail)
    section = tail[:next_heading.start()] if next_heading else tail
    block = _JSON_BLOCK_RE.search(section)
    if not block:
        raise ValueError(f"{registry_name} 登记块缺 JSON")
    try:
        payload = json.loads(block.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{registry_name} 登记块 JSON 无效：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{registry_name} 登记块必须为 JSON 对象")
    return payload


def _accepted_source(ticker, relative):
    """Both registries must consume the intact canonical 07 from one acceptance."""
    from dossier_orchestrator import approved_slot_errors
    company = json.loads(COMPANIES_JSON.read_text(encoding="utf-8"))["companies"].get(ticker)
    if not company:
        raise ValueError("公司身份注册表无此公司")
    expected = (ROOT / company["folder"] / "研究档案" / "07_估值分析.md").resolve()
    source = (ROOT / relative).resolve()
    if not source.is_relative_to(ROOT) or source != expected:
        raise ValueError("队列来源不是该公司的正式 07")
    errors = approved_slot_errors(source.parent, source.name)
    if errors:
        raise ValueError("07 未通过正式接受核验：" + "; ".join(errors))
    meta = json.loads((source.parent / "_meta.json").read_text(encoding="utf-8"))["documents"][source.name]
    provenance = {"source_path": str(source.relative_to(ROOT)), "source_sha256": meta["sha256"],
                  "accepted_batch": meta["accepted_batch"], "source_approved_at": meta["approved_at"]}
    return source.read_text(encoding="utf-8"), company, provenance


def _number(payload, key, positive=False):
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"三年登记 {key} 必须为有限数值")
    if positive and value <= 0:
        raise ValueError(f"三年登记 {key} 必须大于零")
    return float(value)


def _three_year_payload(text, company, provenance):
    """Local transport contract for the source README's existing 3-year formula.

    Required JSON under `### three_year_valuation_registry 登记块`:
    target_year, currency, scenario=base, valuation_method, valuation_type
    (ev/equity/fixed), metric_value_b, target_multiple, net_debt_b,
    share_equivalent_b, target_market_cap_b, target_price_3y, anchor_price,
    anchor_date, source. All *_b values are billions. Fixed equity value may
    leave metric_value_b/target_multiple null. target_date is optional, but its
    year must agree when supplied. The target year must be anchor year + 3.
    Source hashes and acceptance IDs are supplied by the runtime, never guessed.
    """
    payload = _named_registry_payload(text, "three_year_valuation_registry")
    required = ["target_year", "currency", "scenario", "valuation_method", "valuation_type",
                "metric_value_b", "target_multiple", "net_debt_b", "share_equivalent_b",
                "target_market_cap_b", "target_price_3y", "anchor_price", "anchor_date", "source"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError("三年登记缺字段：" + ", ".join(missing))
    if payload["scenario"] != "base":
        raise ValueError("三年登记须为基准情景 base，不能使用乐观/悲观或加权目标")
    currency = str(payload["currency"]).upper()
    if not company.get("currency") or currency != company["currency"].upper():
        raise ValueError("三年登记币种与公司报价币种不一致或未核实")
    if not isinstance(payload["valuation_method"], str) or not payload["valuation_method"].strip():
        raise ValueError("三年登记缺主估值方法")
    if any(term in payload["valuation_method"] for term in (*_WEIGHTED_BAN, "方法加权", "情景加权")):
        raise ValueError("三年登记禁止情景或方法加权目标")
    if not isinstance(payload["source"], str) or not payload["source"].strip():
        raise ValueError("三年登记缺本批次报告中的计算出处说明")
    try:
        anchor = date.fromisoformat(payload["anchor_date"])
    except (ValueError, TypeError):
        raise ValueError("anchor_date 必须为 YYYY-MM-DD")
    year = payload["target_year"]
    if isinstance(year, bool) or not isinstance(year, int) or year != anchor.year + 3:
        raise ValueError("target_year 必须是 anchor_date 年份加 3；其他期限不能冒充三年目标")
    if payload.get("target_date"):
        try:
            target_date = date.fromisoformat(payload["target_date"])
        except (ValueError, TypeError):
            raise ValueError("target_date 必须为 YYYY-MM-DD")
        if target_date.year != year or target_date <= anchor:
            raise ValueError("target_date 与目标年份/锚点不一致")
    for key in ("accepted_batch", "source_path", "source_sha256"):
        if key in payload and payload[key] != provenance[key]:
            raise ValueError(f"三年登记 {key} 指向另一批次或来源")
    shares = _number(payload, "share_equivalent_b", positive=True)
    cap = _number(payload, "target_market_cap_b", positive=True)
    price = _number(payload, "target_price_3y", positive=True)
    _number(payload, "anchor_price", positive=True)
    debt = _number(payload, "net_debt_b")
    kind = payload["valuation_type"]
    if kind in ("ev", "equity"):
        metric = _number(payload, "metric_value_b", positive=True)
        multiple = _number(payload, "target_multiple", positive=True)
        computed_cap = metric * multiple - (debt if kind == "ev" else 0.0)
        if not math.isclose(cap, computed_cap, rel_tol=0.001, abs_tol=1e-9):
            raise ValueError(f"三年目标市值算术不一致：登记 {cap}，计算 {computed_cap}（十亿）")
    elif kind != "fixed":
        raise ValueError("valuation_type 只支持 ev/equity/fixed")
    if not math.isclose(price, cap / shares, rel_tol=0.001, abs_tol=0.01):
        raise ValueError(f"三年每股目标价算术不一致：登记 {price}，计算 {cap / shares}")
    return {**payload, "currency": currency, **provenance, "status": "synced",
            "synced_at": datetime.now().astimezone().isoformat(timespec="seconds")}


def cmd_drain(tickers=None, dry_run=False):
    if not PENDING_SYNC.exists():
        print("队列文件不存在，无需处理。")
        return True
    queue_doc = json.loads(PENDING_SYNC.read_text(encoding="utf-8"))
    pending = queue_doc.get("pending", [])
    todo = [e for e in pending if not tickers or e["ticker"] in tickers]
    if not todo:
        print("队列为空或无匹配条目。")
        return True
    doc = load_json(); companies = doc["companies"]
    three = json.loads(THREE_YEAR_PATH.read_text(encoding="utf-8")) if THREE_YEAR_PATH.exists() else {"schema_version": 2, "companies": {}}
    three.setdefault("companies", {})
    ordinary_done, complete, failures = [], [], []
    changed_three = False
    for entry in todo:
        tk, rel = entry["ticker"], entry["slot07_path"]
        errors = []; valuation_ok = False; three_ok = False
        print(f"\n[{tk}] {rel}")
        try:
            text, company, provenance = _accepted_source(tk, rel)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
        else:
            try:
                if tk not in companies:
                    raise ValueError("valuation_registry 无公司身份条目")
                payload, warnings = _extract_registry_payload(text, tk)
                missing = [k for k in ("rating", "target_price", "zones", "scenario_valuation") if k not in payload]
                if missing:
                    raise ValueError("普通估值登记缺字段：" + ", ".join(missing))
                if payload.get("currency", company.get("currency")) != company.get("currency"):
                    raise ValueError("普通估值币种与公司报价币种不一致")
                for warning in warnings:
                    print("  提示：" + warning)
                companies[tk].update({k: v for k, v in payload.items()
                    if k in ("rating", "target_price", "zones", "scenario_valuation", "opportunity_type", "target_year", "target_date", "horizon")})
                companies[tk].update({**provenance, "currency": company["currency"]})
                ordinary_done.append(tk); valuation_ok = True
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
            try:
                new_three = _three_year_payload(text, company, provenance)
                three_ok = True
            except (ValueError, TypeError) as exc:
                errors.append(str(exc))
                new_three = {**provenance, "currency": company.get("currency"), "status": "pending",
                             "target_price_3y": None, "missing_reason": str(exc)}
            # Never keep a previous batch's number masquerading as the current target.
            old = three["companies"].get(tk)
            if old and old != new_three and old.get("target_price_3y") is not None:
                three.setdefault("history", []).append({"ticker": tk, "entry": old,
                    "superseded_by_batch": provenance["accepted_batch"], "archived_at": datetime.now().astimezone().isoformat(timespec="seconds")})
            three["companies"][tk] = new_three; changed_three = True
            entry.update(provenance)
        entry["valuation_status"] = "synced" if valuation_ok else "pending"
        entry["three_year_status"] = "synced" if three_ok else "pending"
        entry["errors"] = errors
        entry["last_attempt_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if valuation_ok and three_ok:
            complete.append(tk)
            print("  普通估值与三年目标均通过同批次核验。")
        else:
            failures.append(tk)
            for error in errors:
                print("  待补：" + error)
    if dry_run:
        print(f"[dry-run] 未写入。可完整同步 {len(complete)} 家，仍待补 {len(failures)} 家。")
        return not failures
    if ordinary_done:
        atomic_write_text(JSON_PATH.with_name(JSON_PATH.name + ".bak_before_drain"), JSON_PATH.read_text(encoding="utf-8"))
        save_json(companies, "同批次普通估值同步：" + ",".join(ordinary_done))
        cmd_apply(ordinary_done)
    if changed_three:
        if THREE_YEAR_PATH.exists():
            atomic_write_text(THREE_YEAR_PATH.with_name(THREE_YEAR_PATH.name + ".bak_before_drain"), THREE_YEAR_PATH.read_text(encoding="utf-8"))
        three["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        atomic_write_text(THREE_YEAR_PATH, json.dumps(three, ensure_ascii=False, indent=2))
    # Keep the queue until both documents have been saved and the ordinary view matches.
    cmd_check()
    queue_doc["pending"] = [e for e in pending if e["ticker"] not in complete]
    queue_doc["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    atomic_write_text(PENDING_SYNC, json.dumps(queue_doc, ensure_ascii=False, indent=2))
    print(f"队列：完整同步出队 {len(complete)} 条，待补 {len(queue_doc['pending'])} 条")
    return not failures


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    mode = args[0]
    if mode == "extract":
        cmd_extract(force="--force" in args)
    elif mode == "check":
        cmd_check()
    elif mode == "apply":
        if len(args) < 2:
            print("用法：apply {TICKER} [...] 或 apply --all")
            sys.exit(1)
        cmd_apply(args[1:])
    elif mode == "drain":
        tks = [a for a in args[1:] if not a.startswith("--")]
        if not cmd_drain(tickers=tks or None, dry_run="--dry-run" in args):
            sys.exit(1)
    else:
        print(f"未知模式：{mode}（可用：extract / check / apply / drain）")
        sys.exit(1)


if __name__ == "__main__":
    from local_workflow import lock
    with lock():
        main()

