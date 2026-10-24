---
name: "company-dossier-build"
description: "公司研究档案构建 orchestrator skill。仅在用户明确说\"为 {TICKER} 构建档案\"、\"build dossier for {TICKER}\"、\"为 {TICKER} 跑五维分析/全量刷新\"、或\"迁移 {TICKER} 到新档案规范\"时触发。负责建档/迁移/全量重建：按模块间依赖关系调度七个分析模块（Tier 内并行、Tier 间串行；04 战略决策为必选慢刷模块），把产出写入 {公司目录}/研究档案/_pending/{timestamp}/，等待人工\"一键接受\"合并。事件/催化剂/季报驱动的局部刷新不归本 skill——走 research-event-update（v2.5 起 Mode C 已迁出）。仅做编排，不做内容生成——具体分析交由各 sub-skill。"
---

# company-dossier-build — 公司研究档案构建 Orchestrator

## 触发条件

用户明确说出以下任一表达：
- "为 {TICKER} 构建档案"
- "为 {TICKER} 全量刷新档案"
- "build dossier for {TICKER}"
- "为 {TICKER} 跑五维分析"
- "迁移 {TICKER} 到新档案规范"（对应 migrate 模式，不刷新内容）

**不触发（v2.5 起归 research-event-update）：** 事件/催化剂驱动的局部刷新（"TSLA 发财报了评估影响/更新研究"、"刷新 {TICKER} 的战略决策档案"、季报例行 06/07 更新）。那边分诊定刷新集后自行执行，机制与本 skill 相同（同一 orchestrator、同一 _pending/accept）。

## 系统依赖（必读）

**本 skill 强依赖用户 Projects 文件夹下的 `_system/` 目录结构。** 调用前必须确认以下路径存在：

| 路径（相对 Projects 根目录） | 用途 |
|---|---|
| `_system/scripts/dossier_orchestrator.py` | 编排脚本（migrate / prepare-refresh / finalize-refresh / accept / reject / rescan / audit） |
| `_system/dossier_registry.json` | 所有公司档案状态的中央索引，orchestrator 读写此文件 |
| `_system/portfolio_registry.md` | 业务主注册表（只读引用；估值字段由 valuation_registry.json 经 apply 生成） |
| `_system/valuation_registry.json` | **评级/估值区间/目标价的单一事实源**（2026-06-11 引入，accept 后同步，见下文） |
| `_system/scripts/sync_valuations.py` | 估值同步工具（extract / check / apply / drain） |
| `_system/scripts/handoff_lint.py` | 交接块校验（finalize 自动调用） |
| `_system/dossier_schema.md` | 档案规范定义（参考文档，orchestrator 不直接读） |

**bash 脚本的工作目录约定：** 所有 `python3 _system/scripts/dossier_orchestrator.py ...` 命令均在 **Projects 根目录**下执行（即 `C:\Users\dbao0\Documents\Claude\Projects`，bash 里对应 `/sessions/.../mnt/Projects/`）。不得在其他目录下执行，否则相对路径会解析失败。

**数据校验前置要求：** 如果本次刷新涉及财务数据（02/06/07 模块），执行前应按 `_system/数据校验流程_MANDATORY.md` v2.0 的 Step 0 校验：Read 工具读 `_system/market_data/_data_status.json` + bash 跑 `validate_market_data.py`。

---

## 设计原则

1. **本 skill 只做编排，不写分析内容。** 实际分析由各分析模块对应的子 skill 完成。本 skill 负责：
   - 按模块间依赖关系调度子 skill（Tier 内并行、Tier 间串行）
   - 把子 skill 产出文件落到正确位置
   - 写元数据 (_meta.json)、变更摘要 (_diff_summary.md)
   - 维护 `_system/dossier_registry.json` 索引

2. **绝不直接覆盖现版本。** 所有产出先写到 `_pending/{timestamp}/`，由人工通过 `accept` 命令一键接受合并。

3. **Tier 内并行、Tier 间串行。** Tier 1 的无依赖模块用 **Agent 工具并行执行**，主上下文只接收成品摘要——这同时解决速度和"全量刷新上下文爆炸"两个问题。Tier 2/3 因有上游依赖，仍按顺序执行。禁止跨 Tier 抢跑（03 必须等 02 成品，04 必须等 01/02/03，06 必须等 01/02/03，07 必须等 05/06）。

