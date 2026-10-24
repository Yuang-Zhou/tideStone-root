r"""
validate_market_data.py — 每日扫描 Step 0 的 bash 侧数据时效校验
================================================================

背景：bash sandbox 的 FUSE 挂载会缓存陈旧文件（2026-05-13 / 2026-06-03 / 2026-06-10
三次误判事件的根因）。本脚本把"人工 Read vs bash 多文件交叉验证"收敛为一次机器判定：

  权威事实源 = _system/market_data/_data_status.json（fetcher 在宿主机写入，含每
  ticker 的 last_date + 最后一行 OHLCV）。扫描端先用 Read 工具读清单（真实状态），
  再跑本脚本（bash/FUSE 视角），比对即可知道 bash 缓存是否可信。

用法（在 Projects 根目录下）：
    python3 _system/scripts/validate_market_data.py
    python3 _system/scripts/validate_market_data.py --strict  # 发布前：fetch 有任何失败也返回非零

输出：
    - 人类可读摘要（stdout）
    - 最后一行：VALIDATION_JSON: {...}   ← 扫描任务机器解析这一行

退出码：
    0 = PASS              bash 视角与清单完全一致，可直接在 bash 里跑 pandas
    2 = DATA_NOT_TODAY    清单不是今天生成的（fetch 未跑或失败）→ 按数据过期处理
    3 = BASH_CACHE_STALE  bash 看到的 CSV 落后于清单 → 对受影响 ticker 注入
                          LAST_ROW_OVERRIDE（数据直接取自 Read 工具读到的清单），
                          大面积陈旧时切 /tmp 工作流
    4 = MANIFEST_MISSING  清单不存在/损坏 → 退回手动双工具交叉验证流程
    5 = FETCH_FAILURES    --strict 下清单记录了拉取失败 → 禁止发布不完整行情

注意：本脚本自身跑在 bash 里，它读到的清单同样可能是 FUSE 缓存旧版。所以扫描任务
必须比对「Read 工具读到的清单 generated_at」与「本脚本输出的 manifest_generated_at」：
两者不一致 = 连清单都被缓存了 = 一律按 BASH_CACHE_STALE 处理。
"""
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent          # Projects 根目录
MARKET_DATA = ROOT / "_system" / "market_data"
MANIFEST = MARKET_DATA / "_data_status.json"
REGISTRY = ROOT / "_system" / "portfolio_registry.md"

TAIL_BYTES = 4096


