r"""
compute_signals.py — Step 3 纯技术信号引擎（v0.2，口径已定稿）
=====================================================================

定位
----
把 daily-portfolio-scanner 的 Step 3 触发逻辑从"prose 里每天临时重写 pandas"
收敛为一个 committed、确定性、可单测的信号引擎。**只吃价量，不读注册表估值字段**
——这正是"纯技术买入/卖出信号"与基本面解耦的落点。

设计原则（见《scanner_技术触发分层重构方案》第四节讨论）
    1) 先定趋势体制(regime)        —— 由慢指标（MA 结构 + MA60 斜率）给出
    2) 四个独立"指标族"各自投票     —— 趋势 / 动量 / 摆动 / 量价
    3) 合流(confluence)定强弱       —— 同向族越多越强（强信号 = 同向族 ≥ 3）
    4) 体制闸门区分顺势/逆势        —— 逆势信号降级，除非教科书级反转组合

输入
----
    本机前复权 CSV：date,open,high,low,close,volume,amount
    可选 last_row_override（沿用永久契约第 8 条：bash/FUSE 缓存陈旧时，
    用 Read 工具读到的 _data_status.json.tickers.{T}.last_row 注入真实最后一行）

输出
----
    每只股票一个 dict（schema 见文件末尾 SIGNAL_SCHEMA 注释）；
    main() 汇总为 list 并在 stdout 末行打印  SIGNALS_JSON: [...]  供扫描任务解析。
    用法： python3 compute_signals.py APP:/path/APP.csv 700.HK:/path/700.HK.csv ...

口径已定稿（2026-06-24）：RSI 超卖/超买 = 25 / 75；强信号 = 同向族 ≥ 3。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd

# ════════════════════════════════════════════════════════════════════
# 参数常量区 —— 所有口径集中此处，审阅 / 调参只动这一段
# ════════════════════════════════════════════════════════════════════
MA_WINDOWS = (20, 60, 250)      # 三条均线
MA250_FALLBACK = 120            # 历史不足 250 日时 MA250 用 MA120 替代并标注
MA60_SLOPE_LOOKBACK = 5         # MA60 斜率取近 N 日方向

MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_PERIOD = 14
RSI_OVERSOLD, RSI_OVERBOUGHT = 25, 75   # 定稿：超卖 25 / 超买 75

SR_WINDOW = 30                  # 支撑/阻力 = 近 N 日 close 极值（不含今天）
VOL_MA_WINDOW = 60              # 量能比基准 = N 日均量
VOL_BREAKOUT_RATIO = 1.5        # 突破需放量倍数（量比 > 此值才确认）

CROSS_LOOKBACK = 3              # 金叉/死叉判定窗口（近 N 日内发生即计）
SWING_K = 5                     # 摆动点：左右各 K 根都更低/更高 → 局部高/低点
DIVERGENCE_LOOKBACK = 60        # 背离只在最近 N 日内的两个同类摆动点间判定

CONFLUENCE_STRONG = 3           # 定稿：强信号 = 同向族数 ≥ 3
CONFLUENCE_MEDIUM = 2           # 中信号门槛
MIN_HISTORY = 30               # 少于此行数不出方向信号，仅给原始指标 + 数据不足标记

Vote = Literal["bull", "bear", "neutral"]


def _r(x, n=4):
    """None-safe 四舍五入。"""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(x), n)


def _recent_cross(a: pd.Series, b: pd.Series, lookback: int = CROSS_LOOKBACK):
    """判定 a 在近 lookback 日内是否上穿/下穿 b。返回 'golden' / 'death' / None。"""
    d = (a - b).dropna()
    if len(d) < lookback + 1:
        return None
    recent = d.iloc[-(lookback + 1):]
    last = recent.iloc[-1]
    prev = recent.iloc[:-1]
    if last > 0 and (prev <= 0).any():
        return "golden"
    if last < 0 and (prev >= 0).any():
        return "death"
    return None


# ════════════════════════════════════════════════════════════════════
# 数据加载
# ════════════════════════════════════════════════════════════════════
def load_prices(csv_path: str | Path,
                last_row_override: Optional[dict] = None) -> pd.DataFrame:
    """读前复权 CSV → 按日期升序 DataFrame；按需注入 override 真实最后一行。"""
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if last_row_override:
        od = pd.to_datetime(last_row_override["date"])
        if df["date"].iloc[-1] < od:
            row = {c: last_row_override.get(c, np.nan) for c in df.columns}
            row["date"] = od
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df


# ════════════════════════════════════════════════════════════════════
# 指标层（确定性，口径已固定）
# ════════════════════════════════════════════════════════════════════
def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """写入 ma20/ma60/ma250；不足 250 行时 ma250 退化为 ma{MA250_FALLBACK}，
    并在 df.attrs['ma250_fallback'] 标记。"""
    c = df["close"]
    df["ma20"] = c.rolling(MA_WINDOWS[0]).mean()
    df["ma60"] = c.rolling(MA_WINDOWS[1]).mean()
    if len(df) >= MA_WINDOWS[2]:
        df["ma250"] = c.rolling(MA_WINDOWS[2]).mean()
        df.attrs["ma250_fallback"] = False
    else:
        win = min(MA250_FALLBACK, len(df))
        df["ma250"] = c.rolling(win).mean()
        df.attrs["ma250_fallback"] = True
    return df


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    """标准 MACD(12,26,9)：dif=EMA_fast-EMA_slow，dea=dif 的 signal-EMA，hist=2*(dif-dea)。"""
    c = df["close"]
    ema_fast = c.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = c.ewm(span=MACD_SLOW, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=MACD_SIGNAL, adjust=False).mean()
    df["hist"] = 2 * (df["dif"] - df["dea"])
    return df


def add_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """标准 RSI(14)，Wilder 平滑。

    暖机期处理（2026-08-20 修）：原实现对 rs 为 NaN 的行统一 fillna(100.0)，
    把「样本还不够、算不出 RSI」误填成「RSI=100 极度超买」。序列头部前 RSI_PERIOD
    行本就没有足够的涨跌样本（全组实测 142 行被直接填成 100，另有约 770 行是仅凭
    3–13 天数据算出的伪值），这些行会污染任何逐日历史回放/阈值回测——摆动族命中率
    曾因此被高估约 7 倍。

    现在：前 RSI_PERIOD 行一律置 NaN（明确表示"未定义"），暖机期之后若 avg_loss
    仍为 0（确实一路无下跌）才填 100.0。当日信号只取序列尾部，故本次修正
    不改变任何在跑标的的实时信号，只让历史统计变干净。
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / RSI_PERIOD, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # 暖机期之后、avg_loss 真为 0（全程无下跌）→ RSI=100 是有意义的
    rsi = rsi.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    # 暖机期（前 RSI_PERIOD 行）一律未定义
    if len(rsi) >= 1:
        rsi.iloc[: min(RSI_PERIOD, len(rsi))] = np.nan
    df["rsi"] = rsi
    return df


