#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_portfolio.py — 「低估 + 长期增长」策略模拟盘（Paper Portfolio Monitor）

设计（2026-09-30）：
  选股池：valuation_registry 里已打分（有三情景价 + 主导情景判定 + 计分 rationale）的公司。
  入选：主导情景 = 基准；现价→基准价上行 ≥ min_upside；跌到悲观价空间 ≤ max_downside_to_bear；
        三年目标价年化 ≥ min_cagr_3y；行情不陈旧。
  退出（迟滞）：已持仓的票只在上行 < exit_upside（价格逼近目标）或三年年化 < exit_cagr 或 主导切换 时清仓，
        避免在门槛附近每天进进出出。
  仓位（sizing）："equal" = 入选标的等权：每票 = min(max_gross / N, max_weight)
                  "risk_reward" = 按 b = 上行/下行 比例分配 max_gross，单票 ≤ max_weight
        下行 = 1 − 悲观价/现价，有 downside_floor 地板（现价已低于悲观价时用地板）；不满足入选条件权重 = 0
  调仓：每日重算目标权重；|目标−当前| > rebalance_band 才交易；目标 0 且持仓 → 清仓。
        成交按当日（或最近一个）收盘价 × (1 ± slippage)。A/H 股按 100 股整手。
  跟踪：nav_history.csv（净值 vs SPX）、ledger.csv（每笔交易 + 触发规则）、daily/{date}.json、dashboard.html

只用标准库。从 Projects 根目录运行：
  python _system/scripts/paper_portfolio.py                 # 跑当天（同日重跑只重估净值，不重复交易、不改 ledger）
  python _system/scripts/paper_portfolio.py --date 2026-10-01
  python _system/scripts/paper_portfolio.py --init          # 重新初始化（清空 state/ledger/nav）
  python _system/scripts/paper_portfolio.py --dry-run       # 只算不写
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------------
# 默认配置（写入 _system/paper_portfolio/config.json 后以文件为准）
# ----------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "name": "低估+增长 策略模拟盘",
    "start_date": "2026-09-30",
    "start_capital_usd": 126376.38,
    "benchmark": "SPX",
    # 入选门槛
    "min_upside_to_base": 0.25,      # 入场门槛
    "min_cagr_3y": 0.15,             # 入场门槛
    "max_downside_to_bear": 0.30,    # 入场门槛：现价跌到悲观价的空间 ≤30%（"便宜"＝离地板近）；设 1.0 关闭
    "exit_upside_to_base": 0.10,     # 已持仓：上行缩到 <10%（接近目标价）才退出
    "exit_cagr_3y": 0.12,            # 已持仓：三年年化 <12% 才退出（迟滞，防门槛附近来回抖）
    "require_dominant": ["base"],
    "max_price_staleness_days": 7,   # 估值/入选用：超过即视为无效行情
    # 成交用（2026-10-03）：只用"新鲜"收盘价成交——价格不超过 N 个自然日（周一北京时间看上周五 = 3 天），
    # 且不落后于本市场参考指数的最新交易日（单票拉取失败时指数是新的、个股是旧的）。否则当天只重估、不交易。
    "max_trade_staleness_days": 3,
    "market_ref_index": {"USD": "SPX", "HKD": "HSI", "CNY": "CSI300"},
    # 仓位
    "sizing": "equal",               # equal | risk_reward
    "downside_floor": 0.10,
    "max_weight": 0.15,
    "max_gross": 0.80,
    # 交易
    "rebalance_band": 0.03,
    "slippage": 0.001,
    "lot_size": {"CNY": 100, "HKD": 100, "USD": 1},
    # 汇率（USD 计价；本地无汇率源，先用常数，每月手动核一次）
    "fx_to_usd": {"USD": 1.0, "CNY": 0.1408, "HKD": 0.1282},
    # 排除（不在策略框架内的票）
    "exclude": [],
}

