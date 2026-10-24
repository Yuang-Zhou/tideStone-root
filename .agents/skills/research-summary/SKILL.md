---
name: research-summary
description: "将潮石已接受的公司研究档案汇总为可阅读的本地 HTML 总结。仅从指定档案取材，不联网补结论；缺失维度明确显示。"
---

# research-summary · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 完整读取 assets/template.html，按原文七节/术语/三情景/主定价方法/回报拆解要求生成可读 HTML。素材只能是本次指定的档案。
- 正式总结只消费已接受档案；用户明确要求看草稿总结时另存 pending 内，并醒目标待审。缺基准日或股价先查档案/已登记材料，仍缺则标未提供，不凭空补。
- 源仓库的 scripts/example.py、references/api_reference.md、assets/example_asset.txt 是空脚手架，未作为功能迁移；现存有效模板保留。本地网页构建只展示已有报告，不能把简单拼接冒称人工综合总结。
- 本地适配输出到本公司目录 `研究总结_<YYYY-MM-DD>.html`，并保留同名 `.md` 总结供追问；两者数字与结论保持一致。正式版只有接受后才生成；同日已有总结时使用 `研究总结_<YYYY-MM-DD_HHMMSS>` 新文件，保留旧版，不能覆盖历史。待审版留在批次内。用本地文件链接与网页入口交付，不使用 computer:// 或外部上传。

- HTML 与 Markdown 成品保存后，运行 `.venv/bin/python scripts/register_summary.py TICKER --markdown 完整路径.md --html 完整路径.html`，将内容指纹及七份已接受来源登记；随后运行 `python3 scripts/ops.py build`。网页只展示已登记且文件未变的总结；登记失败先核对来源与命名，不绕过。

## 随附材料

- `assets/template.html`

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