def support_resistance(df: pd.DataFrame) -> tuple[float, float]:
    """(support, resistance) = 近 SR_WINDOW 日 close 的 min/max，不含今天。"""
    window = df["close"].iloc[-(SR_WINDOW + 1):-1]
    if window.empty:
        window = df["close"].iloc[:-1]
    return float(window.min()), float(window.max())


def volume_ratio(df: pd.DataFrame) -> float:
    """当日 volume / 近 VOL_MA_WINDOW 日均量（均量不含今天）。"""
    today = float(df["volume"].iloc[-1])
    base = df["volume"].iloc[-(VOL_MA_WINDOW + 1):-1]
    if base.empty or base.mean() == 0:
        return float("nan")
    return today / float(base.mean())


# ════════════════════════════════════════════════════════════════════
# 结构层（摆动点 / 背离 / HH-HL）—— 形态识别的共同地基
# ════════════════════════════════════════════════════════════════════
def find_swings(df: pd.DataFrame, k: int = SWING_K) -> tuple[list[int], list[int]]:
    """返回 (swing_high_idx, swing_low_idx)。局部高点：high[i] 严格大于左右各 k 根的 high。"""
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    hi, lo = [], []
    for i in range(k, n - k):
        win_h = highs[i - k:i + k + 1]
        win_l = lows[i - k:i + k + 1]
        if highs[i] == win_h.max() and (win_h == highs[i]).sum() == 1:
            hi.append(i)
        if lows[i] == win_l.min() and (win_l == lows[i]).sum() == 1:
            lo.append(i)
    return hi, lo


