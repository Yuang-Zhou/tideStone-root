#!/usr/bin/env python3
"""
position_guard.py — 持仓纪律引擎（确定性，不掺叙事）

与 compute_signals.py 同一设计哲学：
  规则一律由 committed 引擎计算，绝不在 prose 里临时重写。
  prose 里的规则会【逐日漂移】、会【被静默跳过】——这正是本文件存在的理由。

职责边界：
  本引擎【只做】确定性判定：区间归类、集中度、快照 diff、7 条偏离规则、
  扳机时效比对、价格型扳机命中。输出一份 verdict JSON。
  本引擎【绝不】：调 MCP、读行情、写扳机文件、生成叙事、给投资建议。
  叙事与事件型扳机（需读财报的，如 CRM 的 CRPO/ARR）交给 daily-position-advisor。

失败哲学（重要）：
  宁可硬失败，不可静默跳过。
  - 输入 JSON 截断 → json.JSONDecodeError → 直接崩，不产出 verdict
  - 声明数量 ≠ 实际数量 → IntegrityError → 直接崩（防"少读几条规则却以为没报警"）
  - 区间字符串解析不出来 → 标记 zone_parse_failed 并暴露，绝不猜

用法：
  python3 position_guard.py --positions <positions.json> --date 2026-07-14 \
      [--root <Projects 根>] [--out <verdict.json>] [--strict]

  --strict：要求 briefing_data / valuation_registry 的日期是今天，否则失败。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 常量区
# 所有阈值集中在此 + position_triggers.json 的 portfolio_rules。
# 调参只动这里或 JSON，不动逻辑。

SCHEMA_VERSION = 1

# 扳机"临近"的定义
NEAR_PRICE_PCT = 5.0      # 距触发价 < 5% 视为临近
NEAR_EVENT_DAYS = 14      # 事件日 ≤ 14 天视为临近

# 清仓后回购的观察窗口（天）；实际值以 portfolio_rules 为准，此为兜底
DEFAULT_REBUY_WINDOW_DAYS = 30
DEFAULT_MAX_SINGLE_PCT = 25.0
DEFAULT_MIN_CASH_PCT = 10.0
DEFAULT_MAX_AVG_DOWN = 1
DEFAULT_AVG_DOWN_RESET_TRIM_PCT = 50.0
# 分批建仓计划未写明目标仓位时的兜底上限（占总资产 %）
DEFAULT_SCALE_IN_TARGET_PCT = 20.0

# 扳机过期未处理的升级阈值（交易日）
STALE_ESCALATE_DAYS = 3

# ticker 归一化：估值台账 key ↔ IBKR ticker
# 台账用 NET.N / SATS，IBKR 用 NET / ECHO。映射不上的不猜，列 uncovered。
TICKER_ALIASES: dict[str, str] = {
    "NET.N": "NET",
    "SATS": "ECHO",   # EchoStar 2026-06-24 改代码
    "ECHO": "ECHO",
    "GOOGL": "GOOG",  # 持仓可能是 C 类
}

# 视为"卖出/减持"性质的区间标签（命中即触发"卖出区仍持有"规则）
SELL_ZONE_LABELS = ("卖出", "强烈卖出", "减持")
BUY_ZONE_LABELS = ("买入", "强烈买入", "强力买入", "逢低买入", "增持")

# 视为"非买入"的评级（新建仓时命中即报警）
NON_BUY_RATINGS = ("持有", "卖出", "减持", "中性", "研究中", "HOLD")


class IntegrityError(RuntimeError):
    """输入文件完整性校验失败 —— 绝不降级、绝不静默继续。"""


# ---------------------------------------------------------------- 工具

def _load_json(path: Path, what: str) -> Any:
    """
    读 JSON。截断/损坏 → 直接崩。这是最重要的截断防线。

    三种截断形态都必须接住（2026-07-14 自测发现只接 JSONDecodeError 会漏）：
      1. UnicodeDecodeError —— 在多字节汉字中间被切断（中文 JSON 最常见）
      2. JSONDecodeError    —— 字节完整但括号没闭合
      3. NUL 字节           —— FUSE 损坏的典型特征
    """
    if not path.exists():
        raise IntegrityError(f"{what} 不存在：{path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise IntegrityError(
            f"{what} UTF-8 解码失败（在多字节字符中间被截断）：{path}\n  {e}"
        ) from e
    if "\x00" in raw:
        raise IntegrityError(f"{what} 含 NUL 字节（FUSE 损坏）：{path}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise IntegrityError(
            f"{what} JSON 解析失败（极可能是 FUSE 截断）：{path}\n  {e}"
        ) from e


def _parse_date(s: Any) -> date | None:
    """宽松解析 YYYY-MM-DD；解析不出来返回 None（调用方一律 fail-closed）。"""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _norm(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    return TICKER_ALIASES.get(t, t)


_PAREN = re.compile(r"[（(][^）)]*[）)]")
_NUM = re.compile(r"\d+(?:\.\d+)?")  # 2026-09-17: 去掉 -?。台账 "$40–52" 归一化后 52 曾被吃成 -52（见 引擎区间解析缺陷修复方案_2026-09-03 ①）


def parse_zone_range(s: str) -> tuple[float | None, float | None, bool]:
    """
    解析估值台账的区间字符串，返回 (low, high, ok)。

    台账里的写法很脏，例如：
      "≤ $119"                          -> (None, 119, True)
      "$122 - $149（安全边际15-30%）"    -> (122, 149, True)   # 括号内 15-30 必须先剥掉
      "> $320（达加权目标价）"           -> (320, None, True)
      "$201 - $228"                     -> (201, 228, True)
      "$96 – $101 减配；> $111 卖出"     -> 歧义 -> ok=False   # 两段，不猜

    ok=False 时调用方必须把该 ticker 标为 zone_parse_failed 并暴露，【绝不猜】。
    """
    if not s:
        return (None, None, False)

    # 1) 剥掉括号内容（里面常有 "15-30%" 这种会污染数字提取的东西）
    t = _PAREN.sub("", s)
    # 2) 归一化各种破折号
    t = t.replace("–", "-").replace("—", "-").replace("~", "-")
    # 3) 分号/多段 = 歧义，拒绝解析
    if "；" in t or ";" in t:
        return (None, None, False)

    has_le = "≤" in t or "<=" in t
    has_lt = "<" in t and not has_le
    has_ge = "≥" in t or ">=" in t
    has_gt = ">" in t and not has_ge

    nums = [float(x) for x in _NUM.findall(t.replace(",", ""))]
    if not nums:
        return (None, None, False)

    if has_le or has_lt:
        return (None, nums[0], True)
    if has_ge or has_gt:
        return (nums[0], None, True)
    if len(nums) >= 2:
        lo, hi = sorted(nums[:2])
        return (lo, hi, True)
    # 只有一个数字又没有比较符 → 歧义
    return (None, None, False)


def classify_zone(price: float, zones: list[dict]) -> tuple[str | None, list[str]]:
    """
    把现价归入台账区间。返回 (区间标签, 解析失败的区间标签列表)。
    命中不了任何区间 → (None, failed)，调用方需暴露。
    """
    failed: list[str] = []
    hit: str | None = None
    for z in zones or []:
        label = (z.get("label") or "").strip()
        lo, hi, ok = parse_zone_range(z.get("range") or "")
        if not ok:
            failed.append(label)
            continue
        if lo is not None and price < lo:
            continue
        if hi is not None and price > hi:
            continue
        # 落在此区间
        if hit is None:
            hit = label
    return hit, failed


def find_zone_gaps(zones: list[dict]) -> list[dict]:
    """
    侦测区间【裂缝】—— 相邻区间之间的无人区。

    真实案例（2026-07-14 引擎首跑发现）：
      META  买入区 ≤$500 | 持有区 $500-$640 | 卖出/减持区 ≥$720
            → $640–$720 是空白。META 现价 $658.69 掉进裂缝，无法归类。
      U     买入区 <$18 | 持有区 $18-$28 | 卖出区 >$34
            → $28–$34 是空白。现价 $30.74 掉进裂缝。

    危害：股价涨进裂缝 → 归类不到任何区间 → 【卖出区仍持有】规则永远不触发
          → 你以为没报警是安全的，其实是规则根本没跑到。
    这正是本引擎存在的意义：把静默失效变成显式报警。
    """
    parsed = []
    for z in zones or []:
        lo, hi, ok = parse_zone_range(z.get("range") or "")
        if ok:
            parsed.append((lo, hi, (z.get("label") or "").strip()))
    # 按下界排序（None 视为 -inf）
    parsed.sort(key=lambda x: (x[0] if x[0] is not None else float("-inf")))

    gaps = []
    for i in range(len(parsed) - 1):
        _, hi_a, lab_a = parsed[i]
        lo_b, _, lab_b = parsed[i + 1]
        if hi_a is not None and lo_b is not None and lo_b > hi_a + 1e-9:
            gaps.append({
                "between": [lab_a, lab_b],
                "gap_low": hi_a,
                "gap_high": lo_b,
                "detail": f"{lab_a} 上界 {hi_a} 与 {lab_b} 下界 {lo_b} 之间存在裂缝",
            })
    return gaps


def _is_sell_zone(label: str | None) -> bool:
    return bool(label) and any(k in label for k in SELL_ZONE_LABELS)


def _is_buy_zone(label: str | None) -> bool:
    return bool(label) and any(k in label for k in BUY_ZONE_LABELS)


def _parse_money(s: Any) -> float | None:
    """从 '$175（DCF...）' / '~$88' / 175 里抠出数字。"""
    if isinstance(s, (int, float)):
        return float(s)
    if not s:
        return None
    t = _PAREN.sub("", str(s))
    m = _NUM.search(t.replace(",", ""))
    return float(m.group()) if m else None


def _rating_stem(s: Any) -> str:
    """
    评级主干 —— 只取破折号前的部分。

    台账的 rating 字段常把叙事拼在评级后面，例如：
      "持有（Hold，中性）— 2026-07-08 六槽全量重估（Iridium SOTP 正式版）；现价 $83.41…"
    严格字符串比较会因为叙事变动而天天误报"评级漂移"。
    真正该触发报警的是【评级本身变了】（买入→持有），不是叙事措辞变了。
    """
    t = str(s or "").strip()
    for sep in ("—", "–", " - ", "；", ";"):
        if sep in t:
            t = t.split(sep)[0]
            break
    return t.strip()


# ---------------------------------------------------------------- 完整性校验

def check_integrity(triggers_doc: dict) -> dict:
    """
    声明式计数校验 —— 防"文件被截断/条目被吞，导致规则静默跳过"。

    position_triggers.json 里若有 _integrity {trigger_count, guard_rule_count}，
    则实际数量必须与之相符，否则硬失败。
    这一条专治：扳机文件少了一条，你却因为"没报警"而以为安全。
    """
    triggers = triggers_doc.get("triggers", [])
    rules = (triggers_doc.get("deviation_guard") or {}).get("rules", [])
    declared = triggers_doc.get("_integrity") or {}

    actual = {"trigger_count": len(triggers), "guard_rule_count": len(rules)}

    if declared:
        for k, want in declared.items():
            if k.startswith("_"):
                continue
            got = actual.get(k)
            if got != want:
                raise IntegrityError(
                    f"position_triggers.json 完整性校验失败：{k} 声明 {want}，实际 {got}。"
                    f" 文件可能被截断或条目被误删 —— 拒绝产出 verdict。"
                )
        verified = True
    else:
        verified = False  # 没声明 _integrity，无法校验，如实上报

    return {
        "counts": actual,
        "declared": {k: v for k, v in declared.items() if not k.startswith("_")},
        "count_check_verified": verified,
    }


# ---------------------------------------------------------------- 核心判定

def enrich_holdings(positions: list[dict], cash: float,
                    registry: dict, briefing: dict | None,
                    oos: dict | None = None) -> tuple[list[dict], dict]:
    """持仓 × 估值台账 × 当日行情 → 每个持仓的完整画像。

    oos = out_of_scope 映射（刻意不入台账的标的）。
    """
    oos = oos or {}
    companies = registry.get("companies", {})
    # 台账 key 归一化后的索引
    reg_by_norm: dict[str, tuple[str, dict]] = {}
    for k, v in companies.items():
        reg_by_norm[_norm(k)] = (k, v)

    bf_by_norm: dict[str, dict] = {}
    for c in (briefing or {}).get("companies", []) or []:
        bf_by_norm[_norm(c.get("ticker", ""))] = c

    equity = sum(float(p.get("market_value") or 0) for p in positions)
    total = equity + cash

    out: list[dict] = []
    for p in positions:
        raw_t = p.get("ticker", "")
        t = _norm(raw_t)
        qty = float(p.get("qty") or 0)
        avg = float(p.get("avg_cost") or 0)
        px = float(p.get("last_price") or 0)
        mv = float(p.get("market_value") or (qty * px))
        upl = p.get("unrealized_pnl")
        upl = float(upl) if upl is not None else (px - avg) * qty

        reg_key, reg = reg_by_norm.get(t, (None, {}))
        zones = reg.get("zones") or []
        zone, zone_failed = (None, [])
        gaps = []
        if zones:
            gaps = find_zone_gaps(zones)
            if px:
                zone, zone_failed = classify_zone(px, zones)
        # 现价掉进裂缝？（归类失败 + 该价位确实落在某条裂缝里）
        in_gap = next(
            (g for g in gaps
             if zone is None and px and g["gap_low"] < px < g["gap_high"]),
            None)

        target = _parse_money(reg.get("target_price"))
        upside = ((target - px) / px * 100.0) if (target and px) else None

        bf = bf_by_norm.get(t, {})

        out.append({
            "ticker": t,
            "raw_ticker": raw_t,
            "registry_key": reg_key,
            "covered": reg_key is not None,
            "qty": qty,
            "avg_cost": round(avg, 4),
            "last_price": round(px, 4),
            "market_value": round(mv, 2),
            "unrealized_pnl": round(upl, 2),
            "unrealized_pct": round((px / avg - 1) * 100, 2) if avg else None,
            "pct_of_equity": round(mv / equity * 100, 2) if equity else None,
            "pct_of_total": round(mv / total * 100, 2) if total else None,
            "rating": reg.get("rating"),
            "target_price": reg.get("target_price"),
            "target_num": target,
            "upside_pct": round(upside, 1) if upside is not None else None,
            "zone": zone,
            "zone_parse_failed": zone_failed,
            "zone_gaps": gaps,
            "price_in_zone_gap": in_gap,
            "in_sell_zone": _is_sell_zone(zone),
            "in_buy_zone": _is_buy_zone(zone),
            "briefing_zone": (bf.get("snapshot") or {}).get("valuation_zone"),
            "rsi": (bf.get("snapshot") or {}).get("rsi"),
        })

    concentration = {
        "equity": round(equity, 2),
        "cash": round(cash, 2),
        "total": round(total, 2),
        "cash_pct": round(cash / total * 100, 2) if total else None,
        "top3_pct": round(
            sum(sorted((h["pct_of_total"] or 0) for h in out)[-3:]), 2
        ) if out else 0.0,
        "n_positions": len(out),
        # 疏漏（不该没覆盖却没覆盖）vs 决定（刻意不覆盖）—— 必须分开
        "uncovered": [h["ticker"] for h in out
                      if not h["covered"] and h["ticker"] not in oos],
        "out_of_scope": [
            {"ticker": h["ticker"], "market_value": h["market_value"],
             "unrealized_pct": h["unrealized_pct"],
             "reason": (oos.get(h["ticker"]) or {}).get("reason")}
            for h in out if h["ticker"] in oos
        ],
        "zone_unresolved": [h["ticker"] for h in out
                            if h["covered"] and h["zone"] is None],
        # 🔴 现价掉进区间裂缝 —— 卖出区规则对这些票【静默失效】，必须修台账
        "price_in_zone_gap": [
            {"ticker": h["ticker"], "price": h["last_price"],
             **h["price_in_zone_gap"]}
            for h in out if h["price_in_zone_gap"]
        ],
        "registry_zone_gaps": [
            {"ticker": h["ticker"], "gaps": h["zone_gaps"]}
            for h in out if h["zone_gaps"]
        ],
    }
    return out, concentration


def diff_snapshot(today: list[dict], prev: dict | None) -> dict:
    """
    与昨日快照 diff → 新建仓 / 加仓 / 减仓 / 清仓 / 均价下移（摊薄）。
    prev 为 None（首次运行）时返回 available=False，调用方须注明"跳过 diff 类检查"。
    """
    if not prev:
        return {"available": False, "reason": "无昨日快照（首次运行）"}

    prev_h = {_norm(h["ticker"]): h for h in prev.get("holdings", [])}
    cur_h = {h["ticker"]: h for h in today}

    opened, added, trimmed, closed, averaged_down = [], [], [], [], []

    for t, h in cur_h.items():
        p = prev_h.get(t)
        if p is None:
            opened.append({"ticker": t, "qty": h["qty"], "avg_cost": h["avg_cost"]})
            continue
        dq = h["qty"] - float(p.get("qty") or 0)
        pa = float(p.get("avg_cost") or 0)
        if dq > 1e-9:
            entry = {"ticker": t, "qty_added": round(dq, 4),
                     "avg_before": pa, "avg_after": h["avg_cost"]}
            added.append(entry)
            # 加仓且均价下移 = 向下摊薄
            if pa and h["avg_cost"] < pa - 1e-9:
                averaged_down.append(entry)
        elif dq < -1e-9:
            pq = float(p.get("qty") or 0)
            trimmed.append({"ticker": t, "qty_reduced": round(-dq, 4),
                            "qty_before": pq,
                            "trim_pct": round(-dq / pq * 100, 2) if pq else None})

    for t, p in prev_h.items():
        if t not in cur_h and float(p.get("qty") or 0) > 0:
            closed.append({"ticker": t, "qty_was": p.get("qty")})

    return {
        "available": True,
        "prev_date": prev.get("date"),
        "opened": opened,
        "added": added,
        "trimmed": trimmed,
        "closed": closed,
        "averaged_down": averaged_down,
    }


def check_scale_in_exemptions(diff: dict, holdings: list[dict],
                             plans: dict, today: date,
                             default_target_pct: float) -> list[dict]:
    """
    「计划内分批建仓」豁免判定（2026-09-04 新增）。

    背景：max_averaging_down_times 只看均价降没降，分不清两件事——
      · 计划内分批：总仓位、价格区间、停手条件【在跌之前】就写好了（TCOM）
      · 计划外摊薄：跌了才想补，哪跌到哪买，没有停手条件（RKLB $105→$95→$84）
    规则原本为后者而写，误伤了前者。本函数只豁免前者。

    四条【全中】才豁免：
      1. 建仓计划写在档案里，写入时间早于本次买入，且未过复核期
      2. 本次买入价（由 qty/avg_cost 反解）落在计划写明的分批建仓区内
      3. 累计仓位未超过计划【当前阶段】的上限
      4. 计划写明了推进到下一阶段的条件

    fail-closed：任何一条验不了（缺字段/日期不可解析/计划过期）一律【不豁免】。
    "验不了" 绝不等于 "通过" —— 这与本引擎其余部分同一哲学。
    """
    out: list[dict] = []
    by_ticker = {h["ticker"]: h for h in holdings}

    for a in (diff.get("averaged_down") or []):
        t = a["ticker"]
        plan = (plans or {}).get(t) or {}
        checks: list[dict] = []

        def chk(no: int, name: str, ok: bool, detail: str) -> None:
            checks.append({"no": no, "name": name,
                           "pass": bool(ok), "detail": detail})

        if not plan:
            chk(1, "计划先于买入且在有效期内", False, "档案无分批建仓计划")
            chk(2, "买入价落在分批建仓区内", False, "无计划 → 无区间可比")
            chk(3, "未超当前阶段仓位上限", False, "无计划 → 无上限可比")
            chk(4, "写明推进到下一阶段的条件", False, "无计划")
            out.append({"ticker": t, "exempt": False, "checks": checks,
                        "implied_buy_price": None,
                        "reason": "无书面分批建仓计划 → 按计划外向下摊薄处理"})
            continue

        # --- 条件 1：计划先于买入、且未过复核期 ---
        written = _parse_date(plan.get("written_at"))
        valid_until = _parse_date(plan.get("valid_until"))
        if written is None:
            chk(1, "计划先于买入且在有效期内", False,
                f"written_at 缺失或不可解析：{plan.get('written_at')!r}")
        elif written >= today:
            chk(1, "计划先于买入且在有效期内", False,
                f"计划写入日 {written} 不早于买入日 {today}（事后补写不算计划）")
        elif valid_until is None:
            chk(1, "计划先于买入且在有效期内", False,
                f"valid_until 缺失或不可解析：{plan.get('valid_until')!r}")
        elif today > valid_until:
            chk(1, "计划先于买入且在有效期内", False,
                f"计划复核期已过（valid_until {valid_until}），须重跑估值后再启用")
        else:
            chk(1, "计划先于买入且在有效期内", True,
                f"计划写于 {written}，有效期至 {valid_until}")

        # --- 条件 2：买入价落在分批建仓区内（由持仓反解本次买入均价）---
        h = by_ticker.get(t)
        implied = None
        try:
            qty_added = float(a.get("qty_added") or 0)
            if h and qty_added > 0:
                qty_after = float(h["qty"])
                qty_before = qty_after - qty_added
                implied = round(
                    (qty_after * float(a["avg_after"])
                     - qty_before * float(a["avg_before"])) / qty_added, 4)
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            implied = None

        lo, hi = plan.get("zone_low"), plan.get("zone_high")
        if implied is None:
            chk(2, "买入价落在分批建仓区内", False, "无法反解本次买入价")
        elif lo is None or hi is None:
            chk(2, "买入价落在分批建仓区内", False,
                "计划缺 zone_low / zone_high")
        elif float(lo) <= implied <= float(hi):
            chk(2, "买入价落在分批建仓区内", True,
                f"本次买入均价 ${implied} 落在 ${lo}–${hi}")
        else:
            chk(2, "买入价落在分批建仓区内", False,
                f"本次买入均价 ${implied} 在 ${lo}–${hi} 之外")

        # --- 条件 3 & 4：当前阶段的仓位上限与推进条件 ---
        stages = plan.get("stages") or []
        try:
            cur_no = int(plan.get("current_stage"))
        except (TypeError, ValueError):
            cur_no = None
        stage = next((s for s in stages
                      if str(s.get("stage")) == str(cur_no)), None)

        target_pct = plan.get("target_position_pct_of_total")
        try:
            target_pct = float(target_pct) if target_pct is not None \
                else float(default_target_pct)
        except (TypeError, ValueError):
            target_pct = None

        if stage is None:
            chk(3, "未超当前阶段仓位上限", False,
                f"current_stage={plan.get('current_stage')!r} 在 stages 中找不到")
            chk(4, "写明推进到下一阶段的条件", False, "无当前阶段条目")
        else:
            share = stage.get("max_share_of_target")
            cur_pct = (h or {}).get("pct_of_total")
            if share is None or target_pct is None or cur_pct is None:
                chk(3, "未超当前阶段仓位上限", False,
                    "缺 max_share_of_target / 目标仓位 / 当前占比")
            else:
                cap = round(float(target_pct) * float(share), 4)
                if float(cur_pct) <= cap:
                    chk(3, "未超当前阶段仓位上限", True,
                        f"阶段{cur_no} 上限 {cap}% 总资产，当前 {cur_pct}%")
                else:
                    chk(3, "未超当前阶段仓位上限", False,
                        f"阶段{cur_no} 上限 {cap}% 总资产，当前已 {cur_pct}%")

            cond = (stage.get("advance_condition") or "").strip()
            chk(4, "写明推进到下一阶段的条件", bool(cond),
                cond if cond else "advance_condition 为空 → 分批会变成一路买到底")

        exempt = all(c["pass"] for c in checks)
        failed = [f'{c["no"]}.{c["name"]}' for c in checks if not c["pass"]]
        out.append({
            "ticker": t,
            "exempt": exempt,
            "checks": checks,
            "implied_buy_price": implied,
            "plan_source": plan.get("source"),
            "reason": ("四条全中 → 计划内分批建仓，本次不计入向下摊薄次数"
                       if exempt else "未通过：" + "、".join(failed)),
        })

    return out


def load_exit_history(positions_dir: Path, today: date,
                      window_days: int) -> dict[str, str]:
    """
    扫历史快照，找出"曾经持有、后来清仓"的 ticker 及其清仓日期。
    用于"清仓后 N 天内回购"检测（GRAL / RKLB 陷阱）。
    """
    snaps: list[tuple[date, dict]] = []
    for f in sorted(positions_dir.glob("snapshot_*.json")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            snaps.append((d, _load_json(f, f"快照 {f.name}")))
        except (ValueError, IntegrityError):
            continue  # 单份历史快照坏掉不应阻断今日判定
    snaps.sort()

    exits: dict[str, str] = {}
    for i in range(1, len(snaps)):
        d_prev, s_prev = snaps[i - 1]
        d_cur, s_cur = snaps[i]
        held_prev = {_norm(h["ticker"]) for h in s_prev.get("holdings", [])
                     if float(h.get("qty") or 0) > 0}
        held_cur = {_norm(h["ticker"]) for h in s_cur.get("holdings", [])
                    if float(h.get("qty") or 0) > 0}
        for t in held_prev - held_cur:
            exits[t] = d_cur.isoformat()  # 记最近一次清仓

    cutoff = today - timedelta(days=window_days)
    return {t: d for t, d in exits.items()
            if datetime.strptime(d, "%Y-%m-%d").date() >= cutoff}


def check_deviations(holdings: list[dict], conc: dict, diff: dict,
                     rules: dict, exits: dict[str, str],
                     avg_down_counts: dict[str, int]) -> list[dict]:
    """
    7 条偏离规则 —— 全部确定性布尔判定。
    每条规则无论命中与否都返回一条记录（checked=True），
    这样"没报警"是【被验证过的没报警】，而不是【规则被静默跳过】。
    """
    max_single = float(rules.get("max_single_position_pct", DEFAULT_MAX_SINGLE_PCT))
    min_cash = float(rules.get("min_cash_pct", DEFAULT_MIN_CASH_PCT))
    max_avg_down = int(rules.get("max_averaging_down_times", DEFAULT_MAX_AVG_DOWN))
    rebuy_days = int(rules.get("no_rebuy_after_full_exit_days",
                               DEFAULT_REBUY_WINDOW_DAYS))

    devs: list[dict] = []

    def add(rule_id, severity, hit, detail, tickers=None):
        devs.append({
            "rule_id": rule_id,
            "severity": severity if hit else None,
            "hit": hit,
            "checked": True,
            "tickers": tickers or [],
            "detail": detail,
        })

    # 1. 卖出区仍持有
    sell_held = [h["ticker"] for h in holdings if h["in_sell_zone"]]
    add("sell_zone_still_holding", "high", bool(sell_held),
        f"持仓落在自建卖出区：{', '.join(sell_held)}" if sell_held
        else "无持仓落在卖出区",
        sell_held)

    # 2. 卖出区还加仓（最高级）
    added_t = {a["ticker"] for a in diff.get("added", [])} if diff.get("available") else set()
    sell_added = sorted(added_t & set(sell_held))
    add("adding_in_sell_zone", "critical", bool(sell_added),
        f"在自建卖出区内加仓：{', '.join(sell_added)}" if sell_added
        else ("无卖出区加仓" if diff.get("available") else "跳过（无昨日快照）"),
        sell_added)

    # 3. 新建仓评级为非买入
    bad_new = []
    if diff.get("available"):
        opened = {o["ticker"] for o in diff.get("opened", [])}
        for h in holdings:
            if h["ticker"] in opened and h["rating"]:
                if any(k in str(h["rating"]) for k in NON_BUY_RATINGS):
                    bad_new.append(f'{h["ticker"]}（评级：{h["rating"]}）')
    add("new_position_not_rated_buy", "high", bool(bad_new),
        f"新建仓标的评级非「买入」：{', '.join(bad_new)}" if bad_new
        else ("无此类新建仓" if diff.get("available") else "跳过（无昨日快照）"),
        [b.split("（")[0] for b in bad_new])

    # 4. 清仓后 N 天内回购（GRAL / RKLB 陷阱）
    rebuys = []
    if diff.get("available"):
        opened = {o["ticker"] for o in diff.get("opened", [])}
        for t in sorted(opened & set(exits)):
            rebuys.append(f"{t}（{exits[t]} 清仓）")
    add("rebuy_within_window", "high", bool(rebuys),
        f"清仓后 {rebuy_days} 天内回购：{', '.join(rebuys)}" if rebuys
        else ("无窗口内回购" if diff.get("available") else "跳过（无昨日快照）"),
        [r.split("（")[0] for r in rebuys])

    # 5. 向下摊薄超限（计数已扣除「计划内分批建仓」豁免，见 verdict.scale_in_exemptions）
    over = [f"{t}（已摊 {n} 次，上限 {max_avg_down}）"
            for t, n in sorted(avg_down_counts.items()) if n > max_avg_down]
    add("averaging_down_exceeded", "high", bool(over),
        f"向下摊薄超限：{', '.join(over)}" if over else "无超限摊薄",
        [o.split("（")[0] for o in over])

    # 6. 单票超配
    heavy = [f'{h["ticker"]}（{h["pct_of_total"]}%）'
             for h in holdings
             if (h["pct_of_total"] or 0) > max_single]
    add("position_oversized", "medium", bool(heavy),
        f"单票 > 总资产 {max_single}%：{', '.join(heavy)}" if heavy
        else f"无单票超过总资产 {max_single}%",
        [x.split("（")[0] for x in heavy])

    # 7. 现金不足
    cash_pct = conc.get("cash_pct")
    low_cash = cash_pct is not None and cash_pct < min_cash
    add("cash_below_floor", "medium", low_cash,
        f"现金占比 {cash_pct}% < {min_cash}%（失去接跌能力）" if low_cash
        else f"现金占比 {cash_pct}%，充足",
        [])

    return devs


def check_trigger_staleness(triggers: list[dict], registry: dict,
                            today: date) -> list[dict]:
    """
    扳机时效校验：valuation_snapshot vs 当前台账。
    扳机【绝不】自动跟随估值 —— 只侦测、只报警，要求人工处理。
    见 position_triggers.json 的 _staleness_policy。
    """
    companies = registry.get("companies", {})
    reg_by_norm = {_norm(k): v for k, v in companies.items()}

    out: list[dict] = []
    for tr in triggers:
        if tr.get("status") != "active":
            continue
        t = _norm(tr.get("ticker", ""))
        snap = tr.get("valuation_snapshot") or {}
        reg = reg_by_norm.get(t) or {}

        drift: list[dict] = []
        if snap:
            snap_target = _parse_money(snap.get("target_price"))
            cur_target = _parse_money(reg.get("target_price"))
            if snap_target is not None and cur_target is not None \
                    and abs(snap_target - cur_target) > 1e-6:
                drift.append({"field": "target_price",
                              "was": snap.get("target_price"),
                              "now": reg.get("target_price")})
            s_rate, c_rate = _rating_stem(snap.get("rating")), _rating_stem(reg.get("rating"))
            if s_rate and c_rate and s_rate != c_rate:
                drift.append({"field": "rating", "was": s_rate, "now": c_rate})

        reaff = tr.get("reaffirmed_at") or tr.get("written_at")
        days_stale = None
        if drift and reaff:
            try:
                days_stale = (today - datetime.strptime(reaff, "%Y-%m-%d").date()).days
            except ValueError:
                pass

        out.append({
            "trigger_id": tr.get("id"),
            "ticker": t,
            "has_snapshot": bool(snap),
            "stale": bool(drift),
            "drift": drift,
            "written_at": tr.get("written_at"),
            "reaffirmed_at": tr.get("reaffirmed_at"),
            "registry_updated_at": registry.get("updated_at"),
            "days_since_reaffirm": days_stale,
            "escalate": bool(drift) and (days_stale or 0) >= STALE_ESCALATE_DAYS,
            "action_required": (
                "人工二选一：(A) 按新估值重写扳机价位并写明理由；"
                "(B) 保留原扳机、更新 reaffirmed_at、写明为何估值变了但扳机不变。"
            ) if drift else None,
        })
    return out


def check_acknowledged(triggers_doc: dict, today: date) -> list[dict]:
    """
    已承认、暂缓修复的台账缺陷。

    承认问题 ≠ 解决问题。这些缺陷【依然让规则真实失效】，只是不再当"新发现"喊。
    超过 review_by 未修 → 自动升回红色（expired=True）。
    没有到期日的"暂缓"就是永久遗忘 —— 所以 review_by 是必填。
    """
    out = []
    ack = (triggers_doc.get("acknowledged_issues") or {}).get("items", [])
    for it in ack:
        rb = it.get("review_by")
        days_left = None
        expired = False
        if rb:
            try:
                d = datetime.strptime(rb, "%Y-%m-%d").date()
                days_left = (d - today).days
                expired = days_left < 0
            except ValueError:
                pass
        out.append({
            **{k: it.get(k) for k in
               ("id", "ticker", "issue", "impact", "acknowledged_at",
                "review_by", "plan")},
            "days_left": days_left,
            "expired": expired,
            "severity": "high" if expired else "known",
        })
    return out


def count_overrides(trigger: dict, today: date) -> dict:
    """
    统计扳机被连续推翻的天数。

    系统【不阻止】你推翻自己 —— 你是决策者。
    但它确保你无法【假装没看见】：连推 2 天升级，连推 3 天最高级。
    见 _override_policy 与 _staleness_policy。
    """
    ovs = trigger.get("overrides") or []
    if not ovs:
        return {"n_overrides": 0, "consecutive_days": 0, "escalate": False,
                "last": None, "missing_reason": False}

    dates = []
    for o in ovs:
        try:
            dates.append(datetime.strptime(o["date"], "%Y-%m-%d").date())
        except (KeyError, ValueError):
            continue
    dates.sort()

    # 从最近一次往回数连续（含今天）的交易日推翻次数
    consec = 0
    cur = today
    dset = set(dates)
    while cur in dset:
        consec += 1
        cur -= timedelta(days=1)

    last = ovs[-1]
    reason = str(last.get("reason") or "")
    missing_reason = ("未记录" in reason) or (not reason.strip())

    return {
        "n_overrides": len(ovs),
        "consecutive_days": consec,
        "escalate": consec >= 2,
        "critical": consec >= 3,
        "last": last,
        "missing_reason": missing_reason,
    }


_COND_PRICE = re.compile(
    r"(?:price|close)\s*(>=|<=|>|<)\s*\$?(\d+(?:\.\d+)?)", re.I)


def eval_triggers(triggers: list[dict], holdings: list[dict],
                  today: date) -> list[dict]:
    """
    价格型扳机判定（确定性）。
    事件型扳机（条件里含 CRPO/ARR 等需读财报的）标 type=event，
    交给 LLM 在财报日处理 —— 引擎【不猜】。
    """
    px_by_t = {h["ticker"]: h["last_price"] for h in holdings}
    out: list[dict] = []

    for tr in triggers:
        if tr.get("status") != "active":
            continue
        t = _norm(tr.get("ticker", ""))
        px = px_by_t.get(t)

        conds_out = []
        for c in tr.get("conditions", []) or []:
            expr = str(c.get("if", ""))
            m = _COND_PRICE.search(expr)
            if not m:
                conds_out.append({
                    "if": expr, "then": c.get("then"),
                    "priority": c.get("priority"),
                    "type": "event" if expr.strip().lower() != "always" else "always",
                    "state": "always_on" if expr.strip().lower() == "always"
                             else "needs_human",  # 事件型：引擎不判，LLM 判
                })
                continue

            op, lvl = m.group(1), float(m.group(2))
            hit = near = False
            dist = None
            if px:
                hit = {">=": px >= lvl, "<=": px <= lvl,
                       ">": px > lvl, "<": px < lvl}[op]
                dist = abs(px - lvl) / lvl * 100.0
                near = (not hit) and dist < NEAR_PRICE_PCT
            conds_out.append({
                "if": expr, "then": c.get("then"), "priority": c.get("priority"),
                "type": "price", "level": lvl, "op": op, "price": px,
                "state": "HIT" if hit else ("NEAR" if near else "watching"),
                "distance_pct": round(dist, 2) if dist is not None else None,
            })

        # 事件日临近
        ev_days = None
        ed = tr.get("event_date")
        if ed:
            try:
                ev_days = (datetime.strptime(ed, "%Y-%m-%d").date() - today).days
            except ValueError:
                pass

        hits = [c for c in conds_out if c.get("state") == "HIT"]
        ov = count_overrides(tr, today)
        out.append({
            "trigger_id": tr.get("id"),
            "ticker": t,
            "price": px,
            "event_date": ed,
            "days_to_event": ev_days,
            "event_near": ev_days is not None and 0 <= ev_days <= NEAR_EVENT_DAYS,
            "conditions": conds_out,
            "any_hit": bool(hits),
            "top_priority_hit": min((c.get("priority") or 9) for c in hits) if hits else None,
            "watch_metrics": tr.get("watch_metrics"),
            "until_then": tr.get("until_then"),
            "override": ov,
            # 命中了、且历史上被推翻过 → 这是"明知故犯"的状态，必须显式暴露
            "hit_but_overridden": bool(hits) and ov["n_overrides"] > 0,
        })
    return out


# ---------------------------------------------------------------- main

def build_verdict(root: Path, positions_doc: dict, today: date,
                  strict: bool) -> dict:
    reg = _load_json(root / "_system" / "valuation_registry.json", "valuation_registry")
    trg = _load_json(root / "_system" / "position_triggers.json", "position_triggers")

    integrity = check_integrity(trg)

    bf_path = root / "_system" / "daily_briefing" / f"briefing_data_{today.isoformat()}.json"
    briefing = None
    briefing_date = None
    if bf_path.exists():
        briefing = _load_json(bf_path, "briefing_data")
        briefing_date = briefing.get("date")
    else:
        cands = sorted((root / "_system" / "daily_briefing").glob("briefing_data_*.json"))
        if cands:
            briefing = _load_json(cands[-1], "briefing_data(fallback)")
            briefing_date = briefing.get("date")
    if strict and briefing_date != today.isoformat():
        raise IntegrityError(
            f"--strict：briefing_data 日期 {briefing_date} ≠ 今日 {today}（scanner 未跑？）")

    positions = positions_doc.get("positions", [])
    cash = float(positions_doc.get("cash") or 0)
    if not positions:
        raise IntegrityError("positions 为空 —— 拒绝产出 verdict（绝不猜测持仓）")

    oos = (trg.get("out_of_scope") or {}).get("tickers", {})
    oos = {_norm(k): v for k, v in oos.items()}
    holdings, conc = enrich_holdings(positions, cash, reg, briefing, oos)

    pos_dir = root / "_system" / "positions"
    pos_dir.mkdir(parents=True, exist_ok=True)

    # 昨日快照
    prev = None
    prev_files = sorted(p for p in pos_dir.glob("snapshot_*.json")
                        if today.isoformat() not in p.name)
    if prev_files:
        prev = _load_json(prev_files[-1], f"昨日快照 {prev_files[-1].name}")

    diff = diff_snapshot(holdings, prev)

    rules = trg.get("portfolio_rules") or {}
    rebuy_days = int(rules.get("no_rebuy_after_full_exit_days", DEFAULT_REBUY_WINDOW_DAYS))
    exits = load_exit_history(pos_dir, today, rebuy_days)

    # 「计划内分批建仓」豁免（四条全中才豁免，fail-closed）
    scale_in_exemptions = check_scale_in_exemptions(
        diff, holdings, trg.get("scale_in_plans") or {}, today,
        float(rules.get("scale_in_default_target_pct",
                        DEFAULT_SCALE_IN_TARGET_PCT)))
    exempt_today = {e["ticker"] for e in scale_in_exemptions if e["exempt"]}

    # 累计摊薄次数（含今日）
    #   avg_down_counts     —— 【计入规则】的次数，已扣除豁免
    #   avg_down_counts_raw —— 事实流水，不扣豁免，仅作审计留痕
    avg_down_counts: dict[str, int] = dict(
        (prev or {}).get("avg_down_counts", {}) if prev else {})
    avg_down_counts_raw: dict[str, int] = dict(
        (prev or {}).get("avg_down_counts_raw", avg_down_counts) if prev else {})
    # 2026-09-20 新增：单日减仓 ≥ avg_down_reset_trim_pct（默认 50%）→ 该票摊薄计数清零。
    # 理由：砍掉一半以上再买，是新一轮决策，不是"跌了补一点"（RKLB 8/7 140→40 先例）。
    # 门槛防漏洞：卖 1 股不能清零。清零动作逐笔记在 avg_down_resets 供审计。
    reset_pct = float(rules.get("avg_down_reset_trim_pct", DEFAULT_AVG_DOWN_RESET_TRIM_PCT))
    avg_down_resets: list[dict] = []
    for tr_ in diff.get("trimmed", []) or []:
        t = tr_["ticker"]
        tp = tr_.get("trim_pct")
        if tp is not None and tp >= reset_pct and (
                avg_down_counts.get(t) or avg_down_counts_raw.get(t)):
            avg_down_resets.append({"ticker": t, "trim_pct": tp,
                                    "count_before": avg_down_counts.get(t, 0),
                                    "raw_before": avg_down_counts_raw.get(t, 0)})
            avg_down_counts.pop(t, None)
            avg_down_counts_raw.pop(t, None)
    for a in diff.get("averaged_down", []) or []:
        t = a["ticker"]
        avg_down_counts_raw[t] = avg_down_counts_raw.get(t, 0) + 1
        if t not in exempt_today:
            avg_down_counts[t] = avg_down_counts.get(t, 0) + 1

    devs = check_deviations(holdings, conc, diff, rules, exits, avg_down_counts)
    stale = check_trigger_staleness(trg.get("triggers", []), reg, today)
    trig = eval_triggers(trg.get("triggers", []), holdings, today)
    acknowledged = check_acknowledged(trg, today)

    # 已承认的区间裂缝 → 从"新发现"降级为"已知待修"，但绝不隐藏
    ack_tickers = {a["ticker"] for a in acknowledged if not a["expired"]}
    for g in conc["price_in_zone_gap"]:
        g["acknowledged"] = g["ticker"] in ack_tickers

    verdict = {
        "schema_version": SCHEMA_VERSION,
        "date": today.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine": "position_guard.py",
        "inputs": {
            "briefing_date": briefing_date,
            "registry_updated_at": reg.get("updated_at"),
            "triggers_updated_at": trg.get("updated_at"),
            "prev_snapshot": prev.get("date") if prev else None,
        },
        "integrity": integrity,
        "concentration": conc,
        "holdings": holdings,
        "diff": diff,
        "deviations": devs,
        "scale_in_exemptions": scale_in_exemptions,
        "avg_down_counts": avg_down_counts,
        "avg_down_counts_raw": avg_down_counts_raw,
        "avg_down_resets": avg_down_resets,
        "deviation_summary": {
            "n_checked": len(devs),
            "n_hit": sum(1 for d in devs if d["hit"]),
            "critical": [d["rule_id"] for d in devs
                         if d["hit"] and d["severity"] == "critical"],
            "high": [d["rule_id"] for d in devs
                     if d["hit"] and d["severity"] == "high"],
        },
        "trigger_staleness": stale,
        "triggers": trig,
        "trigger_summary": {
            "n_active": len(trig),
            "hits": [t["trigger_id"] for t in trig if t["any_hit"]],
            "stale": [s["trigger_id"] for s in stale if s["stale"]],
            "escalated": [s["trigger_id"] for s in stale if s["escalate"]],
            "overridden": [t["trigger_id"] for t in trig if t["hit_but_overridden"]],
            "override_escalate": [t["trigger_id"] for t in trig
                                  if t["override"]["escalate"]],
            "override_missing_reason": [t["trigger_id"] for t in trig
                                        if t["override"]["missing_reason"]],
        },
        "acknowledged": acknowledged,
        "acknowledged_summary": {
            "n": len(acknowledged),
            "expired": [a["id"] for a in acknowledged if a["expired"]],
        },
    }

    # 写今日快照（供次日 diff）—— 引擎唯一被允许写的状态文件
    snap = {
        "date": today.isoformat(),
        "cash": cash,
        "holdings": [{"ticker": h["ticker"], "qty": h["qty"],
                      "avg_cost": h["avg_cost"]} for h in holdings],
        "avg_down_counts": avg_down_counts,
        "avg_down_counts_raw": avg_down_counts_raw,
        "avg_down_resets": avg_down_resets,
    }
    (pos_dir / f"snapshot_{today.isoformat()}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    return verdict


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="持仓纪律引擎（确定性判定）")
    ap.add_argument("--positions", required=True,
                    help="持仓 JSON（由 advisor 从 IBKR MCP 取回后写入）")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--root", default=".", help="Projects 根目录")
    ap.add_argument("--out", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="要求 briefing_data 是今日，否则失败")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    today = datetime.strptime(args.date, "%Y-%m-%d").date()
    pos_doc = _load_json(Path(args.positions), "positions")

    try:
        v = build_verdict(root, pos_doc, today, args.strict)
    except IntegrityError as e:
        print(f"\n❌ INTEGRITY FAILURE — 拒绝产出 verdict\n{e}\n", file=sys.stderr)
        print("VERDICT_JSON " + json.dumps(
            {"ok": False, "error": str(e)}, ensure_ascii=False))
        return 2

    out = Path(args.out) if args.out else \
        root / "_system" / "positions" / f"guard_verdict_{args.date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")

    ds, ts = v["deviation_summary"], v["trigger_summary"]
    conc = v["concentration"]
    print(f"✅ verdict → {out}")
    print(f"   偏离：{ds['n_hit']}/{ds['n_checked']} 命中"
          f"（critical={len(ds['critical'])} high={len(ds['high'])}）")
    print(f"   扳机：{len(ts['hits'])} 命中 / {len(ts['stale'])} 过期"
          f" / {len(ts['escalated'])} 需升级")
    if conc["uncovered"]:
        print(f"   ⚠️ 无估值覆盖（疏漏）：{conc['uncovered']}")
    if conc["zone_unresolved"]:
        print(f"   ⚠️ 区间未能归类：{conc['zone_unresolved']}")
    for g in conc["price_in_zone_gap"]:
        mark = "⚠️ 已知待修" if g.get("acknowledged") else "🔴 新发现"
        print(f"   {mark} {g['ticker']} 现价 {g['price']} 掉进区间裂缝"
              f"（{g['gap_low']}–{g['gap_high']}）→ 卖出区规则对该票仍然失效")
    if conc["out_of_scope"]:
        print(f"   ℹ️ 刻意不覆盖（无纪律约束）："
              f"{[x['ticker'] for x in conc['out_of_scope']]}")
    for ack in v["acknowledged"]:
        if ack["expired"]:
            print(f"   🔴 已承认问题【逾期未修】：{ack['id']}"
                  f"（review_by {ack['review_by']}，已过期 {-ack['days_left']} 天）")
    if ts["overridden"]:
        print(f"   ⚠️ 命中但被推翻：{ts['overridden']}")
    if ts["override_escalate"]:
        print(f"   🔴 连续推翻同一扳机 ≥2 天：{ts['override_escalate']}"
              f" —— 这条扳机要么定错了，要么你在骗自己")
    if ts["override_missing_reason"]:
        print(f"   ⚠️ 推翻未记录理由：{ts['override_missing_reason']}")
    if not v["integrity"]["count_check_verified"]:
        print("   ⚠️ position_triggers.json 未声明 _integrity，无法做计数校验")

    print("VERDICT_JSON " + json.dumps({
        "ok": True,
        "deviations_hit": ds["n_hit"],
        "critical": ds["critical"],
        "high": ds["high"],
        "trigger_hits": ts["hits"],
        "trigger_stale": ts["stale"],
        "overridden": ts["overridden"],
        "acknowledged_expired": v["acknowledged_summary"]["expired"],
        "verdict_path": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
