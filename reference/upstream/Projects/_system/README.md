# `_system` 目录导航

> 最后整理：2026-08-09 · 整理规则见文末「归档约定」
>
> **2026-08-09 变更：** Projects 根目录已清空到只剩四个目录（`companies/` `_system/` `基本面分析汇总/` `website_deploy/`）。
> **2026-09 补充：** 根目录新增第五个目录 `market_rotation_mvp/`（周线资金压力监控器，独立 Streamlit 应用，自带 `.venv/` 和 `data/`，与本系统脚本互不引用；`monitor-startup.*.log` 是启动脚本在用的，勿删；详见其 README）。
> 原先散在根目录的六个文件全部移入 `_system/`：两个 `.bat`、`每日自动部署_设置清单.md`、`last_run.log` 放本级，
> `build_site.py` 进 `scripts/`，一次性的 `cleanup_projects.py` 归档进 `_archive/oneoff/`。
> 脚本内的路径基准已同步改好（`.bat` 用 `cd /d "%~dp0.."`，`build_site.py` 的 `BASE` 上溯三层）。

`_system` 是投资系统的**数据与脚本层**，不放研究内容（研究内容在 `companies/` 下）。
本文件是唯一的目录说明，改结构时请同步更新这里。

---

## 〇、按性质速查（先看这张表）

`_system` 是个混装目录——真相源、引擎、外部数据、每日成果、归档都在里面。
目录名本身看不出这些差别，所以先按**「谁写它 / 丢了能不能重建」**过一遍。
这条线比「数据源 vs 成果」更有用，因为它直接回答**备份该备什么、什么能随便删**。

| 性质 | 是什么 | 文件数 | 谁写 | 丢了会怎样 |
|---|---|---:|---|---|
| 🔴 **真相源** | `companies.json`（全库唯一真相源）· `valuation_registry.json` · `three_year_valuation_registry.json` · `position_triggers.json` | **4** | 人工 / dossier accept | **要重做，无法自动恢复** |
| 🔴 **规范与文档** | `dossier_schema.md` · `数据校验流程_MANDATORY.md` · `catalyst_tracker_template.md` · `README.md` · `每日自动部署_设置清单.md` | 5 | 人工 | 要重写 |
| 🔴 **引擎** | `scripts/` · `host_pipeline/` · `daily_pipeline.bat` · `手动推送上线.bat` · `刷新网站本地预览.bat` | 23 | 人工 | 要重写 |
| 🟡 **每日成果** | `daily_briefing/` · `position_advice/` · `positions/` · `scan_log/` | **237** | 每日扫描流程 / `position_guard.py` / `kelly_engine.py` | 丢的是历史记录，不影响系统运行 |
| 🟢 **外部行情** | `market_data/` | 95 | `market_data_fetcher.py` | 重新拉一次即可 |
| 🟢 **纯生成物** | `portfolio_registry.md`（+`.backup.md`）· `dossier_registry.json` · `pending_valuation_sync.json` · `last_run.log` | 5 | 脚本自动 | 跑 `sync_valuations.py apply` / `dossier_orchestrator.py rescan` 就重建 |
| ⚪ **归档** | `_archive/` | 188 | 人工整理 | 只供回溯，删了不影响任何流程 |

**🔴 必须备份（加起来不到 1 MB）** —— 上面三行。再加上 `companies/*/研究档案/`（333 个 md，系统的核心资产）。
**🟡 值得备份** —— 每日成果，是"我当时怎么判的"的唯一记录，但系统不依赖它。
**🟢⚪ 不用备份** —— 外部行情、生成物、归档，全部可重建或可重拉。

> 整包复制 Projects 约 460 MB，其中 **83% 是 `companies/*/[公司] Wiki/` 里的 SEC 原文和 PDF**（一手素材，可重下）。
> 只想留"丢了要命"的部分，备 `_system` 的 🔴 三行 + `companies/*/研究档案/` 就够，几十 MB。

**几个天然跨界、不要纠结归类的：**
- `valuation_registry.json` —— 既是真相源，又是每日构建的输入，本身还是研究结论
- `daily_briefing/` —— `{date}_daily_briefing.md` 是成果，同目录的 `briefing_data_{date}.json` 是它的数据层
- `portfolio_registry.md` —— 是 `valuation_registry.json` 的生成视图，但人也直接读它

