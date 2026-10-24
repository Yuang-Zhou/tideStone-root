#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
host_signals.py — 阶段 0/1：在【宿主机】计算全部技术信号，产出权威清单
=====================================================================

定位
----
把 daily-portfolio-scanner 的 Step 3（技术信号计算）从沙箱 bash 搬到宿主机。
宿主机直接读本地 CSV，**不经过 Cowork 沙箱的 FUSE 桥接**，因此永远读到真实
最新数据——彻底规避「bash 缓存陈旧 / 截断 / 夹 NUL」这一长期顽疾
（见 `_system/数据校验流程_MANDATORY.md` 的三次事故根因）。

它做什么
--------
1. 读宿主机权威清单 `_system/market_data/_data_status.json`（fetcher 写的）
   → 拿到当天应计算的 ticker 全集（增删公司自动同步，无硬编码列表）。
2. 对每只 ticker，用既有引擎 `_system/scripts/compute_signals.py` 的
   `compute_for_ticker()` 计算四族投票信号（**不改动该引擎一个字节，只 import**）。
3. 额外算 `change_pct`（当日收盘 vs 上一交易日收盘），补全看板 snapshot 所需。
4. 汇总 `signal_stats`（buy/sell/neutral/strong/escalated/counter_trend/conflict）。
5. 写出权威信号清单 `_system/market_data/_signals_status.json`（UTF-8、缩进）。

它【不】做什么（安全边界）
------------------------
- 不修改任何现有脚本/数据/注册表，不删除任何文件。
- 不触网、不做新闻/叙事（那是 Agent 的活）。
- 不渲染看板、不发布 artifact（阶段 3 再议）。
- 失败的单票只记录、不阻断其余；最后用退出码反映整体状态。

退出码（对齐 fetcher 习惯）
--------------------------
- 0：全部 ticker 计算成功
- 2：部分 ticker 失败（清单仍会写出，failures[] 列明）
- 1：致命错误（清单缺失/无法写出等），未产出文件

用法（宿主机）
--------------
    py -3.11 host_signals.py
（由 `跑信号.bat` 调用；起始目录任意，脚本按自身位置解析路径。）
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

# ── 路径解析（按脚本自身位置，cwd 无关）────────────────────────────────
#   本文件位于  <Projects>/_system/host_pipeline/host_signals.py
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / "scripts"))
from tidestone_paths import PROJECTS_ROOT, SOURCE_SCRIPTS
PROJECTS = PROJECTS_ROOT                      # …/Projects
SYSTEM = PROJECTS / "_system"
SCRIPTS = SOURCE_SCRIPTS
MARKET = SYSTEM / "market_data"
MANIFEST = MARKET / "_data_status.json"
OUT = MARKET / "_signals_status.json"

SCHEMA_VERSION = 1

# 让 import compute_signals 能找到引擎（不改引擎，仅加入搜索路径）
sys.path.insert(0, str(SCRIPTS))


def _log(msg: str) -> None:
    print(msg, flush=True)


