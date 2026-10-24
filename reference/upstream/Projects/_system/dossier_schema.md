# 公司研究档案规范 (Dossier Schema) v3.1

> **v3.1 变更 (2026-07-30)**：
> ① 新增 slot `04_战略决策.md`（strategic-decision-analysis skill 产出），Tier 2.5，依赖 01/02/03（+05 参考级）。**定位：必选节点、慢节奏刷新**——战略是财务预测与估值的核心上游（战略可改变财务模型结构、资本市场定位、估值方法与水平），因此首次完整建档必须包含；但战略是慢变量，刷新由催化剂触发（换 CEO / 重大并购 / 公开战略转向 / 年报战略章节大改），stale 阈值单独 365 天，季度例行刷新（Mode C 显式 --slots 06/07）不重跑 04。
> ② **过渡语义**：存量公司的 04 由用户手动分批补齐。补齐前 complete 判定仍按 6 核心槽（04 缺失不打 partial、不阻塞研究总结 HTML、不进 briefing 噪音），briefing 单列"待补战略档案"清单。全部补齐后将 complete 判定切换为 7 槽（orchestrator 内一行常量）。
> ③ 引入**交接块（Handoff Block）规范**（§2.5）：每份档案末尾输出结构化交接块 + 哨兵行，下游强制按来源引用，`handoff_lint.py` 在 finalize 时机器校验——使 DAG 上的逻辑传递可审计、防臃肿、防截断。
>
> **v3 变更 (2026-05-14)**：06_财务预测与估值.md 拆分为 06_财务预测.md + 07_估值分析.md 两个独立 slot。原 5-slot 规范的"06_财务预测与估值.md"在历史 _meta.json 中可能出现，rescan 会自动按新分类规则归到对应新 slot。

# 公司研究档案规范 (Dossier Schema) v1.0

> **状态:** 草案 · 2026-05-13 制定 · 等待首次试点（ISSC）验证后正式生效
> **关联系统:** 投资组合扫描（`daily-portfolio-scanner`）/ portfolio_registry.md / `company-dossier-build` orchestrator skill

## 1. 设计目标

将原本散落在每家公司目录下命名各异的分析文件（"研究报告/"、"研究结果/"、"分析/"、"1 财务数据/"、"4 企业文化/" 等），统一收敛到 **唯一规范目录** `研究档案/`，由 orchestrator skill 按依赖关系自动生成、人工一键审核合并。

历史目录（如 ISSC 的 `1 财务数据/` ~ `5 估值分析/`）作为**只读历史归档**保留，不动；新档案从规范确立日起进入 `研究档案/` 目录。

---

## 2. 五份档案与依赖关系（DAG）

| 序号 | 文件名 | 由哪个 sub-skill 产出 | 依赖 |
|------|--------|----------------------|------|
| 01 | `01_企业文化.md` | mission-vision-assessment + leadership-assessment + corporate-governance-assessment（三份合并为一份，分章节） | 无（上游 · 并行） |
| 02 | `02_财务分析.md` | financial-analysis | 无（上游 · 并行） |
| 03 | `03_商业模式.md` | business-model-analysis | ←02_财务分析（用真实利润/周转率/杠杆反证商业模式描述） |
| 05 | `05_股性分析.md` | stock-character-analysis | 无（上游 · 并行） |
| 06 | `06_财务预测.md / 07_估值分析.md` | financial-forecast + valuation-analysis（两份合并为一份，分两大章节） | ←01企业文化、02财务分析、03商业模式（驱动财务预测）；←05股性分析（提供市场惯用估值锚） |
| 04 | `04_战略决策.md`（v3.1 新增，必选·慢刷） | strategic-decision-analysis | ←01企业文化（真实文化/身份一致性）、02财务分析（资本配置台账）、03商业模式（业务边界与经济引擎基线）、05股性分析（**参考级**：历史事件市场反应）→ 产出战略三情景+预测交接表+定位判断，供 06/07 消费 |

### DAG 执行示意（v3.1）

```
Tier 1（可并行）：①企业文化 · ②财务分析 · ④股性分析
                      │           │            │
                      │           ▼            │
Tier 2：              │       ③商业模式（←②）  │
                      │           │            │
                      ├─────┬─────┤   ┌────────┘（参考级）
                      ▼     ▼     ▼   ▼
Tier 2.5：           ⑦战略决策（←①+②+③，④参考）
                      │
                ┌─────┴──（H2 战略三情景 + H3 预测交接表）
                ▼
Tier 3a：       ⑤a 财务预测（←①+②+③+⑦）
                      │
                      └──────┬──── ④股性（主锚建议）
                             ▼           ⑦（H4 定位判断/锚切换假设 + 监测里程碑）
Tier 3b：             ⑤b 估值（←⑤a + ④ + ⑦）
```