4. **（v2.6 新增）时间预算是设计约束，不是事后感想。** 全量建档的串行链有 5 段，任何一段变长都直接加到总时长上。因此：材料能本地化就不要联网现查、能并行的一律拆开、下游要读的文档不能无限长。见下文"Step 0 材料前置"与"字数上限"两节。

---

## 七份档案 + 子 skill 映射（v3.1 schema）

| 档案 | 由哪些子 skill 产出 | 依赖关系 |
|------|---------------------|---------|
| `01_企业文化.md` | mission-vision-assessment + leadership-assessment + corporate-governance-assessment（**v2.6 起三路并行产出后合并**，分章节） | 无 |
| `02_财务分析.md` | financial-analysis | 无 |
| `03_商业模式.md` | business-model-analysis | 需要先看 `02_财务分析.md`（用真实财务指标反证商业模式描述） |
| `05_股性分析.md` | stock-character-analysis | 无 |
| `04_战略决策.md` | strategic-decision-analysis | 需要先看 `01/02/03`（真实文化 + 资本配置台账 + 经济引擎基线），`05` 为参考级（历史事件市场反应）。**Tier 2.5** |
| `06_财务预测.md` | financial-forecast | 需要先看 `01/02/03`；`04` 存在时**必须消费其交接块**（H2 战略三情景→预测三情景映射、H3 交接表为假设起点、H5 结构判断） |
| `07_估值分析.md` | valuation-analysis | 需要先看 `06`（DCF 输入）+ `05`（主锚历史依据）；`04` 存在时消费 H2 里程碑（路标补充）+ H4 定位判断/锚切换假设 |

### 04 模块语义（v2.4：必选节点 · 慢节奏刷新）

战略是财务预测与估值的核心上游（可改变财务模型结构、资本市场定位、估值方法与水平），但它是慢变量：

- **首次完整建档必须包含 04**（默认 prepare-refresh 已含全部 7 个模块）
- **季度例行不重跑 04**（季报例行走 research-event-update，模块 06/07）；04 刷新由战略级催化剂触发：换 CEO、重大并购、公开战略转向、年报战略章节大改（这类事件也走 research-event-update 分诊后执行）；stale 阈值单独 365 天
- **过渡期**（存量公司 04 由用户手动分批补齐）：complete 判定仍按 6 个核心模块，04 缺失不打 partial、不阻塞研究总结 HTML；briefing 的 `missing_strategy` 清单跟踪待补名单。补齐后用户下令把 orchestrator 的 `COMPLETE_BASIS` 切到 7 个模块（一行改动）
- **04 缺失时 06/07 照常执行**（context bundle 标 `OPTIONAL_MISSING`），报告注明"[战略决策档案未提供，三情景为预测自建]"
- **04 被 accept 后**：accept 脚本自动打印提醒——建议随后重跑 06+07。**（v2.6 补充）若 06/07 与 04 是同一批次产出且 06/07 已消费了 04 的交接块，该提醒属误报，直接忽略**；只有 04 单独刷新时才需按提醒重跑
- **交接块校验**：finalize-refresh 自动对批次内 06/07/04 跑 `handoff_lint.py`（哨兵/H1-H5 字段/行数上限）；lint ERROR 会把该模块标 failed

---

## Step 0：材料前置检查（v2.6 新增，必做）

**这是全流程性价比最高的一步。** 联网现查 vs 读本地材料，在搜索密集的 01/02/03 上是数倍的时间差，事实准确性也不同（一手文件 vs 二手转述）。

**执行：**

