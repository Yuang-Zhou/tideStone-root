# {COMPANY_NAME}（{TICKER}）催化剂跟踪

**最后自动扫描：** {SCAN_DATE}
**当前股价：** {CURRENT_PRICE} {CURRENCY}
**估值区间定位：** {ZONE}（买入区/持有区/卖出区/强烈卖出区）
**加权目标价：** {TARGET_PRICE} {CURRENCY}
**投资评级：** {RATING}

---

## 催化剂状态总览

| # | 优先级 | 催化剂 | 状态 | 预计时间 | 最新进展 |
|---|--------|--------|------|---------|---------|
| 1 | P0 | {catalyst_1} | 待验证 | {date} | {update} |
| 2 | P0 | {catalyst_2} | 待验证 | {date} | {update} |
| 3 | P1 | {catalyst_3} | 待验证 | {date} | {update} |
| 4 | P1 | {catalyst_4} | 待验证 | {date} | {update} |
| 5 | P2 | {catalyst_5} | 待验证 | {date} | {update} |

**状态说明：** 待验证 / 进行中 / 已确认(正面) / 已确认(负面) / 已过期

---

## 事件日志

### {SCAN_DATE}
**来源：** 自动扫描
**发现事件：** {event_count}条

#### 重要事件
> {event_summary}

#### 对估值的影响
- **方向：** {up/down/neutral}
- **是否触发估值修订：** {yes/no}
- **建议操作：** {action}

---

## 估值变动记录

| 日期 | 触发事件 | 变动前 | 变动后 | 说明 |
|------|---------|-------|-------|------|
| {date} | 初始建立 | — | {target_price} | 基于完整研究框架 |

---

## 下一跟踪节点

| 时间 | 事件 | 预期影响 |
|------|------|---------|
| {next_date} | {next_event} | {expected_impact} |

---

*本文件由自动化投资跟踪系统维护，结合人工研究判断使用。*

