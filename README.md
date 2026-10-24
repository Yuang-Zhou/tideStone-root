# 潮石

在 Codex 中研究、追问和确认；在本机网页阅读成果。所有资料保存在这个项目里，正式研究库从空白开始。

**现在开始：**在 Codex 打开本文件夹，说：

> 我想研究某家公司，请按潮石流程从入库、准备资料开始，完成七个模块后给我待审草稿。

**阅读页面：**[打开本地潮石](http://127.0.0.1:8791)。页面关闭不影响文件保存；服务未启动时双击本目录的 `启动潮石.command`，或请 Codex“启动潮石本地网页”。

- [操作指南](docs/操作指南.md)：每一步说什么、得到什么、如何修订和持续跟踪。
- [方法学习报告](docs/method-learning.md)：原方法怎么工作、前提与局限。
- [实施与验证](docs/实施与验证.md)：迁移对应、实测结果、未接通范围。
- [方法对应记录](docs/method-map.md)：原文冲突及本地处理。

业务方法固定于同僚仓库 [e5b147a](https://github.com/flyfish0108/AI-Investment-System/tree/e5b147afa1b2c49bb9a6651094958538d5802a59)，2026-10-24 重新取得。没有迁入同僚公司研究、估值或持仓。旧潮石仅单独提取 Logo。

需要离开电脑时，可说“备份潮石”。不要把整个项目移动或改名后继续运行原定时任务；先请 Codex 更新本地路径登记。

## GitHub 备份与团队协作

项目使用个人私有仓库 [Yuang-Zhou/tideStone-root](https://github.com/Yuang-Zhou/tideStone-root)，主分支为 `main`。GitHub 保存已提交并推送的版本；本地修改不会自动上传。网页仍在本机运行。

版本管理包含代码、项目 Skills、固定来源参考、配置示例、研究材料、待审稿及修订历史、系统业务状态和实际运行日志。`.gitignore` 排除本机凭证、虚拟环境、会话缓存、临时文件、生成网页、重复压缩备份和测试恢复副本；这些排除项继续保存在本机。`.gitattributes` 禁止自动转换换行符，保持材料与原文的内容指纹。当前研究是否已接受，以 `Projects/` 内的工作流记录为准，Git 提交或合并不代表接受研究。

换电脑或从云端恢复，在选定的父目录执行：

```sh
git clone https://github.com/Yuang-Zhou/tideStone-root.git
cd tideStone-root
python3 -m venv .venv
.venv/bin/python -m pip install -r config/requirements-market.lock.txt
python3 scripts/tidestone.py status --json
python3 scripts/ops.py build
python3 scripts/ops.py start
```

当前依赖记录基于 Python 3.10；新的系统或 Python 版本需核验兼容性。需要 SEC 取数时，从 `config/local.env.example` 创建本机 `config/local.env` 并填写自己的标识。定时任务不会随克隆自动安装；`config/` 中的任务路径与状态是原机器快照，换电脑后应重新生成配置、安装并检查实际运行日志。

日常维护先查看 `git status`，用 `git add <本次修改的路径>` 暂存并核对 `git diff --cached`，随后 `git commit -m "说明本次修改"`、`git push`。请勿把密钥、账户凭证加入版本库。

团队成员受邀获得仓库权限后，在各自分支提交修改，通过 Pull Request 审阅合并到 `main`。先阅读 `AGENTS.md`；同一公司或同一研究批次应约定一名写入负责人，避免同时改注册表或接受状态。研究草稿依然需要用户明确接受；合并代码不能替代研究审批。
