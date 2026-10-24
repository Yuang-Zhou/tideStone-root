# 数据对照表：skill 要的数 ↔ financials.json 的字段

第 0b 步的数据底座由 `scripts/render_tables.py` 按本表字段生成；字段名变了同时改本表和脚本顶部的 `FIELDS`。

`financials.json` 由 `_system/scripts/fetch_edgar_financials.py` 生成。**skill 只从这里取数；脚本已经算好的（TTM、勾稽、台账合计）不重算。** 字段名变了改这张表，不改 SKILL.md。

**能力校验只看 `meta.capabilities`（脚本会去找的全部指标名单），不看 `script_version`**——版本号是手敲常量，会和实际能力脱节。判定三分法见 SKILL.md「底稿能力校验」。

## 文件结构

| 顶层键 | 内容 | 怎么用 |
| :-- | :-- | :-- |
| `meta.fetched_at` | 取数日 | 写进报告开头；早于最近一期已发布财报 → 报缺 |
| `meta.capabilities` | 脚本会去找的全部指标名单（v0.4.1 起） | **能力校验唯一依据**。要的字段不在里面 = 脚本要升级，记 F7 数据缺口 |
| `meta.suspect_metrics` | 命中的 tag 全是 `Other*` 残差科目的指标（v0.4.1 起） | **不许直接用**：回原文取全额，正文标注，F7 建议改 `tag_map` |
| `meta.fiscal_year_ends` | 每个年度标签的期末日、天数、周数 | 表头 FY 名称；`weeks=53` 的年份增速标 `*` |
| `meta.week53_years` | 53 周年份列表 | 同上 |
| `meta.missing_metrics` | 没取到的指标 | **不是 0**。逐条判：公司真没有 / 自定义标签 / 在附注里 |
| `meta.tag_map` | 每个指标实际用了哪个 XBRL 标签 | 溯源；`gross_profit` 等标签口径与"收入−成本"不同时要看 |
| `annual` | 指标 → {年度标签: 值} | 5 年比率表的原料 |
| `quarterly` / `ytd` | 单季 / 累计 | 只在需要看季度节奏时用 |
| `ttm` | `period_end`、`flow.*`、`instant.*`、`notes` | **TTM 直接用，不自己算**；`notes` 里"缺去年同期"的指标填 n/a |
| `checks` | 勾稽自检（每条 `check / year / pass / diff_pct / note`） | `pass=false` 的行写进 F1 口径与局限；"其他损益"那行的金额是一次性项目候选 |
| `capital_allocation` / `capital_allocation_total` | 逐年 + 合计 | F4 台账原料；合计里 `cfo` 是分母 |
| `records` | 每个数的申报来源 | 要溯源某个数时查 tag / form / filed / accn；`restated=true` 的看 `prior_value` |

## 七问 ↔ 字段

单位：脚本给的是美元原值，报告统一换成百万。

| skill 要的 | 取法 |
| :-- | :-- |
| 收入、成本、SG&A、研发、营业利润、税前、所得税、净利润 | `annual.revenue / cost_of_revenue / sga_expense / rnd_expense / operating_income / pretax_income / income_tax / net_income` |
| 毛利率 | `(revenue − cost_of_revenue) / revenue`。**先看 `checks` 里"收入−成本=毛利"有没有过**：没过说明公司的 `gross_profit` 标签口径不同（如 Costco 不含会员费），正文注明用的是哪个 |
| 利息支出 / 利息收入 | `annual.interest_expense / interest_income`；`checks` 里"营业利润−利息=税前"的差额 = 其他损益 |
| 折旧摊销、SBC、经营现金流、资本开支 | `annual.depreciation_amortization / sbc / cfo / capex` |
| 自由现金流 | `capital_allocation` 列表中 `year` 匹配行的 `fcf`（脚本已算，= cfo − capex；capex 为正数支付额） |
| 经营性营运资金 | `accounts_receivable + inventory + prepaid_and_other_current − accounts_payable − accrued_liabilities − employee_liabilities − deferred_revenue`。缺哪项按 0 处理并在表下注明 |
| 存货 / 应收 / 应付天数 | 分子用 `inventory / accounts_receivable / accounts_payable`（期初期末平均），分母按 metrics.md |
| 预收 / 递延收入 | `annual.deferred_revenue` |
| 固定资产净值、使用权资产、商誉、无形资产 | `ppe_net / operating_lease_rou / goodwill / intangibles` → 投入资本 |
| 有息负债（含租赁） | `short_term_debt + long_term_debt + operating_lease_liab_current + operating_lease_liab_noncurrent + finance_lease_liab_current + finance_lease_liab_noncurrent` |
| 现金 + 短期投资 | `cash_and_equivalents + short_term_investments` |
| 稀释股本（加权）/ 期末股本 | `shares_diluted`（流量）/ `shares_outstanding`（时点） |
| 少数股东 | `minority_interest`（时点）、`nci_income`（流量）；`net_income_incl_nci` 是含少数股东的净利润 |
| 一次性候选 | `annual.impairment / restructuring`；`checks` 其他损益差额；`records` 里 `restated=true` 的项 |
| 实付税 vs 税费 | `income_taxes_paid` vs `income_tax` |
| 资本配置 5 年 | `capital_allocation` 取最近 5 行；`net_debt_repayment` 已算好（还 − 借）；并购 = `acquisitions + payments_to_nci`；分红字段名是 `dividends_paid` |
| 财务安全体检：债务与现金 | `short_term_debt / long_term_debt / operating_lease_liab_* / finance_lease_liab_* / cash_and_equivalents / short_term_investments / interest_expense`；净还债用 `capital_allocation[年].net_debt_repayment` |
| 财务安全体检：资产质量 | `goodwill / intangibles / accounts_receivable / inventory / impairment / total_assets / total_equity / current_assets / current_liabilities`；v0.4.0 新增 `allowance_doubtful_accounts / inventory_reserve / ppe_gross / accumulated_depreciation / deferred_tax_assets / restricted_cash / finance_lease_rou`。缺的走 `meta.missing_metrics` 判定流程 |
| 财务安全体检：到期与利息 | v0.4.0 新增 `debt_due_1y / debt_due_y2 … debt_due_y5 / debt_due_after_y5`（长期债务本金到期分布，不含租赁）、`operating_lease_payments_due`、`interest_paid`。固定/浮动、币种、契约、信贷额度仍在附注 |
| TTM 所有流量 | `ttm.flow.<指标名>` |
| 最新期末所有时点 | `ttm.instant.<指标名>`；`ttm.notes` 会指出哪些时点数不是最新期末（如商誉只在 10-K 报） |

## 脚本给不了的（去 raw/ 读原文）

分部收入与利润、带维度的收入拆分（会员费、产品线）、租赁明细、商誉减值原因、税务附注里的离散项、一次性损益的性质、应收账款构成、Kirkland 一类的经营指标。**第 1 步财务安全体检要的**：债务到期分布、固定/浮动、币种、加权利率、契约条款、未提取信贷额度、担保与或有负债、采购承诺、商誉按报告单元分布与减值测试 headroom、应收账龄与坏账准备、客户集中度、保理、存货构成与跌价准备、资本化研发、折旧年限变更。这些属于第 0 步（口径）、第 1 步（财务安全）和第 4 步（持续性拆分）要读的附注，不属于第 1–2 步禁读的叙事。