SCORE_RE = re.compile(r"基准\s*([\d.]+)\s*/\s*([\d.]+)")
NUM_RE = re.compile(r"[\d,]+\.?\d*")


# ----------------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------------
def detect_projects_root(start: Path) -> Path:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "_system" / "valuation_registry.json").exists():
            return cand
    raise SystemExit("找不到 Projects 根目录（需含 _system/valuation_registry.json）")


def load_json(p: Path, default=None):
    if not p.exists():
        return default
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(p)


def num(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("¥", "").replace("HK$", "").replace("$", "").replace("元", "")
    m = NUM_RE.search(s)
    return float(m.group().replace(",", "")) if m else None


def last_close_on_or_before(csv_path: Path, d: date):
    """返回 (日期, 收盘价)；找不到返回 (None, None)。"""
    if not csv_path.exists():
        return None, None
    best = (None, None)
    with csv_path.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                rd = date.fromisoformat(row["date"][:10])
                c = float(row["close"])
            except Exception:
                continue
            if rd <= d and (best[0] is None or rd > best[0]):
                best = (rd, c)
    return best


# ----------------------------------------------------------------------------
# 候选评估
# ----------------------------------------------------------------------------
@dataclass
class Candidate:
    ticker: str
    name: str
    currency: str
    price: Optional[float]
    price_date: Optional[str]
    base: Optional[float]
    bear: Optional[float]
    bull: Optional[float]
    dominant: Optional[str]
    confidence: Optional[str]
    p_raw: Optional[float]
    p: Optional[float]
    upside: Optional[float]
    downside: Optional[float]
    b: Optional[float]
    cagr_3y: Optional[float]
    rr: Optional[float]
    target_weight: float
    eligible: bool
    reason: str


def evaluate(ticker: str, c: dict, t3: dict, cfg: dict, root: Path, d: date, held: bool = False) -> Candidate:
    s = c.get("scenario_valuation") or {}
    sc = s.get("scenarios") or {}
    base = num((sc.get("base") or {}).get("price"))
    bear = num((sc.get("bear") or {}).get("price"))
    bull = num((sc.get("bull") or {}).get("price"))
    dom = s.get("dominant")
    conf = s.get("confidence")
    ccy = c.get("currency") or "USD"
    name = (c.get("name") or ticker)[:24]

    pd_, px = last_close_on_or_before(root / "_system" / "market_data" / f"{ticker}.csv", d)
    p3 = (t3.get(ticker) or {}).get("target_price_3y")
    cagr = None
    if p3 and px and px > 0:
        cagr = (float(p3) / px) ** (1 / 3) - 1

    m = SCORE_RE.search(s.get("rationale") or "")
    p_raw = None
    if m:
        a, bb = float(m.group(1)), float(m.group(2))
        if bb > 0:
            p_raw = a / bb

    def out(elig, reason, p=None, up=None, dn=None, b=None, w=0.0):
        return Candidate(ticker, name, ccy, px, pd_.isoformat() if pd_ else None, base, bear, bull,
                         dom, conf, p_raw, p, up, dn, b, cagr, b, w, elig, reason)

    if ticker in cfg["exclude"]:
        return out(False, "配置排除")
    if not (base and bear):
        return out(False, "无三情景价")
    if dom not in cfg["require_dominant"]:
        return out(False, f"主导情景={dom}")
    if px is None:
        return out(False, "无行情")
    if (d - pd_).days > cfg["max_price_staleness_days"]:
        return out(False, f"行情陈旧 {pd_}")
    if px <= 0:
        return out(False, "价格异常")

    up = base / px - 1
    dn = max(1 - bear / px, cfg["downside_floor"])
    p = p_raw
    b = up / dn if dn > 0 else None

    if not held and dn > cfg["max_downside_to_bear"]:
        return out(False, f"跌到悲观价空间 {dn:.0%} > {cfg['max_downside_to_bear']:.0%}", p, up, dn, None)
    up_th = cfg["exit_upside_to_base"] if held else cfg["min_upside_to_base"]
    cg_th = cfg["exit_cagr_3y"] if held else cfg["min_cagr_3y"]
    if up < up_th:
        return out(False, f"上行 {up:.0%} < {up_th:.0%}" + ("（持仓退出线）" if held else ""), p, up, dn, b)
    if cagr is None:
        return out(False, "无三年目标价", p, up, dn, b)
    if cagr < cg_th:
        return out(False, f"三年年化 {cagr:.0%} < {cg_th:.0%}" + ("（持仓退出线）" if held else ""), p, up, dn, b)

    if not b or b <= 0:
        return out(False, "上行/下行比 ≤ 0", p, up, dn, b)
    # 权重在 run() 里按 sizing 统一分配（需要知道入选总数）
    return out(True, "持有" if held else "入选", p, up, dn, b, 0.0)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def run(root: Path, d: date, init: bool, dry: bool) -> int:
    pdir = root / "_system" / "paper_portfolio"
    pdir.mkdir(parents=True, exist_ok=True)
    cfg_path = pdir / "config.json"
    cfg = load_json(cfg_path)
    if cfg is None:
        cfg = DEFAULT_CONFIG
        if not dry:
            save_json(cfg_path, cfg)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)

    state_path = pdir / "state.json"
    ledger_path = pdir / "ledger.csv"
    nav_path = pdir / "nav_history.csv"

    state = load_json(state_path)
    if init or state is None:
        state = {"cash_usd": float(cfg["start_capital_usd"]), "holdings": {}, "start_date": d.isoformat(),
                 "last_run": None}
        if not dry:
            for p in (ledger_path, nav_path):
                if p.exists():
                    p.unlink()
            for p in (pdir / "daily").glob("*.json"):
                p.unlink()

    reg = load_json(root / "_system" / "valuation_registry.json")["companies"]
    t3 = load_json(root / "_system" / "three_year_valuation_registry.json", {}).get("companies", {})
    fx = cfg["fx_to_usd"]

    # 1) 评估全池
    cands: dict[str, Candidate] = {}
    for tk, c in reg.items():
        if c.get("status") != "active":
            continue
        cands[tk] = evaluate(tk, c, t3, cfg, root, d, held=tk in state["holdings"])

    # 持仓里如果有票已不在 registry / 无行情，用上次成交价估值并标记
    for tk, h in state["holdings"].items():
        if tk not in cands:
            cands[tk] = Candidate(tk, tk, h["currency"], None, None, None, None, None, None, None, None, None,
                                  None, None, None, None, 0.0, 0.0, False, "已出库")

    # 2) 目标权重
    elig = {tk: c for tk, c in cands.items() if c.eligible}
    if elig:
        if cfg["sizing"] == "risk_reward":
            tot = sum(c.rr for c in elig.values())
            for c in elig.values():
                c.target_weight = min(cfg["max_weight"], cfg["max_gross"] * c.rr / tot)
        else:  # equal
            w = min(cfg["max_weight"], cfg["max_gross"] / len(elig))
            for c in elig.values():
                c.target_weight = w

    # 3) 估值当前组合
    def px_usd(tk: str) -> Optional[float]:
        c = cands[tk]
        if c.price is None:
            h = state["holdings"].get(tk)
            return h["last_px_usd"] if h else None
        return c.price * fx.get(c.currency, 1.0)

    equity = 0.0
    for tk, h in state["holdings"].items():
        p = px_usd(tk)
        if p is not None:
            h["last_px_usd"] = p
        equity += h["qty"] * h["last_px_usd"]
    nav = state["cash_usd"] + equity

    # 4) 交易 —— 每个日期只做一次交易判定；同日重跑只重估、不重交易、不动 ledger
    #    （2026-10-02 修复：旧逻辑"同日重跑先删当日成交行再重算"会在持仓已建好的情况下把当日成交删空）
    #    例外（2026-10-03）：若当天早先一次运行因旧价拦下了交易（trade_blocked_date=今天），
    #    行情补齐后的同日重跑允许再做一次交易判定；已成交的票已在目标附近，调仓带会挡住重复成交。
    already_traded_today = ((state.get("last_run") == d.isoformat()) and not init
                            and state.get("trade_blocked_date") != d.isoformat())

    # 成交价新鲜度闸门（2026-10-03，修 9/30 用 9/25 旧收盘成交的问题）
    ref_dates = {}
    for ccy, idx in cfg["market_ref_index"].items():
        rd, _ = last_close_on_or_before(root / "_system" / "market_data" / "indices" / f"{idx}.csv", d)
        ref_dates[ccy] = rd

    def trade_block_reason(c: Candidate) -> Optional[str]:
        if not c.price_date:
            return "无行情日期"
        pdt = date.fromisoformat(c.price_date)
        age = (d - pdt).days
        if age > cfg["max_trade_staleness_days"]:
            return f"价格停在 {pdt}（{age} 天前 > {cfg['max_trade_staleness_days']}）"
        rd = ref_dates.get(c.currency)
        if rd and pdt < rd:
            return f"价格 {pdt} 落后于市场最新交易日 {rd}"
        return None

    blocked = []
    trades = []
    band = cfg["rebalance_band"]
    slip = cfg["slippage"]

    def cur_w(tk):
        h = state["holdings"].get(tk)
        return (h["qty"] * h["last_px_usd"] / nav) if h else 0.0

    # 先卖后买
    order = [] if already_traded_today else sorted(cands.keys(), key=lambda t: cands[t].target_weight - cur_w(t))
    for tk in order:
        c = cands[tk]
        w_now, w_tgt = cur_w(tk), c.target_weight
        diff = w_tgt - w_now
        h = state["holdings"].get(tk)
        if c.price is None:
            continue  # 无行情不交易
        pusd = c.price * fx.get(c.currency, 1.0)
        lot = cfg["lot_size"].get(c.currency, 1)

        if h and w_tgt == 0:
            qty = h["qty"]
            reason = f"退出：{c.reason}"
        elif abs(diff) <= band:
            continue
        else:
            qty = (abs(diff) * nav) / pusd
            qty = math.floor(qty / lot) * lot
            if qty <= 0:
                continue
            if diff > 0 and (qty * pusd * (1 + slip)) > state["cash_usd"]:
                qty = math.floor((state["cash_usd"] / (pusd * (1 + slip))) / lot) * lot
                if qty <= 0:
                    continue
            if diff < 0 and h:
                qty = min(qty, h["qty"])
            reason = ("建仓/加仓" if diff > 0 else "减仓") + f"：目标 {w_tgt:.1%} vs 当前 {w_now:.1%}"

        why = trade_block_reason(c)
        if why:
            blocked.append(f"{'BUY' if diff > 0 else 'SELL'} {tk}：{why}")
            continue

        side = "BUY" if diff > 0 else "SELL"
        fill = pusd * (1 + slip if side == "BUY" else 1 - slip)
        amt = qty * fill
        if side == "BUY":
            state["cash_usd"] -= amt
            if h:
                tot = h["qty"] + qty
                h["avg_cost_usd"] = (h["avg_cost_usd"] * h["qty"] + fill * qty) / tot
                h["qty"] = tot
            else:
                state["holdings"][tk] = {"qty": qty, "avg_cost_usd": fill, "currency": c.currency,
                                         "entered": d.isoformat(), "last_px_usd": pusd}
        else:
            state["cash_usd"] += amt
            h["qty"] -= qty
            if h["qty"] <= 0:
                del state["holdings"][tk]
        trades.append({"date": d.isoformat(), "ticker": tk, "side": side, "qty": qty,
                       "price_local": round(c.price, 4), "currency": c.currency,
                       "fill_usd": round(fill, 4), "amount_usd": round(amt, 2), "reason": reason})

    if not already_traded_today:
        if blocked:
            state["trade_blocked_date"] = d.isoformat()
        else:
            state.pop("trade_blocked_date", None)

    # 5) 重估
    equity = sum(h["qty"] * h["last_px_usd"] for h in state["holdings"].values())
    nav = state["cash_usd"] + equity
    state["last_run"] = d.isoformat()

    # 基准
    bd, bpx = last_close_on_or_before(root / "_system" / "market_data" / "indices" / f"{cfg['benchmark']}.csv", d)

    # 6) 写文件
    hold_rows = []
    for tk, h in sorted(state["holdings"].items(), key=lambda kv: -kv[1]["qty"] * kv[1]["last_px_usd"]):
        c = cands[tk]
        mv = h["qty"] * h["last_px_usd"]
        hold_rows.append({"ticker": tk, "name": c.name, "qty": h["qty"], "currency": h["currency"],
                          "price_local": c.price, "price_date": c.price_date,
                          "mv_usd": round(mv, 2), "weight": round(mv / nav, 4),
                          "target_weight": round(c.target_weight, 4),
                          "avg_cost_usd": round(h["avg_cost_usd"], 4),
                          "pnl_pct": round(h["last_px_usd"] / h["avg_cost_usd"] - 1, 4),
                          "b": c.b,
                          "upside": c.upside, "downside": c.downside, "cagr_3y": c.cagr_3y,
                          "entered": h["entered"], "status": c.reason})

    daily = {"date": d.isoformat(), "nav_usd": round(nav, 2), "cash_usd": round(state["cash_usd"], 2),
             "equity_usd": round(equity, 2), "benchmark": cfg["benchmark"], "benchmark_close": bpx,
             "benchmark_date": bd.isoformat() if bd else None,
             "trades": trades, "holdings": hold_rows,
             "candidates": [asdict(c) for c in sorted(cands.values(), key=lambda c: -c.target_weight)]}

    if dry:
        for b in blocked:
            print(f"[paper] blocked {b}")
        print(json.dumps({k: v for k, v in daily.items() if k != "candidates"}, ensure_ascii=False, indent=2))
        return 0

    save_json(state_path, state)
    save_json(pdir / "daily" / f"{d.isoformat()}.json", daily)

    # ledger 只追加，从不删行（同日重跑 trades 为空，账本原样保留）
    rows = []
    if ledger_path.exists():
        with ledger_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    rows.extend(trades)
    with ledger_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "ticker", "side", "qty", "price_local", "currency",
                                          "fill_usd", "amount_usd", "reason"])
        w.writeheader()
        w.writerows(rows)

    # nav 历史
    navs = []
    if nav_path.exists():
        with nav_path.open(encoding="utf-8", newline="") as f:
            navs = [r for r in csv.DictReader(f) if r["date"] != d.isoformat()]
    navs.append({"date": d.isoformat(), "nav_usd": f"{nav:.2f}", "cash_usd": f"{state['cash_usd']:.2f}",
                 "equity_usd": f"{equity:.2f}", "n_positions": len(state["holdings"]),
                 "benchmark_close": f"{bpx:.2f}" if bpx else ""})
    navs.sort(key=lambda r: r["date"])
    with nav_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "nav_usd", "cash_usd", "equity_usd", "n_positions",
                                          "benchmark_close"])
        w.writeheader()
        w.writerows(navs)

    write_dashboard(pdir, cfg, navs, rows, daily)

    # 摘要行（供定时任务读取）：asof=本次记账日期；px_asof=持仓里最旧的价格日期；stale=价格超过 staleness 天数的持仓数
    start_cap = float(cfg["start_capital_usd"])
    peak, mdd = 0.0, 0.0
    for r in navs:
        v = float(r["nav_usd"]) / start_cap
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    px_dates = [cands[tk].price_date for tk in state["holdings"] if cands[tk].price_date]
    stale = sum(1 for tk in state["holdings"] if cands[tk].price_date is None
                or (d - date.fromisoformat(cands[tk].price_date)).days > cfg["max_price_staleness_days"])
    bm_ret = None
    if navs and navs[0]["benchmark_close"] and bpx:
        bm_ret = bpx / float(navs[0]["benchmark_close"]) - 1
    summary = {"asof": d.isoformat(), "px_asof": min(px_dates) if px_dates else None, "days": len(navs),
               "nav": round(nav, 2), "ret": round(nav / start_cap - 1, 4),
               "bm_ret": None if bm_ret is None else round(bm_ret, 4), "mdd": round(mdd, 4),
               "cash_pct": round(state["cash_usd"] / nav, 4), "holds": len(state["holdings"]),
               "trades": len(trades), "stale": stale,
               # 当日累计成交（读 ledger，不受同日重跑影响）与因旧价被拦的交易数
               "trades_today": sum(1 for r in rows if r["date"] == d.isoformat()),
               "blocked": len(blocked),
               "top": [f"{h['ticker']} {h['weight']:.1%} ({h['pnl_pct']:+.1%})" for h in hold_rows[:6]],
               "trade_lines": [f"{t['side']} {t['ticker']} {t['qty']:g}@{t['price_local']} {t['reason']}" for t in trades],
               "trade_lines_today": [f"{r['side']} {r['ticker']} {float(r['qty']):g}@{r['price_local']} {r['reason']}"
                                     for r in rows if r["date"] == d.isoformat()],
               "blocked_lines": blocked}
    save_json(pdir / "summary_latest.json", summary)
    print("[paper] " + " | ".join(f"{k}={v}" for k, v in summary.items()
                                  if k not in ("top", "trade_lines", "trade_lines_today", "blocked_lines")))
    print("[paper] top=" + "; ".join(summary["top"]))
    if summary["trade_lines_today"]:
        print("[paper] trades_today=" + "; ".join(summary["trade_lines_today"]))
    if blocked:
        print("[paper] blocked=" + "; ".join(blocked))
    print(f"[paper_portfolio] {d} NAV ${nav:,.0f}  现金 {state['cash_usd']/nav:.1%}  "
          f"持仓 {len(state['holdings'])}  成交 {len(trades)}")
    for t in trades:
        print(f"  {t['side']:4} {t['ticker']:10} {t['qty']:>8g} @ {t['price_local']} {t['currency']}  "
              f"${t['amount_usd']:,.0f}  {t['reason']}")
    return 0


