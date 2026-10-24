r"""
market_data_fetcher.py
=======================
每日拉取投资组合 OHLCV 数据，保存为 CSV，供 daily-portfolio-scanner 使用。

数据源策略（替代了之前的 Wind 方案）：
- 美股 + 港股 + 国际指数：yfinance（Yahoo Finance，免费稳定）
- A 股个股 + A 股指数：akshare（开源，对 A 股覆盖最好）

依赖安装（首次）：
    py -3.11 -m pip install yfinance akshare pandas

用法：
    1. 命令行：py -3.11 market_data_fetcher.py
    2. Windows 任务计划程序：每日 08:55 自动跑

输出：
    - CSV：C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\{TICKER}.csv
    - 指数：C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\indices\{INDEX}.csv
    - 日志：C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\fetch_log\fetch_log_{YYYY-MM-DD}.txt
    - 清单：C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\_data_status.json
      （权威 data_as_of 清单：每 ticker 的 last_date + 最后一行 OHLCV + 分市场汇总。
       由宿主机写入、不经过 sandbox FUSE，是每日扫描 Step 0 的唯一可信数据时效来源。）

附加用法：
    py -3.11 market_data_fetcher.py --manifest-only
    不拉数据，只根据磁盘上已有 CSV 重建 _data_status.json（fetch 已跑但清单缺失/损坏时用）。
"""
import json
import os
import random
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# ========== 配置区 ==========
#
# 2026-08-0X 分类重构第 3b 步：行情名单不再手工维护，改从 _system/companies.json 生成。
# 加一家新公司只需要写 companies.json，这里自动跟上——原先要记住同步改两处。
#
#   · A 股 / 北交所（.SZ / .SH / .BJ）→ akshare，symbol = 去掉后缀的 6 位代码
#   · 其余（美股 / 港股）→ yfinance，symbol 默认等于 ticker
#   · 例外走 YF_SYMBOL_OVERRIDES；EXCLUDE 里的标的不拉行情（未上市等）
#
COMPANIES_JSON = Path(__file__).resolve().parent.parent / "companies.json"

# 注册表 ticker 与 yfinance symbol 不一致的特例。
# SATS→ECHO：EchoStar 2026-06-24 变更代码，注册表侧尚未改名（第 3b 步 step4 处理）。
# step4 执行后此表应为空。
YF_SYMBOL_OVERRIDES = {}   # step4 之后已无特例

# 不拉行情的标的（未上市 / 无公开报价）。留空表示全部都拉。
EXCLUDE_TICKERS = set()


def _load_ticker_maps():
    raw = COMPANIES_JSON.read_bytes()
    if b"\x00" in raw:
        raise SystemExit("companies.json 含 NUL 填充（FUSE 缓存现象），请确认后重跑")
    data = json.loads(raw.decode("utf-8"))
    yf, ak = {}, {}
    for tk in data["companies"]:
        if tk in EXCLUDE_TICKERS:
            continue
        if tk.endswith((".SZ", ".SH", ".BJ")):
            ak[tk] = tk.split(".")[0]
        else:
            yf[tk] = YF_SYMBOL_OVERRIDES.get(tk, tk)
    if not yf and not ak:
        raise SystemExit("companies.json 里没有可拉行情的标的")
    return yf, ak


# key 是注册表里的 ticker（也是输出 CSV 文件名），value 是数据源接受的 symbol
YF_TICKERS, AK_TICKERS = _load_ticker_maps()

# 指数：yfinance 拉国际指数，akshare 拉 A 股指数
YF_INDICES = {
    "SPX":    "^GSPC",     # S&P 500
    "NDX":    "^NDX",      # Nasdaq 100
    "HSI":    "^HSI",      # 恒生
    # HSTECH 恒生科技：yfinance ^HSTECH 长期返回空数据，已移除
}

AK_INDICES = {
    # akshare stock_zh_index_daily 用 sh/sz 前缀
    "CSI300":  "sh000300",
    "CSI500":  "sh000905",
    "CHINEXT": "sz399006",
}

# 按脚本自身位置定位（_system/scripts/ → _system/market_data/），
# 宿主机 Windows 与 Cowork sandbox 均可运行；不再硬编码绝对路径
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "market_data"
LOOKBACK_DAYS = 400   # 拉 400 自然日，保证 ≥ 250 个交易日

# 失败重试设置
MAX_RETRIES = 2
RETRY_DELAY = 2  # 秒

