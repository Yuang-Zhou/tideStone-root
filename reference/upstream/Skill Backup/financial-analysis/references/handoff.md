# 交接块模板（HANDOFF v3 · 02 财务分析）

放在正文之后，单独一节，每次整块替换、不累加。只写结论和数字，理由用 § 号指回正文。表头 FY-n 换成真实财年。方向列只填：上行 / 下行 / 走平 / 无规律，**只看财年列，不看 TTM**。不适用的填 `n/a`，在表下用一行说明。

**v3 和 v2 的区别**：新增 F2 财务安全；原 F2–F6 顺序重排为"数字 → 安全 → 基线 → 资本 → 说法 → 判断 → 缺口"。下游取数位置变化见文末对照表。

```markdown
## 交接块（HANDOFF v3 · 02 财务分析）

### F1 数字画像与口径（≤8 行）
- 数字画像：[只看数字得出的结论：这大概率是一家做什么的公司，靠什么赚钱]（§七问）
- 财务安全：[一句——会不会出事、账实不实，附最紧的一个约束和数字]（§财务安全体检）
- 公司类型：[重/轻资产] × [成长/成熟/收缩] × [现金流形态]，各附一个支撑数
- 最强一点：[一句 + 数字]
- 最弱一点：[一句 + 数字]
- 利润率空间：[有扩张空间 / 见顶持平 / 被 X 锁住 / 正在修复]，附锁住或打开的那个数（§第 5 步，给 06 机会类型判定）
- 对照结果：[数字画像被公司说法证实 / 部分推翻——推翻处见 F5 第 X 行]
- 口径与局限：[财年范围｜GAAP或non-GAAP｜口径变更｜底稿取数日与勾稽未过项｜数据缺口]

### F2 财务安全（给 05 / 07 / 估值 · 固定 9 行 + 旗）
| 维度 | 关键数（FY-1） | TTM/最新期末 | 5 年方向 | 参照 | 旗 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 债务规模：净负债/EBITDA | | | | | |
| 偿付：利息覆盖 ／ FCF/有息负债 | | | | | |
| 流动性：现金/1 年内到期债务 | | | | | |
| 到期与利率：3 年内到期占比 ／ 浮动占比 | | 附注 | | | |
| 表外：租赁承诺 + 担保 + 或有 | | 附注 | | | |
| 商誉无形：占总资产 ％ ／ headroom | | | | | |
| 应收：增速差 ／ 坏账计提率 | | | | | |
| 存货：增速差 ／ 产成品占比 | | | | | |
| 软资产：资本化比例 ／ 递延税资产占比 | | | | | |
- 红旗：[逐条一句，无则"无"]
- 黄旗：[逐条一句，无则"无"]
- 12 个月内最可能出问题的点：[一句，附触发指标和数值；无则"未发现"]
（净现金公司债务三行填"净现金 X"并说明；金融/REIT 按 metrics.md 替换行）

### F3 可外推的历史基线（给 05 · 直接当假设表的历史列 · 一行不能缺）

**基年绝对值（最近财年 / TTM，单位与币种）**
| 科目 | FY-1 | TTM |
| :-- | :-- | :-- |
| 收入 | | |
| 营业利润（剔一次性后） | | |
| 净利润（剔一次性后） | | |
| 折旧摊销 | | |
| 资本开支 | | |
| 经营现金流 | | |
| SBC | | |
| 现金及等价物 | | 期末 |
| 有息负债（含租赁） | | 期末 |
| 有形权益 | | 期末 |
| 稀释股本 | | 期末 |

**历史比率（已剔除一次性项目；剔了什么见 §持续性拆分）**
| 科目 | FY-5 | FY-4 | FY-3 | FY-2 | FY-1 | 5年 | 方向 | TTM |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 收入增速 | | | | | | CAGR | | |
| 毛利率 | | | | | | 均值 | | |
| 营业利润率 | | | | | | 均值 | | |
| 净利率 | | | | | | 均值 | | |
| 有效税率 | | | | | | 均值 | | |
| 经营性营运资金/收入 | | | | | | 均值 | | |
| 资本开支/收入 | | | | | | 均值 | | |
| 折旧摊销/收入 | | | | | | 均值 | | |
| SBC/收入 | | | | | | 均值 | | |
| 经营现金流/净利润 | | | | | | 均值 | | |
| 稀释股本变动率 | | | | | | CAGR | | |
| ROIC（不含商誉） | | | | | | 均值 | | |
| 增量营业利润率（3年滚动） | | | | | | — | | |
| 净负债/EBITDA | | | | | | 均值 | | 期末 |
| 利息覆盖 | | | | | | 均值 | | |
（口径不可比的格加 `*`，并购并表年加 `†`，表下各用一行说明。ROIC 与增量利润率的 TTM 列固定填 n/a。金融/REIT 按 metrics.md 替换行）

### F4 资本配置台账（给 07 · 固定 7 行 + 1 句）
| 用途 | 近5年累计 | 占同期经营现金流% | 趋势 |
| :-- | :-- | :-- | :-- |
| 资本开支 | | | |
| 研发 | | | |
| 并购 | | | |
| 回购 | | | |
| 分红 | | | |
| 净还债 | | | |
| SBC（非现金） | | | |
- 钱说明公司在想什么：[一句——从花钱去向看，公司处在什么阶段、真正相信的战略是什么]（只推断，不评价对股东好坏）

### F5 说法与数字对照表（给 03 · ≤8 行）
| 谁在说 | 说法 | 数字怎么说 | 一致 / 不一致 / 数据不足 |
| :-- | :-- | :-- | :-- |
（只列公司或市场真在讲的说法。"不一致"的行 03 必须查；没有可对照的说法就写"未发现"）

### F6 业务判断与推翻条件（≤5 条）
| 判断 | 为什么 | 什么情况说明判断错了（指标 + 数值） | 谁去验证 |
| :-- | :-- | :-- | :-- |
（判断要是业务结论，不是比率描述；写不出"为什么"和"什么情况算错"的不许上表。财务安全的红旗至少对应一条判断）

### F7 异常与缺口（≤6 行；无则"未发现"）
| 现象 | 数字 | 可能含义（≥2 种） | 谁去查 |
| :-- | :-- | :-- | :-- |
（问 7 的异常和体检的旗都可以进；数据缺口单列，写清是底稿缺、附注未披露还是公司不适用）

```json
{
  "handoff_version": 3,
  "fiscal_years": ["FY2021", "FY2022", "FY2023", "FY2024", "FY2025"],
  "ttm_end": "2026-06-30",
  "basis": "GAAP|non-GAAP|mixed",
  "restated": false,
  "one_offs_removed": ["一句话描述每项"],
  "company_type": {"asset": "重|轻", "stage": "成长|成熟|收缩", "cashflow": "稳定|周期|前置投入"},
  "numbers_only_profile": "一句话",
  "financial_safety": {
    "verdict": "一句话：会不会出事、账实不实",
    "net_debt_to_ebitda": {"fy_1": 0, "latest": 0, "trend": "上行|下行|走平|无规律|净现金"},
    "interest_coverage": {"fy_1": 0, "ttm": 0, "trend": ""},
    "fcf_to_debt": {"fy_1": 0, "ttm": 0},
    "cash_to_debt_due_1y": {"latest": 0},
    "debt_due_3y_pct": 0, "floating_rate_pct": 0,
    "off_balance_sheet": "一句话或 未披露重大项目",
    "goodwill_intangibles_to_assets": {"fy_1": 0, "latest": 0, "trend": ""},
    "impairment_headroom_min_pct": 0,
    "tangible_equity": 0,
    "receivables_growth_gap_pt": {"fy_2": 0, "fy_1": 0},
    "bad_debt_reserve_pct": 0,
    "inventory_growth_gap_pt": {"fy_2": 0, "fy_1": 0},
    "capitalization_ratio": {"fy_5": 0, "fy_1": 0},
    "red_flags": ["一句话"], "yellow_flags": ["一句话"],
    "watch_12m": "一句话，含触发指标与数值"
  },
  "base_year": {
    "currency": "USD", "unit": "million",
    "fy_1": {"revenue": 0, "op_income_adj": 0, "net_income_adj": 0, "da": 0, "capex": 0, "ocf": 0, "sbc": 0},
    "ttm":  {"revenue": 0, "op_income_adj": 0, "net_income_adj": 0, "da": 0, "capex": 0, "ocf": 0, "sbc": 0},
    "balance_latest": {"cash": 0, "debt_incl_leases": 0, "tangible_equity": 0, "diluted_shares": 0}
  },
  "baseline": {
    "revenue_growth": {"fy_5": 0, "fy_4": 0, "fy_3": 0, "fy_2": 0, "fy_1": 0, "avg5": 0, "trend": "上行|下行|走平|无规律", "ttm": 0},
    "gross_margin": {}, "operating_margin": {}, "net_margin": {}, "tax_rate": {},
    "nwc_to_revenue": {}, "capex_to_revenue": {}, "da_to_revenue": {}, "sbc_to_revenue": {},
    "ocf_to_ni": {}, "share_count_change": {}, "roic_ex_goodwill": {}, "incremental_op_margin": {},
    "net_debt_to_ebitda": {}, "interest_coverage": {}
  },
  "capital_allocation_5y": {"capex": 0, "rnd": 0, "ma": 0, "buyback": 0, "dividend": 0, "net_debt_repay": 0, "sbc": 0, "ocf_total": 0, "what_money_says": "一句话"},
  "claims_vs_numbers": [{"claim": "", "data_says": "", "verdict": "一致|不一致|数据不足"}],
  "judgments": [{"claim": "", "why": "", "wrong_if": "", "owner": "03|05|07|下季财报|管理层"}],
  "anomalies": ["一句话"],
  "data_gaps": ["一句话"]
}
```

<!-- HANDOFF-END v3 -->
```