1. 列公司 Wiki 的 `raw/` 目录，看有没有年报（10-K）、季报（10-Q）、代理声明（DEF 14A）、电话会纪要、招股书
2. **有材料** → 用 `device_stage_files` 一次性把 `raw/` + `wiki/` + `_system/market_data/{TICKER}.csv` 全部 stage 进 `/mnt/user-data/uploads/`（单次上限 50 个文件），派发时把 uploads 路径写进每个 subagent 的 prompt，要求"优先 Read 本地材料，仅在本地没有时才联网补"
3. **raw/ 为空** → 向用户报告并给出选择，不要默默开跑：

   > `{TICKER}` 的 raw/ 是空的，可以全部联网检索来建档，但会明显慢一些（实测约多花 30–40 分钟，且 01/02/03 的事实密度会低一档）。
   > 建议：先把最新 10-K、最近两期 10-Q、DEF 14A 拖进 `{公司目录}/{WIKI} Wiki/raw/`，我再开跑。
   > 你也可以让我现在就全网建档——回一句"直接跑"即可。

4. 用户明确说直接跑 → 照跑，但在派发 prompt 里写明"本地无原始材料，全部事实必须联网检索并标注来源与日期，检索不到写「未检索到」，严禁编造"

**同时做的三项预检（各一行命令，避免中途才发现）：**

```bash
# ① COMPANIES 列表是否已含该 ticker（脚手架常漏，rescan 会报 ValueError，但 prepare-refresh 不会——容易漏过去）
python3 _system/scripts/dossier_orchestrator.py rescan {TICKER}
#   报 "Ticker X not in COMPANIES portfolio" → 在 dossier_orchestrator.py 的 COMPANIES 列表补一行
#   ("{TICKER}", "{中文名}", "{Sector}", "{Sector}/{中文名} ({TICKER_带后缀})"),  再重跑

# ② 是否有未审核的 pending 批次（有则必须先 accept 或 reject，不允许重复 enqueue）
ls "{公司目录}/研究档案/_pending/"

# ③ 财务底稿在不在、新不新（**美股必做；本批次含 02 / 06 / 07 任一即适用**）
#    02 财务分析 v4.0 起「数字只从底稿取，不自己上网搜」，底稿缺失会让 02 停下来报缺、白跑一轮。
#    取数是编排层的职责，不是 02 的——底稿是 02/06/07 三家共享的输入。
cat "{公司目录}/{WIKI} Wiki/raw/财务数据/EDGAR/{TICKER}/financials.json" | python3 -c "import json,sys;m=json.load(sys.stdin)['meta'];print(m['fetched_at'], m['script_version'], len(m.get('suspect_metrics',[])))"
#   文件不存在，或 fetched_at 早于最近一期已发布财报 → 跑一次：
python3 _system/scripts/fetch_edgar_financials.py {TICKER} --out "{公司目录}/{WIKI} Wiki/raw/财务数据/EDGAR"
```

**预检③ 的三条规矩：**

1. **A 股 / 港股不跑**（EDGAR 只有美股）。这两类看 `raw/财务数据/*.xlsx` 在不在，缺就在派发 prompt 里写明"无结构化底稿，三张表从年报原文取"。
2. **跑完把脚本打印的 `[WARN]` 原样写进 02 的派发 prompt**——尤其 `suspect_metrics`（命中 Other* 残差科目的指标）和勾稽未过项。这些是 02 必须回原文核的清单，不转述就会被当成正常数用掉。
3. **stage 材料时带上底稿**：`financials.json` + 四个 csv 一起 stage，派发 prompt 里给 uploads 绝对路径。

---

## 执行模式（migrate / 全量 refresh 两种）

### Mode A: `migrate {TICKER}` — 迁移历史档案到新规范

当 dossier_registry.json 里 `dossier_initialized != True` 且 `documents.*.legacy_source` 非空时使用。仅做文件拷贝 + 元数据生成，**不重新分析**。

**步骤：**
1. 运行 `python3 _system/scripts/dossier_orchestrator.py migrate {TICKER}`
   - 脚本会**自动先 rescan 该公司目录**，刷新 legacy_source 路径（避免文件在 scan→migrate 之间被移动导致的静默漏迁）
   - 末尾打印 SUMMARY 块：migrated/skipped/FAILED 计数。**如有 FAILED，进程会非零退出**
2. 验证 `研究档案/_meta.json` 已生成
3. 报告给用户：迁移了 N/7 份，哪些模块缺失（这些在下次 refresh 时需要新生成）

### 其他辅助命令