# ---- yfinance 限流防护（2026-09-30 加入）----
# 背景：8/25–8/26、9/20、9/29–9/30 多次整批 YFRateLimitError。Yahoo 按 IP 限流，
# 旧逻辑 51 只美股/港股连续请求、失败 2 秒就重试、还有末根修补的额外请求，
# 限流时越重试封得越久。现在：
#   1. 每只之间停 YF_PAUSE 秒（加 0–0.5 秒随机抖动），把请求摊开
#   2. 碰到限流先等 YF_RATE_LIMIT_WAITS 里的秒数再试，不再 2 秒硬重试
#   3. 连续 YF_BREAKER_LIMIT 只退避后仍被限流 → 熔断：本轮剩下的 yfinance 标的直接跳过，
#      原 CSV 原样保留，不再继续打 Yahoo（继续打只会延长封禁）
#   4. 末根修补遇到限流立即停止修补，残 bar 交给 drop_incomplete_ohlc 丢弃
# 注意：yf.download 批量下载在 yfinance 内部仍是逐只请求，并不减少请求数，所以不用它。
YF_PAUSE = 1.5
YF_RATE_LIMIT_WAITS = (20, 60)
YF_BREAKER_LIMIT = 3
_YF_STATE = {"consecutive_rl": 0, "tripped": False}


class YFBreakerTripped(Exception):
    pass


def _is_rate_limit(e):
    s = str(e)
    return type(e).__name__ == "YFRateLimitError" or "Too Many Requests" in s or "Rate limited" in s


def _yf_pause():
    """两只 yfinance 标的之间的停顿；已熔断时不用再等。"""
    if not _YF_STATE["tripped"]:
        time.sleep(YF_PAUSE + random.uniform(0, 0.5))


# ========== 数据拉取函数 ==========

def _yf_normalize(df):
    """yfinance 原始 DataFrame → 统一七列。index 为 DatetimeIndex（可能带时区）。"""
    df = df.reset_index()
    df = df.rename(columns={
        "Date": "date", "Datetime": "date",
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    })
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    # yfinance 不直接给成交额，用 close*volume 近似
    df["amount"] = (df["close"] * df["volume"]).round(2)
    return df[["date", "open", "high", "low", "close", "volume", "amount"]]


def _yf_bar_from_intraday(t, target_date):
    """
    用盘中 5 分钟 bar 聚合出 target_date 当天的日线（open=首根开盘、high=最高、
    low=最低、close=末根收盘、volume=求和）。盘中数据走 Yahoo 另一条接口，
    收盘后立即完整，不受日线接口"只给量不给价"的影响。
    最新一天的复权价 == 未复权价（auto_adjust 只改历史），可直接与日线拼接。
    """
    intra = t.history(period="5d", interval="5m", auto_adjust=False,
                      prepost=False, actions=False)
    if intra is None or intra.empty:
        return None
    intra = intra.reset_index()
    tcol = "Datetime" if "Datetime" in intra.columns else "Date"
    day = intra[intra[tcol].dt.strftime("%Y-%m-%d") == target_date]
    day = day.dropna(subset=["Open", "High", "Low", "Close"])
    if day.empty:
        return None
    vol = float(day["Volume"].sum())
    if vol <= 0:
        return None
    return {
        "date": target_date,
        "open": float(day["Open"].iloc[0]),
        "high": float(day["High"].max()),
        "low": float(day["Low"].min()),
        "close": float(day["Close"].iloc[-1]),
        "volume": vol,
        "amount": round(float(day["Close"].iloc[-1]) * vol, 2),
    }


def _yf_bar_from_period(t, target_date):
    """换一条查询路径（range=5d 而不是 period1/period2）再要一次日线。"""
    alt = t.history(period="5d", interval="1d", auto_adjust=True, actions=False)
    if alt is None or alt.empty:
        return None
    alt = _yf_normalize(alt)
    row = alt[alt["date"] == target_date].dropna(subset=["open", "high", "low", "close"])
    if row.empty:
        return None
    r = row.iloc[-1]
    return {k: (r[k] if k == "date" else float(r[k])) for k in
            ("date", "open", "high", "low", "close", "volume", "amount")}


def _yf_bar_from_fast_info(t, target_date):
    """
    最后兜底：fast_info 的当日 open/dayHigh/dayLow/lastPrice/lastVolume。
    只有当 Yahoo 元数据里的最近交易时间落在 target_date 当天才采用，避免拿错天。
    """
    try:
        meta = t.get_history_metadata() if hasattr(t, "get_history_metadata") else t.history_metadata
    except Exception:
        meta = None
    if not meta:
        return None
    ts = meta.get("regularMarketTime")
    tz = meta.get("exchangeTimezoneName")
    if not ts or not tz:
        return None
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(int(ts), ZoneInfo(tz)).strftime("%Y-%m-%d")
    except Exception:
        return None
    if d != target_date:
        return None
    fi = t.fast_info
    try:
        o, h, l, c, v = (fi["open"], fi["dayHigh"], fi["dayLow"], fi["lastPrice"], fi["lastVolume"])
    except Exception:
        return None
    if any(x is None or x != x for x in (o, h, l, c)):
        return None
    v = float(v or 0)
    return {"date": target_date, "open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": v, "amount": round(float(c) * v, 2)}


