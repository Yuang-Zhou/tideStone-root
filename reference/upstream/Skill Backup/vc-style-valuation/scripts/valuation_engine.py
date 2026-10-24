"""
VC 风格估值引擎 —— vc-style-valuation skill 的确定性计算模块。

分工原则：**判断留在 SKILL.md，算术放这里。**
本模块只做"输入确定 → 输出确定"的部分：
    - 每情景 MOIC / IRR
    - 回报三因子拆解（矛的增长 × 倍数变化 × 稀释调整）
    - 概率加权期望 MOIC / IRR
    - 敏感性矩阵（退出倍数 × 退出年矛水平 → MOIC）
    - 下行测算
    - 反推 DCF 隐含增速求解器（退出倍数法，二分求解）

不做判断：选哪杆矛、给多少倍数、概率多少、算不算得出——这些由 skill/人决定后当作输入喂进来。

纯标准库，无第三方依赖。所有金额用同一货币单位；"矛"(metric)指估值锚定指标
（收入 / ARR / GMV / 毛利 / 净利 / FCF 之一），倍数为对应的**股权**倍数（P/S、P/E、P/GP…）。
EV 类倍数请先折成股权口径或用 net_debt 桥接（见 future_price 说明）。
"""

from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Scenario:
    name: str                 # 情景名（乐观/基准/悲观）
    prob: float               # 概率权重，三情景之和应=1
    exit_metric: float        # 退出年"矛"的总量（与 current_metric 同口径同单位）
    exit_multiple: float      # 退出年该矛的股权倍数
    shares_exit: float        # 退出年摊薄股本
    cum_div_ps: float = 0.0   # 持有期累计每股分红
    net_debt_exit: float = 0.0  # 退出年净债务（净现金填负数）；仅当矛为 EV 口径时用到


@dataclass
class Inputs:
    ticker: str
    current_price: float
    shares_current: float
    current_metric: float             # 当前"矛"的总量（TTM 收入/净利/FCF…）
    N: int                            # 持有期（年）
    scenarios: list                   # List[Scenario]
    current_multiple: Optional[float] = None  # 当前股权倍数；缺省则由市值/矛反算
    metric_is_ev_based: bool = False  # True=矛用 EV 倍数（EV/Sales、EV/EBITDA…）

    def __post_init__(self):
        if self.current_multiple is None:
            self.current_multiple = self.current_mcap / self.current_metric

    @property
    def current_mcap(self) -> float:
        return self.current_price * self.shares_current


# --------------------------------------------------------------------------- #
# 核心计算
# --------------------------------------------------------------------------- #
def future_price(sc: Scenario, ev_based: bool) -> float:
    """退出年每股价格。
    股权倍数：未来市值 = 矛 × 倍数 → 每股 = 市值 / 股本。
    EV 倍数：  未来 EV  = 矛 × 倍数 → 股权 = EV − 净债务 → 每股 = 股权 / 股本。
    """
    gross = sc.exit_metric * sc.exit_multiple
    equity = gross - sc.net_debt_exit if ev_based else gross
    return equity / sc.shares_exit


def moic_irr(fut_price: float, current_price: float, cum_div_ps: float, N: int):
    moic = (fut_price + cum_div_ps) / current_price
    irr = moic ** (1.0 / N) - 1 if moic > 0 else -1.0
    return moic, irr


def decompose(sc: Scenario, inp: Inputs):
    """价格 MOIC ≈ 矛的增长 × 倍数变化 × 稀释调整。
    （股权倍数口径下三因子严格相乘=价格MOIC，忽略分红；EV口径下为近似，净债务桥接单列。）
    """
    metric_growth = sc.exit_metric / inp.current_metric
    multiple_change = sc.exit_multiple / inp.current_multiple
    dilution_adj = inp.shares_current / sc.shares_exit
    return metric_growth, multiple_change, dilution_adj


def analyze(inp: Inputs) -> dict:
    rows = []
    w_moic = 0.0
    w_irr = 0.0
    for sc in inp.scenarios:
        fp = future_price(sc, inp.metric_is_ev_based)
        moic, irr = moic_irr(fp, inp.current_price, sc.cum_div_ps, inp.N)
        mg, mc, dil = decompose(sc, inp)
        rows.append(dict(name=sc.name, prob=sc.prob, fut_price=fp, moic=moic, irr=irr,
                         metric_growth=mg, multiple_change=mc, dilution=dil))
        w_moic += sc.prob * moic
        w_irr += sc.prob * irr
    return dict(rows=rows, weighted_moic=w_moic, weighted_irr=w_irr,
                total_prob=sum(s.prob for s in inp.scenarios))


def sensitivity(inp: Inputs, base: Scenario, metric_levels, multiple_levels):
    """MOIC 网格：行=退出倍数，列=退出年矛水平。用 base 情景的股本/分红/净债务。"""
    grid = []
    for m in multiple_levels:
        row = []
        for x in metric_levels:
            sc = Scenario(base.name, base.prob, x, m, base.shares_exit,
                          base.cum_div_ps, base.net_debt_exit)
            fp = future_price(sc, inp.metric_is_ev_based)
            moic, _ = moic_irr(fp, inp.current_price, base.cum_div_ps, inp.N)
            row.append(moic)
        grid.append(row)
    return grid


