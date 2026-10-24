# TideStone · 潮石

在 Codex 中开展公司研究，在本地网页阅读成果，用 Git 保存版本。

[快速开始](#快速开始) · [文档](docs/README.md) · [贡献指南](CONTRIBUTING.md)

## 功能

- **研究建档**：公司入库、公开资料收集，以及文化、财务、商业模式、战略、股性、预测和估值七个模块。
- **审阅与追溯**：草稿、修订、接受和历史版本分开保存，材料与结论保留来源及内容指纹。
- **持续跟踪**：事件更新、预测偏差复盘、行情维护、研究简报和独立模拟盘。
- **本地阅读**：查看公司状态、研究报告、估值对比与运行记录。

研究由 Codex 执行；本地脚本负责数据、状态和页面。日常数据维护与 AI 新闻扫描分别运行，研究结论须经用户明确接受。

## 快速开始

当前验证环境：**macOS、Python 3.10、Git**。研究工作需要 Codex；其他系统或 Python 版本的兼容性尚未验证。

```sh
git clone https://github.com/Yuang-Zhou/tideStone-root.git
cd tideStone-root
python3 -m venv .venv
.venv/bin/python -m pip install -r config/requirements-market.lock.txt
.venv/bin/python scripts/tidestone.py status --json
.venv/bin/python scripts/ops.py start
```

打开 [http://127.0.0.1:8791](http://127.0.0.1:8791)。服务仅监听本机。已有环境也可双击 `启动潮石.command`。

本仓库同时保存程序与研究工作区，`Projects/` 中包含真实材料及待审记录。克隆后先查看状态，再继续研究。

在 Codex 打开项目目录，输入：

> 我想研究某家公司。请按潮石流程准备材料，完成七模块分析并提交待审稿。

美股 SEC 取数需要在 `config/local.env` 中填写自己的联系标识，格式见 [配置示例](config/local.env.example)。定时任务需在本机单独配置，详见[使用指南](docs/操作指南.md)。

## 常用命令

在项目根目录运行：

| 操作 | 命令 |
| --- | --- |
| 查看研究状态 | `python3 scripts/tidestone.py status --json` |
| 重建网页 | `python3 scripts/ops.py build` |
| 启动网页 | `python3 scripts/ops.py start` |
| 停止网页 | `python3 scripts/ops.py stop` |
| 执行数据维护 | `python3 scripts/ops.py daily` |
| 创建本地备份 | `python3 scripts/ops.py backup` |

完整参数见 `python3 scripts/tidestone.py --help` 与 `python3 scripts/ops.py --help`。运行工具会优先使用项目内的 `.venv`。

## 项目结构

```text
.agents/skills/       研究方法与执行入口
Projects/companies/  公司材料、研究档案与工作流记录
Projects/_system/    共享引擎、注册表与行情数据
scripts/             本地命令行入口
web/                 阅读页面
config/              依赖记录、配置示例与本机任务配置
docs/                使用说明、方法说明与验证记录
reference/upstream/  固定版本的上游参考原件
tests/               隔离回归测试
runs/                运行日志与隔离验证目录
```

## 文档与协作

- [使用指南](docs/操作指南.md)：研究流程、运行维护、备份与恢复。
- [文档索引](docs/README.md)：方法、数据契约和验证记录。
- [贡献指南](CONTRIBUTING.md)：开发环境、测试和 Pull Request 流程。
- [Agent 协作约定](AGENTS.md)：研究依赖、数据边界与接受规则。

`main` 保存项目主线，团队修改通过分支和 Pull Request 审阅。Git 提交或合并不替代研究接受。云端仅保存已推送的版本，本地修改不会自动同步。

## 来源与许可

研究方法与引擎基于 [AI-Investment-System](https://github.com/flyfish0108/AI-Investment-System/tree/e5b147afa1b2c49bb9a6651094958538d5802a59)，固定提交为 `e5b147a`。来源清单见 [SOURCE_LOCK.json](reference/SOURCE_LOCK.json)，本地适配及已知缺口见[方法对应记录](docs/method-map.md)。原始参考文件按原字节保留。

仓库当前为私有协作项目，尚未设置统一开源许可证。上游代码、方法、品牌资产与研究材料的来源分别保留；公开发布前需明确各部分的授权范围。
