# 原方法对应与差异记录

固定来源：flyfish0108/AI-Investment-System，提交 `e5b147afa1b2c49bb9a6651094958538d5802a59`。本文件用于实施与维护，不是用户审批表。原始资料留在 `reference/upstream/`；技能原文在 `.agents/skills/*/references/original.md` 逐字保存。相对引用按技能根目录解析。

## 2026-10-25 私有 GitHub 备份适配

用户明确要求将当前本地项目备份至自己的 GitHub，用于后续维护及团队协作。本地增加独立 Git 仓库，目标为 `Yuang-Zhou/tideStone-root` 私有仓库；不使用同僚仓库的推送、账号或发布配置。本地网页、研究方法及人工接受规则保持原有含义，Git 提交和 Pull Request 合并不构成研究接受。忽略规则保留真实运行日志，排除本机凭证、环境、缓存与可再生或重复副本。恢复和协作入口见根目录 README。这是本地工程适配，不属于上游原方法。

文档整理补充：README 作为项目入口，使用指南集中说明研究与运维，新增贡献指南和 Issue／PR 模板。`ops.py backup` 同时纳入 `CONTRIBUTING.md`、`.github/` 和 `.gitattributes`，使本地压缩备份保留新增协作文件与换行约定。研究方法和接受流程不变。

## 技能与流程对应

| 原入口 | 本地入口（`.agents/skills/`） | 对应功能与输出 |
|---|---|---|
| new-company-onboarding | 同名 | 统一公司登记、资料准备；不产生评级 |
| company-dossier-build | 同名 | 七模块 Tier 编排、pending、差异摘要 |
| mission-vision-assessment | 同名 | 01 的使命愿景部分 |
| leadership-assessment | 同名 | 01 的领导力部分 |
| corporate-governance-assessment | 同名 | 01 的治理部分 |
| corporate-culture-analysis | 同名 | 单独文化研究；不自动替换原编排 |
| financial-analysis | 同名 | 02；六份有效引用、render_tables.py |
| business-model-analysis | 同名 | 03；依赖 02 |
| strategic-decision-analysis | 同名 | 04；现存八步及 H1–H5，三份原引用缺失 |
| stock-character-analysis | 同名 | 05；长期价格与定价依据 |
| financial-forecast | 同名 | 06；三情景、假设表、分歧驱动表 |
| valuation-analysis | 同名 | 07；主导情景、主方法、登记块 |
| research-event-update | 同名 | _events 评估、已授权最小刷新集 |
| financial-forecast-feedback | 同名 | _deviation 偏差判定单，只读正式研究 |
| research-summary | 同名 | 从已接受研究生成 HTML；保留有效模板 |
| technical-analysis | 同名 | 用户点名的完整技术面研究 |
| reverse-dcf | 同名 | 反向估值；methodology/advanced 引用 |
| vc-style-valuation | 同名 | 独立辅助方法；reference.md 与实际计算引擎 |
| Scheduled/daily-portfolio-scanner | daily-portfolio-scanner | 本地行情+实际新闻核验→简报/扫描日志 |
| Scheduled/daily-position-advisor | daily-position-advisor | 用户已授权持仓快照→引擎→说明；默认未接账户 |
| Scheduled/value-growth-paper-monitor | value-growth-paper-monitor | 本项目纸面组合复核；本地网页 |
| 无同名原入口 | tidestone-research | 仅新增自然语言路由，连接原入口与本地状态 |

系统路径、CLI、更新语义在 [本地运行约定](../.agents/skills/tidestone-research/references/local-runtime.md)。实际运行完成度以主项目操作说明、验收记录及日志为准；“技能存在”不等于外部数据已经接通。

## 方法约束的落地

| 约束 | 落地点 |
|---|---|
| Tier 1 → 03 → 04 → 06 → 07 | dossier-build 入口与 runtime context；并发额度不足只排队 |
| 同批依赖消费 | 本批新上游优先；未刷新的读正式版 |
| 04 传递 H2/H3/H5 给 06，H2/H4 给 07 | 各入口、原文、handoff 检查 |
| 禁情景加权和方法加权目标价 | 06/07/summary 入口与正式同步约束 |
| 只消费 06 分歧表的计分信号 | 07、事件更新、偏差分诊 |
| 先草稿再人工接受 | tidestone CLI + 总入口；技术通过不代表接受 |
| 修订保留依据 | revise 前快照、重新 finalize、历史版本 |
| 07 与登记同一来源 | 接受后 sync，三年字段可追溯，缺失待补 |
| 多源与口径 | 原文各模块要求 + local-runtime 的独立来源/日期/单位说明 |
| 正式空库 | 不复制上游公司档案、持仓、目标价、真实账户信息 |