# ----------------------------------------------------------------------------
# 看板
# ----------------------------------------------------------------------------
def write_dashboard(pdir: Path, cfg: dict, navs: list, ledger: list, daily: dict):
    start = float(cfg["start_capital_usd"])
    pts = [(r["date"], float(r["nav_usd"]), float(r["benchmark_close"]) if r["benchmark_close"] else None)
           for r in navs]
    b0 = next((b for _, _, b in pts if b), None)
    nav_idx = [(dt, n / start) for dt, n, _ in pts]
    bm_idx = [(dt, b / b0) for dt, _, b in pts if b and b0]

    nav_last = nav_idx[-1][1] if nav_idx else 1.0
    bm_last = bm_idx[-1][1] if bm_idx else 1.0
    peak, mdd = 0.0, 0.0
    for _, v in nav_idx:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    days = len(nav_idx)

    # SVG 折线
    W, H, PAD = 860, 260, 36
    all_v = [v for _, v in nav_idx] + [v for _, v in bm_idx] or [1.0]
    lo, hi = min(all_v) * 0.98, max(all_v) * 1.02
    if hi - lo < 1e-6:
        lo, hi = lo - 0.02, hi + 0.02

    def poly(series):
        n = max(1, len(series) - 1)
        return " ".join(f"{PAD + i * (W - 2 * PAD) / n:.1f},{H - PAD - (v - lo) / (hi - lo) * (H - 2 * PAD):.1f}"
                        for i, (_, v) in enumerate(series))

    grid = "".join(
        f'<line x1="{PAD}" x2="{W - PAD}" y1="{H - PAD - k / 4 * (H - 2 * PAD):.1f}" y2="{H - PAD - k / 4 * (H - 2 * PAD):.1f}" class="grid"/>'
        f'<text x="{PAD - 6}" y="{H - PAD - k / 4 * (H - 2 * PAD) + 4:.1f}" class="lbl" text-anchor="end">{(lo + (hi - lo) * k / 4 - 1) * 100:+.1f}%</text>'
        for k in range(5))
    svg = (f'<svg viewBox="0 0 {W} {H}" width="100%">{grid}'
           f'<polyline points="{poly(bm_idx)}" class="bm"/>'
           f'<polyline points="{poly(nav_idx)}" class="nav"/></svg>')

    def pct(x, d=1):
        return "—" if x is None else f"{x * 100:+.{d}f}%"

    hold_html = "".join(
        f"<tr><td><b>{h['ticker']}</b><br><span class=dim>{h['name']}</span></td>"
        f"<td class=r>{h['weight'] * 100:.1f}%<br><span class=dim>目标 {h['target_weight'] * 100:.1f}%</span></td>"
        f"<td class=r>{h['qty']:g}</td><td class=r>{h['price_local']:.2f} {h['currency']}<br><span class=dim>{h['price_date']}</span></td>"
        f"<td class=r>{pct(h['pnl_pct'])}</td>"
        f"<td class=r>{'—' if h['b'] is None else f'{h[chr(98)]:.2f}'}</td>"
        f"<td class=r>{pct(h['upside'], 0)} / {pct(-h['downside'] if h['downside'] is not None else None, 0)}</td>"
        f"<td class=r>{pct(h['cagr_3y'], 0)}</td><td>{h['entered']}</td><td class=dim>{h['status']}</td></tr>"
        for h in daily["holdings"])

    cand_html = "".join(
        f"<tr class={'ok' if c['eligible'] else 'no'}><td><b>{c['ticker']}</b> <span class=dim>{c['name']}</span></td>"
        f"<td class=r>{c['target_weight'] * 100:.1f}%</td>"
        f"<td class=r>{'—' if c['b'] is None else f'{c[chr(98)]:.2f}'}</td>"
        f"<td class=r>{pct(c['upside'], 0)}</td><td class=r>{pct(c['cagr_3y'], 0)}</td>"
        f"<td>{c['dominant'] or '—'}/{c['confidence'] or '—'}</td><td class=dim>{c['reason']}</td></tr>"
        for c in daily["candidates"] if c["target_weight"] > 0 or c["reason"] not in ("无三情景价",))

    led_html = "".join(
        f"<tr><td>{t['date']}</td><td><b>{t['ticker']}</b></td><td class={'buy' if t['side'] == 'BUY' else 'sell'}>{t['side']}</td>"
        f"<td class=r>{float(t['qty']):g}</td><td class=r>{float(t['price_local']):.2f} {t['currency']}</td>"
        f"<td class=r>${float(t['amount_usd']):,.0f}</td><td class=dim>{t['reason']}</td></tr>"
        for t in list(reversed(ledger))[:40])

    html = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{cfg['name']}</title>