> **为什么不按这张表把目录拆开？** 2026-08-09 评估过：脚本侧有 **24 处硬编码 `"_system"`**（8 个脚本，可改）；
> 但真正的瓶颈在**账号侧的 skill 正文**——每日扫描写 `scan_log/` 和 `daily_briefing/`、
> `new-company-onboarding` 改 `companies.json` 并跑 rescan，这些路径写死在 skill 里，
> 只能人工逐个改，且无法一次性验证。加上任务计划、GitHub/Cloudflare 发布链。
> 结论：**先用这张表让结构可读，物理拆分等 skill 侧有整体调整时再一起做。**

---

## 一、根目录：单一事实源（Single Source of Truth）

这些文件被脚本和 skill 硬编码引用，**不要重命名、不要移动**。

| 文件 | 作用 | 谁在写 |
|---|---|---|
| `portfolio_registry.md` | 组合注册表（公司清单 + 评级 + 估值区间的**生成视图**） | 人工 / `sync_valuations.py apply` |
| `portfolio_registry.backup.md` | 上面这个文件的自动备份，**每次 apply 覆盖，只留最近一份** | `sync_valuations.py`（自动） |
| `valuation_registry.json` | **估值单一事实源**（rating / zones / target_price） | 人工 / dossier accept 流程 |
| `three_year_valuation_registry.json` | **三年每股目标价事实源**（2028E 目标价、估值锚、等效股数）。schema v2 起含 `scenario_*` / `vs_base` / `needs_recheck` 诊断字段，由 `annotate_three_year_registry.py` 在每次构建前自动刷新 | 人工补录（**07 accept 后必须补**，见下）；诊断字段脚本自动 |
| `three_year_coverage_waivers.json` | 已知且已决定暂不补的三年估值缺口豁免表。豁免只免除校验失败，不免除补录义务 | 人工 |
| `dossier_registry.json` | 研究档案注册表（六维分析的状态与指针） | `dossier_orchestrator.py` |
| `position_triggers.json` | 持仓触发器配置 | 人工 |
| `pending_valuation_sync.json` | 待同步估值的队列（空 = 已同步干净）。写入端 = `dossier_orchestrator.py` accept 07 时；消费端 = `sync_valuations.py drain`（**2026-07-30 补上，此前消费端缺失、队列只进不出，是 registry 陈旧的系统性成因**） | `dossier_orchestrator.py`（写） / `sync_valuations.py drain`（读+出队） |
| `dossier_schema.md` | 研究档案的字段规范 | 人工 |
| `数据校验流程_MANDATORY.md` | 行情数据时效校验流程 v2.0，**每日扫描 Step 0 必读** | 人工 |
| `catalyst_tracker_template.md` | 催化剂追踪模板 | 人工 |

> ⚠️ `portfolio_registry.backup.md` 看着像垃圾，其实是 `sync_valuations.py` 的活跃产物，**不要删**。

### 本级还有（2026-08-09 从 Projects 根目录移入）

| 文件 | 作用 | 备注 |
|---|---|---|
| `daily_pipeline.bat` | 每日自动流水线（2026-09-27 合并）：拉行情 → 算信号 → 模拟盘 → 校验行情 → 重扫档案 → 三年估值覆盖 → 归档旧文件 → 重建网站 → 推 GitHub 触发 Cloudflare | **任务计划程序指向的就是它**；移位后任务计划里的路径必须同步改。不调用下面两个 bat |
| `手动推送上线.bat` | 手动立刻上线（原名 `每日自动更新.bat`，2026-10-20 改名）：严格校验行情 → 重扫档案 → 重建网站 → 推 GitHub。不拉行情 | 双击即可，跑完屏幕显示 SUCCESS/FAILED 并停住 |
| `刷新网站本地预览.bat` | 只在本地重建站点，不上传（原名 `刷新网站.bat`） | 双击即可，改完 `build_site.py` 或新做研究总结后看效果用 |
| `推送简报.bat` | 当天简报上站（2026-10-20 加）：跑 `build_site.py`（含简报页）→ 有变更才 git push。无变更时静默退出 | **任务计划每天 09:30 跑**（扫描器约 08:55 出当天简报，早于它的 08:30 流水线推不到）。无人值守，不 pause |
| `last_run.log` | `daily_pipeline.bat` 的运行结果，每次覆盖 | 看这里判断昨夜是否 SUCCESS；每日简报也读它 |
| `manual_push_last_run.log` | `手动推送上线.bat` 的运行结果，每次覆盖 | 和 `last_run.log` 分开，手动推送不会抹掉当天自动运行的记录 |
| `briefing_push_last_run.log` | `推送简报.bat` 的运行结果，每次覆盖 | 同上，独立日志 |
| `每日自动部署_设置清单.md` | 任务计划 + GitHub + Cloudflare 的一次性设置步骤 | 纯文档，无代码引用 |

