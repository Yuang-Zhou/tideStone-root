# briefing_data.json — Schema v2

## 现行字段（2026-10-09 整理；与下文旧说明冲突时以本节为准）

下文 v1/v2 说明里的 `signals[]`、`trigger_stats`、T1–T7 触发器已废止。当前每日数据文件的实际结构：

- 顶层：`version`(1)、`date`、`weekday`、`scan_time`、`data_status`、`market_pulse`、`actions[]`、`events[]`、`valuation_review[]`、`companies[]`、`catalysts[]`、`calendar[]`、`signal_stats`、`trace`。
- `data_status`：`us_equity / hk_equity / a_share`（各市场数据日期）、`manifest_generated_at`、`signals_source`、`validation_verdict`、`missing[]`、`data_note`、`scan_list`（`{scanned, skipped_inactive[], missing_in_valuation_registry[]}`）、`path_errors[]`（`{ticker, expected_path, reason}`）、`publish_health`（`{status: ok|stale|failed|broken, last_run, stale_days, failed_step, note}`）、`news_coverage`（`{primary_source, websearch_calls, fallback_checked[], degraded[], note}`）、`escalation_policy`（`{escalated_total, full_ta_run[], deferred[], reason}`）、`catalyst_write_log[]`（`{ticker, events_appended, metadata_updated}`）。
- `market_pulse`：`key_metrics[]`（`{name, value, change, asof}`，6–7 个）、`headline`、`risk_note`。
- `actions[]`：3–7 条，`{ticker, name, type: trim|buy|hold|watch, verb, priority: 1-3, desc}`，`desc` 不超过 80 字。
- `events[]`：当日全部 高/中 事件，一条一项：`{id（如 "NVDA-2026-10-09-1"，当日唯一）, ticker, level: 高|中, verified: true|false（是否读到正文或公告）, title（与简报卡片标题、催化剂文件 #### 标题一字不差）, in_briefing: true|false（因超 50KB 被移出简报时为 false）}`；无事件时为空数组。
- `valuation_review[]`：`{ticker, name_cn, verdict: now|wait|stale, criteria: [1-4], reason, wait_for, price, target_price}`；`wait` 必须填 `wait_for`；无点名时为空数组。
- `companies[]`：一家一项，顺序同注册表。
  - `ticker`、`name_cn`、`name_en`、`rating`、`target_price`（后两项每天取自 `valuation_registry.json`）。
  - `snapshot`：`price`、`change_pct`、`ma60`、`macd`（如「零上多头 H+0.6201」）、`rsi`、`vol_ratio`、`support`、`resistance`、`valuation_zone`（只能是 买入区 / 持有区 / 减持区 / 卖出区 / 未标定）。
  - `technical`：信号引擎对该股票的完整输出，原样放入（`trend_posture`、`direction`、`strength`、`counter_trend`、`conflict`、`confluence{bull,bear}`、`families{trend,momentum,oscillator,breakout}`、`indicators`、`structure`、`escalate_full_ta`、`prev_close`、`change_pct`）。
  - `news_bullets[]`：每条以「高：/ 中：/ 低：」开头；没读到正文的在级别后加「（待确认）」，如「高（待确认）：」。高/中 条数必须和该公司在 `events[]` 里的条数相同。
  - `catalysts_summary`、`action_line`、`action_detail`。
  - `links`：`ta_report`（无则 null）、`catalyst_tracker`、`stock_character`。
- `catalysts[]`：`{ticker, label, name, date, bucket: today|this_week|next_week|this_month|q3|q4_plus|open, priority}`。
- `calendar[]`：`{ticker, label, event, date}`，日期未定时 `date` 为 null。
- `signal_stats`：`{buy[], sell[], neutral[], strong[], escalated[], counter_trend[], conflict[]}`，元素为 ticker。
- `trace`：`{skill_version, duration_sec, ta_reports_generated[], catalyst_files_touched[]}`。

---

**v2 变更（2026-05-14 引入）：** 顶层新增 `dossiers` 字段（来自 `dossier_orchestrator.py briefing-snippet`）；`companies[i]` 新增可选 `dossier` 子对象。v1 数据仍能被新看板渲染（缺失字段当 null 处理）。