# 修补顺序：先换日线查询路径（最便宜），再盘中聚合（最可靠），最后 fast_info。
YF_REPAIR_CHAIN = (
    ("period5d", _yf_bar_from_period),
    ("intraday5m", _yf_bar_from_intraday),
    ("fast_info", _yf_bar_from_fast_info),
)


def fetch_yfinance(symbol, start_date, end_date, max_retries=MAX_RETRIES, repair_log=None):
    """
    用 yfinance 拉取一个 symbol 的日线数据。
    返回 DataFrame (date, open, high, low, close, volume, amount) 或 None。

    2026-09-11 加"末根 bar 修补"：Yahoo 日线接口在个股收盘后会先返回一根
    只有 volume、OHLC 全空的残 bar（指数没有这个问题），旧逻辑只能丢弃 → 美股
    永远慢一天。现在：残 bar 的日期就是要补的日期，按 YF_REPAIR_CHAIN 逐个
    数据路径去要那一天的完整 bar，补上后再返回；三条路都失败才放弃（沿用丢弃）。
    repair_log：list，成功/失败的修补记录会 append 进去（供 fetch_log 与清单）。
    """
    import yfinance as yf

    if _YF_STATE["tripped"]:
        raise YFBreakerTripped("前面已连续限流，本轮跳过以免延长封禁，原 CSV 保留")

    rl_waits = list(YF_RATE_LIMIT_WAITS)
    attempt = 0
    while True:
        attempt += 1
        try:
            t = yf.Ticker(symbol)
            df = t.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),  # yfinance end 是 exclusive
                auto_adjust=True,   # 前复权
                actions=False,
            )
            _YF_STATE["consecutive_rl"] = 0
            if df is None or df.empty:
                if attempt < max_retries:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

            df = _yf_normalize(df)
            df = _yf_repair_tail(t, df, repair_log)
            return df
        except Exception as e:
            if _is_rate_limit(e):
                if rl_waits:
                    w = rl_waits.pop(0)
                    print(f"   ⏳ {symbol} 被限流，等 {w} 秒再试")
                    time.sleep(w)
                    continue
                _YF_STATE["consecutive_rl"] += 1
                if _YF_STATE["consecutive_rl"] >= YF_BREAKER_LIMIT and not _YF_STATE["tripped"]:
                    _YF_STATE["tripped"] = True
                    print(f"   🛑 连续 {YF_BREAKER_LIMIT} 只退避后仍被限流 → 熔断，本轮其余 yfinance 标的跳过")
                raise
            if attempt < max_retries:
                time.sleep(RETRY_DELAY)
                continue
            raise


def _yf_repair_tail(t, df, repair_log):
    """找出比最后一根完整 bar 更新的残 bar（OHLC 有空），逐日修补。"""
    import pandas as pd
    price_cols = ["open", "high", "low", "close"]
    complete = df.dropna(subset=price_cols)
    last_ok = complete["date"].max() if not complete.empty else ""
    broken_dates = sorted(set(df.loc[df[price_cols].isna().any(axis=1), "date"]) - set(complete["date"]))
    broken_dates = [d for d in broken_dates if d > last_ok]
    if not broken_dates:
        return df
    fixed_rows = []
    rate_limited = False
    for d in broken_dates:
        bar = None
        used = None
        for tag, fn in YF_REPAIR_CHAIN:
            try:
                bar = fn(t, d)
            except Exception as e:
                bar = None
                if _is_rate_limit(e):
                    rate_limited = True
                    break
            if bar:
                used = tag
                break
            time.sleep(0.5)
        if rate_limited:
            if repair_log is not None:
                repair_log.append(f"补 {d} 中止（被限流，残 bar 交给清洗丢弃）")
            break
        if bar:
            fixed_rows.append(bar)
            if repair_log is not None:
                repair_log.append(f"补 {d} ← {used}")
        else:
            if repair_log is not None:
                repair_log.append(f"补 {d} 失败（三条路径都没价格）")
    if not fixed_rows:
        return df
    fixed = pd.DataFrame(fixed_rows)
    df = df[~df["date"].isin(fixed["date"])]
    df = pd.concat([df, fixed], ignore_index=True).sort_values("date").reset_index(drop=True)
    return df