> 四个 `.bat` 都用 `cd /d "%~dp0.."` 回到 Projects 根再跑，**移动它们必须同步改这一行**。

---

## 二、子目录

### `scripts/` — 核心引擎（全部活跃）

| 脚本 | 作用 |
|---|---|
| `market_data_fetcher.py` | 宿主机拉行情 → `market_data/*.csv` + `_data_status.json` |
| `validate_market_data.py` | 行情时效校验，输出 `VALIDATION_JSON`（PASS / STALE / …） |
| `compute_signals.py` | 技术信号计算，被 `host_pipeline/host_signals.py` 调用 |
| `kelly_engine.py` | 情景凯利仓位建议 → `position_advice/` |
| `position_guard.py` | 持仓守卫 → `positions/guard_verdict_*.json` |
| `sync_valuations.py` | 估值 JSON ↔ registry md 双向同步（extract / check / apply） |
| `build_valuation_comparison.py` | 读取每日行情 + 两个估值注册表，生成 `基本面分析汇总/组合三年估值看板.html`；2026-10-20 起同时写 `_system/valuation_comparison_summary.json` 给首页入口卡 |
| `dossier_orchestrator.py` | 研究档案编排（rescan / prepare / accept / migrate）。**正本优先**：`研究档案/{slot}.md` 存在就以它为准，散落旧文件降级为 `shadowed_legacy` 只做提示 |
| `build_site.py` | 生成研究网站到 `website_deploy/public/`（2026-08-09 从 Projects 根目录移入，`BASE` 已改为上溯三层）。2026-10-20 起：板块可折叠（默认收起）；首页三张入口卡（目标价对比读 `valuation_comparison_summary.json`）；构建时先调 `build_briefing.py`；复制研究总结页时 `skin_research()` 套统一外框、模拟盘页 `skin_paper()` 换掉自带样式——源文件都不动 |
| `site_chrome.py` | 网站共用页头/页脚/`<head>` 片段（2026-10-20 改版）。四个生成脚本都从这里拿同一条顶栏和页脚；样式在 `website_deploy/public/site.css`（五类页面共用：纸面底、墨色字、一种交互色、涨跌只给数字；研究总结页靠 `.rs-wrap`、模拟盘页靠 `.pp-wrap` 套皮）。改外观先改 site.css，再看各脚本的页面专属样式 |
| `build_briefing.py` | 把 `daily_briefing/*_daily_briefing.md` 转成网页，输出 `website_deploy/public/briefing/`（目录页 + 每日一页）。只用标准库，Markdown 转换是手写的，简报新增语法要跟着补。源 md 被归档后站上历史页保留 |
| `audit_core_conclusions.py` | 55 家研究资料覆盖度体检 → `基本面分析汇总/公司核心结论提取审计_{date}.md` + `.json`。手动跑，无自动化调用 |
| `validate_taxonomy.py` | 分类体系八类校验，涉及分类/目录/入库的改动后必跑，应 0 ERROR |
| `handoff_lint.py` | 04 交接块格式校验（禁「概率加权」等硬规则） |
| `archive_old.py` | 把超保留期的日期文件搬进 `_archive/{类别}/{年-月}/`。默认只列清单，`--apply` 执行，`--undo-last` 撤销；按**文件名日期**判断，无日期的一律跳过；另外把超过 3 天的 `*.bak*` 手工备份归进 `_archive/backups/`（固定名的 `valuation_registry.json.bak_before_drain` 除外）。**已挂进 `daily_pipeline.bat` 第 6.5 步，每天自动跑，不阻断发布** |
| `SETUP_MARKET_DATA_FETCHER.md` | fetcher 的宿主机部署说明 |