- `rescan {TICKER}` 或 `rescan` — 重新扫描一家或全部公司的目录，刷新 registry。**保留 `dossier_initialized` 和 `pending_reviews` 状态**（从 disk 上的 `_meta.json` 推断），不会擦掉已迁移标记
- `audit` — 交叉验证每家公司的 `_meta.json` 声称"approved"的模块是否在 disk 上实际存在文件。有问题时进程非零退出

### Mode B: `refresh {TICKER}` — 刷新部分或全部档案

正式工作模式。Tier 内并行、Tier 间串行。

**步骤：**

**1. 准备 pending 目录**

```
python3 _system/scripts/dossier_orchestrator.py prepare-refresh {TICKER} [--slots ...] [--trigger quarterly|catalyst|stale_refresh]
```
输出：`_pending/{ts}/_context_bundle.json`，列出每个待刷新模块的依赖文件路径。

**2. Tier 1（01a/01b/01c + 02 + 05，全部无依赖）——用 Agent 工具五路并行（v2.6 改）**

> **为什么从三路改五路**：实测 01 单 agent 要一个人跑完使命愿景 + 领导力 + 治理三套框架，是 Tier 1 的唯一长板（一次实测 18.7 分钟 / 80 次工具调用，而 02 是 9.9 分钟、05 是 7.4 分钟）。拆成三路后 Tier 1 的耗时由三者中最长的那个决定，通常降到 8 分钟上下，**净省约 10 分钟且零质量损失**——三个子 skill 本来就是独立框架，合并只是排版。

在**同一条消息里**发出五个 Agent 调用（并发执行）：

| Agent | 子 skill SKILL.md | 产出临时文件 |
|---|---|---|
| #1a | `mission-vision-assessment` | `_pending/{ts}/_parts/01a_使命愿景.md` |
| #1b | `leadership-assessment` | `_pending/{ts}/_parts/01b_领导力.md` |
| #1c | `corporate-governance-assessment` | `_pending/{ts}/_parts/01c_公司治理.md` |
| #2 | `financial-analysis` | `_pending/{ts}/02_财务分析.md` |
| #4 | `stock-character-analysis` | `_pending/{ts}/05_股性分析.md` |

每个 subagent 的 prompt 必须包含：
- 公司信息：ticker + 名称 + sector + **材料位置**（Step 0 stage 后的 uploads 路径；若无材料则明确写"本地无原始材料，全部联网检索"）
- 该模块对应子 skill 的 SKILL.md **绝对路径**（让 subagent 先 Read，**严格按其中的分析框架执行**）
- **字数上限**（见下表）
- 产出绝对路径 + "最终回复只报告：已写入路径 + 字数 + 三句结论摘要，**不要把全文贴回主上下文**"

**01 的合并（主上下文做，纯排版不做改写）：** 三份 `_parts/` 按顺序拼成 `_pending/{ts}/01_企业文化.md`，加三个大章节标题 `## 一、使命愿景` / `## 二、管理层领导力` / `## 三、公司治理`，文件头写一行"本档案由三个子 skill 并行产出后合并，各章节内部结论相互独立"。合并后 `_parts/` 保留在 pending 目录里，accept 时不会被提升（只提升顶层七个文件名）。

五个 agent 全部返回后，主上下文逐一校验产出文件存在且非空（用 Read 工具抽查头部；bash `wc -c` 仅作粗检，FUSE 缓存异常时以 Read 为准），再进入 Tier 2。

**3. Tier 2（03，需要 02 成品）**

调用 `business-model-analysis`（或派 subagent，prompt 附 02 成品绝对路径让其 Read）。**必须把 02 作为上游硬约束**：商业模式的每条描述都要被 02 的真实财务指标反证，冲突时以财务数据为准并显式指出。写 `_pending/{ts}/03_商业模式.md`。

**3.5 Tier 2.5（04，需要 01/02/03 成品，05 参考级；仅当本批次包含 04）**

调用 `strategic-decision-analysis`（或派 subagent，prompt 附 01+02+03 绝对路径，05 标注"参考级：历史事件市场反应"）。

⚠️ **派发 prompt 里必须原样写进这两句**（否则 finalize 必被 lint 拒，实测已发生）：

