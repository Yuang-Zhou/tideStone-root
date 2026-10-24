# 贡献指南

潮石使用分支和 Pull Request 协作。开始前请阅读 [README](README.md) 和 [AGENTS.md](AGENTS.md)，并按 README 准备本地环境。

## 提交改动

1. 从最新 `main` 创建分支，例如 `fix/valuation-display` 或 `docs/quickstart`。
2. 一次解决一个明确问题，保留用户文件，避免顺手重排无关代码和资料。
3. 完成相关验证，检查 `git diff`，只暂存本次修改的文件。
4. 提交 Pull Request，说明问题、改动后的行为、验证结果和已知限制。

功能或方法调整较大时，先用 Issue 说明使用场景和影响范围。同一公司、研究批次或注册表应约定一名写入负责人。

## 开发与验证

命令均在仓库根目录执行。核心回归测试使用 Python 标准库；行情取数的额外依赖见 README。

测试数据必须放在 `runs/` 下，并显式设置 `TIDESTONE_PROJECTS`。以下命令先核对实际路径，再运行完整回归和隔离库的页面构建：

```sh
(
  set -eu
  export TIDESTONE_PROJECTS="$PWD/runs/tests/manual/Projects"
  python3 - <<'PY'
import os
from pathlib import Path

root = Path.cwd().resolve()
projects = Path(os.environ["TIDESTONE_PROJECTS"]).resolve()
if not (root / "scripts/tidestone.py").is_file():
    raise SystemExit("请在仓库根目录运行")
if not projects.is_relative_to(root / "runs"):
    raise SystemExit("测试数据根必须位于仓库 runs/ 内")
print(f"隔离测试数据根：{projects}")
PY
  python3 -m unittest discover -s tests -v
  python3 scripts/tidestone.py init
  python3 scripts/ops.py build
)
```

工作流测试还会在 `runs/tests/core/` 创建独立临时库，并在结束后清理。上面的环境变量仅在子 shell 中生效；测试网页保存在 `runs/tests/manual/Projects/_site/`。

代码变更需验证受影响的行为。纯文档修改检查命令、链接和差异即可；不要将旧测试记录描述为本次验证结果。涉及 Skills 时，另运行：

```sh
python3 .agents/skills/tidestone-research/scripts/validate_skills.py
```

## 研究与来源

Git 提交、PR 合并和测试通过都不代表研究已被接受。研究草稿写入公司目录的 `研究档案/_pending/<TS>/`；修改前执行 `revise`，修改后执行 `finalize`。只有用户明确接受可识别批次，才能执行 `accept`。不得直接覆盖正式档案。

`reference/upstream/`、各 Skill 的 `references/original.md` 和原文指纹用于追溯固定来源，不做措辞或格式整理。本地适配应与原文分开保存，在 [方法对应记录](docs/method-map.md) 说明差异；已有适配文件的指纹记录需同步更新，固定来源的原文指纹保持不变。研究材料、批次和登记表的哈希由工作流维护，不手工改成“校验通过”。

## 文档与敏感信息

文档使用简洁中文，先说明用途，再给出操作和结果。示例须可执行；事实、假设和缺失信息应清楚区分。新增配置写入示例文件，不提交密钥、令牌、账户凭证或本机环境文件。

提交前检查暂存区，尤其是研究附件和日志。Issue、PR 和截图同样需要移除敏感信息；涉及凭证泄露或安全问题时，先私下联系仓库维护者。