### `host_pipeline/` — 宿主机每日任务
`跑信号.bat`（任务计划调用）→ `host_signals.py` → 写 `market_data/_signals_status.json`。
部署与对账见 `README_部署与对账.md`。

> 任务计划里「程序或脚本」必须写 **python.exe 完整路径**，不能靠 .py 关联。

### `market_data/` — 行情数据（每日覆盖写）
- `*.csv` — 51 只标的的 OHLCV
- `indices/` — 6 个基准指数
- `_data_status.json` — 数据时效清单（校验流程的输入）
- `_signals_status.json` — 信号计算结果
- `fetch_log/` — 拉取日志，**保留 31 天**

### `daily_briefing/` — 每日简报
- `{date}_daily_briefing.md` — 简报正文，**保留 31 天**
- `briefing_data_{date}.json` — 简报数据层，**保留 31 天**（单个已涨到 ~180KB，是体积大头）
- `dashboard_template.html` + `render_dashboard.py` → `dashboard_rendered.html`（每次重生成）
- `SCHEMA.md` — briefing_data 的字段规范

### `positions/` — 持仓守卫
`guard_verdict_{date}.json`（守卫判定）+ `snapshot_{date}.json`（持仓快照），**保留 31 天**。
凯利引擎以当日 `guard_verdict_{date}.json` 为持仓事实源；不再使用固定名称的临时持仓文件。

### `position_advice/` — 仓位建议
`{date}_position_advice.md`、`{date}_kelly_advice.md`、`_kelly_out_{date}.json`、`_kelly_dashboard_{date}.html`，**保留 31 天**。

### `scan_log/` — 每日扫描叙事
`{date}.md` 每日一篇（**保留 31 天**）；`registry_changelog.md` 记公司增删（**永久保留**）；`README.md` 说明写法。

> `portfolio_registry.md` 头部「最后更新」只留一行指针（≤120 字符），**禁止头部日志堆积**。

### `_archive/` — 历史归档（只读）
按 `{类别}/{年-月}/` 分层，超过保留期的文件搬到这里——用 `scripts/archive_old.py --apply`。当前类别：
`briefing_data/`、`daily_briefing/`、`scan_log/`、`fetch_log/`、`positions/`、`position_advice/`、`dashboard/`。
`_move_log.jsonl` 是每次归档的流水（**日志放这里、不放会被整体删除的目录**——2026-08-09 的教训：manifest 跟着 `_to_delete` 一起没了，事后无法归因）。
另有 `oneoff/` —— 用完的一次性工具，不按年月分层：
- `cleanup_projects.py`（2026-08-09 全库清理专用，已完成；`--empty-dirs` 之类还能用，但路径基准是自己所在目录，重新启用前要先改 `ROOT`）
- `_replaced/` —— 被就地替换掉的旧版本文件

脚本和 skill **不读这里**，只供人工回溯。

### `_to_delete/` — 待人工删除
Cowork 沙盒无删除权限，判定为死文件的东西集中放这里，人工确认后整个删掉。
分类：`backups/`（旧 .bak）、`tmp/`、`oneoff_scripts/`（一次性生成脚本）、
`oneoff_html/`、`misplaced/`（放错目录的）、`pycache/`。

---

## 三、归档约定

1. **保留期 31 天**：`daily_briefing`（md + json）、`scan_log`、`fetch_log`、`positions`、`position_advice` 的日期文件，超期搬入 `_archive/{类别}/{YYYY-MM}/`。
2. **永久保留**：根目录的单一事实源、`scripts/`、`host_pipeline/`、`market_data/*.csv`、`scan_log/registry_changelog.md`。
3. **备份文件不留在原地**：临时性 `.bak_before_xxx_{date}` 用完即搬 `_to_delete/backups/`；只有脚本自动维护的固定名备份（`portfolio_registry.backup.md`）可以留在根目录。
4. **一次性脚本不放业务目录**：调试用的 `_gen_*.py` / `_md_*.py` 之类跑完就搬 `_to_delete/oneoff_scripts/`。
5. **新增目录必须在本文件登记**，否则下次整理会被当成孤儿。

