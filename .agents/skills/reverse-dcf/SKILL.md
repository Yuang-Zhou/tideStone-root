---
name: reverse-dcf
description: "按上游反向现金流估值方法解释市场价格隐含增长，支持单股、同业、产业链和分部比较；用于用户问市场已计入什么，不直接改正式目标价。"
---

# reverse-dcf · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 必读 references/methodology.md，按需要读取 references/advanced.md。现金流为负/估值极端时按原文终态反推，不硬套正常模型。
- 明确反推所得是一组参数条件下的隐含增长，不是市场真实共识的直接观测；独立保存报告，不能直接覆写 07 目标价。

## 随附材料

- `references/advanced.md`
- `references/methodology.md`

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