> 产出必须含文末 H1–H5 交接块 + 末行哨兵 `<!-- HANDOFF-END v1 -->`，严格按 SKILL.md「档案系统集成」章的模板与行数上限。
> **交接块内禁止出现"概率加权"四字**（handoff_lint 硬拦，命中即把本模块标 failed）——量级估算留在正文 §7.x，交接块只写定性判断。

写 `_pending/{ts}/04_战略决策.md`。

**4. Tier 3a（06，需要 01/02/03 成品；04 存在时附上）**

调用 `financial-forecast`（context: 01+02+03 绝对路径 + 04 路径若有——其 H3 交接表是三情景假设的标准输入，H2 三情景要映射到预测三情景，H5 影响模型结构）。派发时强调：历史实际数一律从 02 承接、三情景禁止加权、必须产出"预测分歧驱动表"（这是后续事件分诊的信号源头）。写 `_pending/{ts}/06_财务预测.md`。

**5. Tier 3b（07，需要 06 + 05 成品；04 存在时附上）**

调用 `valuation-analysis`（context: 06 + 05 + 04 路径若有）。

⚠️ **派发 prompt 里必须写明 §4.8 登记块的完整字段清单**（v2.6 新增，否则 accept 后 `drain` 不同步评级和区间）：

> 文末 §4.8 valuation_registry 登记块的 JSON **顶层必须同时包含**：
> - `rating`（字符串，与正文投资评级章节逐字一致）
> - `zones`（数组 `[{"label": "...", "range": "..."}]`，range 里只放价格与倍数关系，不要塞长解释文字）
> - `target_price`（主导情景目标价，含"主导情景=X"标注）
> - `scenario_valuation`（三情景价 + dominant + confidence + rationale + signals 数组）
> - `opportunity_type`（business_track / price_pattern / label / return_split / holding_style / regime_switch，来自 §4.0 机会类型判定；输入取 02 F1"利润率空间"、03 §七"增长引擎性质"、05 步骤四第 5 项、04 H1"轨迹性质"）
>
> 缺 `rating` / `zones` 会导致 `sync_valuations.py drain` 静默跳过评级与区间同步，新公司会一直停在"研究中/待完成"。
> JSON 必须与正文数字逐项勾稽一致，落笔前自查一遍。

写 `_pending/{ts}/07_估值分析.md`。

**6. finalize**

```
python3 _system/scripts/dossier_orchestrator.py finalize-refresh {TICKER} {timestamp}
```
生成 `_pending/{ts}/_meta.json` + `_diff_summary.md`，更新 registry，自动跑 handoff_lint。

**7. 报告给用户**
- 完成的模块列表 + 任何失败的模块
- `_diff_summary.md` 的关键变化摘录（不超过 200 字）
- 审核命令：`accept {ticker} {ts}` 一键接受 / `reject ...` 整体退回

---

## 字数上限（v2.6 新增，硬约束写进每个派发 prompt）

**为什么要限**：不是为了省单个模块的时间，而是砍下游成本——05 开工前要读 01+02+03+04，07 要读 06+05+04。上游每多写 10 KB，下游每一段都要重读一遍，沿串行链复利放大。

| 模块 | 建议上限 | 说明 |
|---|---|---|
| 01_企业文化.md（三章合计） | **35 KB** | 每章约 12 KB。一次实测写到 92 KB，收益递减而成本全部传给下游 |
| 02_财务分析.md | **40 KB** | 表格密集，放宽 |
| 03_商业模式.md | **50 KB** | |
| 05_股性分析.md | **30 KB** | |
| 04_战略决策.md | **45 KB** | 含 H1–H5 交接块 |
| 06_财务预测.md | **60 KB** | 三情景 × 五年三张表，最大的一份 |
| 07_估值分析.md | **60 KB** | 含 §4.8 登记块与勾稽自检表 |

超限不是错误，但派发时给出上限能有效抑制"什么都写一点"。**宁可正文精炼、把细节推给表格**。

---

## 耗时基线（v2.6 新增，用于给用户预期）

2026-07-31 MU 全量七模块建档、raw/ 为空全网检索的实测：

