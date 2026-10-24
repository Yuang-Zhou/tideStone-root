---
name: value-growth-paper-monitor
description: "复核潮石低估加增长模拟盘及当日行情，生成本地看板和摘要；只处理本项目纸面组合，不继承同僚本金、持仓、起点或通知。"
---

# value-growth-paper-monitor · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 先读本项目模拟盘 config 与状态，保留原筛选/等权/迟滞/新鲜度/同日幂等规则。若不同源文档写 7 天而当前引擎为 3 天，以实际引擎配置并明确记录为准。
- 不继承原本金 $126,376.38、2026-09-30 起点、旧持仓及净值。空研究库显示未运行/无合格标的，不伪造表现；初始化与参数以本项目用户意图及配置为准。
- 只执行纸面引擎并核 stdout + 实际输出；报告 trades_today，不把重跑 trades=0 当当天没成交。行情陈旧要同时显示价格日期。
- 本地构建代替原 Artifact 发布；不访问原账号、不 git push、不发送外部提醒。

## 随附材料

本技能没有另附有效文件；系统级规范按原文路径在 `Projects/_system/` 读取。

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