<style>
:root{{--bg:#fff;--fg:#1a1a1a;--dim:#6b6b6b;--line:#e5e5e5;--nav:#1f5fbf;--bm:#a0a0a0;--up:#1a7f4b;--dn:#b0342c;--ok:#f3f9f4}}
@media(prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#111;--fg:#eee;--dim:#999;--line:#2a2a2a;--nav:#6ea0ff;--bm:#777;--ok:#15201a}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;max-width:1100px;margin:auto}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px}} .dim{{color:var(--dim);font-size:12px}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}}
.kpi div{{border:1px solid var(--line);border-radius:8px;padding:10px 12px}} .kpi b{{display:block;font-size:20px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--dim);font-weight:500}} .r{{text-align:right}} .buy{{color:var(--up)}} .sell{{color:var(--dn)}} tr.ok{{background:var(--ok)}} tr.no td{{color:var(--dim)}}
svg .grid{{stroke:var(--line)}} svg .lbl{{fill:var(--dim);font-size:11px}} svg .nav{{fill:none;stroke:var(--nav);stroke-width:2}} svg .bm{{fill:none;stroke:var(--bm);stroke-width:1.5;stroke-dasharray:4 3}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h1>{cfg['name']}</h1>
<div class=dim>起点 {cfg['start_date']} · ${start:,.0f} · {'等权' if cfg['sizing'] == 'equal' else '按上行/下行比加权'} · 单票 ≤{cfg['max_weight']:.0%} · 总敞口 ≤{cfg['max_gross']:.0%} · 入选：上行≥{cfg['min_upside_to_base']:.0%} & 三年年化≥{cfg['min_cagr_3y']:.0%} & 距悲观价≤{cfg['max_downside_to_bear']:.0%} & 主导=基准 · 最近运行 {daily['date']}</div>
<div class=kpi>
<div><span class=dim>净值</span><b>{pct(nav_last - 1, 2)}</b><span class=dim>${daily['nav_usd']:,.0f}</span></div>
<div><span class=dim>{cfg['benchmark']}</span><b>{pct(bm_last - 1, 2)}</b><span class=dim>同期</span></div>
<div><span class=dim>超额</span><b>{pct(nav_last - bm_last, 2)}</b><span class=dim>{days} 个交易日</span></div>
<div><span class=dim>最大回撤</span><b>{pct(mdd, 2)}</b></div>
<div><span class=dim>现金</span><b>{daily['cash_usd'] / daily['nav_usd'] * 100:.0f}%</b><span class=dim>{len(daily['holdings'])} 只持仓</span></div>
</div>
{svg}<div class=dim>实线 = 模拟盘净值，虚线 = {cfg['benchmark']}</div>
<h2>持仓</h2><div class=wrap><table><tr><th>标的</th><th class=r>权重</th><th class=r>股数</th><th class=r>价格</th><th class=r>盈亏</th><th class=r>上行/下行比</th><th class=r>上行/下行</th><th class=r>3年年化</th><th>建仓</th><th>状态</th></tr>{hold_html}</table></div>
<h2>候选池（含未入选原因）</h2><div class=wrap><table><tr><th>标的</th><th class=r>目标权重</th><th class=r>上行/下行比</th><th class=r>上行</th><th class=r>3年年化</th><th>主导/置信</th><th>判定</th></tr>{cand_html}</table></div>
<h2>成交记录（最近 40 笔）</h2><div class=wrap><table><tr><th>日期</th><th>标的</th><th>方向</th><th class=r>股数</th><th class=r>价格</th><th class=r>金额</th><th>触发</th></tr>{led_html}</table></div>
<p class=dim>上行 = 基准价/现价 − 1；下行 = 1 − 悲观价/现价（地板 {cfg['downside_floor']:.0%}）。汇率为常数（config.json fx_to_usd），A/H 股按 100 股整手。</p>
</body></html>"""
    (pdir / "dashboard.html").write_text(html, encoding="utf-8")


def main(argv):
    ap = argparse.ArgumentParser(description="低估+增长 策略模拟盘")
    ap.add_argument("--root", default=".")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--init", action="store_true", help="重新初始化（清空历史）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    root = detect_projects_root(Path(a.root))
    return run(root, date.fromisoformat(a.date), a.init, a.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