**战略的三条传导路径**（04 存在的理由）：
1. **战略→财务模型（06）**：不只改参数取值，可能改模型结构（收入驱动方式/成本结构/资本强度）→ H5 结构判断
2. **战略→资本市场定位→估值方法（07 主锚）**：05 是后视镜（市场过去用什么尺子），04 判断"公司在变成什么物种、尺子会不会换"→ H4 锚切换假设（**切锚判定权在 07 计分制**，04 只提假设+确认条件）
3. **战略→估值水平（re-rating）**：定位变化→可比集变化→倍数区间变化 → 乐观情景倍数的重估依据

过渡期 04 缺失时 06/07 照常执行（context bundle 标 `OPTIONAL_MISSING`），报告注明"[战略决策档案未提供，三情景为预测自建]"。

### 2.5 交接块（Handoff Block）规范 v1（2026-07-30）

**原则：每份档案 = 给人读的正文 + 给下游 skill 读的交接块。** 六条防臃肿设计原则：

1. **快照不是日志**：每次刷新整块替换，只描述当前有效判断，零累积；历史演变去 `_history/{ts}/` 翻旧版
2. **只传分歧与结论**：凡是不改变下游行为的信息不进交接块；论证/证据链留正文，交接块每格一句话/一个数 + "见正文 §X"指针
3. **定长契约**：字段清单固定、行数硬上限；想加内容先挤掉一行旧的（被迫按重要性排序）
4. **指针不复制**：下游引用写"04 §H3 第 2 行"，不抄内容——同一信息只在产生地存一份（单一事实源原则的推广）
5. **哨兵行 + 机器校验**：每个交接块末行固定 `<!-- HANDOFF-END v1 -->`；`_system/scripts/handoff_lint.py` 在 finalize-refresh 时校验（哨兵缺失=截断/漏写→FAIL；字段缺失→FAIL；行数超限→WARN，跑顺后改 FAIL）
6. **Schema 版本化**：字段增删必须 bump 哨兵版本号（v1→v2），禁止单公司档案自行加字段；旧档案缺新字段按 null 处理

**04_战略决策.md 交接块字段（H1-H5，全块约 30 行）：**

```markdown
## 交接块（HANDOFF v1）

### H1 核心战略命题（≤4 行）
- 一句话命题：通过【资源/行动】把【当前业务】转向【目标定位】，以【经济机制】获得【回报】
- 结构判断：单一核心 / 双核心互补 / 双核心冲突 / 核心未形成
- 轨迹性质：守住轨迹 / 创造新轨迹，期望增量：接近零 / 显著（2026-08-28 新增，给 07 机会类型判定）
- 置信度：高/中/低 + 一句话最强证据

### H2 战略三情景（恰好 3 行）
| 情景 | 成立条件（≤2条） | 时间窗 | 领先指标（≤2个） | 证伪信号（1条） |
| 失败 / 基准成功 / 上行 | … | … | … | … |

### H3 战略—财务预测交接表（≤12 行，只收三情景取值不同的变量）
| 变量 | 反事实基准 | 下行 | 基准 | 上行 | 起始/爬坡 | 正文依据（§指针） |

### H4 给估值的定位判断（≤5 行）
| 项 | 判断 | 可证伪的确认条件 |
| 可比公司集是否变化 / 锚切换假设（仅当有：当前锚X→候选锚Y） / 重估方向 |

### H5 模型结构判断（1 行）
现有预测模型结构可沿用 / 需重建（指明：收入驱动/成本结构/资本强度）

<!-- HANDOFF-END v1 -->
```

**明确不进 04 交接块**（留正文）：历史决策台账、pattern 规则表、概率加权增量 EV、所有论证过程。

**全 DAG 交接边一览**（各边传什么、下游怎么用）：