| 阶段 | 耗时 |
|---|---|
| Tier 1（三路并行，01 未拆） | 18.7 min（长板是 01） |
| 03 | 10.7 min |
| 04 | 13.3 min |
| 06 | 14.8 min |
| 07 | 15.8 min |
| 研究总结 HTML | 6.7 min |
| **合计（含编排与一次 lint 返工）** | **约 90 min** |

按 v2.6 优化后的预期：材料齐备 + 01 拆三路 ≈ **50–60 min**；材料为空但 01 拆三路 ≈ **75 min**。
开跑前把这个预期告诉用户一句，别让人干等。

---

## 云端会话的落盘方式（v2.6 收编自实践笔记）

在云端 Cowork 会话（非"在您的计算机上"模式）跑本流程时，subagent 在云容器里，**写不到用户磁盘**。三处适配：

1. **落盘**：orchestrator 脚本用 `device_bash` 在挂载盘跑（prepare/finalize/rescan/accept 均正常）；subagent 写云端 `/home/claude/{ticker}_pending/`，主上下文用 `SendUserFile`（`display=attach`，正好给用户审核）拿到 file_uuid → `device_commit_files` 落到 `研究档案/_pending/{ts}/` → 再 `device_bash` 跑 finalize
2. **行情数据**：云容器 yfinance 被网络白名单挡（curl connection reset），**不要重试也不要绕**。改用 IBKR MCP：`search_contracts` 拿 contract_id → `get_price_history`（如 FIVE_YEARS + ONE_WEEK 周线）+ `get_price_snapshot`（misc_statistics 给 52 周区间）。subagent 可自行 ToolSearch 加载
3. **材料 stage**：`device_stage_files` 一次最多 50 个文件，`raw/` + `wiki/` + `market_data/{TICKER}.csv` 一把梭

---

## 失败处理

| 情况 | 处置 |
|---|---|
| 某个子 skill / subagent 失败（抛错 / 产出为空 / 文件未写入） | 在 `_meta.json` 对应模块写 `"approval_status": "failed"` + `"error_message"`；已完成的模块保留；提示用户选择"丢弃整批"还是"保留已完成部分手工修复"。单个 Tier 1 subagent 失败可单独重派，不影响其他四路 |
| **handoff_lint 拒绝 04（如交接块出现"概率加权"）** | **不必重做全文**：直接改那一行为定性表述 → 重新 commit 该文件 → 重跑 finalize 即可 |
| prepare-refresh 脚本失败 | 检查 Projects 根目录是否正确；检查 `dossier_registry.json` 里该 ticker 是否存在 |
| rescan 报 `Ticker X not in COMPANIES portfolio` | 在 `dossier_orchestrator.py` 的 COMPANIES 列表补一行（见 Step 0 预检①） |
| finalize 脚本失败 | `_pending/{ts}/` 里的档案文件仍有效，可手工补写 `_meta.json` 后重跑 finalize |
| 同一公司已有 pending 未审核 | **不允许重新 enqueue**；提示用户先 accept 或 reject 当前批次 |

---

## Accept / Reject 命令

```bash
python3 _system/scripts/dossier_orchestrator.py accept {TICKER} {timestamp}
python3 _system/scripts/dossier_orchestrator.py reject {TICKER} {timestamp}
```

### Accept 后的估值同步（v2.6 修订：优先走 drain）

`_system/valuation_registry.json` 是评级/估值区间/目标价的**单一事实源**；`portfolio_registry.md` 的估值字段是它的生成视图。

**首选（自动）：**

```bash
python3 _system/scripts/sync_valuations.py drain {TICKER}
```

它从 07 §4.8 登记块提取 → 写 valuation_registry.json → 写回 portfolio_registry.md → 自动 check → 出队。

⚠️ **必须看 drain 的输出有没有 `⚠️ 登记块缺 X` 警告**。缺 `rating` / `zones` 时 drain 会**静默保留 registry 现值**并继续报成功——新公司就会停在"研究中（脚手架入库）"+ 区间"待完成"，看着 accept 成功了其实评级没进去。