---

## 三年估值覆盖规则（2026-08-14 补）

**规则：任何公司的 `07_估值分析.md` 一旦 accept，必须同时往 `three_year_valuation_registry.json` 写一条。**

为什么要写成规则：这张表历史上只有一个写入口——2026-06-30 那次
`build_valuation_comparison.py --migrate` 从旧看板一次性导入。此后 `new-company-onboarding`
建新公司、`company-dossier-build` 跑完整档案，**都不会碰这张表**。结果是 6/30 之后新建的
档案（美光、英特尔、联合健康、礼来、台积电…）在组合三年估值看板上一律显示"待补录"，
2028E 数据其实就躺在各自的 `07_估值分析.md` 里，只是没人搬过去。

**一条条目要填的字段**：`target_year` / `valuation_method` / `valuation_type`(ev|equity|fixed) /
`metric_value_b`（目标年指标）/ `target_multiple`（**取基准情景倍数**）/ `net_debt_b` /
`share_equivalent_b` / `anchor_price` + `anchor_date` / `source`（写明来自哪个文件哪一节）。
`target_market_cap_b` 与 `target_price_3y` 由前面几项算出，不要手填不一致的值。

**两道闸门**：

| 闸门 | 位置 | 行为 |
|---|---|---|
| accept 时 | `dossier_orchestrator.py accept`，批次含 07 时触发 | 打印缺口告警，**不阻断 accept** |
| 每日构建 | `daily_pipeline.bat` [6/8] | 跑 `validate_three_year_coverage.py`，缺口写进 `last_run.log`，**不阻断发布** |

两道都只告警不阻断——缺口不该拦住当天发布，但必须每天可见。确实暂时补不了的，写进
`three_year_coverage_waivers.json` 并说明原因；补完后把豁免条目删掉。

需要硬失败时（例如 CI 或人工巡检）：`python _system/scripts/validate_three_year_coverage.py --strict`。


---

## 「低估 + 增长」策略模拟盘（`_system/paper_portfolio/`，2026-09-30 起）

一个与真实账户完全独立的纸面组合，用来检验"价格短期被低估、业务长期有增长"这条策略
在本系统数据上的实际战绩。引擎：`_system/scripts/paper_portfolio.py`，只用标准库，
每日由 `daily_pipeline.bat` [3/8] 自动跑（放在行情校验闸门之前，行情拉取失败当天也照常记账）；也可手动 `python _system/scripts/paper_portfolio.py`。

**选股池**：`valuation_registry.json` 里有三情景价 + 主导情景判定的公司。

**入选**（四条同时满足）：主导情景 = 基准；现价→基准价上行 ≥ 25%；现价跌到悲观价的空间 ≤ 30%
（"便宜"＝离地板近）；三年目标价年化 ≥ 15%（来自 `three_year_valuation_registry.json`）。
行情超过 7 天未更新的票不交易。

**仓位**：入选标的等权，每票 = min(80% / N, 15%)，其余现金（`sizing` 可改为 `risk_reward`，按上行/下行比加权）。
不用概率、不用 Kelly。

**调仓**：每天重算；|目标 − 当前| > 3 个百分点才交易。持仓退出用迟滞线（上行 < 10% 或三年年化 < 12%
或主导情景切换），避免在门槛附近来回抖。成交价 = 当日收盘 × (1 ± 0.1%)，A/H 股 100 股整手，
汇率为 `config.json` 里的常数（`fx_to_usd`，每月核一次）。

**产出**：`state.json`（持仓/现金）、`ledger.csv`（每笔成交 + 触发规则）、`nav_history.csv`（净值 vs SPX）、
`daily/{date}.json`（全池评估快照，含每票未入选原因）、`dashboard.html`（净值曲线 / 持仓 / 候选池 / 成交）。

**改参数**：编辑 `config.json`（门槛、仓位上限、汇率、排除名单）。**重来**：`--init`（清空历史）。
**同日重跑**是幂等的（覆盖当日记录）。**只看不写**：`--dry-run`。

已知局限：汇率是常数；成交按收盘价，无冲击成本；基准只有 SPX，没有按 A/H 仓位混合；
门槛附近的票（如三年年化 14.99%）会被卡在外面，这是刻意的——门槛不做人工微调。