def last_data_line(path):
    """高效读 CSV 最后一个非空行（bash/FUSE 视角）"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        return lines[-1] if lines else None
    except FileNotFoundError:
        return None


def csv_last_date(path):
    line = last_data_line(path)
    if not line:
        return None
    first = line.split(",")[0].strip()
    return first if len(first) == 10 and first[4] == "-" else None


def registry_bash_view():
    """bash 视角的注册表指纹，供扫描任务与 Read 工具尾部读取比对（FUSE 截断检测）"""
    try:
        with open(REGISTRY, "rb") as f:
            data = f.read()
        # FUSE 缓存陈旧的典型特征：文件被改小后，bash 仍按旧 size 读，尾部用 NUL 填充。
        # 出现 NUL = bash 视角的注册表 100% 不可信，扫描端必须走 Read→/tmp 解析路线。
        has_nul = b"\x00" in data
        text = data.replace(b"\x00", b"").decode("utf-8", errors="replace")
        lines = text.splitlines()
        last_nonempty = next((ln for ln in reversed(lines) if ln.strip()), "")
        return {
            "lines": len(lines),
            "bytes": len(data),
            "md5": hashlib.md5(data).hexdigest(),
            "last_line_head": last_nonempty[:80],
            "nul_padding_detected": has_nul,
        }
    except FileNotFoundError:
        return {"error": "registry not found"}


def main():
    strict = "--strict" in sys.argv
    result = {
        "verdict": None,
        "manifest_generated_at": None,
        "manifest_generated_by": None,
        "markets": {},
        "checked": 0,
        "match": 0,
        "bash_older": [],   # [{ticker, bash_date, manifest_date}]
        "bash_newer": [],
        "missing_csv": [],
        "manifest_failures": [],
        "registry_bash": registry_bash_view(),
    }

    # 1. 读清单（bash 视角）
    try:
        with open(MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        result["verdict"] = "MANIFEST_MISSING"
        print(f"❌ 清单不可用：{MANIFEST}（{type(e).__name__}）")
        print("→ 退回手动流程：双工具交叉验证（数据校验流程_MANDATORY.md 附录）")
        print("VALIDATION_JSON: " + json.dumps(result, ensure_ascii=False))
        sys.exit(4)

    result["manifest_generated_at"] = manifest.get("generated_at")
    result["manifest_generated_by"] = manifest.get("generated_by")
    result["markets"] = manifest.get("markets", {})
    result["manifest_failures"] = manifest.get("failures", [])

    # 2. 逐 ticker 比对 bash 视角 CSV 尾行 vs 清单
    groups = [
        (manifest.get("tickers", {}), MARKET_DATA),
        (manifest.get("indices", {}), MARKET_DATA / "indices"),
    ]
    for entries, base in groups:
        for name, entry in entries.items():
            if not entry or entry.get("status") == "fail":
                continue
            result["checked"] += 1
            bash_date = csv_last_date(base / f"{name}.csv")
            m_date = entry.get("last_date")
            if bash_date is None:
                result["missing_csv"].append(name)
            elif bash_date == m_date:
                result["match"] += 1
            elif bash_date < m_date:
                result["bash_older"].append(
                    {"ticker": name, "bash_date": bash_date, "manifest_date": m_date})
            else:
                result["bash_newer"].append(
                    {"ticker": name, "bash_date": bash_date, "manifest_date": m_date})

    # 3. 判定
    gen_date = (result["manifest_generated_at"] or "")[:10]
    if strict and result["manifest_failures"]:
        result["verdict"] = "FETCH_FAILURES"
        code = 5
    elif result["bash_older"] or result["bash_newer"] or result["missing_csv"]:
        # bash_newer 意味着 bash 读到的"清单"本身是旧缓存 → 同样不可信
        result["verdict"] = "BASH_CACHE_STALE"
        code = 3
    elif gen_date != date.today().isoformat():
        result["verdict"] = "DATA_NOT_TODAY"
        code = 2
    else:
        result["verdict"] = "PASS"
        code = 0

    # 4. 人类可读摘要
    print(f"=== 行情数据时效校验（bash/FUSE 视角） ===")
    print(f"清单生成时间：{result['manifest_generated_at']}（{result['manifest_generated_by']}）")
    for m, info in sorted(result["markets"].items()):
        print(f"  {m}: 最新 {info.get('max_last_date')}（{info.get('tickers')} 只）")
    print(f"比对：{result['checked']} 个文件，{result['match']} 一致，"
          f"{len(result['bash_older'])} bash偏旧，{len(result['bash_newer'])} bash偏新，"
          f"{len(result['missing_csv'])} 缺失")
    if result["manifest_failures"]:
        print(f"⚠️ fetch 阶段失败 {len(result['manifest_failures'])} 项："
              + "; ".join(result["manifest_failures"][:5]))
    for item in result["bash_older"][:10]:
        print(f"  ⚠️ {item['ticker']}: bash={item['bash_date']} < 清单={item['manifest_date']}（FUSE 缓存陈旧）")
    if result["registry_bash"].get("nul_padding_detected"):
        print("  ⚠️ 注册表 bash 视角含 NUL 填充 = FUSE 缓存陈旧，注册表解析必须走 Read→/tmp 路线（Step 0.2b）")
    print(f"判定：{result['verdict']}")
    print("VALIDATION_JSON: " + json.dumps(result, ensure_ascii=False))
    sys.exit(code)


if __name__ == "__main__":
    main()