**契约（不可破坏）：**

1. 每个交易日的自动化任务**必须**产出三件东西：
   - `_system/daily_briefing/briefing_data_{YYYY-MM-DD}.json` — 完整结构化数据
   - `_system/daily_briefing/{YYYY-MM-DD}_daily_briefing.md` — 短格式可读 markdown，**严格 ≤ 50KB**（2026-09-15 起；此前 5KB→8KB→20KB）
   - **重新渲染并发布** `portfolio-daily-dashboard` artifact（通过 `render_dashboard.py` + `update_artifact`）
2. 历史文件**绝不**修改。当日发现错误时，**只覆盖当日的 JSON 和 markdown**（artifact 会被重新渲染覆盖），不动昨日及更早的文件。
3. JSON 顶层 `version` 字段标识 schema 版本。增加字段不破坏老看板（forward-compatible）；删除字段或语义变更必须升 version。
4. **看板 artifact 内嵌最近 7 天 JSON**（由 `render_dashboard.py` 在每日任务里完成）。Cowork artifact 沙箱不能调用 `mcp__workspace__bash` 等本地文件读取工具，所以采用内嵌模式而非现读模式。
5. **看板 UI 模板** `dashboard_template.html` 与 `render_dashboard.py` 一同保存在 `_system/daily_briefing/`。修改 UI 时只改模板；模板里用 `__WINDOW_DATA__` / `__DEFAULT_DATE__` / `__RENDERED_AT__` 三个占位符。

---

## JSON Schema (version 1)

```json
{
  "version": 1,
  "date": "2026-05-13",
  "weekday": "周三",
  "scan_time": "2026-05-13 09:09 +08:00",
  "data_status": {
    "us_equity": "2026-05-12",
    "hk_equity": "2026-05-12",
    "a_share": "2026-05-12",
    "missing": ["V"],
    "note": "可选；说明数据完整性"
  },
  "market_pulse": {
    "key_metrics": [
      { "label": "CPI YoY", "value": "+3.8%", "trend": "down", "note": "近 3 年最高" },
      { "label": "10Y", "value": "4.46%", "trend": "down", "note": "1 年新高" },
      { "label": "SPX", "value": "7400.96", "change_pct": -0.16 },
      { "label": "NDX", "value": "29064.80", "change_pct": -0.42 },
      { "label": "CSI300", "value": "4948.05" },
      { "label": "HSI", "value": "26406.84" }
    ],
    "headline": "高 P/S 标的全线承压；6 月降息预期被压缩",
    "risk_note": "可选；一句话风险提示"
  },
  "actions": [
    {
      "ticker": "RKLB",
      "type": "trim",
      "verb": "分批兑现 40%",
      "desc": "三重高位信号 T2+T5+T6；第一批 $115-120",
      "priority": 1
    }
  ],
  "companies": [
    {
      "ticker": "RKLB",
      "name": "Rocket Lab",
      "rating": "持有",
      "sector": "航空航天",
      "snapshot": {
        "price": 117.35,
        "ccy": "$",
        "change_pct": 0.2,
        "ma60": "↑ +58%",
        "macd": "多头排列 H5.48",
        "rsi": 68.1,
        "vol_ratio": 2.45,
        "support": 105.47,
        "resistance": 121.49,
        "valuation_zone": "卖"
      },
      "signals": ["T2","T5","T6"],
      "news_bullets": ["..."],
      "catalysts_summary": "P0 Neutron Q4 / Backlog $2.2B",
      "action_line": "本周强烈分批兑现 50-70%",
      "action_detail": "...完整多情景建议...",
      "links": {
        "ta_report": "../../3. 航空航天/Rocket Lab (RKLB.O)/技术分析/RKLB_技术分析_20260513.md",
        "folder": "../../3. 航空航天/Rocket Lab (RKLB.O)",
        "stock_character": null,
        "valuation": null
      }
    }
  ],
  "catalysts": [
    {
      "date_display": "5/13 BMO",
      "bucket": "today",
      "ticker": "NBIS",
      "desc": "Q1 2026 财报 + 8:00 ET call (ARR / Meta / CapEx)",
      "priority": "P0"
    }
  ],
  "calendar": [
    { "date": "5/13 (今日)", "events": "NBIS Q1 · BABA Q4 · PPI", "imp": 5, "is_today": true }
  ],
  "trigger_stats": {
    "T1": ["DUOL","CRM","PDD","TCOM","ISSC","300054.SZ","9992.HK","TEM","3690.HK"],
    "T2": ["3317.HK","RKLB","GRAL","300054.SZ","PLTR"],
    "T3": ["DUOL","TSLA"],
    "T4": ["BA","CRM","DUOL","NVDA","CACI"],
    "T5": ["RKLB","RDW"],
    "T6": ["RKLB","ASTS","RDW"],
    "T7_near": ["GOOGL","DOCN","META"]
  },
  "trace": {
    "skill_version": "phase2-v1",
    "generated_by": "daily-portfolio-scanner",
    "duration_sec": 142,
    "fundamental_events_count": 11,
    "ta_reports_generated": ["RKLB","ASTS","TSLA","GRAL","PLTR","3690.HK"]
  },

  "dossiers": {
    "summary": {
      "total": 35,
      "complete": 23,
      "partial": 9,
      "empty": 3,
      "stale": 0,
      "pending_review": 1,
      "not_initialized": 3
    },
    "pending_review": [
      {
        "ticker": "V",
        "name": "Visa Inc.",
        "sector": "1. SaaS软件",
        "batch_ts": "2026-05-14T02-41-46Z",
        "trigger": "initiation",
        "headline": "V 待审档案 — 2026-05-14T02-41-46Z",
        "diff_summary_path": "1. SaaS软件/Visa (V.N)/研究档案/_pending/2026-05-14T02-41-46Z/_diff_summary.md"
      }
    ],
    "stale": [
      { "ticker": "X", "name": "...", "max_age_days": 180, "stale_slots": ["02_财务分析.md"] }
    ],
    "partial": [
      { "ticker": "PLTR", "name": "Palantir", "sector": "1. SaaS软件", "missing_slots": ["01_企业文化.md","03_商业模式.md"], "exists_count": 3 }
    ],
    "stale_threshold_days": 120,
    "generated_at": "2026-05-14T02:58:43+00:00"
  }
}
```

