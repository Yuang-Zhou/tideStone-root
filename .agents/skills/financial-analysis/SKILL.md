---
name: financial-analysis
description: "按潮石原方法完成 02 财务分析。先核财务底稿口径与财务安全，再从数字推生意，最后核管理层叙事，产生下游交接；用于建档编排或明确财务分析请求。"
---

# financial-analysis · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 先读 references/data-contract.md，再按原文顺序读取其余参考文件；原文列的六份为本技能必需参考，不可只读概述。
- 数字来自本公司统一底稿/一手报告。先查 fetched_at、币种、财年、单位、suspect_metrics 和勾稽告警；缺底稿交回编排层补取，不能自己用零或二手摘数凑表。
- “先数字、后叙事”的顺序须真实执行。输出 02 与交接块，事实、推断、假设分清；数据不足可形成受限草稿，不能标完成。

## 随附材料

- `references/data-contract.md`
- `references/data-tables.md`
- `references/handoff.md`
- `references/health-check.md`
- `references/metrics.md`
- `references/seven-questions.md`
- `scripts/render_tables.py`

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
