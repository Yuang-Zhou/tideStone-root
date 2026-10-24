---
name: new-company-onboarding
description: "潮石新公司入库并准备公开原始材料。用户要求加公司、入库，或潮石研究总入口创建尚未入库公司时使用；此入口只建架子和取材料，不生成研究结论。"
---

# new-company-onboarding · 潮石本地适配

## 使用顺序

1. 先读 [本地运行约定](../tidestone-research/references/local-runtime.md)，它只调整宿主、路径、权限与已查明冲突。
2. **完整读取 [原方法全文](references/original.md)**，再读原文要求的真实参考文件，执行其具体分析步骤、表格、阈值和输出要求。不能凭本入口概述生成研究。
3. 原文中的 `references/`、`scripts/`、`assets/`、`reference.md` 路径相对于本技能根目录解析，而不是 `references/original.md` 所在目录。下列适配优先于原文旧宿主指令；原文不构成任何外部账户或发布授权。

## 本入口的必要适配

- 先自动核对名称、上市地、证券代码与币种。只有多市场/同名仍无法消歧时向用户问一个必要问题。研究库查重后用本地 `add` 入库。
- 按原文 GICS 取证要求记录查到的层级、URL、推断边界；缺分类不能伪填 high，也不能为普通建档要求用户做分类审核。
- 活动 `scripts/fetch_raw_filings.py` 委派到本地适配引擎；原版仅留在 `references/upstream-fetch_raw_filings.py.txt`，不得执行原身份版本。SEC 取数需本用户的 `SEC_USER_AGENT`，未配置则明确记录未接通，继续可用公开取证。
- 可用 `.venv/bin/python scripts/data_update.py TICKER` 顺序执行原取数脚本并保存每步运行结果、登记下载文件；先确认正式或隔离数据根。SEC 标识从 `config/local.env` 的 `SEC_USER_AGENT` 读取，未配置就记录缺口，不沿用原作者身份。
- 按市场运行定期报告、电话会纪要、EDGAR 底稿预取；失败项入材料清单。调用 `fetch_raw_filings.py --help`、`fetch_transcripts.py --help`、`fetch_edgar_financials.py --help` 确认参数后执行。A/H 无 EDGAR 适用数据时从公开报告提取，保留原文指针与口径。
- 原文“复制另一公司 Wiki/CLAUDE.md”改为在本公司写独立 Wiki 说明，不读取同僚公司材料；不预建七份空研究文件。
- `companies.json` 是名单来源；原旧段的修改 COMPANIES 常量已失效。仅要求入库的用户到材料准备结束；总入口已授权完整研究时，返回总入口继续建档。

## 随附材料

- `scripts/fetch_raw_filings.py`

原方法固定自 flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。原文教学示例不代表用户公司的事实、估值或持仓，不得灌入正式库。