每个 `companies[i]` 还可附加可选的 `dossier` 子对象（来源同 `briefing-snippet` 的 `companies_dossier[ticker]`）：

```json
{
  "ticker": "V",
  "name": "Visa",
  "...": "...",
  "dossier": {
    "initialized": true,
    "exists_count": 1,
    "max_age_days": 1,
    "slot_status": ".+...",
    "has_pending": true,
    "pending_batch_ts": "2026-05-14T02-41-46Z",
    "pending_trigger": "initiation",
    "stale_slots": [],
    "dossier_path": "1. SaaS软件/Visa (V.N)/研究档案"
  }
}
```

**`slot_status` 字符串规则（5 字符，对应 01-05 五份档案）：**
- `+` 已审批通过 + 未过期
- `~` 已审批通过但超过 `stale_threshold_days` (默认 120 天)
- `.` 缺失（未生成）
- `!` 子 skill 跑过但失败
- `?` 状态不明（v1 数据没有 _meta.json）

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `version` | int | ✓ | Schema 版本号，目前为 1 |
| `date` | string `YYYY-MM-DD` | ✓ | 简报日期 |
| `weekday` | string | ✓ | 中文星期 |
| `scan_time` | string ISO+TZ | ✓ | 实际扫描完成时间 |
| `data_status.{market}` | string `YYYY-MM-DD` | ✓ | 各市场行情数据最新日期 |
| `data_status.missing` | string[] | | 数据缺失的 ticker 列表 |
| `market_pulse.key_metrics[]` | array | ✓ | 顶部市场指标行 |
| `market_pulse.headline` | string | ✓ | 一句话本日特点 |
| `actions[]` | array | ✓ | 今日动作卡片；3-7 张为宜 |
| `actions[].type` | enum | ✓ | `trim` / `buy` / `hold` / `watch` |
| `actions[].priority` | int 1-3 | ✓ | 1=最高，决定排序 |
| `companies[]` | array | ✓ | 所有 active 公司，一家一项 |
| `companies[].signals[]` | string[] | ✓ | `T1`..`T7` 数组，空数组表示无触发 |
| `companies[].snapshot.valuation_zone` | enum | ✓ | `买` / `持` / `卖` / `中` |
| `companies[].links.ta_report` | string\|null | | 当日 TA 报告相对路径，无则 null |
| `catalysts[].bucket` | enum | ✓ | `today` / `this_week` / `next_week` / `this_month` / `q3` / `q4_plus` / `open` |
| `catalysts[].priority` | enum | ✓ | `P0` / `P1` / `P2` / `Macro` |
| `trigger_stats.{Tn}` | string[] | | 命中该触发条件的 ticker 列表 |
| `dossiers.summary` | object | v2 | 35 家公司各档案状态分布的聚合 |
| `dossiers.pending_review[]` | array | v2 | 当前有 `_pending/{ts}/` 等待人工审核的批次 |
| `dossiers.stale[]` | array | v2 | 任一档案超过 `stale_threshold_days` 的公司 |
| `dossiers.partial[]` | array | v2 | 已初始化但未集齐 5 份档案的公司 |
| `companies[].dossier` | object | v2 | 该公司档案状态摘要（来自 `briefing-snippet`） |