def _read_manifest() -> dict:
    """读 fetcher 写的权威清单。宿主机本地读，不走 FUSE。"""
    with open(MANIFEST, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _prev_close(csv_path: Path, as_of: str) -> float | None:
    """上一交易日收盘（用于 change_pct）。容错：读不到返回 None。"""
    try:
        import pandas as pd
        df = pd.read_csv(csv_path)
        df = df.dropna(subset=["close"]).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        if len(df) < 2:
            return None
        cutoff = pd.to_datetime(as_of)
        sub = df[df["date"] < cutoff]
        if len(sub):
            return float(sub["close"].iloc[-1])
        return float(df["close"].iloc[-2])
    except Exception:
        return None


def main() -> int:
    started = dt.datetime.now().astimezone()
    _log(f"[host_signals] start {started.isoformat(timespec='seconds')}")

    if not MANIFEST.exists():
        _log(f"[FATAL] 权威清单缺失：{MANIFEST} —— 请先跑 market_data_fetcher.py")
        return 1
    try:
        manifest = _read_manifest()
    except Exception as e:  # noqa: BLE001
        _log(f"[FATAL] 清单解析失败：{e}")
        return 1

    try:
        import compute_signals as cs
    except Exception as e:  # noqa: BLE001
        _log(f"[FATAL] 无法 import compute_signals（检查 {SCRIPTS}）：{e}")
        return 1

    manifest_tickers: dict = manifest.get("tickers", {}) or {}
    if not manifest_tickers:
        _log("[FATAL] 清单 tickers 为空，无可计算标的")
        return 1

    signals: dict[str, dict] = {}
    failures: list[dict] = []

    for ticker, meta in manifest_tickers.items():
        csv_path = MARKET / f"{ticker}.csv"
        if not csv_path.exists():
            failures.append({"ticker": ticker, "reason": f"CSV 不存在: {csv_path.name}"})
            _log(f"  x {ticker}: CSV 缺失")
            continue
        # 用清单 last_row 作 override（belt-and-suspenders：即便写入有竞态，
        # 也保证信号收盘价 == 清单 last_row.close；CSV 已最新时 override 不生效）。
        lr = meta.get("last_row") if isinstance(meta, dict) else None
        override = None
        if isinstance(lr, dict) and lr.get("date"):
            override = {
                "date": lr["date"],
                "open": lr.get("open"), "high": lr.get("high"),
                "low": lr.get("low"), "close": lr.get("close"),
                "volume": lr.get("volume"),
            }
        try:
            sig = cs.compute_for_ticker(ticker, str(csv_path), last_row_override=override)
            pc = _prev_close(csv_path, sig.get("as_of", ""))
            close = sig.get("indicators", {}).get("close")
            sig["prev_close"] = pc
            sig["change_pct"] = (
                round((close / pc - 1) * 100, 2)
                if (isinstance(close, (int, float)) and isinstance(pc, (int, float)) and pc)
                else None
            )
            signals[ticker] = sig
            tag = f"{sig.get('direction')}/{sig.get('strength')}"
            _log(f"  - {ticker:10} {tag:8} posture={sig.get('trend_posture')}")
        except Exception as e:  # noqa: BLE001 — 单票失败不阻断
            failures.append({"ticker": ticker, "reason": str(e)})
            _log(f"  x {ticker}: {e}")

    # ── 汇总 signal_stats ────────────────────────────────────────────
    stats = {k: [] for k in
             ("buy", "sell", "neutral", "strong", "escalated",
              "counter_trend", "conflict")}
    for t, s in signals.items():
        d = s.get("direction")
        if d == "买入":
            stats["buy"].append(t)
        elif d == "卖出":
            stats["sell"].append(t)
        else:
            stats["neutral"].append(t)
        if s.get("strength") == "强":
            stats["strong"].append(t)
        if s.get("escalate_full_ta"):
            stats["escalated"].append(t)
        if s.get("counter_trend"):
            stats["counter_trend"].append(t)
        if s.get("conflict"):
            stats["conflict"].append(t)

    finished = dt.datetime.now().astimezone()
    out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": finished.isoformat(timespec="seconds"),
        "generated_by": "host_signals.py（宿主机，无 FUSE）",
        "source_manifest_generated_at": manifest.get("generated_at"),
        "engine": "compute_signals.py 四族投票（纯技术，T1-T7 已废止）",
        "counts": {
            "computed": len(signals),
            "failed": len(failures),
            "manifest_tickers": len(manifest_tickers),
        },
        "signal_stats": stats,
        "signals": signals,
        "failures": failures,
    }

    # 原子写：先写临时文件再替换，避免读者读到半截
    tmp = OUT.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    tmp.replace(OUT)

    _log(f"[host_signals] wrote {OUT.name}: "
         f"computed={len(signals)} failed={len(failures)} "
         f"(buy={len(stats['buy'])} sell={len(stats['sell'])} "
         f"neutral={len(stats['neutral'])} escalated={len(stats['escalated'])})")
    _log(f"[host_signals] done {finished.isoformat(timespec='seconds')}")

    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

