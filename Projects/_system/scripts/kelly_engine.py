#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情景凯利持仓建议引擎 v3 (registry 驱动 + 主导情景判定)
================================================
每日流水线用。产出 = 凯利最优目标组合 + 与当前持仓的增减建议。

方法:  单票情景凯利  f* = E[r] / σ²
  E[r] = valuation_registry 12M 预期收益 (研究/估值, 单一事实源)
         · v3: 有主导情景判定 (scenario_valuation.dominant) → 主导情景 60% + 相邻情景 30% + 远端情景 10% (base主导时两侧各20%)
           (残余权重 = 判定出错的保险, 不是情景概率; 系统已废弃情景概率加权综合估值)
         · 无判定 → 回退: 显式三情景加权 (legacy) 或 单点目标 ±spread
  σ    = 各票近一年日收益年化实现波动率 (market_data CSV, 每日市场情况)
  → 1/4 凯利 → 25% 单票上限 → 90% 投资预算 (10% 现金地板) 水填充分配

数据源 (全部本地, 无网络):
  估值   _system/valuation_registry.json   ← 直接读, 跟随你的重估自动更新
  行情   _system/market_data/*.csv + _data_status.json (前复权收盘)
  持仓   _system/positions/guard_verdict_{date}.json；
         裸 snapshot 仅在所有持仓均可安全估值时兜底

产出 (写到 _system/position_advice/):
  {date}_kelly_advice.md · _kelly_dashboard_{date}.html · _kelly_out_{date}.json

用法:  python kelly_engine.py [BASE_DIR] [DATE]
  BASE_DIR 默认 = 脚本推断 (…/Projects/_system 的上级)。云端跑时传 /mnt/user-data/uploads/Projects
  DATE     默认 = 今天；历史重跑必须显式传 YYYY-MM-DD
只读估值/行情/持仓, 不下单, 不改估值, 不改扳机。
"""
import json, math, csv, os, re, sys
from datetime import date

# ---------- 路径 ----------
_FLAGS = [a for a in sys.argv[1:] if a.startswith("--")]
_POS   = [a for a in sys.argv[1:] if not a.startswith("--")]
US_ONLY = "--us-only" in _FLAGS          # 只保留美元(美股/ADR)标的, 剔除 A股/港股
SUF      = "_us" if US_ONLY else ""      # 输出文件后缀, 与全量版并行不覆盖
UNIV_TAG = "（美股-only）" if US_ONLY else ""
BASE = _POS[0] if len(_POS) > 0 else None
if not BASE:
    from tidestone_paths import PROJECTS_ROOT
    BASE = str(PROJECTS_ROOT)
SYS = os.path.join(BASE, "_system")
MD  = os.path.join(SYS, "market_data")
POS = os.path.join(SYS, "positions")
OUT = os.path.join(SYS, "position_advice")

# ---------- 参数 ----------
KELLY_FRACTION = 0.25
MAX_WEIGHT     = 0.25
MAX_POSITIONS  = 10        # 目标组合最多持仓数(按凯利原始需求取前 N)
CASH_FLOOR     = 0.10
VOL_FLOOR      = 0.20
NO_VOL_DEFAULT = 0.60      # 无历史时的保守高波动
TRADING_DAYS   = 252
SPREAD_UP, SPREAD_DN = 0.25, 0.30   # 单点目标的 C 级情景 ±spread
DOMINANT_W, ADJ_W, FAR_W = 0.60, 0.30, 0.10  # 主导情景/相邻情景/远端情景权重(方向性倾斜); base主导时两侧对称各0.20

# ---------- 日期 ----------
DATE = _POS[1] if len(_POS) > 1 else None
if not DATE:
    DATE = date.today().isoformat()

# ---------- 行情 ----------
STATUS = json.load(open(f"{MD}/_data_status.json", encoding="utf-8"))
CSV_FILE = {}                              # registry key → csv 文件名映射（当前无例外）

def _finite(x):
    return isinstance(x, (int, float)) and x == x and x > 0

def _last_close(t, v):
    """manifest last_row.close 有效则用之; 否则(残行/NaN)从 CSV 尾部回扫最后一个有效收盘价"""
    c = v.get("last_row", {}).get("close")
    if _finite(c): return c
    path = os.path.join(MD, CSV_FILE.get(t, f"{t}.csv"))
    if os.path.exists(path):
        try:
            rows = list(csv.DictReader(open(path, encoding="utf-8")))
        except Exception:
            rows = []
        for row in reversed(rows):
            try:
                x = float(row["close"])
                if _finite(x): return x
            except (ValueError, TypeError, KeyError):
                pass
    return None

PX = {t: _last_close(t, v) for t, v in STATUS["tickers"].items()}
_n_fallback = sum(1 for t, v in STATUS["tickers"].items() if not _finite(v.get("last_row", {}).get("close")))
if _n_fallback:
    print(f"[kelly][WARN] {_n_fallback} 个 ticker 的 manifest 收盘价无效(残行/NaN), 已回退 CSV 最后有效收盘价 — 请检查行情拉取")

def ann_vol(ticker):
    fn = CSV_FILE.get(ticker, f"{ticker}.csv")
    path = os.path.join(MD, fn)
    if not os.path.exists(path):
        return None, 0
    closes = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try: closes.append(float(row["close"]))
            except: pass
    closes = closes[-TRADING_DAYS-1:]
    rets = [math.log(closes[i]/closes[i-1]) for i in range(1, len(closes)) if closes[i-1] > 0]
    n = len(rets)
    if n < 20: return None, n
    mean = sum(rets)/n
    var  = sum((r-mean)**2 for r in rets)/(n-1)
    return math.sqrt(var*TRADING_DAYS), n

# ---------- 估值解析 (registry 单一事实源) ----------
REG = json.load(open(f"{SYS}/valuation_registry.json", encoding="utf-8"))["companies"]
NUM = r"[-+]?\d[\d,]*\.?\d*"
BULL, BASEW, BEAR = r"(?:乐观|牛|Bull)", r"(?:基准|中性|Base)", r"(?:悲观|熊|Bear)"

def parse_base(tp):
    if not tp: return None
    m = re.search(r"[¥$]?\s*("+NUM+r")", tp.replace(",", ""))
    return float(m.group(1)) if m else None

def _seg(seg):
    w = re.search(r"(\d+(?:\.\d+)?)\s*%", seg)
    seg2 = re.sub(r"\d+(?:\.\d+)?\s*%", "", seg)
    p = re.search(r"[¥$]?\s*("+NUM+r")", seg2.replace(",", ""))
    return (float(w.group(1))/100 if w else None, float(p.group(1)) if p else None)

def parse_scenarios(tp):
    """显式三情景 → (weights, prices)；解析不到返回 None"""
    if not tp: return None
    pos = {}
    for k, pat in (("bull", BULL), ("base", BASEW), ("bear", BEAR)):
        m = re.search(pat, tp)
        if not m: return None
        pos[k] = m.start()
    order = sorted(pos.items(), key=lambda kv: kv[1])
    segs = {}
    for i, (k, st) in enumerate(order):
        end = order[i+1][1] if i+1 < len(order) else len(tp)
        segs[k] = tp[st:end]
    pr = {k: _seg(segs[k]) for k in segs}
    prices = {k: pr[k][1] for k in pr}
    if any(prices[k] is None for k in prices): return None
    wt = {k: pr[k][0] for k in pr}
    w = (wt["bull"], wt["base"], wt["bear"]) if all(wt[k] is not None for k in wt) else (0.25, 0.50, 0.25)
    s = sum(w)
    if abs(s-1) > 0.02: w = tuple(x/s for x in w)     # 权重归一
    return w, (prices["bull"], prices["base"], prices["bear"])

def scenarios_dominant(c):
    """结构化 scenario_valuation + dominant 判定 → (weights, prices, 'S'); 不可用返回 None"""
    sv = c.get("scenario_valuation")
    if not isinstance(sv, dict): return None
    dom = sv.get("dominant")
    if dom not in ("bull", "base", "bear"): return None
    sc = sv.get("scenarios") or {}
    try:
        prices = {k: float(sc[k]["price"]) for k in ("bull", "base", "bear")}
    except (KeyError, TypeError, ValueError):
        return None
    if dom == "bull":   w = (DOMINANT_W, ADJ_W, FAR_W)          # 60/30/10
    elif dom == "bear": w = (FAR_W, ADJ_W, DOMINANT_W)          # 10/30/60
    else:               w = (0.20, DOMINANT_W, 0.20)            # base 主导: 两侧对称 20/60/20
    return w, (prices["bull"], prices["base"], prices["bear"]), "S"

def scenarios_for(c):
    """返回 (weights, (bull,base,bear), conf).
    conf: S=主导情景判定(60/30/10方向倾斜)  A=显式三情景加权(legacy, 待判定)  C=单点+统一spread"""
    dom = scenarios_dominant(c)
    if dom: return dom
    tp = c.get("target_price")
    sc = parse_scenarios(tp)
    if sc:
        # 保证 bull>=base>=bear 语义 (有的串是 悲观/基准/乐观 顺序, 已按价对齐标签, 无需再排)
        return sc[0], sc[1], "A"
    base = parse_base(tp)
    if base is None: return None
    return (0.25, 0.50, 0.25), (round(base*(1+SPREAD_UP), 4), base, round(base*(1-SPREAD_DN), 4)), "C"

# ---------- 持仓 (自包含，过期/币种不明时 fail closed) ----------
SNAP_KEY = {}                                           # snapshot ticker → registry key（当前无例外）


def _input_date(doc):
    """读取持仓输入的事实日期；不再用“文件存在”代替“数据是当天的”。"""
    for key in ("as_of", "date"):
        value = doc.get(key)
        if isinstance(value, str) and len(value) >= 10:
            return value[:10]
    return None


def load_positions():
    guard = os.path.join(POS, f"guard_verdict_{DATE}.json")
    snap = os.path.join(POS, f"snapshot_{DATE}.json")

    # position_guard 的 verdict 来自当日 IBKR market_value，已统一为账户基准币种。
    if os.path.exists(guard):
        d = json.load(open(guard, encoding="utf-8"))
        as_of = _input_date(d)
        conc = d.get("concentration") or {}
        hs = d.get("holdings") or []
        if as_of == DATE and conc.get("cash") is not None and hs:
            cash = float(conc["cash"])
            pos = {h["ticker"]: float(h["market_value"]) for h in hs}
            return cash, pos, "guard_verdict", as_of

    if os.path.exists(snap):
        d = json.load(open(snap, encoding="utf-8"))
        as_of = _input_date(d)
        if as_of != DATE:
            raise SystemExit(f"[kelly][FATAL] 快照日期 {as_of or '缺失'} != 计算日期 {DATE}")
        unsafe = []
        pos = {}
        for h in d.get("holdings", []):
            raw_tk = h["ticker"]
            tk = SNAP_KEY.get(raw_tk, raw_tk)
            company = REG.get(tk)
            if not company:
                unsafe.append(f"{raw_tk}:未纳入估值注册表")
                continue
            if str(company.get("currency") or "USD").upper() != "USD":
                unsafe.append(f"{raw_tk}:非USD且无汇率")
                continue
            px = PX.get(tk)
            if not _finite(px):
                unsafe.append(f"{raw_tk}:无有效现价")
                continue
            pos[raw_tk] = float(h["qty"]) * px
        if unsafe:
            raise SystemExit(
                "[kelly][FATAL] 当日只有裸快照，以下持仓无法安全折算为美元市值："
                + "；".join(unsafe)
                + "。请先生成当日 guard_verdict")
        return float(d["cash"]), pos, "snapshot_safe", as_of

    raise SystemExit(
        f"[kelly][FATAL] 没有 {DATE} 的可靠持仓：需要当日 guard_verdict 或可安全估值的 snapshot")


cash, raw_pos, pos_src, position_as_of = load_positions()
have_positions = True

equity = (cash or 0.0) + sum(raw_pos.values())
holdings = {}
for tk, mv in raw_pos.items():
    k = SNAP_KEY.get(tk, tk)
    holdings[k] = {"mv": mv, "w": mv/equity if equity else 0.0}
cash_w = (cash/equity) if equity else 0.0

# ---------- 逐票凯利 ----------
rows = []
modeled_tickers = set()
for t, c in REG.items():
    if c.get("status") != "active": continue
    modeled_tickers.add(t)
    if not c.get("target_price") or not c.get("zones"):
        # 研究中/无区间 → 跳过(无可用估值)
        if t not in holdings: continue
    sc = scenarios_for(c)
    P = PX.get(t)
    cur_w = holdings.get(t, {}).get("w", 0.0)
    if sc is None or P is None:
        # 无估值或无价: 只在持仓里体现, 目标 0
        rows.append({"t":t,"name":c.get("name",t),"rating":c.get("rating",""),"conf":"—",
                     "ccy":c.get("currency","USD"),
                     "P":P or 0,"base":0,"upside_base":0,"bull":0,"bear":0,"er":0,
                     "vol":0,"vol_used":0,"nobs":0,"f_full":0,"w_raw":0,"cur_w":cur_w,
                     "held":t in holdings,"note":"无估值/无价"})
        continue
    w, tg, conf = sc
    rets = [tp/P - 1.0 for tp in tg]
    er = sum(pi*ri for pi, ri in zip(w, rets))
    vol, nobs = ann_vol(t)
    if vol is None: vol = NO_VOL_DEFAULT
    vol_used = max(vol, VOL_FLOOR)
    f_full = max(0.0, er) / (vol_used**2)
    rows.append({"t":t,"name":c.get("name",t),"rating":c.get("rating",""),"conf":conf,
                 "ccy":c.get("currency","USD"),
                 "P":P,"base":tg[1],"upside_base":tg[1]/P-1,"bull":tg[0],"bear":tg[2],
                 "er":er,"vol":vol,"vol_used":vol_used,"nobs":nobs,
                 "f_full":f_full,"w_raw":f_full*KELLY_FRACTION,"cur_w":cur_w,
                 "held":t in holdings,"note":""})

# 未纳入活跃估值注册表的实有持仓不再静默消失：保持现状、占用预算，但不生成买卖建议。
fixed_rows = []
for t, h in holdings.items():
    if t in modeled_tickers:
        continue
    fixed_rows.append({"t": t, "name": t, "rating": "未覆盖", "conf": "—",
                       "ccy": "USD", "P": 0, "base": 0, "upside_base": 0,
                       "bull": 0, "bear": 0, "er": 0, "vol": 0, "vol_used": 0,
                       "nobs": 0, "f_full": 0, "w_raw": 0, "cur_w": h["w"],
                       "held": True, "note": "模型外持仓，保持现状", "fixed": True})
rows.extend(fixed_rows)

# ---------- universe 过滤 (--us-only: 只留美元标的, 模型外固定持仓照留) ----------
if US_ONLY:
    rows = [r for r in rows if r.get("fixed") or r.get("ccy", "USD") == "USD"]

# ---------- 目标持仓数上限 (最多 MAX_POSITIONS 支) ----------
# 在所有 E[r]>0(w_raw>0) 的名字里, 按凯利原始需求 w_raw 取最大的前 N 支;
# 其余(含已持有)目标清零(w_raw→0) = 建议减/清。预算只在保留的 N 支内水填充。
_pos_demand = sorted([r for r in rows if r["w_raw"] > 0], key=lambda r: -r["w_raw"])
_keep = {r["t"] for r in _pos_demand[:MAX_POSITIONS]}
for r in rows:
    r["capped_out"] = (r["w_raw"] > 0 and r["t"] not in _keep)
    if r["capped_out"]:
        r["w_raw"] = 0.0

# ---------- 预算分配 (regime A/B + 水填充) ----------
fixed_weight = sum(r["cur_w"] for r in fixed_rows)
budget = max(0.0, 1.0 - CASH_FLOOR - fixed_weight)
gross = sum(r["w_raw"] for r in rows)
if gross <= budget:
    regime = "A"
    for r in rows: r["w_target"] = r["cur_w"] if r.get("fixed") else min(r["w_raw"], MAX_WEIGHT)
else:
    regime = "B"
    remaining = budget
    active = {r["t"]: r["w_raw"] for r in rows if r["w_raw"] > 0}
    final = {}
    for _ in range(200):
        tot = sum(active.values())
        if tot <= 0: break
        capped = {t: MAX_WEIGHT for t, wr in active.items() if remaining*wr/tot >= MAX_WEIGHT-1e-9}
        if not capped:
            for t, wr in active.items(): final[t] = remaining*wr/tot
            break
        for t, cv in capped.items():
            final[t] = cv; remaining -= cv; del active[t]
    for r in rows: r["w_target"] = r["cur_w"] if r.get("fixed") else final.get(r["t"], 0.0)
for r in rows:
    r["delta"] = r["w_target"] - r["cur_w"]

# ---------- 整股可实现化 ----------
# 目标金额必须是「现价 × 整数股」。USD 名字(权益本币)直接四舍五入到整股;
# 非 USD 名字(A股/港股, 需汇率)本地无 FX 文件, 保留连续权重并标注 realizable=False。
FRACTIONAL_OK = False        # 账户支持碎股可置 True(仍会给出整股参考)
for r in rows:
    P = r["P"]; wt = r["w_target"]
    r["cur_mv"] = holdings.get(r["t"], {}).get("mv", 0.0)
    if r.get("fixed"):
        r["shares"] = None
        r["mv_real"] = r["cur_mv"]
        r["w_real"] = r["cur_w"]
        r["realizable"] = False
        r["dust"] = False
    elif r.get("ccy", "USD") == "USD" and P > 0:
        raw_sh = wt * equity / P
        sh = round(raw_sh)                       # 四舍五入到整股(<0.5 股→0, 自动剔除碎额)
        r["shares"] = sh
        r["mv_real"] = sh * P
        r["w_real"] = (sh * P / equity) if equity else 0.0
        r["realizable"] = True
        r["dust"] = (wt > 1e-4 and sh < 1)       # 有正目标但不足 1 股
    else:
        r["shares"] = None                        # 无 FX, 无法折算美元→整股
        r["mv_real"] = wt * equity
        r["w_real"] = wt
        r["realizable"] = False
        r["dust"] = False
    r["delta_real"] = r["w_real"] - r["cur_w"]
    r["delta_mv"] = r["mv_real"] - r["cur_mv"]

rows.sort(key=lambda r: -r["w_real"])

target_invested = sum(r["w_target"] for r in rows)
realizable_invested = sum(r["w_real"] for r in rows)
realizable_cash = 1.0 - realizable_invested
out = {"date":DATE,"position_as_of":position_as_of,"equity":equity,"cash_w":cash_w,
       "have_positions":have_positions,"pos_src":pos_src,
       "params":{"kelly_fraction":KELLY_FRACTION,"max_weight":MAX_WEIGHT,"cash_floor":CASH_FLOOR,
                 "vol_floor":VOL_FLOOR,"spread_up":SPREAD_UP,"spread_dn":SPREAD_DN},
       "gross_raw_demand":gross,"regime":regime,"fractional_ok":FRACTIONAL_OK,
       "target_invested":target_invested,"target_cash":1.0-target_invested,
       "realizable_invested":realizable_invested,"realizable_cash":realizable_cash,"rows":rows}

os.makedirs(OUT, exist_ok=True)
json.dump(out, open(os.path.join(OUT, f"_kelly_out_{DATE}{SUF}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ================= 报告生成 =================
def render_md(o):
    rows = o["rows"]; eq = o["equity"]
    held = {r["t"] for r in rows if r["held"]}
    fixed = [r for r in rows if r.get("fixed")]
    buy = [r for r in rows if not r.get("fixed") and ((r["realizable"] and r["shares"] and r["shares"] >= 1) or (not r["realizable"] and r["w_target"] > 1e-4))]
    dust = [r for r in rows if r.get("dust")]
    zero = [r for r in rows if not r.get("fixed") and r["w_target"] <= 1e-4]
    turnover = sum(abs(r["delta_real"]) for r in rows)/2 if o["have_positions"] else 0
    def dd(x): return f"+{x*100:.1f}%" if x >= 0 else f"{x*100:.1f}%"
    def shcell(r): return f"{r['shares']:,}" if r["realizable"] else "—*"
    L = []; A = L.append
    A(f"# 凯利公式持仓建议{UNIV_TAG} — {o['date']}\n")
    A("**方法：** 单票情景凯利 `f* = E[r] / σ²` → 1/4 凯利 → 25% 单票上限 → 90% 投资预算水填充 → **整股取整**")
    A("**E[r]：** valuation_registry 12M 预期收益（研究）——有主导情景判定的（S级）按 锚定60%+其余各20%；未判定回退三情景加权/单点spread　·　**σ：** 近一年日收益年化波动率（市场）")
    A(f"**账户：** 权益 ${eq:,.0f}　·　当前现金 {o['cash_w']*100:.1f}%　→　凯利目标现金 **{o['realizable_cash']*100:.1f}%**（整股后可实现）")
    A(f"**今日机制：** regime {o['regime']}（1/4 凯利原始需求 {o['gross_raw_demand']*100:.0f}% vs 90% 预算）"
      + ("" if o["have_positions"] else "　·　⚠️ 未取到持仓, 仅目标组合无增减") + "\n")
    A("> **目标金额 = 现价 × 整数股**，可直接对照下单。这是凯利最优目标组合，不是「今天全部换成这样」的交易单"
      + (f"（单边换手率约 {turnover*100:.0f}%）" if o["have_positions"] else "")
      + "。实盘仍要顾及交易成本、position_guard 纪律与税。**看方向与最大缺口，逐步靠拢。**\n")
    A("---\n## 一、今日目标组合（按可实现目标仓排序）\n")
    A("| # | 代码 | 名称 | 评级 | 置信 | 现价 | 目标价 | E[r] | 年化波动 | 凯利f | **目标仓** | **目标股数** | 目标金额 | 当前仓 | 增减 |")
    A("|--:|---|---|---|:-:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for i, r in enumerate(buy, 1):
        star = "✅" if r["t"] in held else ""
        A(f"| {i} | {r['t']} | {r['name']} | {r['rating']} | {r['conf']} | {r['P']:.2f} | {r['base']:.1f} | "
          f"{r['er']*100:.0f}% | {r['vol']*100:.0f}% | {r['f_full']:.2f} | **{r['w_real']*100:.1f}%** | "
          f"**{shcell(r)}** | ${r['mv_real']:,.0f} | {r['cur_w']*100:.1f}%{star} | {dd(r['delta_real'])} |")
    A(f"\n合计可实现投资 **{o['realizable_invested']*100:.1f}%** + 现金 **{o['realizable_cash']*100:.1f}%** = 100%"
      + "　（✅=当前已持有 · `—*`=非USD/A股需汇率与整手，暂按连续权重 · 置信 S=主导情景判定 60/30/10 方向倾斜 A=三情景加权待判定 C=单点+spread）\n")
    if dust:
        A("> **碎额剔除（正目标但不足 1 股，已忽略）：** "
          + "、".join(f"{r['t']}（{r['w_target']*100:.2f}%≈{r['w_target']*eq/r['P']:.2f} 股 @${r['P']:.0f}）" for r in dust) + "\n")
    if fixed:
        A("## 模型外持仓（保持现状，不参与凯利分配）\n")
        A("| 代码 | 当前市值 | 当前仓 | 处理 |\n|---|--:|--:|---|")
        for r in fixed:
            A(f"| {r['t']} | ${r['cur_mv']:,.0f} | {r['cur_w']*100:.1f}% | 未覆盖，不自动给买卖建议 |")
        A("")
    A("## 二、目标仓 = 0（E[r] ≤ 0，凯利不配 / 清仓）\n")
    A("| 代码 | 名称 | 评级 | 现价 | 目标价 | base涨幅 | E[r] | 当前仓 | 建议 |")
    A("|---|---|---|--:|--:|--:|--:|--:|---|")
    for r in sorted(zero, key=lambda r: -r["cur_w"]):
        act = "**减/清**" if r["cur_w"] > 0.005 else "不建仓"
        A(f"| {r['t']} | {r['name']} | {r['rating']} | {r['P']:.2f} | {r['base']:.1f} | "
          f"{r['upside_base']*100:.0f}% | {r['er']*100:.0f}% | {r['cur_w']*100:.1f}% | {act} |")
    if o["have_positions"]:
        A("\n## 三、最该动的几手（|增减| 最大，按可实现整股）\n")
        A("| 方向 | 代码 | 名称 | 当前仓 | 目标仓 | 增减 | 目标股数 | 约动用金额 |")
        A("|:-:|---|---|--:|--:|--:|--:|--:|")
        for r in sorted(rows, key=lambda r: -abs(r["delta_real"]))[:10]:
            A(f"| {'🟢加' if r['delta_real']>0 else '🔴减'} | {r['t']} | {r['name']} | {r['cur_w']*100:.1f}% | "
              f"{r['w_real']*100:.1f}% | {dd(r['delta_real'])} | {r['shares'] if r['realizable'] else '—*'} | ${abs(r['delta_mv']):,.0f} |")
    A(f"\n*引擎 kelly_engine.py · registry 驱动 · 只读, 不下单。持仓源: {o['pos_src']}（{o['position_as_of']}）。*")
    return "\n".join(L)

md = render_md(out)
open(os.path.join(OUT, f"{DATE}_kelly_advice{SUF}.md"), "w", encoding="utf-8").write(md)

# ================= HTML 看板 =================
def render_html(o):
    rows = o["rows"]; eq = o["equity"]
    held = {r["t"] for r in rows if r["held"]}
    fixed = [r for r in rows if r.get("fixed")]
    buy = [r for r in rows if not r.get("fixed") and ((r["realizable"] and r["shares"] and r["shares"] >= 1) or (not r["realizable"] and r["w_target"] > 1e-4))]
    dust = [r for r in rows if r.get("dust")]
    zero = [r for r in rows if not r.get("fixed") and r["w_target"] <= 1e-4]
    movers = sorted([r for r in rows if not r.get("fixed")], key=lambda r: -abs(r["delta_real"]))[:8] if o["have_positions"] else []
    turnover = sum(abs(r["delta_real"]) for r in rows)/2 if o["have_positions"] else 0
    def dd(x): return f"+{x*100:.1f}%" if x >= 0 else f"{x*100:.1f}%"
    def cl(x): return "pos" if x > 0 else ("neg" if x < 0 else "dim")
    def shc(r): return f'{r["shares"]:,}' if r["realizable"] else '<span class="dim" title="非USD/A股, 需汇率与整手">—*</span>'
    BADGE = {"S":'<span class="b bS">S</span>',"A":'<span class="b bA">A</span>',"C":'<span class="b bC">C</span>',"—":'<span class="b bC">—</span>'}
    def tr(r, i):
        star = ' <span class="held">持</span>' if r["t"] in held else ""
        return (f'<tr><td class="dim">{i}</td><td class="tk">{r["t"]}</td><td>{r["name"]}</td>'
                f'<td class="dim">{r["rating"]}</td><td>{BADGE.get(r["conf"],"")}</td>'
                f'<td class="num">{r["P"]:.2f}</td><td class="num">{r["base"]:.1f}</td>'
                f'<td class="num {cl(r["er"])}">{r["er"]*100:.0f}%</td><td class="num">{r["vol"]*100:.0f}%</td>'
                f'<td class="num dim">{r["f_full"]:.2f}</td><td class="num tgt">{r["w_real"]*100:.1f}%</td>'
                f'<td class="num tgt">{shc(r)}</td><td class="num dim">${r["mv_real"]:,.0f}</td>'
                f'<td class="num">{r["cur_w"]*100:.1f}%{star}</td><td class="num {cl(r["delta_real"])}">{dd(r["delta_real"])}</td></tr>')
    buy_rows = "\n".join(tr(r, i) for i, r in enumerate(buy, 1))
    dust_html = ('<div class="note" style="border-left-color:var(--dim)"><b>碎额剔除</b>（正目标但不足 1 股，已忽略）：'
                 + "、".join(f'{r["t"]} ({r["w_target"]*100:.2f}%≈{r["w_target"]*eq/r["P"]:.2f} 股 @${r["P"]:.0f})' for r in dust)
                 + '</div>') if dust else ""
    fixed_html = ('<div class="note"><b>模型外持仓保持现状：</b>'
                  + "、".join(f'{r["t"]} ${r["cur_mv"]:,.0f}（{r["cur_w"]*100:.1f}%）' for r in fixed)
                  + '。这些仓位占用组合预算，但引擎不自动给买卖建议。</div>') if fixed else ""
    def zr(r):
        act = '<span class="neg">减/清</span>' if r["cur_w"] > 0.005 else '<span class="dim">不建仓</span>'
        return (f'<tr><td class="tk">{r["t"]}</td><td>{r["name"]}</td><td class="dim">{r["rating"]}</td>'
                f'<td class="num">{r["P"]:.2f}</td><td class="num">{r["base"]:.1f}</td>'
                f'<td class="num {cl(r["er"])}">{r["er"]*100:.0f}%</td><td class="num">{r["cur_w"]*100:.1f}%</td><td>{act}</td></tr>')
    zero_rows = "\n".join(zr(r) for r in sorted(zero, key=lambda r: -r["cur_w"]))
    def mr(r):
        return (f'<tr><td class="{cl(r["delta_real"])}">{"▲" if r["delta_real"]>0 else "▼"}</td><td class="tk">{r["t"]}</td><td>{r["name"]}</td>'
                f'<td class="num">{r["cur_w"]*100:.1f}%</td><td class="num tgt">{r["w_real"]*100:.1f}%</td>'
                f'<td class="num {cl(r["delta_real"])}">{dd(r["delta_real"])}</td>'
                f'<td class="num tgt">{shc(r)}</td><td class="num dim">${abs(r["delta_mv"]):,.0f}</td></tr>')
    mv_rows = "\n".join(mr(r) for r in movers)
    top = buy[0] if buy else {"t":"—","w_real":0}
    trim = movers[0] if movers else {"t":"—","delta_real":0}
    mv_block = (f'<div class="card"><h2>② 最该动的几手（可实现整股）</h2><table><thead><tr><th></th><th>代码</th><th>名称</th>'
                f'<th class="num">当前</th><th class="num">目标</th><th class="num">增减</th><th class="num">目标股数</th><th class="num">约金额</th></tr></thead>'
                f'<tbody>{mv_rows}</tbody></table></div>') if movers else ""
    turnover_tile = (f'<div class="tile"><div class="k">单边换手率</div><div class="v">{turnover*100:.0f}%</div></div>'
                     if o["have_positions"] else '<div class="tile"><div class="k">持仓</div><div class="v dim">未取到</div></div>')
    S = "{"; E = "}"
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>凯利持仓建议{UNIV_TAG} {o['date']}</title>
<style>
:root{S}--bg:#0f1216;--card:#171b22;--card2:#1d222b;--line:#272d38;--tx:#e6e9ef;--dim:#8b94a3;
--pos:#3fb950;--neg:#f0616d;--tgt:#5aa9ff;--acc:#7c5cff;{E}
@media(prefers-color-scheme:light){S}:root{S}--bg:#f4f6fa;--card:#fff;--card2:#f7f9fc;--line:#e4e8ef;
--tx:#1a1f28;--dim:#6b7480;--pos:#1a8a3a;--neg:#d23f4d;--tgt:#1f6fe0;--acc:#6b4bf0;{E}{E}
*{S}box-sizing:border-box{E}body{S}margin:0;background:var(--bg);color:var(--tx);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;padding:20px{E}
.wrap{S}max-width:1120px;margin:0 auto{E}h1{S}font-size:22px;margin:0 0 4px{E}.sub{S}color:var(--dim);font-size:13px;margin-bottom:16px{E}
.meth{S}background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:14px;font-size:13px{E}
.meth code{S}background:var(--card2);padding:1px 6px;border-radius:4px;color:var(--tgt){E}
.tiles{S}display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px{E}
@media(max-width:720px){S}.tiles{S}grid-template-columns:repeat(2,1fr){E}{E}
.tile{S}background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px{E}
.tile .k{S}color:var(--dim);font-size:12px{E}.tile .v{S}font-size:20px;font-weight:650;margin-top:3px{E}
.tile .v small{S}font-size:12px;font-weight:400;color:var(--dim){E}
.card{S}background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 4px;margin-bottom:16px;overflow-x:auto{E}
.card h2{S}font-size:15px;margin:12px 12px 8px{E}
table{S}width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap{E}
th,td{S}padding:7px 9px;text-align:left;border-bottom:1px solid var(--line){E}
th{S}color:var(--dim);font-weight:600;font-size:12px;cursor:pointer;user-select:none;position:sticky;top:0;background:var(--card){E}
th.num,td.num{S}text-align:right;font-variant-numeric:tabular-nums{E}tr:hover td{S}background:var(--card2){E}
.tk{S}font-weight:650;font-family:ui-monospace,Menlo,monospace{E}
.tgt{S}color:var(--tgt);font-weight:700{E}.pos{S}color:var(--pos){E}.neg{S}color:var(--neg){E}.dim{S}color:var(--dim){E}
.held{S}font-size:10px;background:var(--acc);color:#fff;padding:0 4px;border-radius:3px{E}
.b{S}font-size:11px;font-weight:700;padding:1px 6px;border-radius:4px{E}
.bS{S}background:rgba(90,169,255,.2);color:var(--tgt){E}.bA{S}background:rgba(63,185,80,.18);color:var(--pos){E}.bC{S}background:rgba(139,148,163,.2);color:var(--dim){E}
.note{S}background:var(--card2);border-left:3px solid var(--acc);padding:10px 14px;border-radius:0 8px 8px 0;font-size:13px;margin:0 4px 16px{E}
details{S}background:var(--card);border:1px solid var(--line);border-radius:10px;padding:4px 14px;margin-bottom:14px{E}
summary{S}cursor:pointer;font-weight:600;padding:8px 0{E}details li{S}color:var(--dim);font-size:13px{E}
.foot{S}color:var(--dim);font-size:12px;text-align:center;margin-top:10px{E}
</style></head><body><div class="wrap">
<h1>凯利公式持仓建议{UNIV_TAG}</h1>
<div class="sub">{o['date']} · 持仓截至 {o['position_as_of']}（{o['pos_src']}） · 权益 ${eq:,.0f} · 前复权收盘 · registry 驱动</div>
<div class="meth"><b>方法：</b>单票情景凯利 <code>f* = E[r] / σ²</code> → 1/4 凯利 → 25% 上限 → 90% 预算水填充 → <b>整股取整</b>。
<b>E[r]</b>=12M 预期收益（研究）：S级=主导情景60%+相邻30%+远端10%（base主导为20/60/20），未判定回退三情景加权/单点spread；<b>σ</b>=近一年年化实现波动率（市场）。
<b>目标金额 = 现价 × 整数股</b>，可直接对照下单。今日 <b>regime {o['regime']}</b>：1/4 凯利原始需求 {o['gross_raw_demand']*100:.0f}% vs 90% 预算。</div>
<div class="tiles">
<div class="tile"><div class="k">目标现金（整股后）</div><div class="v">{o['realizable_cash']*100:.0f}% <small>（当前 {o['cash_w']*100:.0f}%）</small></div></div>
<div class="tile"><div class="k">头号加仓</div><div class="v tgt">{top['t']} <small>{top['w_real']*100:.1f}%</small></div></div>
<div class="tile"><div class="k">头号减仓</div><div class="v neg">{trim['t']} <small>{dd(trim['delta_real'])}</small></div></div>
{turnover_tile}
</div>
<div class="note">这是<b>凯利最优目标组合</b>，不是「今天全部换成这样」的交易单。<b>目标金额已按现价×整数股取整</b>，不足 1 股的碎额已剔除。实盘仍要顾及交易成本、position_guard 的纪律和税。<b>正确读法：看方向与最大缺口，逐步靠拢。</b></div>
<div class="card"><h2>① 今日目标组合（点表头可排序）</h2>
<table id="main"><thead><tr><th>#</th><th>代码</th><th>名称</th><th>评级</th><th>置信</th>
<th class="num">现价</th><th class="num">目标价</th><th class="num">E[r]</th><th class="num">年化波动</th>
<th class="num">凯利f</th><th class="num">目标仓</th><th class="num">目标股数</th><th class="num">目标金额</th><th class="num">当前仓</th><th class="num">增减</th></tr></thead>
<tbody>{buy_rows}</tbody></table>
<div style="padding:8px 12px;color:var(--dim);font-size:12px">合计可实现投资 {o['realizable_invested']*100:.1f}% + 现金 {o['realizable_cash']*100:.1f}% = 100% · <code>—*</code>=非USD/A股需汇率与整手 · <span class="b bS">S</span>=主导情景判定(60/30/10) <span class="b bA">A</span>=三情景加权(待判定) <span class="b bC">C</span>=单点目标+统一±spread(可靠度低)</div></div>
{dust_html}
{fixed_html}
{mv_block}
<div class="card"><h2>③ 目标仓 = 0（E[r] ≤ 0，凯利不配）</h2>
<table><thead><tr><th>代码</th><th>名称</th><th>评级</th><th class="num">现价</th><th class="num">目标价</th><th class="num">E[r]</th><th class="num">当前仓</th><th>建议</th></tr></thead>
<tbody>{zero_rows}</tbody></table></div>
<details><summary>方法与局限（务必读一遍）</summary><ul>
<li><b>单票独立假设：</b>按单票凯利, 未建协方差矩阵, 忽略持仓相关性——多只强相关 AI/SaaS 同时满配会低估组合真实风险。</li>
<li><b>凯利不认沉没成本：</b>只看从现价到目标价的前瞻分布, 不管已有浮亏。减仓建议=“这仓位不该这么大”, 不是“认赔”。</li>
<li><b>置信分级：</b>S 级(主导情景判定, 60/30/10 方向倾斜; base主导两侧各20%)最可信——非主导权重是判定出错的保险, 不是情景概率; A 级(三情景加权)为遗留口径, 待下次估值刷新补判定; C 级(单点+统一±spread)edge 可能虚高, 给大仓位前先核目标价时效。</li>
<li><b>σ 是历史值：</b>用过去一年实现波动, 市场骤变时滞后。</li>
<li><b>与 position_guard 关系：</b>guard 管纪律(该不该动), 凯利管尺寸(该配多少), 互补。</li></ul></details>
<div class="foot">kelly_engine.py · registry 驱动 · 只读估值/行情/持仓, 不下单</div>
<script>
document.querySelectorAll('#main th').forEach((th,i)=>{S}th.addEventListener('click',()=>{S}
const tb=th.closest('table').querySelector('tbody');const rows=[...tb.rows];const asc=th._asc=!th._asc;
const val=td=>{S}const t=td.innerText.replace(/[$,%持]/g,'').trim();const n=parseFloat(t);return isNaN(n)?t.toLowerCase():n;{E};
rows.sort((a,b)=>(val(a.cells[i])<val(b.cells[i])?-1:val(a.cells[i])>val(b.cells[i])?1:0)*(asc?1:-1));
rows.forEach(r=>tb.appendChild(r));{E});{E});
</script></div></body></html>"""

open(os.path.join(OUT, f"_kelly_dashboard_{DATE}{SUF}.html"), "w", encoding="utf-8").write(render_html(out))

adds  = sorted([r for r in rows if r["delta_real"] > 0.005], key=lambda r:-r["delta_real"])[:3]
trims = sorted([r for r in rows if r["delta_real"] < -0.005], key=lambda r: r["delta_real"])[:3]
print(f"[kelly] date={DATE} universe={'US-only' if US_ONLY else 'all'} position_as_of={position_as_of} pos_src={pos_src} "
      f"equity=${equity:,.0f} regime={regime} target_cash={out['realizable_cash']*100:.1f}% "
      f"fixed={','.join(r['t'] for r in fixed_rows) or '无'} rows={len(rows)}")
print(f"[kelly] top_targets: " + ", ".join(
    f"{r['t']} {r['w_real']*100:.1f}%" for r in [x for x in rows if not x.get('fixed') and x['w_real'] > 0][:5]))
print(f"[kelly] top_adds: "   + (", ".join(f"{r['t']} +{r['delta_real']*100:.1f}%" for r in adds)  or "无"))
print(f"[kelly] top_trims: "  + (", ".join(f"{r['t']} {r['delta_real']*100:.1f}%" for r in trims) or "无"))
print(f"[kelly] files: position_advice/{DATE}_kelly_advice{SUF}.md, _kelly_dashboard_{DATE}{SUF}.html, _kelly_out_{DATE}{SUF}.json")

