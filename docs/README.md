# 文档

[项目首页](../README.md) · [贡献指南](../CONTRIBUTING.md)

## 使用与维护

| 文档 | 内容 |
| --- | --- |
| [使用指南](操作指南.md) | 研究流程、页面、配置、日常维护、备份与恢复 |
| [贡献指南](../CONTRIBUTING.md) | 分支协作、验证和变更提交 |
| [Agent 协作约定](../AGENTS.md) | 研究依赖、文件权限与接受规则 |

## 方法与实现

| 文档 | 内容 |
| --- | --- |
| [方法学习报告](method-learning.md) | 原方法的逻辑、前提和局限 |
| [方法对应记录](method-map.md) | 上游来源、本地适配与已知差异 |
| [数据与登记契约](runtime-adaptation.md) | 研究状态、估值登记、同步及总结来源 |
| [固定来源清单](../reference/SOURCE_LOCK.json) | 上游提交、文件路径与内容指纹 |

## 验证记录

[实施与验证](实施与验证.md)、[工作流试跑](workflow-trial.md)和[网站观察](source-website.md)记录特定日期的检查结果，证据保存在 [evidence/](evidence/)。记录中的机器路径、测试目录和状态属于当时环境；测试与恢复副本不随 Git 分发。

当前研究状态以 `python3 scripts/tidestone.py status --json` 为准，实际运行结果以本机日志为准。