def implied_growth_reverse_dcf(current_ev, fcf0, wacc, exit_multiple, years=10,
                               lo=-0.5, hi=1.5, tol=1e-6):
    """反推 DCF（退出倍数法）：解出让现值=当前EV 的 FCF 复合增速 g。
    EV = Σ_{t=1..N} FCF0·(1+g)^t /(1+w)^t  +  FCF0·(1+g)^N·exit_mult /(1+w)^N
    二分法。返回隐含 g；无解返回 None。"""
    def pv(g):
        s = 0.0
        for t in range(1, years + 1):
            fcf_t = fcf0 * (1 + g) ** t
            s += fcf_t / (1 + wacc) ** t
        terminal = fcf0 * (1 + g) ** years * exit_multiple
        s += terminal / (1 + wacc) ** years
        return s
    f_lo, f_hi = pv(lo) - current_ev, pv(hi) - current_ev
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = pv(mid) - current_ev
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------- #
# Markdown 输出
# --------------------------------------------------------------------------- #
def md_scenarios(res: dict) -> str:
    h = "| 情景 | 概率 | 未来股价 | MOIC | IRR | 矛增长 | 倍数变化 | 稀释 |\n"
    h += "| :-- | --: | --: | --: | --: | --: | --: | --: |\n"
    for r in res["rows"]:
        h += (f"| {r['name']} | {r['prob']:.0%} | {r['fut_price']:.2f} | "
              f"{r['moic']:.2f}x | {r['irr']:.1%} | ×{r['metric_growth']:.2f} | "
              f"×{r['multiple_change']:.2f} | ×{r['dilution']:.2f} |\n")
    h += (f"| **期望** | {res['total_prob']:.0%} | | **{res['weighted_moic']:.2f}x** "
          f"| **{res['weighted_irr']:.1%}** | | | |\n")
    return h


def md_sensitivity(grid, metric_levels, multiple_levels, star=None) -> str:
    h = "| 退出倍数 \\ 矛水平 | " + " | ".join(f"{x:g}" for x in metric_levels) + " |\n"
    h += "| :-- " + "| --: " * len(metric_levels) + "|\n"
    for i, m in enumerate(multiple_levels):
        cells = []
        for j, _ in enumerate(metric_levels):
            v = f"{grid[i][j]:.1f}x"
            if star and star == (i, j):
                v = f"★{v}"
            cells.append(v)
        h += f"| {m:g}x | " + " | ".join(cells) + " |\n"
    return h


# --------------------------------------------------------------------------- #
# 自测示例（通用，非任何真实公司）—— 直接 `python valuation_engine.py`
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    # 示例：一家高增长 SaaS，退出时点的"矛"= 收入（股权 P/S 口径）。
    # 当前：股价 50，股本 1.0亿股 → 市值 50亿；TTM 收入 5亿 → 当前 P/S = 10x。
    inp = Inputs(
        ticker="ACME(示例)",
        current_price=50.0,
        shares_current=1.0e8,
        current_metric=5.0e8,     # TTM 收入
        N=3,
        scenarios=[
            # 乐观：变性质成功——收入3年3x，市场认其高留存复利，P/S重估到15x
            Scenario("乐观", 0.30, exit_metric=15.0e8, exit_multiple=15.0, shares_exit=1.10e8),
            # 基准：收入2.2x，P/S小幅回落到8x
            Scenario("基准", 0.45, exit_metric=11.0e8, exit_multiple=8.0, shares_exit=1.12e8),
            # 悲观：市场换矛回看利润，收入1.6x但P/S压到4x
            Scenario("悲观", 0.25, exit_metric=8.0e8, exit_multiple=4.0, shares_exit=1.15e8),
        ],
    )
    res = analyze(inp)
    print(f"# {inp.ticker} 前瞻回报（持有 {inp.N} 年）")
    print(f"当前市值 {inp.current_mcap/1e8:.1f}亿，当前倍数 {inp.current_multiple:.1f}x\n")
    print(md_scenarios(res))

    base = inp.scenarios[1]
    metric_levels = [8e8, 10e8, 11e8, 13e8, 15e8]
    multiple_levels = [4, 6, 8, 11, 15]
    grid = sensitivity(inp, base, metric_levels, multiple_levels)
    print("\n## 敏感性（单元格=MOIC，★=基准）")
    # 基准落在 矛=11e8(列2)、倍数=8x(行2)
    print(md_sensitivity(grid, [x/1e8 for x in metric_levels], multiple_levels, star=(2, 2)))

    g = implied_growth_reverse_dcf(current_ev=50e8, fcf0=0.6e8, wacc=0.10, exit_multiple=20)
    print(f"\n## 反推DCF：当前价隐含的10年FCF复合增速 ≈ {g:.1%}"
          if g is not None else "\n## 反推DCF：无解（区间外）")

    # --- 自洽性断言 ---
    for r in res["rows"]:
        recon = r["metric_growth"] * r["multiple_change"] * r["dilution"]
        assert abs(recon - r["moic"]) < 1e-6, f"拆解不自洽: {r['name']}"
    assert abs(res["weighted_moic"] - sum(x.prob * r["moic"]
               for x, r in zip(inp.scenarios, res["rows"]))) < 1e-9
    print("\n[自测通过] 三因子相乘=MOIC；加权=各情景加权和。")
