---
name: "research-event-update"
description: "研究更新分诊+定向刷新 skill。当用户报告某公司发生新事件（财报发布、重大合同、换CEO、并购、战略转向、竞争格局变化等）并要求评估影响或更新研究时触发，例如\"TSLA 发财报了，评估影响\"、\"评估 {事件} 对 {TICKER} 档案的影响\"、\"{TICKER} 出了 {事件}，研判一下\"、\"{TICKER} 季报例行更新\"。先分诊——把事件逐条比对档案已登记的信号清单（06 分歧驱动表、04 交接块领先指标/证伪信号、valuation_registry 切换路标），输出影响矩阵 + 响应级别 + 最小刷新集；用户批准后由本 skill 端到端执行定向刷新（调 dossier_orchestrator prepare/finalize，派 sub-skill，产出进 _pending 等人工 accept）。事件驱动的一切局部刷新（含季报例行）归本 skill；建档/迁移/全量重建归 company-dossier-build。不做分析内容生成。"
---

# research-event-update — 事件驱动的研究更新（分诊 + 定向刷新）

## 定位

本 skill 端到端拥有事件驱动的研究更新流程：

```
事件发生 → [本 skill：分诊评估 → 停，等批准 → 执行定向刷新（产出进 _pending）] → 人工 accept 审核
```

与 company-dossier-build 的分工（v1.1 起）：**事件/催化剂/季报驱动的局部刷新全部归本 skill**（原 dossier-build Mode C 已迁入并退役）；**建档、迁移、stale 全量重建归 dossier-build**。两者共用同一执行机制——`dossier_orchestrator.py` 是唯一写入者，`_pending/` + accept 审核流一步不少。

三条铁律：
1. **分诊+编排，不生成内容**。评估"影响哪些模块、刷多深"并派发执行；具体档案内容一律由各 sub-skill 产出。
2. **评估先出，批准后再刷**。本 skill 跑完分诊停在评估报告；用户明确说"执行"/"批准刷新"后才进入执行段。
3. **不绕过审核流**。任何档案内容变更仍走 `_pending/` + accept；情景判定（dominant scenario）翻转必须通过重跑 07 实现，禁止只改 registry 里的判定结论。

## 触发条件

用户明确报告事件并要求评估或更新，如：
- "TSLA 发财报了，评估影响"
- "评估 {事件} 对 {TICKER} 档案的影响"
- "{TICKER} 宣布 {并购/换CEO/重大合同}，研判一下要不要更新研究"
- "{TICKER} 季报例行更新"（季报也是事件，走 E1 流程，分诊照做不跳过）

仅手动触发。日常扫描/简报发现的催化剂不自动调用本 skill（scanner 只提示"建议跑事件研判"）。

**不归本 skill：** 新公司建档、历史档案迁移、stale 全量重建 → company-dossier-build；未入库公司 → new-company-onboarding。

## 系统依赖

工作目录约定：所有 bash 命令在 **Projects 根目录**执行（`/sessions/{sid}/mnt/Projects/`）。

| 路径 | 用途 |
|---|---|
| `{公司目录}/研究档案/06_财务预测.md` | 读**分歧驱动表**（计分信号唯一来源） |
| `{公司目录}/研究档案/04_战略决策.md` | 读交接块 H2（领先指标/证伪信号）、H4（锚切换确认条件）、H5（结构判断） |
| `_system/valuation_registry.json` | 读该公司 `scenario_valuation.signals`（切换路标）；signal 状态可写（见 §5） |
| `_system/dossier_registry.json` | 读各模块的 last_updated / source_period / pending 状态 |
| `{公司目录}/研究档案/_meta.json` | 读 source_period，判断事件是否已被现有档案覆盖 |
| `_system/scripts/sync_valuations.py` | signal 状态更新后 apply/check |
| `_system/scripts/dossier_orchestrator.py` | 执行段：rescan / prepare-refresh / finalize-refresh / accept / reject（唯一写入者） |
| `{公司目录}/催化剂跟踪.md` | 事件日志累积处（无则按 `_system/catalyst_tracker_template.md` 初始化） |

前置检查：若该公司在 dossier_registry 有未审 pending 批次，先提示用户处理（accept/reject）再评估——同一公司不允许叠加第二批 pending。

## 执行流程

### Step 1 — 事件归档

确定：ticker、事件类型、事件日期、证据来源。

事件类型枚举（一个事件可属多类）：
- **E1 财报/指引**：季报、年报、指引上调/下调
- **E2 战略级**：换 CEO、重大并购/分拆、公开战略转向、年报战略章节大改
- **E3 经营催化剂**：重大合同、产品发布、监管审批、产能落地
- **E4 竞争格局**：竞对重大动作、新进入者、技术路线变化
- **E5 治理/管理层**：高管变动（非CEO）、股权激励大改、审计/诉讼
- **E6 资本结构**：增发、回购、发债、拆股
- **E7 行业/宏观**：政策、关税、利率、行业景气拐点