| 边 | 传递内容 | 下游消费 |
|---|---|---|
| 02→03 | 真实利润率/周转/杠杆/现金转化 | 反证商业模式主张 |
| 01→06 | 执行力评级+承诺兑现；激励一致性；文化风险 | 执行折扣；文化风险进悲观情景 |
| 02→06 | 历史基线指标轨迹 | 预测起点 |
| 03→06 | 收入天花板/渗透率；增长驱动；定价权与竞争格局 | 收入与毛利率中长期调整 |
| 01→04 | 宣称 vs 真实文化；管理层换代；治理拍板结构 | 身份一致性；战略时期划分；决策规则约束 |
| 02→04 | 资本配置台账；资产负债表约束 | 资源承诺证据（口号与钱流不一致以钱为准）；可行性边界 |
| 03→04 | 业务边界与经济引擎基线 | 判断核心战略是否改变价值创造逻辑 |
| 05→04（参考级） | 历史重大事件的市场反应模式 | 决策台账"资本市场预期变化"列证据 |
| 04→06 | H2 三情景；H3 交接表；H5 结构判断 | 三情景**必须声明映射**；H3 为假设起点（偏离须注明）；结构变更时重建模型 |
| 05→07 | 主锚建议+历史倍数区间+当前位置 | 主锚选择的历史依据 |
| 06→07 | 三情景预测序列；**分歧驱动表** | DCF 输入；计分信号唯一来源 |
| 04→07 | H2 里程碑（事件型）；H4 定位判断/锚切换假设/重估方向 | 路标补充（标 `[04 H2/H4]`，阈值与 04 一致）；锚切换按 H4 预设条件、判定权在计分制；乐观情景倍数 re-rating 依据 |
| 07→registry | 4.8 登记块 | accept 后同步 → 凯利 → 扫描 |

**三条硬规则（全 DAG 通用）：**
1. 下游引用上游必须注明来源（档案+块+行）；不得绕过上游自行研究出矛盾结论——发现矛盾 → 标上游 stale 提示重跑
2. 上游重跑被 accept → 全部下游依赖标 stale（04 被 accept 后提示重跑 06+07，提示不自动）
3. **禁加权边界**：04 的"概率加权增量企业价值"仅作战略层内部参考，禁止流入 07 任何目标价；情景归属由计分制判定，计分信号唯一来源仍是 06 分歧驱动表（04 只做交叉校验 + 事件型路标补充）

### 2.6 机会类型判定链 v1（2026-08-28）

**回答的问题**：这是一个什么样的投资机会——赚的是哪段钱、该怎么拿。目标价说涨多少，机会类型说怎么拿，两者缺一不可。

**两轴分开判，不合成一个形容词：**

| 轴 | 取值 | 产生地 |
| :-- | :-- | :-- |
| 业务轨迹 | 相变型 / 复利型 / 修复型 / 周期型 | 07 §4.0，输入取 02 F1「利润率空间」、03 §七「增长引擎性质 + 增速轨迹」、04 H1「轨迹性质」 |
| 股价表达 | 台阶（自身触发）/ 台阶（外部触发）/ 单边 / 反转 / 正弦 / 横盘 | 05 步骤四第 5 项「股价表达类型」四行表 |

**回报拆解**：主导情景到目标价的上行空间 = 盈利增长 + 估值倍数变动 + 股东回报，三块占比之和 = 1；占比最大的一块就是"赚的是哪段钱"。三块之和与 07 §4.3 上行差 >2 个百分点算勾稽不匹配。

**判定规则（按顺序命中即停）**：① 03=新引擎接力 且 04=创造新轨迹 → 相变型；② 02=正在修复 或 05=反转 → 修复型；③ 利润率与增速跟外部价格/景气走 → 周期型；④ 其余 → 复利型（按 02 利润率空间细分：有扩张空间 / 纯盈利复利）。上游字段缺失时 07 标「上游未提供」并括注正文线索，不许自行推断；上游互相打架标勾稽不匹配，按证据强的一方判。

**registry 字段**（07 §4.8 登记块顶层，`sync_valuations.py drain` 搬进 `valuation_registry.json`）：

```json
"opportunity_type": {
  "business_track": "相变型|复利型|修复型|周期型",
  "price_pattern": "台阶（自身触发）|台阶（外部触发）|单边|反转|正弦|横盘",
  "label": "{业务轨迹}业务 · {股价表达}股价 · 回报主要来自{占比最大的一块}",
  "return_split": {"earnings": 0.0, "multiple": 0.0, "yield": 0.0},
  "holding_style": "等业务拐点|拿着收复利|分批核修复|按周期进出",
  "regime_switch": "一个可核对的事件或数字，触发后本判定作废"
}
```

**下游消费**：`portfolio_registry.md` 条目 `- **Opportunity:** {label}｜{holding_style}`（accept 后手工回填，sync_valuations 不写 md）；research-summary 一句话画像第二句 = label、第三句 = holding_style，估值节加回报拆解小表。凯利/持仓守卫暂不消费 `holding_style`，research-event-update 暂不比对 `regime_switch`。

---

## 3. 目录结构

每家公司在自己原有的 sector 文件夹内新增 `研究档案/`：

