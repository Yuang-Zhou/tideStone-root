---
name: tidestone-research
description: 潮石公司研究与维护总入口。用户说“我想研究某家公司”“继续研究”“修订这份报告”“接受/退回草稿”“新财报更新”“看预测偏差”时使用；读项目状态后协调入库、准备资料、原七模块分析、待审、正式保存和总结。研究在 Codex 中完成，本地网页用于阅读。
---

# 从一句话开始潮石研究

先读 [本地运行约定](references/local-runtime.md)。本入口只把自然语言接到原系统工作流，不另造研究方法。21 个原名技能的全文、有效引用和计算脚本保存在相邻目录；调用前必须完整读对应 `SKILL.md` 和 `references/original.md`。

## 开始或继续

1. 读 `AGENTS.md` 和 `python3 scripts/tidestone.py status --json`。由 `_system/companies.json` 找公司，读材料清单、当前待审批次、正式档案和记录。不能把聊天记忆当状态。第一次无 Projects 时运行 `init`。
2. “我想研究 X”默认表示从当前状态做到可讨论的完整待审稿。自动核名称、证券代码和市场；仅在无法消歧时问必要问题。未入库就调用 `new-company-onboarding`，已入库不重复创建。仅说“入库”则停在资料准备。
3. 入库后自动准备公开报告、财务底稿、代理声明、电话会材料及行情。优先使用一手文件；独立新闻与对手资料用来交叉核验。失败项写清来源、日期、错误、受影响模块和下一步。能查证的继续查，不把逐项技术审核交给用户。没有数据不能编造。
4. 调用 `company-dossier-build`，按原 Tier 顺序完成七份。它调用各分析技能生成真实有证据分析；脚本不会替 Codex 研究。每个子任务有明确输出文件负责人；主任务校验依赖、数字和交接，完成后 `finalize`。
5. 告诉用户核心判断、最可能改变判断的事实、证据缺口和待审批次。给出“进一步解释”“修订”“接受这一批”“退回”的具体说法。完整研究授权不等于提前接受报告。

## 讨论、修订、接受或退回

- 解释时读现有稿和其来源，不凭记忆回答。若用户只追问，不把提问当修改或接受。
- 修改前运行 `revise TICKER TS --reason '用户修改意见'` 保存上一稿，再改指定批次；影响下游假设时按依赖更新下游。更新 `_diff_summary.md` 与修改依据，重新 `finalize`。不能直接改正式档案。
- 仅在用户明确接受可识别的具体批次后运行 `accept TICKER TS --reason '用户明确接受；简述原话与日期'`。若用户指代不明，先定位最近展示且唯一的批次；仍无法定位才问清。脚本验证通过不等于用户接受。
- 用户明确退回时运行 `reject TICKER TS --reason '用户理由'`，保留被退回稿与原正式档案。未说明理由可记“用户退回，未说明理由”，无需逼问。
- 接受后核同步队列、估值表、三年目标价与催化剂信息；全部数字能追溯到本次已接受档案。无法提取就待补，绝不能用另一份案例补齐。
- 仅在接受后调用 `research-summary`，在本公司目录生成 `研究总结_<YYYY-MM-DD>.html` 和同名 `.md` 总结；待审总结留在批次内，不覆盖正式版。按 research-summary 入口登记两份成品及来源指纹，再 `python3 scripts/ops.py build` 更新阅读网页。网页只是读盘结果，页面存在不证明研究完成。

## 后续维护

- 新财报或事件：调用 `research-event-update`，保留事件来源和影响矩阵；明确要求更新即执行已授权的本地待审刷新。仅要求评估就只评估。接受依然是另一项明确的用户决定。
- “对一下预测”：调用 `financial-forecast-feedback`，只形成偏差判定单。其结果不能自动改 06/07 或派更新。
- 日常扫描、持仓守卫、模拟盘分别调对应技能；没有数据或外部账号就真实显示未接入。手动运行和已经验证的定时运行分开报告。
- 换会话继续时读盘查找 pending、材料缺口、上次运行记录，再从未完成处推进。不能重复接受、重复建档或重放已处理事件。

## 原技能入口

| 工作 | 技能 |
|---|---|
| 入库/材料 | [new-company-onboarding](../new-company-onboarding/SKILL.md) |
| 完整编排 | [company-dossier-build](../company-dossier-build/SKILL.md) |
| 01 使命/领导力/治理 | [mission-vision-assessment](../mission-vision-assessment/SKILL.md) · [leadership-assessment](../leadership-assessment/SKILL.md) · [corporate-governance-assessment](../corporate-governance-assessment/SKILL.md) |
| 02 财务 | [financial-analysis](../financial-analysis/SKILL.md) |
| 03 商业模式 | [business-model-analysis](../business-model-analysis/SKILL.md) |
| 04 战略 | [strategic-decision-analysis](../strategic-decision-analysis/SKILL.md) |
| 05 股性 | [stock-character-analysis](../stock-character-analysis/SKILL.md) |
| 06 预测 | [financial-forecast](../financial-forecast/SKILL.md) |
| 07 估值 | [valuation-analysis](../valuation-analysis/SKILL.md) |
| 事件/偏差 | [research-event-update](../research-event-update/SKILL.md) · [financial-forecast-feedback](../financial-forecast-feedback/SKILL.md) |
| 总结 | [research-summary](../research-summary/SKILL.md) |
| 每日/持仓/模拟盘 | [daily-portfolio-scanner](../daily-portfolio-scanner/SKILL.md) · [daily-position-advisor](../daily-position-advisor/SKILL.md) · [value-growth-paper-monitor](../value-growth-paper-monitor/SKILL.md) |
| 单独补充研究 | [corporate-culture-analysis](../corporate-culture-analysis/SKILL.md) · [technical-analysis](../technical-analysis/SKILL.md) · [reverse-dcf](../reverse-dcf/SKILL.md) · [vc-style-valuation](../vc-style-valuation/SKILL.md) |

已知原始缺口与口径冲突见 [方法对应说明](../../../docs/method-map.md)；详细评价见 [方法学习报告](../../../docs/method-learning.md)。