def detect_divergence(df: pd.DataFrame,
                      swing_high_idx: list[int],
                      swing_low_idx: list[int],
                      osc_col: str = "dif") -> dict:
    """最近 DIVERGENCE_LOOKBACK 内取最近两个同类摆动点比较价格 vs 振荡指标。"""
    n = len(df)
    cutoff = n - DIVERGENCE_LOOKBACK
    osc = df[osc_col].values
    lows = [i for i in swing_low_idx if i >= cutoff]
    highs = [i for i in swing_high_idx if i >= cutoff]
    out = {"bottom": False, "top": False}
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if df["low"].iloc[b] < df["low"].iloc[a] and osc[b] > osc[a]:
            out["bottom"] = True
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if df["high"].iloc[b] > df["high"].iloc[a] and osc[b] < osc[a]:
            out["top"] = True
    return out


def swing_structure(df: pd.DataFrame,
                    swing_high_idx: list[int],
                    swing_low_idx: list[int]) -> Literal["HH_HL", "LH_LL", "mixed"]:
    """由最近两组高/低点判定结构：高低点齐抬=HH_HL，齐降=LH_LL，其余=mixed。"""
    if len(swing_high_idx) < 2 or len(swing_low_idx) < 2:
        return "mixed"
    h1, h2 = swing_high_idx[-2], swing_high_idx[-1]
    l1, l2 = swing_low_idx[-2], swing_low_idx[-1]
    hh = df["high"].iloc[h2] > df["high"].iloc[h1]
    hl = df["low"].iloc[l2] > df["low"].iloc[l1]
    lh = df["high"].iloc[h2] < df["high"].iloc[h1]
    ll = df["low"].iloc[l2] < df["low"].iloc[l1]
    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    return "mixed"


# ════════════════════════════════════════════════════════════════════
# 趋势体制（闸门用）
# ════════════════════════════════════════════════════════════════════
def trend_regime(df: pd.DataFrame) -> Literal["多头", "空头", "中性"]:
    """多头：close>ma60 且 ma20>ma60 且 ma60 近 N 日上行；空头镜像；其余中性。"""
    close = df["close"].iloc[-1]
    ma20 = df["ma20"].iloc[-1]
    ma60 = df["ma60"].iloc[-1]
    if pd.isna(ma60) or pd.isna(ma20):
        return "中性"
    if len(df) > MA60_SLOPE_LOOKBACK and not pd.isna(df["ma60"].iloc[-1 - MA60_SLOPE_LOOKBACK]):
        slope_up = ma60 > df["ma60"].iloc[-1 - MA60_SLOPE_LOOKBACK]
        slope_dn = ma60 < df["ma60"].iloc[-1 - MA60_SLOPE_LOOKBACK]
    else:
        slope_up = slope_dn = False
    if close > ma60 and ma20 > ma60 and slope_up:
        return "多头"
    if close < ma60 and ma20 < ma60 and slope_dn:
        return "空头"
    return "中性"


# ════════════════════════════════════════════════════════════════════
# 四族投票 —— 每族独立给出 bull / bear / neutral + 一句理由
# ════════════════════════════════════════════════════════════════════
@dataclass
class FamilyVote:
    vote: str
    reason: str


