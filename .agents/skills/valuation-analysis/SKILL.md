---
name: valuation-analysis
description: "按潮石原方法完成 07 估值，消费 05/06 与 04，按已登记信号判主导情景并选主定价方法；禁止情景和方法加权目标价。用于建档编排或明确估值请求。"
---

# valuation-analysis · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 先读 05/06 与 04 交接；缺所需输入时补齐相应分析，不能将过期或空报告视为满足前置条件。
- 计分信号取 06 分歧驱动表，04 仅作交叉校验与事件路标。主导情景和主估值方法分别判定；目标价等于该方法在该情景的值，不做平均价。
- 若原文兼容旧预测的“补建分歧表”被使用，补建内容先作为 06 待审修订，不越过待审流程静默改权威版。
- 07 §4.8 登记块与正文数字、评级、区间、情景、机会类型逐项一致。没有可验证数值时留明确缺口，不能用 0、示例价或不明字符串充数。

- 本地三年目标同步使用独立的 `### three_year_valuation_registry 登记块` JSON，沿用原三年基准估值公式。必需字段：`target_year, currency, scenario, valuation_method, valuation_type, metric_value_b, target_multiple, net_debt_b, share_equivalent_b, target_market_cap_b, target_price_3y, anchor_price, anchor_date, source`。`scenario=base`，所有 `_b` 用十亿，目标年份等于建锚年份加三；`valuation_type` 为 `ev/equity/fixed`，EV法要减净债。每股价须与目标股权市值÷股数一致。可写 target_date 说明确切日期；出处写本批06/07实际计算位置，不填示例。同步程序自动添加接受批次与内容指纹，不手造来源。无法支持三年数值时如实留缺口，同步保留待补而不沿用旧价。

## 随附材料

本技能没有另附有效文件；系统级规范按原文路径在 `Projects/_system/` 读取。

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
