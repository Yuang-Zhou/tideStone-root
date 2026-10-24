# -*- coding: utf-8 -*-
r"""
validate_taxonomy.py — 分类体系重构的校验工具（第 0 步）
========================================================

用途：在分类重构的每一步之后跑一次，确认五份名单没有走散。

    python3 _system/scripts/validate_taxonomy.py            # 人读的报告
    python3 _system/scripts/validate_taxonomy.py --json     # 机器读的结果
    python3 _system/scripts/validate_taxonomy.py --quiet    # 只打不通过的项

退出码：0 = 无 ERROR（可能有 WARN）；1 = 有 ERROR；2 = 工具自身出错（读不到文件等）

校验的五份名单
--------------
  N1 companies.json               _system/companies.json                     ← 目标真相源
  N2 portfolio_registry.md        `### {TICKER} — {名称}` 标题               ← 每日扫描消费
  N3 valuation_registry.json      companies 字典的 key                       ← 网站/看板消费
  N4 COMPANIES 常量               dossier_orchestrator.py（AST 解析，不 import）← 建档流水线消费
  N5 文件系统                     实际存在的公司目录                          ← 档案落盘位置

七类检查
--------
  C1 五方 ticker 差集              归一化后任意两方不一致 → ERROR（已知豁免除外）
  C1b ticker 拼写不统一             同一家公司在各名单里拼法不同（NET vs NET.N）→ ERROR
  C2 受控词表                      gics.confidence 不在 vocab → ERROR
  C3 GICS 代码自洽                 长度 2/4/6/8 且逐级前缀包含 → ERROR
  C4 GICS 代码有名字                一级不在 gics_sector_names、四级不在 gics_sub_industry_names
                                   → ERROR（四级名是网站小节标题的来源）
  C5 目录存在                      companies.json 指向的目录在磁盘上不存在 → ERROR
  C6 旧板块标签一致性               legacy_sector vs valuation.sector vs COMPANIES.sector
                                   vs Folder 前缀，四方比对 → WARN（迁移期允许不一致）
  C7 待人工核对                    gics.confidence 分布 + low 名单 → INFO
  C8 行情数据存在                  每家在 _system/market_data/ 有无 CSV（沿用 build_site
                                   的 .N 回退规则）→ ERROR
  C9 旧板块目录回潮                 顶层重新出现 `{数字}. {板块名}/` → ERROR

FUSE 提示
---------
本脚本读文件时会剥离 NUL 填充（Cowork sandbox 的已知现象）。若结论与预期不符，
先确认 bash 视角的文件不是缓存旧版——2026-07-31 就因为这个误判过一次成员数。
"""

import ast
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# 路径：脚本位于 Projects/_system/scripts/
# --------------------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
from tidestone_paths import PROJECTS_ROOT
BASE = str(PROJECTS_ROOT)
SYSTEM_DIR = str(PROJECTS_ROOT / "_system")

COMPANIES_JSON = os.path.join(SYSTEM_DIR, "companies.json")
PORTFOLIO_MD = os.path.join(SYSTEM_DIR, "portfolio_registry.md")
VALUATION_JSON = os.path.join(SYSTEM_DIR, "valuation_registry.json")
ORCHESTRATOR_PY = os.path.join(SCRIPTS_DIR, "dossier_orchestrator.py")

# --------------------------------------------------------------------------
# 已知豁免 —— 每条都要写清"为什么可以不一致"，不许当垃圾桶用
# key = (名单A, 名单B, ticker)，方向无关
# --------------------------------------------------------------------------
KNOWN_EXCEPTIONS = {
    # 目前为空。若第 1 步审完仍有合理差异，写在这里并注明原因和预计消除时间。
    # 例： ("N1", "N5", "SPCX"): "未上市，无档案目录，2026-Q4 前不建",
}

MARKET_DATA_DIR = os.path.join(SYSTEM_DIR, "market_data")