证据：优先用用户上传的材料（财报 PDF/新闻）；不足时联网检索补齐关键事实（数字、原文表述）。**行情数据用 IBKR MCP，不用 yfinance。**

### Step 2 — 信号比对（核心步骤）

读取该公司当前**权威版**档案（`研究档案/` 顶层，不是 _pending），提取三份信号清单，逐条比对：

1. **06 分歧驱动表**：事件是否改变任何一个三情景取值不同的变量的当期读数？改变的话偏向哪个情景？
2. **04 交接块 H2**：是否命中某情景的领先指标？是否触发证伪信号？H4 锚切换确认条件是否满足？事件是否属于战略级催化剂（触发 04 慢刷条件）？
3. **valuation_registry signals**：逐条判断状态变化（未触发→已触发/部分触发/已失效），注明证据。

每条命中都必须写：信号原文（含来源指针，如 "06 §分歧驱动表 第3行" / "04 H2 上行情景"）、事件证据、判定（命中/未命中/部分）。**不得绕过档案自行得出与上游矛盾的结论**——发现事件证据与上游档案基础假设冲突，标注该上游模块 stale，进刷新建议。

### Step 3 — 影响矩阵 + 响应分级

按依赖关系输出影响矩阵（每个模块一行：影响判定 + 依据指针），然后定级：

| 级别 | 判定条件 | 动作 |
|---|---|---|
| **L0 仅登记** | 未命中任何驱动变量/信号，或仅确认已在预期内的进展 | 写事件日志 + 更新 signal 状态，不刷档案 |
| **L1 参数级** | 改变 06 驱动表变量取值，但模型结构、战略判断、主锚不变 | 刷 06+07 |
| **L2 结构/战略级** | 命中 04 证伪信号、H4 锚切换条件、H5 结构重建条件，或属 E2 战略级事件 | 先刷 04（catalyst 触发），accept 后按提醒级联 06+07 |
| **L3 上游级** | 事件动摇 01/02/03 的基础事实（年报大改→02；业务边界/经济引擎变化→03；换CEO/治理剧变→01+04） | 刷对应上游模块，accept 后全部下游依赖标 stale 级联 |

固定规则：
- **E1 财报固定至少 L1**（季报天然更新预测基线，刷 06+07）；信号比对只用于判断是否**升级**到 L2/L3。
- 情景判定可能翻转的（计分信号变化足以改变 dominant scenario），无论级别，**必须包含 07 重跑**——判定权在 07 计分制，本 skill 不预判结论，只标注"可能翻转 + 哪些信号变了"。
- 04 的 stale 阈值 365 天、慢刷语义不变：只有 L2 战略级条件命中才刷 04，L1 事件不碰 04。

### Step 4 — 落盘评估报告

两处（指针不复制原则）：

1. **完整评估** → `{公司目录}/研究档案/_events/{YYYY-MM-DD}_{事件slug}.md`，结构：
   - 事件摘要（≤5 行：类型、日期、关键数字、证据来源）
   - 信号比对表（逐条：信号原文指针 / 事件证据 / 判定）
   - 影响矩阵（按模块）
   - 响应级别 + 建议刷新集 + 理由
   - 待执行命令（prepare-refresh 的完整命令行，供批准后直接用）
2. **一行摘要** → 追加到 `{公司目录}/催化剂跟踪.md` 的事件日志（无此文件则先按 template 初始化）：日期 | 事件 | 级别 | 建议动作 | 评估文件指针。

### Step 5 — signal 状态更新（允许的唯一直接写操作）

若 Step 2 判定某些 registry signals 状态变化、**且不涉及情景判定翻转**：
1. Edit `_system/valuation_registry.json` 中该公司 `scenario_valuation.signals` 对应条目的状态字段（只改状态/日期/证据注记，**禁止改 dominant、三情景价、目标价、评级**）
2. `python3 _system/scripts/sync_valuations.py apply {TICKER}` + `check`（必须 exit 0）
3. 若信号变化可能翻转情景判定 → 不改 registry 判定，在评估报告标注"待 07 重跑判定"，刷新建议必含 07

### Step 6 — 报告用户，等批准

向用户报告（≤200 字）：事件一句话、命中信号数、响应级别、建议刷新集、评估文件路径。然后**停**，等用户明确批准（可整批批准，也可只批准部分模块）。

### Step 7 — 执行定向刷新（批准后，本 skill 端到端负责）

> 本段吸收自原 dossier-build Mode C；执行机制与它完全一致（同一 orchestrator、同一 pending 语义），差别只在事件 context 注入。