## 写完前自查

- F2 九行一行不缺；净现金公司写明；红黄旗与 `financial_safety.red_flags / yellow_flags` 一致
- F3 两张表一行不缺；`n/a` 的行表下有说明；比率与 `baseline` JSON 逐项一致；基年绝对值与 `base_year` 一致
- F4 七行与 `capital_allocation_5y` 一致，`ocf_total` 是分母
- F6 每条都有"为什么"和"什么情况算错"；有红旗时至少一条判断对应红旗；F5 每条都有"谁在说"
- 方向列没有用到 TTM
- 没有把三张表和推算过程写进交接块
- 最后一行是结束标记 `<!-- HANDOFF-END v3 -->`

## v2 → v3 下游取数位置对照（改下游 skill 时用）

| 内容 | v2 | v3 | 取用方 |
| :-- | :-- | :-- | :-- |
| 数字画像 + 口径 | F1 | F1（多一行"财务安全"） | 全部 |
| 财务安全 | — | **F2（新）** | 05 / 07 / 估值 |
| 可外推历史基线 | F2 | **F3**（多"有形权益""净负债/EBITDA""利息覆盖"三行） | 05 |
| 资本配置台账 | F4 | F4（不变） | 07 |
| 说法与数字对照 | F3 | **F5** | 03 |
| 业务判断 | F5 | **F6** | 03 / 05 / 07 |
| 异常与缺口 | F6 | **F7** | 03 / 07 / research-event-update |
| JSON | `handoff_version: 2` | `handoff_version: 3`，新增 `financial_safety`，`baseline` 多两键，`balance_latest` 多 `tangible_equity` | 全部 |
| 结束标记 | `<!-- HANDOFF-END v2 -->` | `<!-- HANDOFF-END v3 -->` | 编排层 |

下游按节号硬取数的（03 取 F3、05 取 F2、research-summary 找 `HANDOFF-END v2`）要跟着改；按标题文字或 JSON 键取的不受影响。