# 美股在各名单里被写成 NET / NET.N / TSLA.O 三种形态。比对时归一化掉这两个后缀；
# .HK / .SZ / .SH / .BJ 是真实的市场标识，必须保留。
US_SUFFIX_RE = re.compile(r"\.(N|O)$")


def norm(tk):
    """归一化 ticker：仅剥离美股的 .N / .O 后缀。"""
    return US_SUFFIX_RE.sub("", tk or "")


HEADING_RE = re.compile(r"^### (\S+) — (.*)$")     # 与 sync_valuations.py 保持一致
SECTOR_RE = re.compile(r"^## (\d+\..*)$")
FOLDER_RE = re.compile(r"^- \*\*Folder:\*\*\s*`(.+?)`\s*$")

NAMES = {
    "N1": "companies.json",
    "N2": "portfolio_registry.md",
    "N3": "valuation_registry.json",
    "N4": "COMPANIES 常量",
    "N5": "文件系统",
}


# ==========================================================================
# 读取工具
# ==========================================================================
def read_text(path):
    """读文本并剥离 FUSE 的 NUL 填充。"""
    with open(path, "rb") as f:
        raw = f.read()
    if b"\x00" in raw:
        sys.stderr.write("  ! %s 含 NUL 填充，已剥离（FUSE 缓存现象，结论存疑请在宿主机复核）\n"
                         % os.path.basename(path))
        raw = raw.replace(b"\x00", b"")
    return raw.decode("utf-8", errors="replace")


def load_json(path):
    return json.loads(read_text(path))


# ==========================================================================
# 五份名单
# ==========================================================================
def load_n1():
    """companies.json —— {ticker: entry}，外加 vocab / gics_sector_names / gics_sub_industry_names。"""
    d = load_json(COMPANIES_JSON)
    return (d.get("companies", {}), d.get("vocab", {}),
            d.get("gics_sector_names", {}), d.get("gics_sub_industry_names", {}))


def load_n2():
    """portfolio_registry.md —— {ticker: {"sector": 所在##板块, "folder": Folder字段}}。"""
    out, sector, cur = {}, None, None
    for line in read_text(PORTFOLIO_MD).splitlines():
        m = SECTOR_RE.match(line)
        if m:
            sector = m.group(1).strip()
            continue
        m = HEADING_RE.match(line)
        if m:
            cur = m.group(1).strip()
            out[cur] = {"sector": sector, "folder": None, "name": m.group(2).strip()}
            continue
        m = FOLDER_RE.match(line)
        if m and cur:
            out[cur]["folder"] = m.group(1).strip()
    return out


def load_n3():
    """valuation_registry.json —— {ticker: entry}。"""
    d = load_json(VALUATION_JSON).get("companies", {})
    if isinstance(d, list):                     # 兼容早期数组形态
        d = {x.get("ticker"): x for x in d if isinstance(x, dict)}
    return d


def load_n4():
    """
    dossier_orchestrator.py 的 COMPANIES —— AST 解析，绝不 import（避免副作用）。

    返回 (entries, collapsed)。第 3a 步（2026-08-01）之后 COMPANIES 不再是字面量
    列表，而是 `COMPANIES = load_companies_list()`——即已经收口到 companies.json。
    这时 collapsed=True，调用方应把 N4 视作与 N1 同源，跳过两者之间的比对
    （拿 N1 去跟 N1 比没有意义，只会掩盖真正的问题）。
    """
    tree = ast.parse(read_text(ORCHESTRATOR_PY))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "COMPANIES" for t in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return {}, True                     # 已收口
        rows = ast.literal_eval(node.value)
        return {r[0]: {"name": r[1], "sector": r[2], "folder": r[3]} for r in rows}, False
    raise RuntimeError("dossier_orchestrator.py 里找不到 COMPANIES 常量")