def fetch_akshare_stock(symbol, start_date, end_date, max_retries=MAX_RETRIES):
    """
    A 股个股，前复权。多源 fallback：baostock → tencent → eastmoney
    baostock 是独立专业财经数据 API，海外访问稳定，是首选源。
    """
    import akshare as ak

    sources = [
        # 主源：baostock（独立 API，海外稳定无墙）
        ("baostock", lambda: _fetch_baostock(symbol, start_date, end_date)),
        # 备用源 1：腾讯证券
        ("tencent", lambda: ak.stock_zh_a_hist_tx(
            symbol=_to_tx_symbol(symbol),
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )),
        # 备用源 2：东财（最不稳定，海外常 ProxyError）
        ("eastmoney", lambda: ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq",
        )),
    ]

    errors = []
    for source_name, fetcher in sources:
        for attempt in range(1, max_retries + 1):
            try:
                df = fetcher()
                if df is None or df.empty:
                    if attempt < max_retries:
                        time.sleep(RETRY_DELAY)
                        continue
                    errors.append(f"[{source_name}] 返回空数据")
                    break  # 换下一源
                # 统一列名（不同源字段不同）
                df = _normalize_a_share_columns(df)
                return df
            except Exception as e:
                err_short = f"[{source_name}] {type(e).__name__}: {str(e)[:100]}"
                if attempt < max_retries:
                    time.sleep(RETRY_DELAY)
                    continue
                errors.append(err_short)
                break  # 换下一源

    raise RuntimeError(f"所有 A 股数据源都失败。详情：{' | '.join(errors)}")


def _fetch_baostock(symbol, start_date, end_date):
    """用 baostock 拉取 A 股日线（前复权）。baostock 不支持北交所，遇到北交所代码直接抛出由 fallback 接管。"""
    import baostock as bs
    import pandas as pd

    if _is_bj_symbol(symbol):
        raise RuntimeError("baostock 不支持北交所，跳过到下一数据源")

    bs_symbol = f"sh.{symbol}" if symbol.startswith("6") else f"sz.{symbol}"

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login 失败: {lg.error_msg}")

    try:
        rs = bs.query_history_k_data_plus(
            bs_symbol,
            "date,open,high,low,close,volume,amount",
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            frequency="d",
            adjustflag="2",  # 1=后复权 2=前复权 3=不复权
        )
        if rs.error_code != "0":
            raise RuntimeError(f"baostock query 失败: {rs.error_msg}")
        df = rs.get_data()
        if df is None or df.empty:
            return None
        # baostock 的数值列是字符串，转 float
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    finally:
        bs.logout()


def _is_bj_symbol(symbol):
    """北交所代码识别：4xxxxx / 8xxxxx / 920xxx 三段，详见 2023 北交所代码扩容方案"""
    return symbol.startswith(("4", "8")) or symbol.startswith("920") or symbol.startswith("83") or symbol.startswith("87")


def _to_tx_symbol(symbol):
    """把 '300054' 转换为腾讯接口要求的 'sz300054' 格式"""
    if symbol.startswith("6"):
        return f"sh{symbol}"
    elif symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    elif _is_bj_symbol(symbol):
        return f"bj{symbol}"  # 北交所（含新代码段 920xxx）
    return symbol


def _normalize_a_share_columns(df):
    """不同 A 股数据源列名不同，统一映射到 date/open/high/low/close/volume/amount"""
    column_map = {
        # 腾讯源
        "date": "date", "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume", "amount": "amount",
        # 东财源（中文列名）
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "成交额": "amount",
    }
    df = df.rename(columns=column_map)
    df["date"] = df["date"].astype(str)
    cols = ["date", "open", "high", "low", "close", "volume", "amount"]
    # 北交所走腾讯接口 (stock_zh_a_hist_tx) 时只返回 6 列：date/open/close/high/low/amount，
    # 没有 volume。经数量级核对，该 "amount" 列实际是成交量（股），不是成交额（元）。
    # 因此：amount → volume，再用 close*volume 重算真正的成交额。
    if "volume" not in df.columns and "amount" in df.columns:
        df["volume"] = df["amount"]
        df["amount"] = (df["close"] * df["volume"]).round(2)
    # 兜底：有些源不返回 amount，用 close*volume 算
    if "amount" not in df.columns:
        df["amount"] = (df["close"] * df["volume"]).round(2)
    return df[cols]


def fetch_akshare_index(symbol, start_date, end_date, max_retries=MAX_RETRIES):
    """A 股指数。"""
    import akshare as ak

    for attempt in range(1, max_retries + 1):
        try:
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                if attempt < max_retries:
                    time.sleep(RETRY_DELAY)
                    continue
                return None

            df = df.rename(columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            })
            df["date"] = df["date"].astype(str)
            df["amount"] = (df["close"] * df["volume"]).round(2)

            # 筛选 lookback 范围内的数据
            start_str = start_date.strftime("%Y-%m-%d")
            df = df[df["date"] >= start_str].reset_index(drop=True)
            return df[["date", "open", "high", "low", "close", "volume", "amount"]]
        except Exception:
            if attempt < max_retries:
                time.sleep(RETRY_DELAY)
                continue
            raise

    return None


def save_csv(df, path):
    """统一 CSV 输出格式"""
    df.to_csv(path, index=False, encoding="utf-8")