## 查明的差异与处理

| 原文或依赖 | 查明问题 | 本地处理与影响 |
|---|---|---|
| 战略三份 references | 固定提交完整树中不存在 | 不补造；用现存正文+H1–H5，报告披露方法不完整 |
| 旧 build 的 COMPANIES 补行 | 新入库和代码改为 companies.json | 读统一表；不改引擎名单 |
| 六份 complete 过渡 | 旧库为缺战略暂时兼容 | 新库首次七份齐全；保留 04 慢刷语义 |
| event-update “一律正式版” | 与同批 06→07 等依赖冲突 | 本批新上游优先，并记来源版本 |
| scanner slot06_path/加权价 | 模块迁移与新版估值未同步 | 只同步已接受 07，使用 drain/check；不恢复加权价 |
| 旧原文云端路径和工具 | Cowork、Windows、stage/commit 均不适用于本机 | 映射本地 Projects、原生文件工具、Codex 子代理 |
| 空 raw 要再问用户 | 新版入库已要求自动预取，用户本次授权主动研究 | 先自动查公开材料，缺口记录；不重复索要研究许可 |
| 事件 Step 6 等批准 | 用户明确要求更新时已有授权 | 完成本地待审刷新；接受结果仍需明确用户决定 |
| 独立文化方法 | 与完整编排三路文化并存 | 两者保留，全量不无声替换 |
| VC 加权回报 | 与核心双禁加权定价口径不同 | 仅独立显式研究，不进核心 registry |
| feedback vs 新 EDGAR 能力 | 文本不支持部分外币/金融数据，新抓取器范围更宽 | 下载成功不代表偏差算法兼容，逐项核口径并披露边界 |
| research-summary 空示例文件 | example.py、api_reference.md、example_asset.txt 为占位 | 不迁为执行能力；有效 template.html 原样保留 |
| 原任务账号、通知、Artifact、GitHub/Cloudflare | 属同僚宿主与账号 | 不继承；仅本地。真实账户须另行授权且接通 |
| 定时新闻扫描 | 原依赖云端定时 AI 与可联网工具 | 本地脚本刷新状态不冒称 AI 新闻扫描；按实际调度证据分类 |
| 模拟盘本金/起点/持仓 | 是同僚现有案例数据 | 不迁入；只迁规则和引擎，正式空库无收益表现 |
| 原 README 的行情 7 天 vs 新监测 3 天 | 文档更新不同步 | 按当前引擎/配置实际规则核验并注明，不挑宽松限制 |

## 引用与校验

清单：`.agents/skills/tidestone-research/references/upstream-manifest.json`，记录每份原文与有效资源的 SHA-256、源路径、固定提交、被排除的空脚手架和已知缺失引用。验证命令：

```text
python3 .agents/skills/tidestone-research/scripts/validate_skills.py
```

该检查验证入口命名、必需字段、引用可达、原文与资源哈希一致，并将已知三份上游缺失单独报告。它不证明投资方法有效，也不替代真实流程验收。独立使用应以“从新公司到待审→修订→接受→新事件→重启继续”的实际产物为准。

2026-10-24 的本次入口检查：22 个技能入口、21 份上游原文及有效资源哈希、本地 Markdown 链接通过。初检用 Ruby YAML 解析器验证全部 22 份 frontmatter；随后在项目 .venv 安装 PyYAML，原 Skill Creator quick_validate.py 的 22 项检查也全部通过，记录在 docs/evidence/skill-validation.json。VC 原计算引擎通用自测通过；财务表与本地取数包装器的帮助入口可运行。这些检查不替代[完整研究流程验收](workflow-trial.md)，后续计算修复应单独记录为本地适配，保留原件及新文件哈希。