def load_n5(n1):
    """
    文件系统实际存在的公司目录。

    **一律以 companies.json 声明的路径去反查磁盘**，不从目录名反推 ticker。
    目录名在两种布局下都不可靠：迁移前是「公司名 (TICKER)」中英混排，
    迁移后是「TICKER 中文名」——都得解析才能拿到 ticker，解析就会出错。
    路径由 JSON 声明、磁盘只负责回答"在不在"，这也正是 C5 要验的东西。

    布局标签只用于展示：
      legacy  全部还在 {N. 板块}/ 下
      flat    全部已在 companies/ 下
      mixed   迁移进行中，新老并存（增量走新规范时的正常状态）
    """
    out, flat_n = {}, 0
    for tk, e in n1.items():
        rel = e.get("folder") or e.get("legacy_folder")
        if not rel:
            continue
        if os.path.isdir(os.path.join(BASE, rel.replace("/", os.sep))):
            out[tk] = {"folder": rel}
        if rel.replace("\\", "/").startswith("companies/"):
            flat_n += 1

    if flat_n == 0:
        layout = "legacy"
    elif flat_n == len(n1):
        layout = "flat"
    else:
        layout = "mixed(%d 新 / %d 旧)" % (flat_n, len(n1) - flat_n)
    return out, layout


# ==========================================================================
# 检查
# ==========================================================================
class Report(object):
    def __init__(self):
        self.items = []          # (level, check, message)

    def add(self, level, check, msg):
        self.items.append((level, check, msg))

    def count(self, level):
        return sum(1 for lv, _, _ in self.items if lv == level)


def exempt(a, b, tk):
    return ((a, b, tk) in KNOWN_EXCEPTIONS) or ((b, a, tk) in KNOWN_EXCEPTIONS)


def check_c1(rep, sets, keys):
    """五方 ticker 差集，两两比对（归一化后）。"""
    normed = {k: {norm(t) for t in sets[k]} for k in keys}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            for tk in sorted(normed[a] - normed[b]):
                if not exempt(a, b, tk):
                    rep.add("ERROR", "C1", "%s 有 %s，%s 没有" % (NAMES[a], tk, NAMES[b]))
            for tk in sorted(normed[b] - normed[a]):
                if not exempt(a, b, tk):
                    rep.add("ERROR", "C1", "%s 有 %s，%s 没有" % (NAMES[b], tk, NAMES[a]))


def check_c1b(rep, sets, keys):
    """同一家公司在各名单里的拼法是否统一。"""
    by_norm = {}
    for k in keys:
        for raw in sets[k]:
            by_norm.setdefault(norm(raw), {}).setdefault(raw, []).append(NAMES[k])
    for base, spellings in sorted(by_norm.items()):
        if len(spellings) > 1:
            detail = "；".join("%s ← %s" % (s, "、".join(v)) for s, v in sorted(spellings.items()))
            rep.add("ERROR", "C1b", "%s 的 ticker 拼法不统一：%s" % (base, detail))


def check_c2(rep, n1, vocab):
    """
    受控词表。

    2026-09-11（schema 1.3）：business_model / tier / needs_review / lifecycle 四个自定义维度
    全部删除，顶层已无受控字段。本检查因此改为验 **gics.confidence** —— 它是唯一剩下的受控取值，
    而在此之前竟然没有任何检查管它：写成 "High" 或 "unknown" 都会一路静默通过，
    C7 的分布统计还会多出一个看不懂的桶。

    仍保留 TOP_FIELDS 循环——将来再加顶层受控字段时只需往元组里添一项。
    """
    for tk, e in sorted(n1.items()):
        allowed = set(vocab.get("confidence", []))
        if not allowed:
            rep.add("ERROR", "C2", "companies.json 的 vocab 里没有 confidence 词表")
            break
        g = e.get("gics")
        if not isinstance(g, dict):
            continue                      # gics 缺失/类型不对由 C3 报，这里不重复
        v = g.get("confidence")
        if v is None:
            rep.add("ERROR", "C2", "%s 缺 gics.confidence" % tk)
        elif v not in allowed:
            rep.add("ERROR", "C2", "%s 的 gics.confidence = %r 不在词表内" % (tk, v))

    TOP_FIELDS = ()
    for field in TOP_FIELDS:
        allowed = set(vocab.get(field, []))
        if not allowed:
            rep.add("ERROR", "C2", "companies.json 的 vocab 里没有 %s 词表" % field)
            continue
        for tk, e in sorted(n1.items()):
            v = e.get(field)
            if v is None:
                rep.add("ERROR", "C2", "%s 缺 %s 字段" % (tk, field))
            elif v not in allowed:
                rep.add("ERROR", "C2", "%s 的 %s = %r 不在词表内" % (tk, field, v))


