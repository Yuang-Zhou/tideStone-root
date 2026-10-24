---
name: financial-forecast-feedback
description: "潮石季度预测偏差分诊。用于财报实际值与预测比较、偏差复盘；只出偏差判定单，不修改正式档案、估值或自动发起刷新。"
---

# financial-forecast-feedback · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 逐行按原文进行同比/TTM/季节性/事件口径对齐、T1/T2/T3 核对和 03→04→01 重审建议；缺历史与无数据均明确写出。
- 输出 _deviation/ 判定单及事实来源，不修改正式 06/07、registry，不自动调 research-event-update。
- 原文对金融股/外币 ADR 的限制不能被“新 fetcher 能下载”解除。须核底稿 capabilities、币种、季度可比性；未验证适配则标不支持自动分诊，可另给注明范围的人工比较。

## 随附材料

本技能没有另附有效文件；系统级规范按原文路径在 `Projects/_system/` 读取。

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
