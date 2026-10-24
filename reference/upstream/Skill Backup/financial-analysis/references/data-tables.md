# 数据底座：第 0b 步要摆出来的表

目的：让读者一眼看到这家公司五年长什么样，后面每个判断都能回这里核。**不是照抄报表**，每张表十来行，全部来自底稿。由 `scripts/render_tables.py` 生成，模型只加标记和注释。

通用格式：列 = FY-5 … FY-1 + TTM；单位百万，币种在表头写明；缺的格填 `n/a`；口径标记 `*`（不可比）、`†`（并购并表年）、`53w`（53 周财年）放在列头或格子后面，表下一行说明。

---

## 表 1 利润表（精简）

| 行 | 取自 | 备注 |
| :-- | :-- | :-- |
| 收入 | `annual.revenue` | |
| 收入增速 | 算 | 需 6 年数据才能填满 5 列 |
| 营业成本 | `annual.cost_of_revenue` | |
| 毛利 | 收入 − 成本 | `checks` 没过时注明与公司标签的差异 |
| 研发 | `annual.rnd_expense` | 没有则整行 n/a |
| 销售管理 | `annual.sga_expense` | |
| 折旧摊销 | `annual.depreciation_amortization` | |
| 减值 / 重组 | `annual.impairment` + `annual.restructuring` | 一次性候选 |
| 营业利润 | `annual.operating_income` | |
| 利息支出（净） | `annual.interest_expense` − `annual.interest_income` | |
| 其他损益 | `checks` 差额 | 一次性候选 |
| 税前利润 | `annual.pretax_income` | |
| 所得税 | `annual.income_tax` | |
| 净利润 | `annual.net_income` | |
| SBC | `annual.sbc` | |
| 稀释股本 | `annual.shares_diluted` | 百万股 |

## 表 2 资产负债表（期末，精简）

| 行 | 取自 |
| :-- | :-- |
| 现金 + 短期投资 | `cash_and_equivalents` + `short_term_investments` |
| 应收账款 | `accounts_receivable` |
| 存货 | `inventory` |
| 固定资产净值 | `ppe_net` |
| 使用权资产 | `operating_lease_rou` |
| 商誉 | `goodwill` |
| 无形资产 | `intangibles` |
| 总资产 | `total_assets` |
| 应付账款 | `accounts_payable` |
| 递延收入 | `deferred_revenue` |
| 有息负债（含租赁） | 按 metrics.md 公式合计 |
| 股东权益 | `total_equity` |
| 有形权益 | 权益 − 商誉 − 无形 |

## 表 3 现金流量表（精简）

| 行 | 取自 |
| :-- | :-- |
| 经营现金流 | `annual.cfo` |
| 资本开支 | `annual.capex` |
| 自由现金流 | `capital_allocation[年].fcf` |
| 并购 | `capital_allocation[年].acquisitions` + `payments_to_nci` |
| 回购 | `capital_allocation[年].buyback` |
| 分红 | `capital_allocation[年].dividend` |
| 净还债 | `capital_allocation[年].net_debt_repayment` |
| 实付所得税 | `annual.income_taxes_paid` |

## 表 4 关键比率速览

| 行 | 算法 |
| :-- | :-- |
| 毛利率 / 营业利润率 / 净利率 | 表 1 |
| 经营现金流 / 净利润 | 表 3 ÷ 表 1 |
| 自由现金流 / 收入 | |
| 资本开支 / 收入 | |
| 固定资产 / 总资产 | 总资产缺则 n/a |
| 应收天数 / 存货天数 / 应付天数 / 现金转换周期 | metrics.md |
| 经营性营运资金 / 收入 | metrics.md |
| ROIC（不含商誉） | metrics.md，TTM 填 n/a |
| 净负债 / EBITDA | metrics.md，净现金写"净现金" |
| 利息覆盖 | metrics.md |
| 商誉 + 无形 / 总资产 | |
| SBC / 经营现金流 | |

## 表 6 体检补充（脚本生成，v0.4.0 底稿字段）

流动比率、速动比率、现金/1 年内到期债务、1 年内到期债务、3 年内到期占比、经营现金流/利息实付、坏账计提率、存货跌价计提率、折旧率、递延税资产/总资产、受限现金。公司不再申报某标签时该行 n/a（如 Costco 2012 年后不报坏账准备），不是 0。

## 表 5 一次性项目标注（模型填，脚本只给候选）

| 财年 | 科目 | 金额 | 性质 | 剔除？ | 来源 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| | 减值 / 重组 / 处置 / 诉讼 / 税务 / 其他 | | 一句话 | 是 / 否 / 待定 | 附注页码或 `records` |

候选来源：表 1 的"减值 / 重组"和"其他损益"行、`records` 里 `restated=true` 的项、税率异常年份。**没有就写"未发现重大一次性项目"**，不硬找。"剔除后"的营业利润和净利润在这张表下面各给一行，第 1、2 步和 F3 用剔除后的数。

---

## 0c 形态速判（≤3 行，表 5 之后）

- 类型：非金融 / 银行 / 保险 / 券商 / REIT → 用 metrics.md 哪套指标
- 资产：重 / 轻（固定资产/总资产 X%，资本开支/收入 Y%）
- 营运资金：正 / 负，是否行业常态

这三行只为第 1 步选阈值，不是结论。