def check_c3_c4(rep, n1, sector_names, sub_names):
    """
    GICS 代码自洽 + 一级代码有名字 + 四级代码有中文名。

    2026-09-11：网站改成板块大节内按四级子行业分小节后，子行业名表成了展示的必需品。
    缺名字不会让 build_site 崩，只会在页面上印出「未命名子行业 45103010」——
    那种错没人会在构建日志里发现，所以在这里拦。
    """
    levels = [("sector", 2), ("industry_group", 4), ("industry", 6), ("sub_industry", 8)]
    for tk, e in sorted(n1.items()):
        g = e.get("gics")
        if not isinstance(g, dict):
            rep.add("ERROR", "C3", "%s 缺 gics 字段" % tk)
            continue

        codes = {}
        ok = True
        for field, width in levels:
            c = g.get(field)
            if c is None:
                rep.add("ERROR", "C3", "%s 的 gics 缺 %s" % (tk, field))
                ok = False
                continue
            c = str(c)
            if not c.isdigit() or len(c) != width:
                rep.add("ERROR", "C3", "%s 的 gics.%s = %r 应为 %d 位数字" % (tk, field, c, width))
                ok = False
                continue
            codes[field] = c

        if ok:
            # 逐级前缀包含：sub[:6]==industry, industry[:4]==group, group[:2]==sector
            chain = ["sub_industry", "industry", "industry_group", "sector"]
            for child, parent in zip(chain, chain[1:]):
                w = dict(levels)[parent]
                if codes[child][:w] != codes[parent]:
                    rep.add("ERROR", "C3", "%s 的 gics.%s(%s) 不属于 %s(%s)"
                            % (tk, child, codes[child], parent, codes[parent]))
            if codes["sector"] not in sector_names:
                rep.add("ERROR", "C4", "%s 的 gics.sector = %s 在 gics_sector_names 里没有名字"
                        % (tk, codes["sector"]))
            if codes["sub_industry"] not in sub_names:
                rep.add("ERROR", "C4", "%s 的 gics.sub_industry = %s 在 gics_sub_industry_names "
                        "里没有中文名（网站小节标题会显示成「未命名子行业」）"
                        % (tk, codes["sub_industry"]))

        if not g.get("as_of"):
            rep.add("WARN", "C3", "%s 的 gics 缺 as_of（改版后无法回溯是哪一版判定）" % tk)


def check_c5(rep, n1, layout):
    """companies.json 指向的目录在磁盘上是否存在。"""
    for tk, e in sorted(n1.items()):
        rel = e.get("folder") or e.get("legacy_folder")
        if not rel:
            rep.add("ERROR", "C5", "%s 既无 folder 也无 legacy_folder" % tk)
            continue
        if not os.path.isdir(os.path.join(BASE, rel.replace("/", os.sep))):
            rep.add("ERROR", "C5", "%s 的目录不存在：%s" % (tk, rel))