**补救（手工）：**
1. 把缺的字段补进 07 的 §4.8 登记块（将来 drain 才全自动）
2. 用 `atomic_dump_json` 补进 `valuation_registry.json`（**禁止裸 `open(w)`**，FUSE 盘上会写半截）
3. `python3 _system/scripts/sync_valuations.py apply {TICKER}` → `check` 必须 exit 0
4. 向用户报告新旧目标价/区间对比

**禁止写入任何情景加权价或方法加权价**（双禁加权规范）。

### Accept 后的注册表回填（v2.6 新增，必做）

`sync_valuations` 只管评级/区间/目标价三项，**催化剂与日期字段它不碰**。新建档公司如果不回填，`portfolio_registry.md` 会留着脚手架占位（"[P0] 待研究阶段识别" / "Next Key Date: 待确认"），每日扫描的"建议操作"栏会持续空转——NVDA 曾因此空转近一个月。

accept 后手工回填两处（用原子写）：

1. **`portfolio_registry.md` 该公司条目**：`Key Catalysts`（从 07 §4.8 的 signals 数组提炼，带阈值）、`Next Key Date`（最快可验证的分歧驱动对应的日期）、`Last Research`（`{YYYY-MM-DD}（七维完整建档：...）`）、`Note`（一句话画像 + 核心矛盾 + 评级与目标价）、`Opportunity`（新增一行 `- **Opportunity:** {07 §4.0 一句话}｜{持有方式}`，放在 Rating 之后）
2. **`{公司目录}/催化剂跟踪/催化剂跟踪_自动化.md`**：头部四个字段（现价/区间定位/目标价/评级）、催化剂总览表、估值区间表、评级变动触发条件、预警阈值。数据源全部来自 07 §4.2/§4.3/§4.4/§4.8 与 06 的分歧驱动表——**不要另起炉灶重新想催化剂**

3. 在 `_system/scan_log/registry_changelog.md` 追加一行建档记录

### Accept 后的研究总结 HTML 生成

`accept` 在 6 个模块全部就位时会打印 `[NEXT STEP — 请立即执行]`。看到后在当前会话里立即执行：

1. 调用 `research-summary` skill，传入该公司 `研究档案/` 目录路径
2. 输出到 `基本面分析汇总/{公司名}_{YYYY-MM-DD}_研究总结.html`（`{公司名}` 与注册表 `company_name` 一致）
3. 云端会话记得 `SendUserFile` → `device_commit_files` 落盘
4. 无需其他操作——每日的网站更新任务会自动打包

---

## 已知坑 & 兜底

| 现象 | 原因 | 兜底 |
|---|---|---|
| **finalize 报 `LINT ERROR [04] 交接块内出现"概率加权"字样`** | strategic-decision-analysis 默认会把加权增量 EV 写进 H4，即使自注"不得作为价值锚"也照拦 | 改那一行为定性表述 → 重 commit → 重跑 finalize。**派发时就把禁令写进 prompt**（见 Tier 2.5） |
| **drain 后评级仍是"研究中"、区间仍是"待完成"** | 07 §4.8 登记块缺 `rating` / `zones`，drain 静默跳过 | 见"Accept 后的估值同步"补救三步；派发 07 时列全字段清单 |
| **rescan 报 `Ticker X not in COMPANIES portfolio`** | 脚手架入库漏改 `dossier_orchestrator.py` 的 COMPANIES 列表（prepare-refresh 不报错，容易漏过去） | Step 0 预检① 先跑一次 rescan；报错就补一行 |
| 建档很慢（>90 min） | 串行链 5 段 + 材料为空全网检索 + 01 单 agent 跑三套框架 | Step 0 材料前置 + Tier 1 五路并行 + 字数上限，三条一起用 |
| `dossier_orchestrator.py` 报 PermissionError | 硬编码了旧 session 的 sandbox 路径 | `detect_projects_root()` 已 glob `/sessions/*/mnt/Projects` + 防御 PermissionError |
| `_context_bundle.json` 里上游路径指向 `_pending/` 而非权威版 | rescan 未在 prepare 前运行 | prepare 前先跑一次 `rescan {TICKER}` |
| 产出写到了 `研究档案/` 顶层而非 `_pending/` | 写入路径未显式指定 | 派发时给绝对路径；finalize 前校验文件位置 |
| bash 读刚被 Edit/Write 过的文件出现截断/NUL | sandbox FUSE 缓存陈旧 | 校验一律以 Read 工具为准；bash 侧只做 `wc -c` 粗检 |
| 上下文过长 | 串行调用 + context 累积 | Tier 1 并行（主上下文只收摘要）；Tier 3 给 subagent 传路径让其自行 Read，不要把全文粘进主上下文；字数上限 |