def vote_trend(df: pd.DataFrame, regime: str) -> FamilyVote:
    """①趋势结构族：采用 regime 方向；理由附均线排列 + MA20×MA60 近 N 日交叉。"""
    cross = _recent_cross(df["ma20"], df["ma60"])
    cross_txt = {"golden": "，MA20×MA60 金叉", "death": "，MA20×MA60 死叉"}.get(cross, "")
    if regime == "多头":
        return FamilyVote("bull", f"多头排列、MA60 上行{cross_txt}")
    if regime == "空头":
        return FamilyVote("bear", f"空头排列、MA60 下行{cross_txt}")
    return FamilyVote("neutral", f"均线缠绕/震荡{cross_txt}")


def vote_momentum(df: pd.DataFrame, divergence: dict) -> FamilyVote:
    """②动量族（MACD）：dif 与 dea 的相对位置定多空，背离可覆盖；零轴位置入理由。"""
    dif = df["dif"].iloc[-1]
    dea = df["dea"].iloc[-1]
    cross = _recent_cross(df["dif"], df["dea"])
    zone = "零上" if dif > 0 else "零下"
    if divergence.get("bottom"):
        return FamilyVote("bull", f"MACD 底背离（{zone}）")
    if divergence.get("top"):
        return FamilyVote("bear", f"MACD 顶背离（{zone}）")
    if dif > dea:
        tag = "金叉" if cross == "golden" else "多头"
        return FamilyVote("bull", f"{zone}{tag}（DIF>DEA）")
    if dif < dea:
        tag = "死叉" if cross == "death" else "空头"
        return FamilyVote("bear", f"{zone}{tag}（DIF<DEA）")
    return FamilyVote("neutral", "MACD 黏合")


def vote_oscillator(df: pd.DataFrame) -> FamilyVote:
    """③摆动族（RSI，均值回归）：超卖修复回升=bull，超买修复回落=bear，其余 neutral。"""
    rsi = df["rsi"]
    cur = rsi.iloc[-1]
    if pd.isna(cur):          # 暖机期未定义 → 不投票
        return FamilyVote("neutral", "RSI 暖机期未定义")
    prev_window = rsi.iloc[-(CROSS_LOOKBACK + 1):-1]
    rising = len(rsi) >= 2 and cur > rsi.iloc[-2]
    falling = len(rsi) >= 2 and cur < rsi.iloc[-2]
    if (prev_window <= RSI_OVERSOLD).any() and cur > RSI_OVERSOLD and rising:
        return FamilyVote("bull", f"RSI 超卖修复回升（{cur:.0f}）")
    if (prev_window >= RSI_OVERBOUGHT).any() and cur < RSI_OVERBOUGHT and falling:
        return FamilyVote("bear", f"RSI 超买修复回落（{cur:.0f}）")
    return FamilyVote("neutral", f"RSI {cur:.0f}，中性")


def vote_breakout(df: pd.DataFrame, support: float, resistance: float,
                  vratio: float) -> FamilyVote:
    """④量价突破族（事件性，无事件=neutral）：放量破阻=bull，放量破支=bear。"""
    close = df["close"].iloc[-1]
    confirmed = (not pd.isna(vratio)) and vratio > VOL_BREAKOUT_RATIO
    if confirmed and close > resistance:
        return FamilyVote("bull", f"放量突破 30 日阻力（量比 {vratio:.1f}）")
    if confirmed and close < support:
        return FamilyVote("bear", f"放量跌破 30 日支撑（量比 {vratio:.1f}）")
    return FamilyVote("neutral", "无有效突破")


# ════════════════════════════════════════════════════════════════════
# 合流 + 体制闸门 → 方向 / 强度
# ════════════════════════════════════════════════════════════════════
@dataclass
class Signal:
    direction: str       # 买入 / 卖出 / 中性
    strength: str        # 强 / 中 / 弱 / 无
    counter_trend: bool
    conflict: bool
    bull_count: int
    bear_count: int


def _tier(count: int) -> str:
    if count >= CONFLUENCE_STRONG:
        return "强"
    if count >= CONFLUENCE_MEDIUM:
        return "中"
    if count == 1:
        return "弱"
    return "无"