def check_c6(rep, n1, n2, n3, n4):
    """
    旧板块标签四方一致性。迁移期允许不一致（第 2/3 步会逐步消除），故为 WARN。
    第 3 步完成后 legacy_sector 应已删除，本检查自动跳过。
    """
    n2n = {norm(k): v for k, v in n2.items()}
    n3n = {norm(k): v for k, v in n3.items()}
    n4n = {norm(k): v for k, v in n4.items()}
    checked = 0
    for tk, e in sorted(n1.items()):
        legacy = e.get("legacy_sector")
        if not legacy:
            continue
        checked += 1
        b = norm(tk)
        vals = {"companies.json": legacy}
        if b in n2n:
            vals["registry ## 标题"] = n2n[b].get("sector")
            fold = n2n[b].get("folder")
            if fold:
                vals["registry Folder 前缀"] = fold.split("/")[0]
        if b in n3n:
            vals["valuation_registry"] = n3n[b].get("sector")
        if b in n4n:
            vals["COMPANIES"] = n4n[b].get("sector")

        distinct = set(v for v in vals.values() if v)
        if len(distinct) > 1:
            detail = "，".join("%s=%s" % (k, v) for k, v in sorted(vals.items()) if v)
            rep.add("WARN", "C6", "%s 的旧板块标签不一致：%s" % (tk, detail))
    if checked == 0:
        rep.add("INFO", "C6", "companies.json 已无 legacy_sector 字段，跳过旧标签比对（第 3 步已完成）")


def check_c7(rep, n1):
    """
    待人工核对的计数。

    2026-09-11（schema 1.2）：needs_review 字段已删除，待核信号只由 gics.confidence 承担。
    删它的理由是它涨到过 29/64=45% 且没有任何环节会回头清——一个永远为真的标记等于没有标记。
    confidence 不会有这个毛病：它是三档的事实陈述（有没有一手来源），不是待办状态。
    """
    dist = {}
    for e in n1.values():
        c = (e.get("gics") or {}).get("confidence") or "（缺）"
        dist[c] = dist.get(c, 0) + 1
    rep.add("INFO", "C7", "gics.confidence 分布：" + "  ".join(
        "%s %d" % (k, dist[k]) for k in ("high", "medium", "low", "（缺）") if k in dist))

    low = sorted(tk for tk, e in n1.items()
                 if isinstance(e.get("gics"), dict) and e["gics"].get("confidence") == "low")
    if low:
        rep.add("INFO", "C7", "confidence=low 共 %d 家（无一手来源，优先核）：%s" % (len(low), " ".join(low)))
    else:
        rep.add("INFO", "C7", "无 confidence=low 条目 —— GICS 全部有据")


LEGACY_DIR_RE = re.compile(r"^\d+\.\s")


def check_c9(rep):
    """
    旧板块目录回潮检测。

    2026-08-09 新增。扁平化迁移之后本该只剩 `companies/`，但 08-07 有个流程重新
    创建了空的 `1. SaaS软件/Cloudflare (NET.N)/`——目录是空的没丢数据，可它在那儿
    躺了两天没人发现，因为当时没有任何检查会看"多出来的目录"。
    C5 只验"声明的目录在不在"，验不了"不该在的目录冒出来了"。

    任何 `{数字}. {名字}/` 形态的顶层目录都视为回潮：要么是某个 skill / 脚本还在用
    写死的旧路径，要么是人手工建的。空目录直接删；非空的说明有数据被写进了错误位置，
    必须查清来源再处理。
    """
    strays = []
    try:
        entries = sorted(os.listdir(BASE))
    except OSError as e:
        rep.add("WARN", "C9", "读不到 Projects 顶层目录：%s" % e)
        return
    for name in entries:
        p = os.path.join(BASE, name)
        if not os.path.isdir(p) or not LEGACY_DIR_RE.match(name):
            continue
        try:
            n = sum(len(fs) for _, _, fs in os.walk(p))
        except OSError:
            n = -1
        strays.append((name, n))

    for name, n in strays:
        if n == 0:
            rep.add("ERROR", "C9", "旧板块目录回潮（空壳，可直接删）：%s/" % name)
        else:
            rep.add("ERROR", "C9",
                    "旧板块目录回潮且**里面有 %d 个文件**：%s/ —— 有东西正往旧路径写，"
                    "先查来源再搬，别直接删" % (n, name))