# ========== 行数守卫（2026-08-27 加，ISSC 静默毁史事故） ==========
#
# 事故经过：save_csv 是**全量覆盖**——每天拿 400 天窗口重拉后整个盖掉旧文件。
# 当数据源退化（换代码/退市/限流返回残值）时，yfinance 会返回零散残行而不是报错。
# 旧逻辑只判「df 是否为空」，非空即写盘、manifest 即判 ok，于是残缺响应
# 直接**覆盖掉完整历史**，且全链路无人报警。
#
# ISSC（2026-08-18 改代码为 IA）就是这么从 275 行被盖成 16 行、连断 3 天无察觉：
# 返回的 16 行日期还是跳的（7/17,7/20,7/21,7/22 → 7/31 → 8/6…），
# 8/18 那行 volume=0、OHLC 四值全等。信号引擎靠 data_sufficient 挡住了，
# 但 manifest 仍报 success 61/0 —— 被骗的是清单，不是引擎。
#
# 守卫原则：**宁可拒绝写盘并报 fail，也不要用残缺数据覆盖完整历史。**
# 拒绝写盘时原 CSV 原样保留，fail>0 会让 fetcher exit(2)、发布链显式失败 —— 这是想要的效果。
SHRINK_MIN_ROWS = 30      # 低于此行数一律可疑（连 MA20/MA60 都算不出来）
SHRINK_RATIO = 0.70       # 新数据不得少于现有 CSV 行数的 70%


# ========== OHLC 残行清洗（2026-09-09 加，"清单说谎"事故） ==========
#
# 事故经过：2026-09-09 早上 08:31 那次 fetch，49 只美股 CSV 都多出一行
#   2026-09-08,,,,,118984635,
# ——只有 volume，OHLC 五列全空（yfinance 在盘中/数据延迟时会返回这种残 bar）。
# 旧逻辑照单全收写盘，后果是一条骗人的链：
#   1) 清单 last_date 报 2026-09-08，但那天根本没有有效价格 → **清单说谎**；
#   2) compute_signals.py 的 indicators.close / ma20 / ma60 / ma250 对这 49 只全返回 null；
#   3) 扫描器只能退回 prev_close（= 09-04 收盘），与前一日扫描完全相同却看似"数据已更新"。
#
# 原则与 guard_shrink 一致：**没有价格的行不是数据，落盘前就该丢掉。**
# 丢弃数量写进 manifest entry 的 dropped_rows 与 fetch_log，保证可见而不是静默。
def drop_incomplete_ohlc(df):
    """丢弃 OHLC 任一为空的行。返回 (清洗后的 df, 被丢弃的行数)。"""
    if df is None or df.empty:
        return df, 0
    cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    if not cols:
        return df, 0
    before = len(df)
    cleaned = df.dropna(subset=cols).reset_index(drop=True)
    return cleaned, before - len(cleaned)


def _rowcount(path):
    if not path.exists():
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)   # 减表头
    except Exception:
        return 0


def guard_shrink(df, csv_path):
    """返回 None 放行；返回字符串 = 拒绝写盘的理由。"""
    old = _rowcount(csv_path)
    n = len(df)
    if old == 0:
        return None                                 # 新标的首次落盘，无从比较
    if n < SHRINK_MIN_ROWS <= old:
        return f"新数据仅 {n} 行（< {SHRINK_MIN_ROWS}），现有 {old} 行，疑似数据源退化"
    if n < old * SHRINK_RATIO:
        return f"新数据 {n} 行 < 现有 {old} 行的 {SHRINK_RATIO:.0%}，疑似数据源退化"
    return None


# ========== 盘中半根 bar 守卫（2026-09-11 加） ==========
#
# 2026-09-09 23:09 手动跑那次正值美股盘中，yfinance 把当天没走完的 bar 当日线返回，
# 旧逻辑照单落盘 → 那天的"收盘价"其实是盘中某一刻的价。
# 规则：bar 日期 == 该市场"今天"，且该市场还没收盘 → 这根 bar 不要。
MARKET_CLOSE = {
    # 市场: (时区, 收盘后多少分钟才算数据定稿)
    "US": ("America/New_York", 16 * 60 + 5),
    "HK": ("Asia/Hong_Kong",   16 * 60 + 15),
    "CN": ("Asia/Shanghai",    15 * 60 + 5),
}


def drop_unfinished_session_bar(df, name, now_utc=None):
    """丢掉"该市场今天且尚未收盘"的 bar。返回 (df, 被丢的日期或 None)。"""
    if df is None or df.empty:
        return df, None
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        tz_name, close_min = MARKET_CLOSE[market_of(name)]
        now_utc = now_utc or datetime.now(timezone.utc)
        local = now_utc.astimezone(ZoneInfo(tz_name))
    except Exception:
        return df, None                       # 时区库不可用就不拦，别把正常流程拦死
    today_local = local.strftime("%Y-%m-%d")
    if local.hour * 60 + local.minute >= close_min:
        return df, None                       # 已收盘，今天的 bar 是定稿
    mask = df["date"] == today_local
    if not mask.any():
        return df, None
    return df[~mask].reset_index(drop=True), today_local