### 信号字典

| 信号 | 含义 |
|---|---|
| T1 | 买入预警：价 ≤ 买入区上限 且 技术非空头 |
| T2 | 卖出预警：价 ≥ 卖出区下限 且 技术非多头 |
| T3 | MA20×MA60 近 3 日金叉 / 死叉 |
| T4 | MACD 近 10 日顶背离 / 底背离 |
| T5 | 突破 30 日支撑/阻力 + 量能比 > 1.5 |
| T6 | 量能比 > 2.0 |
| T7 | RSI ≥ 85 或 ≤ 25（极端） |

### 时间桶判定

`scan_time` 当天为 D。各 bucket 边界（动态）：
- `today` = D
- `this_week` = (D, D+7d]
- `next_week` = (D+7d, D+14d]
- `this_month` = D 月内剩余天数（去除 this_week / next_week 已覆盖部分）
- `q3` = Jun-Sep（D 不在此区间内则统一桶 q3）
- `q4_plus` = Oct+
- `open` = 触发条件型 / 无明确日期

每日重新生成时根据 D 重新分桶。历史 JSON 的 bucket 字段反映**生成那天的视角**——回看时桶可能与当下不一致，这是预期行为（你看 5/1 那天的 JSON，"本周"指的就是 5/1 周）。

---

## 短 Markdown 模板

```markdown
# 投资组合每日简报 — {date} {weekday}

**扫描:** {scan_time} · {company_count} 家组合 · 数据 {data_status_summary}

---

## 市场脉搏

{metric1} | {metric2} | ... | {metricN}
> {headline}

## 🎯 今日动作（{action_count}）

- {verb_icon} **{ticker}** {verb} — {desc}
- ...

## 📅 今日要闻

- {today_catalyst_1}
- {today_catalyst_2}
- ...

## 触发统计

T1×{N1} {ticker_list} · T2×{N2} {ticker_list} · T3-T7×{N3} · RSI 极端：{near_t7}

## ⚠️ 风险提示

{one_line_risk_note}

---

📊 **完整看板：** Cowork artifact `portfolio-daily-dashboard`
📁 **结构化数据：** `briefing_data_{date}.json`
📜 **历史简报：** `_system/daily_briefing/{YYYY-MM-DD}_daily_briefing.md`

*由 daily-portfolio-scanner v{skill_version} 自动生成于 {scan_time}。*
```

**长度限制：≤ 5KB**。如果超出，砍 actions 描述、砍 catalyst 数量，永远不砍触发统计和动作清单。

---

## 历史档案

- **2026-04-15 至 2026-05-13 的 26 份长 markdown**：旧格式（49KB 级别），原地保留，**绝不动**。看板按日期选择器选这些日期时显示"📜 legacy mode"。
- **2026-05-14 起**：每日双产物（JSON + 短 markdown）。
