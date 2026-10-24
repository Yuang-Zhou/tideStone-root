---
name: vc-style-valuation
description: "按上游独立 VC 风格方法研究十倍机会的增长、重估、稀释与下行。仅在用户明确要求此方法时使用，结果不进入核心非加权估值登记表。"
---

# vc-style-valuation · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 必读 reference.md。计算必须使用随附 scripts/valuation_engine.py，并检查结果与输入。
- 此方法原文确实计算概率加权 MOIC/IRR，与核心 07 的双禁加权口径不同。保留独立辅助报告，明确概率为主观假设，不把其加权值、建议区间或评级同步到核心 valuation_registry。
- 用户没有明确要求 VC 风格时，完整档案继续用 valuation-analysis；二者不相互替换。

## 随附材料

- `reference.md`
- `scripts/valuation_engine.py`

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