1. **prepare**（Projects 根目录执行；建议先 `rescan {TICKER}` 确保 registry 路径最新）：
   ```
   python3 _system/scripts/dossier_orchestrator.py prepare-refresh {TICKER} --slots {批准的刷新集} --trigger catalyst
   ```
   E1 季报例行用 `--trigger quarterly`。输出 `_pending/{ts}/_context_bundle.json`。

2. **派发 sub-skill / subagent，按依赖顺序：**
   - 批次含 01/02/03/05 上游模块时，Tier 顺序与并行约定照 dossier-build（Tier 1 三路 subagent 并行、Tier 间串行；03 等 02 成品）
   - **04 单独成批**：L2 战略级先只刷 04，finalize 后等用户 accept，再按提醒另起批次刷 06+07（慢刷语义，不与 06/07 同批）
   - 06 → 07 串行（07 需要 06 成品 + 05 权威版 + 04 交接块）
   - 上游依赖一律从 `研究档案/` **当前权威版**读，不从 _pending 读
   - **事件 context 注入（本 skill 特有）**：每个 sub-skill / subagent 的 prompt 必须附上——本次事件评估文件路径（`_events/{date}_{slug}.md`）+ 事件证据材料路径，明确要求"以评估文件中的命中判定为新事实输入，不要重新检索事件本身"
   - 产出写 `_pending/{ts}/{slot文件名}`，文件名严格按 schema；主上下文用 Read 校验存在且非空

3. **finalize**（自动跑 handoff_lint，lint ERROR 的模块标 failed）：
   ```
   python3 _system/scripts/dossier_orchestrator.py finalize-refresh {TICKER} {ts}
   ```

4. **报告**：完成/失败模块清单、`_diff_summary.md` 关键变化（≤200 字）、审核命令 `accept {TICKER} {ts}` / `reject {TICKER} {ts}`。

5. **accept 之后的既有链条不变**（估值同步 sync_valuations apply/check、6 个模块齐全时研究总结 HTML、04 被 accept 后提醒重跑 06+07）——这些约定的权威定义在 dossier-build skill 的"Accept 后"两节，照它执行，不在本文件复制（指针不复制原则）。

**升级条款：** 若批准的刷新集 ≥4 个模块（接近全量），提示用户改走 dossier-build Mode B 全量刷新更合适，由用户决定。

## 边界与禁区

- 04 缺失的公司（missing_strategy 名单）：Step 2 跳过 04 信号比对，评估报告注明"[04 未建，战略级判断不可用]"；若事件属 E2 战略级，建议顺势补建 04。
- 不修改 `_system/` 下任何脚本、schema、orchestrator——本 skill 是纯流程消费方。
- 禁加权规则照旧：任何概率加权价不进任何输出。
- 评估报告是研究记录，不进 `_pending/`（它不是档案模块），直接写 `_events/`；`研究档案/_events/` 目录不存在时创建。
- 多家公司同时受一个行业事件影响（E7）：逐家跑 Step 2-4，评估文件各写各的；刷新建议按公司分列，用户可分批批准。

## 失败处理

| 情况 | 处置 |
|---|---|
| 该公司档案不完整（06/07/04 缺失） | 信号清单缺哪份就跳过哪份并注明；若核心模块大面积缺失，建议直接走 dossier-build 补建而非事件分诊 |
| valuation_registry 无该公司条目 | 提示先走 new-company-onboarding 补注册 |
| sync_valuations check 失败 | 回滚 signal 编辑（registry 有自动备份），报告用户，signal 状态改留待人工 |
| 有未审 pending 批次 | 评估照做，但刷新建议标注"需先处理 pending 批次" |

## 失败处理（执行段补充）

| 情况 | 处置 |
|---|---|
| 某 sub-skill / subagent 失败 | 与 dossier-build 约定一致：_meta 对应模块标 failed + error_message，已完成的保留，可单独重派 |
| finalize 失败 | `_pending/{ts}/` 档案仍有效，手工补 _meta 后重跑 finalize |
| 同公司已有 pending 未审 | 不允许 enqueue，先 accept/reject |

## 版本

- v1.2（2026-08-29）：模块编号迁移——预测 05→06、估值 06→07、战略 07→04、股性 04→05；全文引用同步更新。
- v1.1（2026-07-30）：**吸收 dossier-build Mode C，本 skill 端到端拥有事件驱动局部刷新**（含季报例行）；新增 Step 7 执行段（prepare→派发→finalize，事件 context 注入）；≥4 个模块升级条款；dossier-build 同步升 v2.5 删除 Mode C。执行机制不变：orchestrator 唯一写入者，_pending/accept 审核一步不少。
- v1.0（2026-07-30）：初版。分诊五步流程；L0-L3 响应分级；signal 状态直改白名单（判定翻转必须重跑估值）；手动触发；落盘 _events/ + 催化剂跟踪；执行交棒 dossier-build Mode C。
