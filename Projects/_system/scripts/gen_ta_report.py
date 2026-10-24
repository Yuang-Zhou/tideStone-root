#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_ta_report.py — 由每日扫描器调用，为 escalate_full_ta=True 的公司生成
纯量化七维技术分析报告（与 compute_signals.py 同口径，不掺基本面）。

用法：
    python3 _system/scripts/gen_ta_report.py --date 2026-09-04 --tickers APP,DUOL,...

数据源：仅 _system/market_data/{TICKER}.csv + indices/{SPX|HSI|CSI300}.csv
输出：  {folder}/技术分析/{TICKER}_技术分析_{YYYYMMDD}.md
"""
import argparse, json, os, sys
import pandas as pd
import numpy as np

from tidestone_paths import PROJECTS_ROOT
ROOT = str(PROJECTS_ROOT)
MD = os.path.join(ROOT, "_system", "market_data")

BENCH = {"HK": "HSI", "CN": "CSI300", "US": "SPX"}


def market_of(t):
    if t.endswith(".HK"):
        return "HK"
    if t.endswith((".SZ", ".SH", ".BJ")):
        return "CN"
    return "US"


def load(path):
    df = pd.read_csv(path, header=None,
                     names=["date", "open", "high", "low", "close", "vol", "amt"])
    df = df[pd.to_numeric(df["close"], errors="coerce").notna()].copy()
    for c in ["open", "high", "low", "close", "vol"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.reset_index(drop=True)


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"].shift()
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def build(ticker, folder, sig, date_str, name=""):
    csv = os.path.join(MD, ticker + ".csv")
    if not os.path.exists(csv):
        return None, "csv missing"
    df = load(csv)
    # keep the report on the same price data as the briefing:
    # 1) if the fetcher manifest has a newer / different last row than the CSV (stale mount cache), use the manifest row
    try:
        lr = json.load(open(os.path.join(MD, "_data_status.json"), encoding="utf-8"))["tickers"][ticker]["last_row"]
        d_csv = str(df["date"].iloc[-1])[:10]
        row = {"date": lr["date"], "open": lr["open"], "high": lr["high"], "low": lr["low"],
               "close": lr["close"], "vol": lr.get("volume"), "amt": None}
        if lr["date"] > d_csv:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        elif lr["date"] == d_csv and abs(float(lr["close"]) - float(df["close"].iloc[-1])) > 1e-4 * max(1.0, abs(float(lr["close"]))):
            for k, v in row.items():
                if v is not None:
                    df.loc[df.index[-1], k] = v
    except Exception:
        pass
    # 2) refuse to write a report whose last price disagrees with the signal it is built on
    sc = ((sig.get("indicators") or {}).get("close"))
    if sc is not None:
        lc = float(df["close"].iloc[-1])
        if abs(lc - float(sc)) > 1e-3 * max(1.0, abs(float(sc))):
            return None, "price mismatch: csv/manifest close %s (%s) vs signal close %s (as_of %s)" % (
                lc, str(df["date"].iloc[-1])[:10], sc, sig.get("as_of"))
    if len(df) < 60:
        return None, "history < 60"
    c = df["close"]
    last = c.iloc[-1]
    asof = df["date"].iloc[-1]
    n = len(df)
    ma20, ma60 = c.tail(20).mean(), c.tail(60).mean()
    ma_n = min(250, n)
    ma250 = c.tail(ma_n).mean()
    dif = ema(c, 12) - ema(c, 26)
    dea = ema(dif, 9)
    hist = (dif - dea) * 2
    r = rsi(c)
    vol20 = df["vol"].tail(20).mean()
    volr = df["vol"].iloc[-1] / vol20 if vol20 else float("nan")
    win = df.tail(30)
    sup, res = win["low"].min(), win["high"].max()
    y = df.tail(min(250, n))
    y_lo, y_hi = y["low"].min(), y["high"].max()
    a = atr(df).iloc[-1]

    bm = BENCH[market_of(ticker)]
    bpath = os.path.join(MD, "indices", bm + ".csv")
    rel = {}
    if os.path.exists(bpath):
        b = load(bpath)
        for w in (20, 60, 120):
            if len(df) > w and len(b) > w:
                rel[w] = ((c.iloc[-1] / c.iloc[-1 - w] - 1) -
                          (b["close"].iloc[-1] / b["close"].iloc[-1 - w] - 1)) * 100
    abs_ret = {w: (c.iloc[-1] / c.iloc[-1 - w] - 1) * 100 for w in (5, 20, 60) if len(df) > w}
    vol_ann = c.pct_change().tail(60).std() * (252 ** 0.5) * 100

    ccy = {"HK": "HK$", "CN": "¥"}.get(market_of(ticker), "$")
    f = sig["families"]
    st = sig["structure"]
    pos52 = (last - y_lo) / (y_hi - y_lo) * 100 if y_hi > y_lo else float("nan")
    arr = ("空头排列（MA20<MA60<MA250）" if ma20 < ma60 < ma250 else
           "多头排列（MA20>MA60>MA250）" if ma20 > ma60 > ma250 else "均线交织，无明确排列")

    def pc(x, base=last):
        return f"{(x/base-1)*100:+.1f}%"

    L = []
    A = L.append
    A(f"# {name or ticker}（{ticker}）技术分析\n")
    A(f"**生成日期：** {date_str}　**数据截至：** {asof}　**样本：** {n} 根日K")
    A(f"**数据源：** 本机 `_system/market_data/{ticker}.csv` + `_system/market_data/indices/{bm}.csv`")
    A(f"**触发原因：** 每日扫描技术信号引擎判定 `escalate_full_ta=True`"
      f"（方向 {sig['direction']}／强度 {sig['strength']}，合流 多{sig['confluence']['bull']}／空{sig['confluence']['bear']}）\n")
    A("> ⚠️ 本报告由每日扫描器自动生成，纯量化口径、不掺基本面。仅从本机行情 CSV 计算，未调用任何外部行情终端。\n")
    A("---\n")
    A("## 一、结论速览\n")
    A("| 项 | 读数 |\n|:---|:---|")
    A(f"| 最新收盘 | **{ccy}{last:,.2f}**（{asof}） |")
    A(f"| 技术方向／强度 | **{sig['direction']} / {sig['strength']}** |")
    A(f"| 趋势体制 | {sig['trend_posture']} |")
    A(f"| 四族投票 | 趋势 {f['trend']['vote']}｜动量 {f['momentum']['vote']}｜摆动 {f['oscillator']['vote']}｜量价 {f['breakout']['vote']} |")
    A(f"| 逆势／矛盾 | {'有' if sig['counter_trend'] else '无'} / {'有' if sig['conflict'] else '无'} |")
    A(f"| 52周区间位置 | {pos52:.0f}%（低 {ccy}{y_lo:,.2f} — 高 {ccy}{y_hi:,.2f}） |\n")
    A(f"**一句话：** 当前处于「{sig['trend_posture']}」体制下的 {sig['direction']}（{sig['strength']}）信号，"
      f"四族中 {sig['confluence']['bull']} 族看多、{sig['confluence']['bear']} 族看空，"
      f"{'已达' if sig['strength']=='强' else '未达'}三族合流的强信号门槛。\n")
    A("---\n")
    A("## 二、七维量化分析\n")
    A("### 1. 趋势（均线系统）\n")
    A("| 均线 | 数值 | 价格相对位置 |\n|:---|---:|:---|")
    A(f"| MA20 | {ccy}{ma20:,.2f} | {'上方' if last>ma20 else '下方'} {abs(last/ma20-1)*100:.1f}% |")
    A(f"| MA60 | {ccy}{ma60:,.2f} | {'上方' if last>ma60 else '下方'} {abs(last/ma60-1)*100:.1f}% |")
    A(f"| MA{ma_n}{'（不足250日，降级）' if ma_n<250 else ''} | {ccy}{ma250:,.2f} | {'上方' if last>ma250 else '下方'} {abs(last/ma250-1)*100:.1f}% |\n")
    A(f"- 均线排列：{arr}")
    A(f"- 引擎判定：**{f['trend']['vote']}** — {f['trend']['reason']}\n")
    A("### 2. 动量（MACD 12,26,9）\n")
    A("| 指标 | 数值 |\n|:---|---:|")
    A(f"| DIF | {dif.iloc[-1]:.4f} |")
    A(f"| DEA | {dea.iloc[-1]:.4f} |")
    A(f"| 柱 (HIST) | {hist.iloc[-1]:.4f} |")
    A(f"| 状态 | {sig['indicators']['macd']['state']} |\n")
    A(f"- 引擎判定：**{f['momentum']['vote']}** — {f['momentum']['reason']}")
    A("- 柱体近 5 日：" + " → ".join(f"{v:.2f}" for v in hist.tail(5)) + "\n")
    A("### 3. 摆动指标（RSI 14）\n")
    A(f"- RSI(14) = **{r.iloc[-1]:.1f}**（超买阈 75／超卖阈 25）")
    A(f"- 近 20 日 RSI 区间：{r.tail(20).min():.1f} — {r.tail(20).max():.1f}")
    A(f"- 引擎判定：**{f['oscillator']['vote']}** — {f['oscillator']['reason']}\n")
    A("### 4. 量价\n")
    A(f"- 当日量能比（成交量÷20日均量）= **{volr:.2f}**（>1.5 放量／<0.7 缩量）")
    A("- 近 5 日量能比：" + " / ".join(f"{v:.2f}" for v in (df['vol'].tail(5) / vol20)) + "")
    A(f"- 引擎判定：**{f['breakout']['vote']}** — {f['breakout']['reason']}\n")
    A("### 5. 形态与结构\n")
    A(f"- 摆动结构：**{st['swing']}**（HH_HL=高点抬高低点抬高／LH_LL=高点降低低点降低／mixed=混合）")
    A(f"- 底背离：{'✅ 有' if st['divergence']['bottom'] else '无'}　顶背离：{'✅ 有' if st['divergence']['top'] else '无'}\n")
    A("### 6. 支撑与阻力（近 30 日）\n")
    A("| 位置 | 价格 | 距现价 |\n|:---|---:|---:|")
    A(f"| 阻力 | {ccy}{res:,.2f} | {pc(res)} |")
    A(f"| 现价 | **{ccy}{last:,.2f}** | — |")
    A(f"| 支撑 | {ccy}{sup:,.2f} | {pc(sup)} |")
    A(f"| 52周高 | {ccy}{y_hi:,.2f} | {pc(y_hi)} |")
    A(f"| 52周低 | {ccy}{y_lo:,.2f} | {pc(y_lo)} |\n")
    A(f"### 7. 相对强度（vs {bm}）与波动率\n")
    A("| 窗口 | 超额收益 |\n|:---|---:|")
    for w in (20, 60, 120):
        if w in rel:
            A(f"| {w}日 | {rel[w]:+.2f}pct |")
    A("")
    A("| 绝对涨跌 | " + " / ".join(f"{w}日 {v:+.2f}%" for w, v in abs_ret.items()) + " |\n")
    A(f"- ATR(14) = {ccy}{a:,.2f}（占现价 {a/last*100:.2f}%）")
    A(f"- 60日年化波动率 = {vol_ann:.1f}%\n")
    A("---\n")
    A("## 三、操作位（纯技术，不含估值判断）\n")
    A("| 场景 | 触发 | 位置 |\n|:---|:---|:---|")
    A(f"| 上破确认 | 收盘站上 {ccy}{res:,.2f} 且量能比 >1.5 | 追踪至 52周高 {ccy}{y_hi:,.2f} |")
    A(f"| 下破确认 | 收盘跌破 {ccy}{sup:,.2f} | 下一参考 52周低 {ccy}{y_lo:,.2f} |")
    A(f"| 技术止损参考 | 现价 − 2×ATR | {ccy}{last-2*a:,.2f} |")
    A(f"| 震荡区间 | {ccy}{sup:,.2f} — {ccy}{res:,.2f} | 区间宽度 {(res/sup-1)*100:.1f}% |\n")
    A("---\n")
    A("## 四、与估值区间的交叉参考（仅供人工撮合，引擎不掺入）\n")
    for k, v in (sig.get("_reg") or {}).items():
        if v:
            A(f"- {k}：{v}")
    A("\n> 技术信号与估值区间的撮合由人工/决策层完成，本报告不给出综合买卖建议。\n")
    A("---\n")
    A(f"*由 daily-portfolio-scanner v phase2-v2 于 {date_str} 自动生成。数据截至 {asof}。*")

    outdir = os.path.join(ROOT, folder, "技术分析")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, f"{ticker}_技术分析_{date_str.replace('-','')}.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return os.path.relpath(out, ROOT).replace(os.sep, "/"), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--signals", default=None, help="signals JSON ({signals:{ticker:...}} or {ticker:...}); default = market_data/_signals_status.json")
    ap.add_argument("--reg", default=None, help="可选 JSON：{ticker:{评级,买入区,卖出区,加权目标价}}")
    args = ap.parse_args()

    sig_path = args.signals or os.path.join(MD, "_signals_status.json")
    if not os.path.exists(sig_path):
        sys.exit("signals file not found: %s (pass --signals <file> with the signals used for today's briefing)" % sig_path)
    _sd = json.load(open(sig_path, encoding="utf-8"))
    sigs = _sd["signals"] if "signals" in _sd else _sd
    comp = json.load(open(os.path.join(ROOT, "_system", "companies.json"), encoding="utf-8"))["companies"]
    reg = json.load(open(args.reg, encoding="utf-8")) if args.reg else {}

    done, errs = {}, {}
    for t in args.tickers.split(","):
        t = t.strip()
        if not t:
            continue
        if t not in sigs or t not in comp:
            errs[t] = "not in signals/companies"
            continue
        folder = comp[t]["folder"]
        if not os.path.isdir(os.path.join(ROOT, folder)):
            errs[t] = "folder not found on disk"
            continue
        s = dict(sigs[t])
        s["_reg"] = reg.get(t, {})
        p, e = build(t, folder, s, args.date, comp[t].get("name_en") or comp[t].get("name_cn"))
        if e:
            errs[t] = e
        else:
            done[t] = p
    print(json.dumps({"generated": done, "errors": errs}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