# ========== 长历史文件增量追加（2026-09-11 加） ==========
#
# 0700.HK / 600519 / 300760 三只 CSV 是几千行长历史，而每日拉取只有 400 天窗口，
# guard_shrink 的 70% 规则把它们每天都拒掉 → 卡在旧日期无人发现。
# 现在：新数据比旧文件短时，不整体覆盖，只把"比旧文件最后一天更新"的行追加上去。
# 追加前必须过一道"重叠校验"：新数据里得有旧文件最后一天那根 bar，且收盘价相差
# 不超过 OVERLAP_TOL——对不上说明数据源退化或换了复权口径，照旧拒绝。
# 代价：旧行的前复权系数不会随新分红/拆股更新。文件头部日期太老时应整体重拉一次。
OVERLAP_TOL = 0.03


def incremental_append(df, csv_path):
    """
    返回 (merged_df, appended_rows, reason)。
    reason 非 None 表示不能增量（调用方按原来的拒绝处理）。
    """
    import pandas as pd
    old = pd.read_csv(csv_path, dtype={"date": str})
    old = old.dropna(subset=["open", "high", "low", "close"])
    if old.empty:
        return None, 0, "旧文件无有效行"
    old_last = old["date"].max()
    if df["date"].min() > old_last:
        return None, 0, f"新数据从 {df['date'].min()} 起，与旧文件末日 {old_last} 之间有断档，不能增量"
    overlap = df[df["date"] == old_last]
    if overlap.empty:
        return None, 0, f"新数据里没有旧文件末日 {old_last} 那根 bar，无法校验重叠"
    old_close = float(old.loc[old["date"] == old_last, "close"].iloc[-1])
    new_close = float(overlap["close"].iloc[-1])
    if old_close <= 0 or abs(new_close - old_close) / old_close > OVERLAP_TOL:
        return None, 0, (f"重叠日 {old_last} 收盘价对不上（旧 {old_close:.4f} / 新 {new_close:.4f}，"
                         f"差 {abs(new_close-old_close)/old_close:.1%} > {OVERLAP_TOL:.0%}），疑似换口径")
    new_rows = df[df["date"] > old_last]
    merged = pd.concat([old[df.columns], new_rows], ignore_index=True)
    merged = merged.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
    return merged, int(len(new_rows)), None


# ========== data_as_of 清单（_data_status.json） ==========

MANIFEST_PATH = OUTPUT_DIR / "_data_status.json"
MANIFEST_SCHEMA_VERSION = 1


# 指数名 → 市场（盘中守卫要知道它按哪个市场的收盘时间算；2026-09-11 HSI 曾被当成美股放行了盘中 bar）
INDEX_MARKET = {"SPX": "US", "NDX": "US", "HSI": "HK", "CSI300": "CN", "CSI500": "CN", "CHINEXT": "CN"}


def market_of(name):
    """ticker / 指数名 → 市场分类（分市场汇总 max last_date + 盘中守卫）"""
    if name in INDEX_MARKET:
        return INDEX_MARKET[name]
    if name.endswith(".HK"):
        return "HK"
    if name.endswith((".SZ", ".SH", ".BJ")):
        return "CN"
    return "US"


def entry_from_df(df):
    """从 DataFrame 提取清单条目：行数 + 最后一行完整 OHLCV"""
    last = df.iloc[-1]
    return {
        "last_date": str(last["date"]),
        "rows": int(len(df)),
        "last_row": {
            "date": str(last["date"]),
            "open": round(float(last["open"]), 4),
            "high": round(float(last["high"]), 4),
            "low": round(float(last["low"]), 4),
            "close": round(float(last["close"]), 4),
            "volume": int(float(last["volume"])) if last["volume"] == last["volume"] else None,
        },
    }


def entry_from_csv(path):
    """从磁盘 CSV 重建清单条目（--manifest-only 模式用，仅标准库）"""
    import csv as _csv
    with open(path, "r", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        rows = 0
        last = None
        skipped = 0
        for row in reader:
            if not row.get("date"):
                continue
            rows += 1
            # 与 drop_incomplete_ohlc 同口径：OHLC 任一为空的行不能当作"最新一行"，
            # 否则清单 last_date 会指向一个没有价格的日子（2026-09-09 事故）。
            if any(not (row.get(k) or "").strip() for k in ("open", "high", "low", "close")):
                skipped += 1
                continue
            last = row
    if last is None:
        return None

    def _f(key):
        try:
            return round(float(last[key]), 4)
        except (TypeError, ValueError, KeyError):
            return None

    vol = None
    try:
        vol = int(float(last["volume"]))
    except (TypeError, ValueError, KeyError):
        pass
    entry = {
        "last_date": last["date"],
        "rows": rows + 1,  # 与 fetch_log 口径一致：含表头
        "last_row": {
            "date": last["date"],
            "open": _f("open"), "high": _f("high"),
            "low": _f("low"), "close": _f("close"),
            "volume": vol,
        },
    }
    if skipped:
        entry["skipped_incomplete_rows"] = skipped
    return entry


def write_data_status(tickers, indices, success, fail, failures, generated_by):
    """写 _data_status.json。tickers/indices: {name: entry}；entry 可含 status 字段。"""
    markets = {}
    for name, entry in tickers.items():
        if not entry or entry.get("status") == "fail":
            continue
        m = market_of(name)
        bucket = markets.setdefault(m, {"max_last_date": "", "tickers": 0})
        bucket["tickers"] += 1
        if entry["last_date"] > bucket["max_last_date"]:
            bucket["max_last_date"] = entry["last_date"]

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": generated_by,
        "summary": {"success": success, "fail": fail},
        "markets": markets,
        "tickers": tickers,
        "indices": indices,
        "failures": failures,
    }
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MANIFEST_PATH)
    return MANIFEST_PATH


