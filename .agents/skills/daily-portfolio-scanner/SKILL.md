---
name: daily-portfolio-scanner
description: "运行潮石每日公司扫描，核本地行情及新闻、已登记催化剂和估值更新需求，生成本地简报与扫描记录；不改研究结论、不下单、不发布外网。"
---

# daily-portfolio-scanner · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 必读 Projects/_system/scanner/简报模板.md、daily_briefing/SCHEMA.md 现行字段及数据校验规范。名单、行情、估值、催化剂分别从原文规定的当前本地来源取。
- 原 0a 的 slot06_path/加权目标价是旧字段：改用已接受 07 的同步队列和 sync_valuations.py drain，再 apply/check；不自行从草稿补目标价。
- 新闻需要实际检索与两条独立来源核验，转引同一新闻稿不算独立来源。搜不到写覆盖降级，不写“无事件”。没有新闻执行器时，确定性日常脚本只代表刷新状态，不能宣称已完成 AI 新闻扫描。
- 保留点名 now/wait/stale、不可更改历史与催化剂追加规则；日志健康语义改为本地运行/构建健康。
- 本地健康证据读取 `Projects/_system/local_pipeline_status.json`、其 run_dir 下逐步日志与 `config/scheduler_status.json`，不因缺旧云端 last_run.log 就误报发布故障。逐步失败、上次运行时间、未运行AI要分别披露。
- 保留原 Markdown/JSON/扫描日志输出及数据校验；完成后运行 `python3 Projects/_system/scripts/validate_briefing.py 日期 --no-dashboard`，该命令尊重 TIDESTONE_PROJECTS。原 render_dashboard/make_artifact_html 外部看板链改为 `python3 scripts/ops.py build`，网页读取实际简报 Markdown；未通过内容校验不把草稿搬入正式简报目录。
- 全部输出留本地；原 Artifact URL、推送、邮件及发布账号不继承。原定时时间仅参考；只有实际注册且有运行日志的任务可称自动运行。

## 随附材料

本技能没有另附有效文件；系统级规范按原文路径在 `Projects/_system/` 读取。

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
