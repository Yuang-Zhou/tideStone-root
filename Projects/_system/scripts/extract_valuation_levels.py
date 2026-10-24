#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_valuation_levels.py -- derive plain-number price lines from valuation_registry.json.

Why: valuation_registry.json keeps zones as free text ("<= $339 (target x 75%...)").
The daily scanner needs plain numbers to decide the valuation zone mechanically.
This script reads the registry (never writes it) and writes _system/valuation_levels.json:

  { ticker: { currency, buy_below, reduce_above, sell_above, target,
              flags: [...], confirmed: bool, source_hash } }

Zone rule used by the scanner (price = latest close):
  price <= buy_below            -> buy
  price >= sell_above           -> sell
  price >= reduce_above         -> reduce
  otherwise                     -> hold
  any of the lines missing      -> unrated

Re-run after any valuation change. Entries whose source text changed lose `confirmed`.
Manual fixes go in _system/valuation_levels_overrides.json (same keys, wins over parsing).

Usage: python3 _system/scripts/extract_valuation_levels.py [--zone-check]
"""
import json, os, re, sys, hashlib, datetime

from tidestone_paths import SYSTEM_DIR
ROOT = str(SYSTEM_DIR)
REG = os.path.join(ROOT, "valuation_registry.json")
OUT = os.path.join(ROOT, "valuation_levels.json")
OVR = os.path.join(ROOT, "valuation_levels_overrides.json")

IGNORE = ("改锚", "地板", "止损", "再评估", "结构", "基准日", "Forward", "风险", "切换目标")
BUY = ("买入", "建仓", "加仓", "低估", "深度价值", "左侧分批", "增持")
SELL = ("卖出", "回避", "透支", "清仓", "高估")
REDUCE = ("减持", "减仓", "减配", "轻减")
STRONG_REDUCE = ("强减持", "主动减仓", "强力卖出", "强烈卖出")


def nums(s):
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", s)]


def head(rng):
    return re.split(r"[（(｜|；;。]", rng, 1)[0]


def bounds(rng):
    """return (lower, upper) parsed from the leading part of a zone range"""
    h = head(str(rng))
    n = nums(h)
    if not n:
        return None, None
    if re.search(r"≤|<=|<|以下", h) and len(n) == 1:
        return None, n[0]
    if re.search(r"≥|>=|>|以上", h) and len(n) == 1:
        return n[0], None
    if len(n) >= 2:
        return n[0], n[1]
    return None, None


def derive(entry):
    flags = []
    buy_up, red_lo, sell_lo = [], [], []
    for z in entry.get("zones") or []:
        lab = str(z.get("label") or "")
        if not lab or lab == "None" or any(k in lab for k in IGNORE):
            continue
        lo, up = bounds(z.get("range"))
        is_buy = any(k in lab for k in BUY)
        is_sell = any(k in lab for k in SELL) or any(k in lab for k in STRONG_REDUCE)
        is_red = any(k in lab for k in REDUCE)
        if is_buy and not (is_sell or is_red):
            if up is not None:
                buy_up.append(up)
        else:
            if is_red and lo is not None:
                red_lo.append(lo)
            if is_sell and lo is not None:
                sell_lo.append(lo)
    buy_below = max(buy_up) if buy_up else None
    allr = red_lo + sell_lo
    reduce_above = min(allr) if allr else None
    pure_sell = [x for x in sell_lo]
    if pure_sell:
        sell_above = min(pure_sell) if not red_lo else max(min(pure_sell), reduce_above)
    elif len(red_lo) >= 2:
        sell_above = max(red_lo)
    else:
        sell_above = reduce_above
    sv = entry.get("scenario_valuation") or {}
    dom = sv.get("dominant")
    target = None
    if dom and (sv.get("scenarios") or {}).get(dom, {}).get("price") is not None:
        target = float(sv["scenarios"][dom]["price"])
    else:
        n = nums(head(str(entry.get("target_price") or "")))
        target = n[0] if n else None
    if buy_below is None: flags.append("no_buy_line")
    if reduce_above is None: flags.append("no_sell_line")
    if target is None: flags.append("no_target")
    if buy_below is not None and reduce_above is not None and buy_below > reduce_above:
        flags.append("buy_line_above_sell_line")
    if target is not None and buy_below is not None and target < buy_below:
        flags.append("target_below_buy_line")
    if target is not None and sell_above is not None and target > sell_above:
        flags.append("target_above_sell_line")
    src = json.dumps([entry.get("zones"), entry.get("target_price"), dom], ensure_ascii=False, sort_keys=True)
    return {
        "currency": entry.get("currency"),
        "buy_below": buy_below, "reduce_above": reduce_above, "sell_above": sell_above,
        "target": target, "dominant": dom, "flags": flags,
        "source_hash": hashlib.md5(src.encode("utf-8")).hexdigest()[:12],
    }


def zone_of(price, lv):
    b, r, s = lv.get("buy_below"), lv.get("reduce_above"), lv.get("sell_above")
    if price is None or b is None or r is None or s is None:
        return "未标定"
    if price <= b: return "买入区"
    if price >= s: return "卖出区"
    if price >= r: return "减持区"
    return "持有区"


def main():
    reg = json.load(open(REG, encoding="utf-8"))["companies"]
    old = json.load(open(OUT, encoding="utf-8")).get("levels", {}) if os.path.exists(OUT) else {}
    ovr = json.load(open(OVR, encoding="utf-8")) if os.path.exists(OVR) else {}
    out = {}
    for t, e in reg.items():
        lv = derive(e)
        o = ovr.get(t) or {}
        for k in ("buy_below", "reduce_above", "sell_above", "target"):
            if k in o:
                lv[k] = o[k]
        if o:
            lv["override_note"] = o.get("note", "")
            lv["flags"] = [f for f in lv["flags"] if f not in (o.get("clear_flags") or [])]
            if None not in (lv["buy_below"], lv["reduce_above"], lv["sell_above"], lv["target"]):
                lv["flags"] = [f for f in lv["flags"] if not f.startswith("no_")]
        prev = old.get(t) or {}
        lv["confirmed"] = bool(prev.get("confirmed")) and prev.get("source_hash") == lv["source_hash"] \
            and all(prev.get(k) == lv[k] for k in ("buy_below", "reduce_above", "sell_above", "target"))
        out[t] = lv
    doc = {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "rule": "price<=buy_below 买入区; >=sell_above 卖出区; >=reduce_above 减持区; else 持有区; 缺线=未标定",
           "levels": out}
    tmp = OUT + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    if "--zone-check" in sys.argv:
        man = json.load(open(os.path.join(ROOT, "market_data", "_data_status.json"), encoding="utf-8"))["tickers"]
        for t, lv in out.items():
            p = (man.get(t) or {}).get("last_row", {}).get("close")
            r = (p / lv["target"]) if p and lv["target"] else None
            print("%-10s %9s | buy<=%-8s reduce>=%-8s sell>=%-8s target %-8s | %s | x%s | %s" % (
                t, p, lv["buy_below"], lv["reduce_above"], lv["sell_above"], lv["target"],
                zone_of(p, lv), ("%.2f" % r) if r else "-", ",".join(lv["flags"])))
    keys = ("buy_below", "reduce_above", "sell_above", "target", "flags")
    changed = [t for t, v in out.items() if t in old and any(old[t].get(k) != v.get(k) for k in keys)]
    added = [t for t in out if t not in old] if old else []
    print("LEVELS_JSON " + json.dumps({"n": len(out), "changed_since_last_run": changed, "new_tickers": added,
                                        "flagged": [t for t, v in out.items() if v["flags"]],
                                        "unconfirmed": sum(1 for v in out.values() if not v["confirmed"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()

