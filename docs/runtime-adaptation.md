# 本地运行适配与三年登记契约

原方法固定于 `e5b147afa1b2c49bb9a6651094958538d5802a59`。本文件说明本地数据传递和状态校验，不新增估值方法。原件保存在 `reference/upstream/`，适配代码和哈希记录在 `Projects/_system/runtime_adaptation.json`。

## 数据位置与正式状态

默认数据根为本项目的 `Projects/`。测试必须把 `TIDESTONE_PROJECTS` 设为项目内隔离目录，源码仍从本项目 `Projects/_system/scripts/` 运行。材料、批次和历史不会被文件名扫描误认成正式结论；正式模块须同时满足规范路径、非空内容、已批准元数据、接受批次、接受时间和内容 SHA-256 一致。

新公司首次接受必须七份模块齐全。入库不预写空报告，也不恢复原引擎的旧档案自动发现或六份核心模块过渡状态。

## 币种登记

`scripts/tidestone.py add` 接受可选 `--currency`，格式是三位大写字母。US/HK/CN 分别默认 USD/HKD/CNY，实际证券报价不同可明确覆盖；OTHER 必须明确提供币种。这里验证代码格式，研究者仍须根据证券身份核对报价币种、财务报表币种和换算依据。

## 07 的两种登记块

接受 07 后进入 `Projects/_system/pending_valuation_sync.json`。运行 `python3 scripts/tidestone.py sync TICKER` 时，两类登记都读取该公司规范路径下同一份已接受、内容哈希匹配的 07。读取 pending 报告、历史报告或另一个公司路径会失败。

普通估值使用 `### 4.8 valuation_registry 登记块` 下的 JSON 对象，必需字段为 `rating`、`target_price`、`zones`、`scenario_valuation`。币种沿用已核实公司报价币种；若显式填入则必须相同。此登记保留当前主导情景及其期限，不能用情景或方法加权目标替代。

三年目标单独使用以下标题，紧接一个 JSON 代码块：

```text
### three_year_valuation_registry 登记块
```

必需字段如下。金额和股数的 `_b` 均为十亿；每股价格采用公司报价币种，不是十亿单位。

| 字段 | 约束 |
|---|---|
| `target_year` | 整数，等于 `anchor_date` 年份加 3；这是本地防止期限混用的规则 |
| `currency` | 与公司已核实报价币种相同 |
| `scenario` | `base`，沿用原三年登记的基准情景口径 |
| `valuation_method` | 说明主估值方法，不得写情景或方法加权 |
| `valuation_type` | `ev`、`equity` 或 `fixed` |
| `metric_value_b` | 所用预测指标；`ev`/`equity` 要求正有限数，`fixed` 可为 null |
| `target_multiple` | 所用倍数；`ev`/`equity` 要求正有限数，`fixed` 可为 null |
| `net_debt_b` | 有限数；净现金可为负数，PE 不重复扣减净债务 |
| `share_equivalent_b` | 正有限数，说明摊薄及 ADR 等价股口径 |
| `target_market_cap_b` | 正有限数，目标股权市值 |
| `target_price_3y` | 正有限数，三年每股目标价 |
| `anchor_price` | 正有限数，锚点价格 |
| `anchor_date` | `YYYY-MM-DD`，锚点日期 |
| `source` | 本次 07 与所消费 06 的计算出处；不能填未经研究的旧结论或示例 |

建议另填 `target_date`、`financial_period`、`note`，区分估值兑现日期和所用财年指标。`target_date` 如提供，必须晚于锚点且年份与 `target_year` 相同。其他估值期限不要改标签混入三年登记。

数值复核采用原三年市值到股价的关系：`ev` 为指标 × 倍数 − 净债务；`equity` 为指标 × 倍数；`fixed` 使用有出处的股权市值，再统一除以等价股数。市值相对容差为 0.1%，每股价相对容差为 0.1% 或绝对 0.01。有限数校验排除 NaN、Infinity 和布尔值。运算成立仅证明登记可复算，不证明预测或倍数合理。

普通主价与三年基准价可以来自不同情景和期限，必须在 07 和展示中分别说明。它们不能被合成为加权价。

同步器自动写入 `source_path`、`source_sha256`、`accepted_batch`、`source_approved_at`。报告无需猜这些运行字段；若报告显式给出前三项，必须匹配真正已接受的 07。两张注册表因此能追溯到同一接受批次。

## 缺失或失败时保留待补

三年登记不是接受研究报告的硬门槛，但它是三年同步成功的门槛。缺标题、缺字段、币种冲突、年份不符、来源不符或算术失败时，`sync` 退出码非零，队列保留具体错误及 `valuation_status` / `three_year_status`。普通估值成功时可先保存；三年目标显示 `status: pending`、`target_price_3y: null` 和 `missing_reason`。上批三年价进入历史，不充当本批目标；只有两类登记均成功并通过视图一致性检查才出队。

补齐须修订对应研究批次并重新经过接受流程，不能直接伪填注册表或清空队列。程序不会联网补造缺失预测。

## 日常跟踪与模拟盘候选

`valuation_registry.json` 的 `status` 沿用上游原含义：`active` 进入日常扫描池，`paused` 暂停跟踪。新公司入库默认 active，但评级仍为“待研究”，档案仍显示 empty；这不是完成研究，也不代表有任何持仓。`validate_briefing.py` 按 active 核验扫描覆盖范围，不能把跟踪状态误当七模块完成度。

用户说“把这家公司纳入日常跟踪”或“恢复跟踪”时，可由 Codex 执行：

```text
python3 scripts/tidestone.py track TICKER --status active --reason "用户明确要求纳入日常跟踪"
python3 scripts/ops.py build
```

缺七模块或三年目标不会阻止入库和日常跟踪。新闻扫描仍须实际在 Codex 中执行；程序维护成功不代表 AI 新闻已扫描。低层行情下载可按 companies 全池缓存数据，不等于暂停公司仍在新闻扫描候选中。

用户要求暂停跟踪时执行 `track TICKER --status paused --reason "用户说明的理由"`。暂停保留公司、研究、材料和历史，但从日常扫描和模拟盘候选中退出；如已有该票虚拟持仓，下一次模拟盘运行会按原引擎处理出池状态，应先说明这一影响。状态同时写入 JSON 与 Markdown，理由和前一状态进入公司 `_workflow.json`。不要靠手改一份注册表来维护状态。

active 公司进入模拟盘评估后，仍须通过原引擎的三情景估值、三年目标、行情新鲜度、主导情景、低估与增长条件，才可能产生虚拟交易。新入库的空档案不会因此生成投资结论。没有初始化模拟盘时，track 不创建账户或持仓，也不代表真实买入。

模拟盘币种转换使用配置里的 `fx_to_usd`。缺少该币种的有效正有限汇率时，候选不得买入；如已有该币种持仓，则停止运行，不用 1:1 换算编造新净值。固定汇率沿用原引擎口径，需核对日期、市场参考指数、整手与成交假设，尤其是 OTHER 市场。

## 接受后的后续提示

同批已接受 04、06、07 时不会再次建议重跑 06/07；仅提示尚未同批覆盖的下游模块。七模块齐全后，总结应写在公司根目录 `研究总结_<时间>.md` 与同名 `.html`，再由 `scripts/register_summary.py` 登记两份文件及来源哈希，最后运行本地 build。旧的“基本面分析汇总”路径不是本地总结入口。