```
{Sector}/{Company} ({TICKER})/
├── ...（原有目录保留，作为历史归档）
└── 研究档案/
    ├── 01_企业文化.md           ← 当前权威版（已审核）
    ├── 02_财务分析.md
    ├── 03_商业模式.md
    ├── 05_股性分析.md
    ├── 06_财务预测.md / 07_估值分析.md
    ├── _meta.json              ← 每份档案的元信息（见 §4）
    ├── _pending/               ← orchestrator 自动产出，等待人工审核
    │   └── {YYYY-MM-DDTHH-MM-SS}/
    │       ├── 01_企业文化.md
    │       ├── 02_财务分析.md
    │       ├── 03_商业模式.md
    │       ├── 05_股性分析.md
    │       ├── 06_财务预测.md / 07_估值分析.md
    │       ├── _meta.json      ← 此批次的产出元信息
    │       └── _diff_summary.md ← 与现版本的关键差异（人工审核入口）
    └── _history/                ← 已被覆盖的旧版本
        └── {YYYY-MM-DDTHH-MM-SS}/
            └── ...
```

### 合并语义（"一键接受整份"）

用户在 dashboard 点击"接受 {ticker} 待审档案"时：

1. 当前 `研究档案/{01-05}.md` + `_meta.json` 整体移动到 `_history/{现在时间戳}/`
2. `_pending/{该批次时间戳}/{01-05}.md` + `_meta.json` 整体移动到 `研究档案/` 顶层
3. `_pending/{该批次时间戳}/` 目录置空（或仅保留 `_diff_summary.md` 一份）
4. 更新 `_system/dossier_registry.json` 中此 ticker 的 `last_updated` 与 `dossier_status`

**拒绝**：将 `_pending/{时间戳}/` 整体移动到 `_pending/_rejected/{时间戳}/`，不动当前权威版。

---

## 4. `_meta.json` Schema（per-company）

每家公司的 `研究档案/_meta.json` 记录五份档案各自的状态：

```json
{
  "schema_version": "1.0",
  "ticker": "ISSC",
  "company_name": "Innovative Aerosystems",
  "sector": "3. 航空航天",
  "documents": {
    "01_企业文化.md": {
      "last_updated": "2026-04-07T10:30:00Z",
      "source_period": "FY2026 Q1",
      "trigger": "initiation",
      "approval_status": "approved",
      "approved_at": "2026-04-07T11:00:00Z",
      "sub_skills_used": [
        "mission-vision-assessment",
        "leadership-assessment",
        "corporate-governance-assessment"
      ],
      "session_id": null
    },
    "02_财务分析.md": {
      "last_updated": "2026-04-07T10:30:00Z",
      "source_period": "FY2026 Q1",
      "trigger": "initiation",
      "approval_status": "approved",
      "approved_at": "2026-04-07T11:00:00Z",
      "sub_skills_used": ["financial-analysis"],
      "session_id": null
    },
    "03_商业模式.md": { "...同上结构..." },
    "05_股性分析.md": { "...同上结构..." },
    "06_财务预测.md / 07_估值分析.md": {
      "last_updated": "...",
      "source_period": "...",
      "trigger": "...",
      "approval_status": "...",
      "sub_skills_used": ["financial-forecast", "valuation-analysis"],
      "target_price": 33.0,
      "target_price_currency": "USD",
      "rating": "买入"
    }
  }
}
```

### 字段说明

- `last_updated`: ISO 8601 时间戳，档案最后一次被人工接受合并的时间
- `source_period`: 这份档案基于的财报期（"FY2026 Q1"、"2025 年报"、"2026 H1" 等）。下游 skill 引用上游档案时用此字段判断"是否过期"
- `trigger`: 本次刷新的触发原因，枚举值：
  - `"initiation"` — 新公司入库首次建档
  - `"quarterly"` — 季度财报后例行刷新
  - `"catalyst"` — 重大催化剂落地触发
  - `"manual"` — 用户手动触发
  - `"stale_refresh"` — 距上次刷新超过 `stale_threshold_days`
- `approval_status`: `"approved"` / `"pending"` / `"rejected"` / `"draft"`（pending 仅在 `_pending/` 目录里使用）
- `sub_skills_used`: 实际调用的子 skill 列表（用于追溯）
- `session_id`: orchestrator 跑这一批次时的 session ID（用于回溯日志，可为 null）

---

## 5. `_system/dossier_registry.json` Schema

中央索引，记录所有公司的档案状态。`daily-portfolio-scanner` 每天读它来发现"该刷新了"的公司。