def check_c8(rep, n1):
    """行情 CSV 是否存在。回退规则与 build_site.last_close 一致（tk 与去掉 .N 的形态各试一次）。"""
    if not os.path.isdir(MARKET_DATA_DIR):
        rep.add("WARN", "C8", "找不到 _system/market_data/，跳过行情检查")
        return
    for tk in sorted(n1):
        cands = [tk, tk.replace(".N", ""), norm(tk)]
        if not any(os.path.exists(os.path.join(MARKET_DATA_DIR, c + ".csv")) for c in cands):
            rep.add("ERROR", "C8", "%s 没有行情 CSV —— 网站上现价与上行空间会是空的" % tk)


# ==========================================================================
# 主流程
# ==========================================================================
def main(argv):
    as_json = "--json" in argv
    quiet = "--quiet" in argv

    try:
        n1, vocab, sector_names, sub_names = load_n1()
    except FileNotFoundError:
        sys.stderr.write("找不到 %s —— 第 1 步尚未开始？\n" % COMPANIES_JSON)
        return 2
    except Exception as e:
        sys.stderr.write("读 companies.json 失败：%s\n" % e)
        return 2

    try:
        n2 = load_n2()
        n3 = load_n3()
        n4, n4_collapsed = load_n4()
        n5, layout = load_n5(n1)
    except Exception as e:
        sys.stderr.write("读取名单失败：%s\n" % e)
        return 2

    rep = Report()
    sets = {"N1": n1, "N2": n2, "N3": n3, "N4": n4, "N5": n5}
    keys = ["N1", "N2", "N3", "N5"] if n4_collapsed else ["N1", "N2", "N3", "N4", "N5"]

    check_c1(rep, sets, keys)
    check_c1b(rep, sets, keys)
    check_c2(rep, n1, vocab)
    check_c3_c4(rep, n1, sector_names, sub_names)
    check_c5(rep, n1, layout)
    check_c6(rep, n1, n2, n3, n4)
    check_c7(rep, n1)
    check_c8(rep, n1)
    check_c9(rep)
    if n4_collapsed:
        rep.add("INFO", "C1", "COMPANIES 已收口到 companies.json（第 3a 步），"
                              "N4 与 N1 同源，已跳过两者比对")

    if as_json:
        print(json.dumps({
            "layout": layout,
            "companies_collapsed": n4_collapsed,
            "counts": {k: len(sets[k]) for k in keys},
            "errors": rep.count("ERROR"),
            "warnings": rep.count("WARN"),
            "items": [{"level": lv, "check": c, "message": m} for lv, c, m in rep.items],
        }, ensure_ascii=False, indent=2))
        return 1 if rep.count("ERROR") else 0

    print("=" * 68)
    LAYOUT_LABEL = {"flat": "已扁平化（companies/）", "legacy": "迁移前（板块目录）"}
    print("分类体系校验 —— 目录布局：%s" % LAYOUT_LABEL.get(layout, "迁移中 " + layout))
    print("=" * 68)
    print("名单规模：" + "  ".join("%s %d" % (NAMES[k], len(sets[k])) for k in keys)
          + ("   （COMPANIES 已收口，不再是独立名单）" if n4_collapsed else ""))
    print()

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    shown = [it for it in rep.items if not (quiet and it[0] == "INFO")]
    if not shown:
        print("  全部通过。")
    for level in sorted(set(lv for lv, _, _ in shown), key=lambda x: order.get(x, 9)):
        block = [it for it in shown if it[0] == level]
        print("── %s（%d）" % (level, len(block)))
        for _, check, msg in block:
            print("   [%s] %s" % (check, msg))
        print()

    err, warn = rep.count("ERROR"), rep.count("WARN")
    print("-" * 68)
    print("结论：%d 个 ERROR，%d 个 WARN。%s"
          % (err, warn, "可以进下一步。" if err == 0 else "先修 ERROR 再进下一步。"))
    return 1 if err else 0


if __name__ == "__main__":
    try:                                     # Windows 控制台中文输出
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))