def rebuild_manifest_from_csvs():
    """--manifest-only：扫描磁盘 CSV 重建清单，不联网。"""
    tickers, indices, failures = {}, {}, []
    success = fail = 0
    for csv_path in sorted(OUTPUT_DIR.glob("*.csv")):
        name = csv_path.stem
        entry = entry_from_csv(csv_path)
        if entry:
            tickers[name] = entry
            success += 1
        else:
            tickers[name] = {"status": "fail"}
            failures.append(f"{name}: CSV 为空")
            fail += 1
    idx_dir = OUTPUT_DIR / "indices"
    if idx_dir.is_dir():
        for csv_path in sorted(idx_dir.glob("*.csv")):
            name = csv_path.stem
            entry = entry_from_csv(csv_path)
            if entry:
                indices[name] = entry
                success += 1
            else:
                indices[name] = {"status": "fail"}
                failures.append(f"指数 {name}: CSV 为空")
                fail += 1
    path = write_data_status(
        tickers, indices, success, fail, failures,
        generated_by="market_data_fetcher.py --manifest-only（按磁盘现有 CSV 重建，非当日拉取凭证）",
    )
    print(f"✅ 清单已重建：{path}（{success} 成功 / {fail} 失败）")


# ========== 主逻辑 ==========

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    indices_dir = OUTPUT_DIR / "indices"
    indices_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().date()
    start_date = today - timedelta(days=LOOKBACK_DAYS)

    log = []
    log.append(f"=== 市场数据拉取日志 {today} ===")
    log.append(f"启动时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.append(f"数据窗口：{start_date} ~ {today}（{LOOKBACK_DAYS} 个自然日）")
    log.append(f"输出目录：{OUTPUT_DIR}")
    log.append("")

    # 依赖检查
    try:
        import yfinance  # noqa
    except ImportError:
        msg = "❌ 缺少 yfinance。请运行：py -3.11 -m pip install yfinance"
        print(msg)
        log.append(msg)
        write_log(today, log)
        sys.exit(1)

    try:
        import akshare  # noqa
    except ImportError:
        msg = "❌ 缺少 akshare。请运行：py -3.11 -m pip install akshare"
        print(msg)
        log.append(msg)
        write_log(today, log)
        sys.exit(1)

    success = 0
    fail = 0
    manifest_tickers = {}
    manifest_indices = {}
    failures = []

    # ---- 美股 + 港股（yfinance）----
    log.append("--- 美股 + 港股（yfinance）---")
    print("\n--- 美股 + 港股（yfinance）---")
    for name, sym in YF_TICKERS.items():
        ok, msg, entry = run_one(
            label="个股",
            name=name,
            sym=sym,
            fetcher=lambda rl=None, sym=sym: fetch_yfinance(sym, start_date, today, repair_log=rl),
            out_dir=OUTPUT_DIR,
        )
        _yf_pause()
        log.append(msg)
        print(msg)
        manifest_tickers[name] = entry
        if ok:
            success += 1
        else:
            fail += 1
            failures.append(msg)

    # ---- A 股（akshare）----
    log.append("\n--- A 股（akshare）---")
    print("\n--- A 股（akshare）---")
    for name, sym in AK_TICKERS.items():
        ok, msg, entry = run_one(
            label="A股",
            name=name,
            sym=sym,
            fetcher=lambda rl=None, sym=sym: fetch_akshare_stock(sym, start_date, today),
            out_dir=OUTPUT_DIR,
        )
        log.append(msg)
        print(msg)
        manifest_tickers[name] = entry
        if ok:
            success += 1
        else:
            fail += 1
            failures.append(msg)

    # ---- 国际指数（yfinance）----
    log.append("\n--- 国际指数（yfinance）---")
    print("\n--- 国际指数（yfinance）---")
    for name, sym in YF_INDICES.items():
        ok, msg, entry = run_one(
            label="指数",
            name=name,
            sym=sym,
            fetcher=lambda rl=None, sym=sym: fetch_yfinance(sym, start_date, today, repair_log=rl),
            out_dir=indices_dir,
        )
        _yf_pause()
        log.append(msg)
        print(msg)
        manifest_indices[name] = entry
        if ok:
            success += 1
        else:
            fail += 1
            failures.append(msg)

    # ---- A 股指数（akshare）----
    log.append("\n--- A 股指数（akshare）---")
    print("\n--- A 股指数（akshare）---")
    for name, sym in AK_INDICES.items():
        ok, msg, entry = run_one(
            label="指数",
            name=name,
            sym=sym,
            fetcher=lambda rl=None, sym=sym: fetch_akshare_index(sym, start_date, today),
            out_dir=indices_dir,
        )
        log.append(msg)
        print(msg)
        manifest_indices[name] = entry
        if ok:
            success += 1
        else:
            fail += 1
            failures.append(msg)

    # ---- 写 data_as_of 清单（必须在 fetch_log 之前完成，保证两者一致）----
    try:
        manifest_path = write_data_status(
            manifest_tickers, manifest_indices, success, fail, failures,
            generated_by="market_data_fetcher.py（宿主机定时拉取）",
        )
        log.append(f"\n📋 data_as_of 清单 → {manifest_path.name}")
        print(f"\n📋 data_as_of 清单 → {manifest_path}")
    except Exception as e:
        msg = f"❌ 清单写入失败：{type(e).__name__}: {e}"
        log.append(msg)
        print(msg)
        fail += 1

    # ---- 收尾 ----
    if _YF_STATE["tripped"]:
        log.append("\n🛑 本轮 yfinance 触发限流熔断：后续美股/港股/国际指数未请求，原 CSV 保留。隔几小时再手动跑一次。")
    log.append("")
    log.append("=" * 60)
    log.append(f"汇总：✅ 成功 {success} / ❌ 失败 {fail}")
    log.append(f"完成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    write_log(today, log)

    print(f"\n=== 完成：成功 {success} / 失败 {fail} ===")
    print(f"日志：{OUTPUT_DIR / 'fetch_log' / f'fetch_log_{today}.txt'}")

    if fail > 0:
        sys.exit(2)


def run_one(label, name, sym, fetcher, out_dir):
    """通用单 ticker 处理流水线。返回 (ok, msg, manifest_entry)"""
    try:
        repair_log = []
        df = fetcher(repair_log)
        if df is None or df.empty:
            return False, f"⚠️  {label} {name} ({sym}): 返回空数据", {"status": "fail"}
        notes = []
        extra = {}
        # 盘中半根 bar：该市场今天还没收盘，今天的 bar 不算数
        df, unfinished = drop_unfinished_session_bar(df, name)
        if unfinished:
            notes.append(f"丢弃盘中未收盘 bar {unfinished}")
            extra["dropped_unfinished"] = unfinished
        # OHLC 残行清洗：只有 volume、没有价格的行落盘会让清单 last_date 说谎
        df, dropped = drop_incomplete_ohlc(df)
        if df is None or df.empty:
            return False, f"⚠️  {label} {name} ({sym}): 清洗掉 {dropped} 行残 bar 后无有效数据", {"status": "fail"}
        if repair_log:
            notes.extend(repair_log)
            extra["repair"] = list(repair_log)
        if dropped:
            notes.append(f"已丢弃 {dropped} 行 OHLC 残 bar")
            extra["dropped_rows"] = dropped
        csv_path = out_dir / f"{name}.csv"
        # 行数守卫：残缺响应绝不允许覆盖完整历史（见 guard_shrink 注释）
        reason = guard_shrink(df, csv_path)
        mode = "full"
        if reason:
            merged, appended, inc_reason = incremental_append(df, csv_path)
            if inc_reason:
                return (
                    False,
                    f"🛑 {label} {name} ({sym}): {reason}；增量也不行：{inc_reason} → 已拒绝覆盖，原 CSV 保留",
                    {"status": "fail", "guard": reason, "incremental": inc_reason, "rejected_rows": len(df)},
                )
            df = merged
            mode = "incremental"
            notes.append(f"🟡 旧文件为长历史，增量追加 {appended} 行")
            extra["appended_rows"] = appended
        save_csv(df, csv_path)
        entry = entry_from_df(df)
        entry["status"] = "ok"
        entry["mode"] = mode
        entry.update(extra)
        msg = f"✅ {label} {name} ({sym}) → {csv_path.name} ({len(df)} 行)"
        if notes:
            msg += "｜" + "；".join(notes)
        return True, msg, entry
    except Exception as e:
        # 简短异常 + 完整堆栈（堆栈仅写日志，不上 stdout）
        return False, f"❌ {label} {name} ({sym}): {type(e).__name__}: {e}", {"status": "fail"}


def write_log(date, lines):
    log_dir = OUTPUT_DIR / "fetch_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"fetch_log_{date.strftime('%Y-%m-%d')}.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    if "--manifest-only" in sys.argv:
        rebuild_manifest_from_csvs()
    else:
        main()