```json
{
  "schema_version": "1.0",
  "last_updated": "2026-05-13",
  "default_stale_threshold_days": 120,
  "companies": [
    {
      "ticker": "ISSC",
      "company_name": "Innovative Aerosystems",
      "sector": "3. 航空航天",
      "folder": "3. 航空航天/创新软件 (ISSC.O)",
      "dossier_path": "3. 航空航天/创新软件 (ISSC.O)/研究档案",
      "dossier_status": "partial",
      "documents": {
        "01_企业文化.md": {
          "exists": true,
          "last_updated": "2026-04-07",
          "age_days": 36,
          "is_stale": false,
          "legacy_source": "3. 航空航天/创新软件 (ISSC.O)/4 企业文化/Innovative_Aerosystems_企业文化分析.md"
        },
        "02_财务分析.md": {
          "exists": true,
          "last_updated": "2026-04-07",
          "age_days": 36,
          "is_stale": false,
          "legacy_source": "3. 航空航天/创新软件 (ISSC.O)/3 财务分析/ISSC_Financial_Analysis_v3.docx"
        },
        "03_商业模式.md": {
          "exists": false,
          "legacy_source": null
        },
        "05_股性分析.md": {
          "exists": true,
          "last_updated": "2026-04-07",
          "age_days": 36,
          "is_stale": false,
          "legacy_source": "3. 航空航天/创新软件 (ISSC.O)/2 股性分析/ISSC_股性分析.md"
        },
        "06_财务预测.md / 07_估值分析.md": {
          "exists": true,
          "last_updated": "2026-04-07",
          "age_days": 36,
          "is_stale": false,
          "legacy_source": "3. 航空航天/创新软件 (ISSC.O)/5 估值分析/估值分析. claude.md"
        }
      },
      "pending_reviews": [],
      "stale_threshold_days": 120,
      "next_review_trigger": "Q2 FY2026 财报 (2026-05-14)"
    }
  ]
}
```

### `dossier_status` 枚举值

- `"complete"` — 五份齐全且都未过期
- `"partial"` — 部分文档存在（迁移期常见状态）
- `"empty"` — `研究档案/` 目录尚未建立
- `"stale"` — 五份齐全但至少有一份超过 stale_threshold_days
- `"pending_review"` — 有待审批次（`_pending/` 非空）

### `legacy_source` 字段

迁移期专用字段，记录这份档案的"内容来源"。如果是从旧目录迁移过来的文件，记录原路径；如果是 orchestrator 新生成的，置为 null。一旦档案进入正常更新流程，未来不再使用此字段（迁移完成后可移除）。

---

## 6. 失败处理 & 边界情形

- **orchestrator 跑到某个 skill 失败**：已生成的部分留在 `_pending/{时间戳}/`，`_meta.json` 中失败 skill 的 `approval_status` 写为 `"failed"`，并附 `error_message` 字段。用户可决定是否丢弃整批次或保留已生成部分。
- **新公司首次建档**：`dossier_status: "empty"` → orchestrator 跳过"读取现版本"步骤，直接从 raw materials（10-K/财报 PDF）开始
- **`研究档案/` 与 `_pending/` 共存**：dashboard 显示"待审"高亮，未审完前不允许再次 enqueue（同一公司不能有两批 pending）
- **`source_period` 不一致**：下游 skill 读上游档案时，如果发现上游的 `source_period` 比当前最新财报老一期以上，警告但不阻塞（让用户决定是否重跑上游）

---

## 7. 与 portfolio_registry.md 的关系

`portfolio_registry.md` 仍是公司"业务层注册表"（评级、目标价、催化剂、估值区），由人工维护。

`dossier_registry.json` 是"档案层索引"，由 orchestrator 和 daily-portfolio-scanner 自动维护。

两者通过 `ticker` 字段关联。**当 `_pending/` 中包含 `06_财务预测.md / 07_估值分析.md` 且其 `target_price` 与 portfolio_registry 中不一致时**，dashboard 标红提示"目标价待更新"——用户接受档案合并后，需要手动同步到 portfolio_registry.md（或后续 Phase B 中加自动同步开关）。

---

## 8. 版本演进

本规范 v1.0。重大字段变更会 bump 到 v1.1+，但旧版 `_meta.json` 保持向后兼容（缺失字段当成 null 处理）。

- 2026-08-28：§2.5 H1 加「轨迹性质」行（≤3→≤4 行）；新增 §2.6 机会类型判定链（`opportunity_type` 字段）。旧档案缺该字段按 null 处理，drain 只 WARN 不阻塞。