研究总结的本地落点适配为本公司目录 `研究总结_<YYYY-MM-DD>.html`，同时保存同名 Markdown 供讨论。正式总结仅在对应批次接受后生成；同日修订用时间后缀新文件，不覆盖历史。HTML 和 Markdown 成品必须用 scripts/register_summary.py 登记内容指纹及七份已接受来源，网页只展示登记且匹配的成品；待审总结留批次内。原 raw-filings 脚本携带原作者 SEC 联系身份，其原件仅保存在技能 references 的 `.txt` 存档；活动脚本委派到使用本用户 SEC_USER_AGENT 的本地取数引擎。

## 补充资料的证据地位

进一步读取了上游“投资研究系统设计”目录的 README、来源边界、2026-10-10 机制核对以及两份早期设计提案。目录 README 明确撤回了早期“现有反馈机制缺失”等判断：2026-10-09 文档只是未核验提案，不是已经实现的机制或迁移清单。本地以现有 Skills、实际引擎和10月10日核对为准；没有把 proposed 记录契约强加给原研究流程。新增来源均记录在 reference/SOURCE_LOCK.json。

上游 market_rotation_mvp 是独立的周线资金压力 Streamlit 工具，使用其自身样本池与人工数据更新流程，不是主站公司研究链。本次查阅其 README 并识别边界，未迁入该独立工具及同僚样本数据。它属于后续可单独实施的模块，不能算当前已实现功能。

## 2026-10-24 首家公司实际入库核对

宁德时代入库实查：本地 `add` 仅创建公司/研究档案/materials 目录和最小注册表，不会自动创建 Wiki、技术分析、催化剂、pending/history 子目录，也不核 GICS 四级。入库技能负责在命令后补齐独立空骨架、真实身份/分类证据及变更记录，不创建七份空报告。公司目录按本地命令返回的 `companies/300750.SZ` 使用，不为套用原示例改名。`add` 仍写旧 `Folder` 行，本次登记已按原统一名单规范去掉该冗余行，路径仍只由 companies.json 提供；未改引擎。

本地 `data_update.py` 对 A/H 股将 Motley Fool 纪要和 EDGAR 底稿明确标记 `not_applicable`，没有执行不适用的美股下载器；其帮助入口已检查。实际以公司/交易所投资者关系活动记录补业绩交流，以原始 CAS 财报制作有页码和计算校验的基础摘录；这些不冒称逐字电话会稿、完整 EDGAR 78 指标底稿或已完成财务分析。原预取渠道的网络失败与直链补取分别保留运行记录，不能用后一项成功覆盖前一项失败。

本次首次有真实材料后发现，本地网页生成器将 `raw/` 所有文件（含清单、提取文本）与 `_materials.json` 登记副本相加，21项登记错误显示为57份材料。已作本地显示修复：只按 `_materials.json` 中不重复的登记路径计数，不把原件与副本重复统计。原件仍完整保留；未登记原件须按材料命令登记后才计入网页。这是本地工程适配，不改变研究方法。

来源逐字节核对：81份参考文件均已按固定提交Git blob指纹匹配。连接器添加的末尾换行及BAT换行转换已还原。reverse-dcf 的 methodology.md 本身末尾截断于UTF-8字符中间：原始字节存档保留，活动可读副本显式标明缺损，不补写方法含义。见 docs/evidence/upstream-hash-check.json。

## 2026-10-24 首次完整建档的回报口径核对

估值原文§4.0要求“盈利增长、估值倍数变动、股东回报”三块加回§4.3的目标股价上行，第三块又定义为分红率加回购注销率。现金股利属于持有总回报，并不自动增加期末股价；若回购缩股已进入每股盈利，再单加注销率还会重复计算。原件保持不变，本地报告须明确这一数学口径差异，不能为了通过合计约束把股息塞进目标价。

本地适配：价格桥使用同口径EPS与PE，设盈利增长因子e=目标年度EPS/当前TTM EPS、倍数因子m=目标PE/当前PE，则盈利贡献e−1、倍数贡献e×(m−1)，合计e×m−1恰等于股价涨跌；未另建独立缩股贡献时第三项记0并解释回购若已在EPS中不再计。现金股息另列持有总回报，不能进入目标价格或price return_split。若存在独立拆出的缩股效应，则从EPS增长中移除后才可转列第三项，仍不得重复。登记块return_split是上述价格贡献占总价格变动的比例，和为1；若价格变动为负应如实注明，有抵消效应时允许贡献比例超出0–1，并解释，不能伪装为概率。此为本地数学口径修正，不冒充上游原方法规定。