def combine(votes: dict[str, FamilyVote], regime: str) -> Signal:
    """合流定强弱 + 体制闸门定顺逆（详见 docstring 规则）。"""
    bull = sum(1 for v in votes.values() if v.vote == "bull")
    bear = sum(1 for v in votes.values() if v.vote == "bear")

    # 矛盾：多空都达到中信号门槛
    if bull >= CONFLUENCE_MEDIUM and bear >= CONFLUENCE_MEDIUM:
        return Signal("中性", "无", False, True, bull, bear)

    if bull > bear:
        direction, count = "买入", bull
    elif bear > bull:
        direction, count = "卖出", bear
    else:
        return Signal("中性", "无", False, False, bull, bear)

    strength = _tier(count)

    # 体制闸门：方向与趋势族相反 = 逆势
    trend_vote = votes["trend"].vote
    counter = (direction == "买入" and trend_vote == "bear") or \
              (direction == "卖出" and trend_vote == "bull")
    # 逆势封顶为"弱"，除非已构成 ≥3 族反转组合（强度本就达"强"）
    if counter and count < CONFLUENCE_STRONG:
        strength = "弱"
    return Signal(direction, strength, counter, False, bull, bear)


# ════════════════════════════════════════════════════════════════════
# 顶层编排
# ════════════════════════════════════════════════════════════════════
def _macd_state(dif, dea) -> str:
    zone = "零上" if dif > 0 else "零下"
    side = "多头" if dif > dea else ("空头" if dif < dea else "黏合")
    return f"{zone}{side}"


def compute_for_ticker(ticker: str, csv_path: str | Path,
                       last_row_override: Optional[dict] = None) -> dict:
    """跑完整流水线，返回符合 SIGNAL_SCHEMA 的 dict。"""
    df = load_prices(csv_path, last_row_override)
    as_of = df["date"].iloc[-1].strftime("%Y-%m-%d")
    n = len(df)

    add_moving_averages(df)
    add_macd(df)
    add_rsi(df)

    indicators_base = {
        "close": _r(df["close"].iloc[-1]),
        "ma20": _r(df["ma20"].iloc[-1]), "ma60": _r(df["ma60"].iloc[-1]),
        "ma250": _r(df["ma250"].iloc[-1]),
        "ma250_fallback": bool(df.attrs.get("ma250_fallback", False)),
        "macd": {"dif": _r(df["dif"].iloc[-1]), "dea": _r(df["dea"].iloc[-1]),
                 "hist": _r(df["hist"].iloc[-1]),
                 "state": _macd_state(df["dif"].iloc[-1], df["dea"].iloc[-1])},
        "rsi": _r(df["rsi"].iloc[-1], 2),
    }

    if n < MIN_HISTORY:
        indicators_base.update({"vol_ratio": None, "support": None, "resistance": None})
        return {
            "ticker": ticker, "as_of": as_of, "history_rows": n,
            "data_sufficient": False, "trend_posture": "中性",
            "direction": "中性", "strength": "无", "counter_trend": False,
            "conflict": False, "confluence": {"bull": 0, "bear": 0},
            "families": {}, "indicators": indicators_base,
            "structure": {"swing": "mixed", "divergence": {"bottom": False, "top": False}},
            "escalate_full_ta": False,
            "notes": [f"历史仅 {n} 行（<{MIN_HISTORY}），不出方向信号"],
        }

    support, resistance = support_resistance(df)
    vratio = volume_ratio(df)
    hi, lo = find_swings(df)
    divergence = detect_divergence(df, hi, lo)
    structure = swing_structure(df, hi, lo)
    regime = trend_regime(df)

    votes = {
        "trend": vote_trend(df, regime),
        "momentum": vote_momentum(df, divergence),
        "oscillator": vote_oscillator(df),
        "breakout": vote_breakout(df, support, resistance, vratio),
    }
    sig = combine(votes, regime)

    indicators_base.update({
        "vol_ratio": _r(vratio, 2), "support": _r(support), "resistance": _r(resistance),
    })

    # 2026-09-26 收紧（用户要求）：原规则「强/中 或 任一量价突破 或 任一背离」每天触发 24–27 家，
    # 19–25 份完整 TA 报告几乎只进档案、下游无人读取。现只保留两种情况：
    #   1) 强信号（≥3 族合流）；2) 中信号且量价族给出有效突破（方向有量能确认）。
    # 回测 9/19–9/26：每天 0–5 家（原 24–27 家）。背离与孤立突破仍记录在 structure / families 里，不再单独触发。
    escalate = sig.strength == "强" \
        or (sig.strength == "中" and votes["breakout"].vote != "neutral")

    notes = []
    if df.attrs.get("ma250_fallback"):
        notes.append(f"⚠️ 历史不足 250 日，MA250 用 MA{min(MA250_FALLBACK, n)} 替代")

    return {
        "ticker": ticker, "as_of": as_of, "history_rows": n,
        "data_sufficient": True, "trend_posture": regime,
        "direction": sig.direction, "strength": sig.strength,
        "counter_trend": sig.counter_trend, "conflict": sig.conflict,
        "confluence": {"bull": sig.bull_count, "bear": sig.bear_count},
        "families": {k: {"vote": v.vote, "reason": v.reason} for k, v in votes.items()},
        "indicators": indicators_base,
        "structure": {"swing": structure, "divergence": divergence},
        "escalate_full_ta": bool(escalate),
        "notes": notes,
    }