---

## 与其他 Skill 的边界

| Skill | 何时用 |
|---|---|
| **本 Skill** | 建档 / 迁移 / 全量重建 |
| `new-company-onboarding` | 公司从无到有进系统的脚手架（在本 skill 之前） |
| `research-event-update` | 事件/催化剂/季报驱动的局部刷新（v2.5 起 Mode C 已迁出至此） |
| `research-summary` | accept 后生成研究总结 HTML |
| 单个子 skill | 由本 skill 内部调用，用户不直接调 |

---

## 版本

- **v1.0**：单脚本直接生成所有档案，无 pending/审核机制
- **v2.0**（2026-05-14）：引入 `_pending/` + accept/reject 审核流；06/07 拆分
- **v2.1**：补全子 skill 调用约定、失败处理、accept/reject 说明
- **v2.2**（2026-06-11）：Tier 1 三路并行；接入估值单一事实源；数据校验前置升级 MANDATORY v2.0
- **v2.3**（2026-06-29）：accept 后自动化扩展（估值同步队列 + `[NEXT STEP]` 触发研究总结 HTML）
- **v2.4**（2026-07-30）：新增 `04_战略决策.md`（Tier 2.5，必选慢刷）；交接块规范 + `handoff_lint.py`
- **v2.5**（2026-07-30）：Mode C 迁出至 research-event-update v1.1；本 skill 收缩为建档/迁移/全量重建
- **v2.9**（2026-08-29）：**模块编号迁移**——战略 07→04、股性 04→05、预测 05→06、估值 06→07；全文与派发模板同步更新；orchestrator 的 CANONICAL_SLOTS 已按新编号排序、CORE_SLOTS 改为显式排除 04_战略决策
- **v2.8**（2026-08-28）：Step 0 新增**预检③ 财务底稿**——美股建档前由编排层跑 `fetch_edgar_financials.py`，并把脚本的 `[WARN]`（suspect_metrics / 勾稽未过）转写进 02 派发 prompt。此前"取数集中在编排层"只是设计意图，从未写进正文，导致每次都靠人临时想起来跑，漏跑则 02 停下来报缺、白费一轮
- **v2.7**（2026-08-28）：07 派发字段清单加 `opportunity_type`（机会类型判定链：02 F1 / 03 §七 / 05 §四.5 / 04 H1 → 07 §4.0 → registry → research-summary）
- **v2.6**（2026-07-31）：⏱ **性能与可靠性修订**，触发事件为 MU 首次七模块全量建档实测 90 分钟。
  ① 新增 **Step 0 材料前置检查**（raw/ 为空时先问用户，并给出耗时代价）+ 两项预检（COMPANIES 列表、未审 pending）；
  ② **Tier 1 由三路改五路并行**——01 拆成使命愿景/领导力/治理三个 agent，主上下文只做排版合并，省约 10 分钟；
  ③ 新增**字数上限表**（抑制上游膨胀导致的下游读取成本沿串行链复利）；
  ④ 新增**耗时基线**用于给用户预期；
  ⑤ 派发模板补两条硬警告：04 交接块禁"概率加权"、07 §4.8 登记块必须含 `rating` + `zones`（否则 drain 静默跳过评级与区间）；
  ⑥ 新增 **accept 后注册表回填**一节（催化剂/Next Key Date/催化剂跟踪表，sync_valuations 不管这些，不填则每日扫描空转）；
  ⑦ 收编**云端会话落盘方式**（subagent 写云端 → SendUserFile → device_commit_files；行情走 IBKR MCP）；
  ⑧ 04 accept 后"建议重跑 06+07"的误报场景已说明