def main(argv: list[str]) -> int:
    """用法：python3 compute_signals.py <TICKER:csv_path> [<TICKER:csv_path> ...]"""
    if not argv:
        print("用法: python3 compute_signals.py TICKER:/path/to.csv [...]", file=sys.stderr)
        return 1
    results = []
    for arg in argv:
        ticker, _, path = arg.partition(":")
        try:
            results.append(compute_for_ticker(ticker, path))
        except Exception as e:  # noqa: BLE001 — 单票失败不阻断其余
            results.append({"ticker": ticker, "error": str(e)})
    for r in results:
        if "error" in r:
            print(f"  x {r['ticker']}: {r['error']}", file=sys.stderr)
        else:
            print(f"  - {r['ticker']:8} {r['direction']}/{r['strength']:2} "
                  f"posture={r['trend_posture']} "
                  f"{'[逆势]' if r['counter_trend'] else ''}"
                  f"{'[矛盾]' if r['conflict'] else ''}", file=sys.stderr)
    print("SIGNALS_JSON: " + json.dumps(results, ensure_ascii=False))
    return 0


# ════════════════════════════════════════════════════════════════════
# 输出 schema（每只股票）—— 供 scanner Step 4 落进 briefing_data.json
# ════════════════════════════════════════════════════════════════════
SIGNAL_SCHEMA = {
    "ticker": "APP", "as_of": "2026-06-23", "history_rows": 274,
    "data_sufficient": True,
    "trend_posture": "多头", "direction": "买入", "strength": "强",
    "counter_trend": False, "conflict": False,
    "confluence": {"bull": 3, "bear": 0},
    "families": {
        "trend":      {"vote": "bull", "reason": "多头排列、MA60 上行"},
        "momentum":   {"vote": "bull", "reason": "零上金叉（DIF>DEA）"},
        "oscillator": {"vote": "neutral", "reason": "RSI 58，中性"},
        "breakout":   {"vote": "bull", "reason": "放量突破 30 日阻力（量比 1.4）"},
    },
    "indicators": {
        "close": 467.02, "ma20": None, "ma60": None, "ma250": None,
        "ma250_fallback": False,
        "macd": {"dif": None, "dea": None, "hist": None, "state": "零上多头"},
        "rsi": 58.0, "vol_ratio": 1.4, "support": None, "resistance": None,
    },
    "structure": {"swing": "HH_HL", "divergence": {"bottom": False, "top": False}},
    "escalate_full_ta": True, "notes": [],
}

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

