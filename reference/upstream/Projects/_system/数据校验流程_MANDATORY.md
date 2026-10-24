# 每日扫描数据校验流程（强制性，每日扫描必须执行）

**版本：** v2.0（2026-06-11 重构：清单驱动；v1.1 2026-06-10；v1.0 2026-05-13 创建）
**触发器：** 每日扫描任务（daily-portfolio-scanner）启动后**第一件事**

---


## ⚠️ 云端运行时的做法（2026-10-09 补；每日扫描现在走这一节）

每日扫描任务现在跑在云端，通过 `device_bash` 在用户电脑上的 Linux 虚拟机里读写 Projects 文件夹。**云端的 Read 工具读不到这些文件**，所以下文所有「用 Read 工具读」「比对 Read 视角和 bash 视角」的步骤在这个环境里做不了，按本节执行：

1. `device_bash` 里读 `_system/market_data/_data_status.json`：`generated_at` 必须是今天，否则按数据过期处理。
2. `device_bash` 里跑 `python3 _system/scripts/validate_market_data.py`，取末行 `VALIDATION_JSON`。它逐只比对清单的 `last_row` 和 CSV 尾行，这是这个环境里唯一能做的缓存检查。
   - `PASS`：直接用 CSV。
   - `BASH_CACHE_STALE`：对 `bash_older[]` 里的 ticker，用清单的 `tickers.{T}.last_row` 作为 `last_row_override` 传给 `compute_signals.compute_for_ticker`。
   - `DATA_NOT_TODAY` / `MANIFEST_MISSING`：数据过期。沿用最近一份可用数据出简报，在风险提示里写明各市场数据停在哪天，并发推送。
3. 只有一个读取视角，没法像下文那样双视角交叉验证。作为替代：`_data_status.json` 的 `generated_at` 和 `_signals_status.json` 的 `source_manifest_generated_at` 对不上时，逐只比对两边的收盘价，有任何一只不一致就不用信号文件，自己算。
4. 自己算出的信号存成 `_system/market_data/_signals_scanner_{date}.json`（结构 `{"signals": {ticker: {...}}}`），后面生成技术分析报告时用 `gen_ta_report.py --signals` 指向它，保证简报和报告用的是同一批信号。
5. 注册表截断检查：`validate_market_data.py` 输出的 `registry_bash.lines / bytes` 和 `wc -l / wc -c` 的结果对一下，再看文件末行是不是完整的一行。对不上就在扫描日志里记录，并在最终回复里提醒。

下文保留原样，供桌面会话（有 Read 工具时）和排查历史问题使用。

---

## 一、为什么必须有这个文档

bash sandbox 的 FUSE 挂载层会缓存陈旧文件快照——bash/pandas 读到的可能是旧数据，而 Read 工具看到的是磁盘真实状态。已发生三次实际误判：

| 日期 | 事件 |
|:---|:---|
| 2026-05-13 | 300054.SZ / 688362.SH / ASTS 等多 ticker 信号基于陈旧 CSV 误判（T1/T2 全错） |
| 2026-06-03 | bash 读到截断的 June 2 行，全部技术信号基于 June 1 计算，简报重发 |
| 2026-06-10 | bash 读 portfolio_registry.md 在 ~912 行处截断，601872.SH / 300750.SZ 被误报"研究中/估值待定" |

**v2.0 核心变化：** fetcher 在**宿主机**（不经过 FUSE）写入权威清单 `_system/market_data/_data_status.json`，内含每个 ticker 的 `last_date` + **最后一行完整 OHLCV**。从此：

1. 数据时效判定 = Read 工具读**一个**清单文件（不再逐个 Read 40+ 份 CSV）
2. bash 缓存是否可信 = 跑一次 `validate_market_data.py` 机器判定（不再人工抽 3 只 ticker 交叉对比）
3. `LAST_ROW_OVERRIDE` 直接从清单的 `last_row` 字段构建（数据已带 OHLCV，无需再读 CSV）

---

## 二、Step 0 强制预检（先于其他所有步骤）

### 步骤 0.1：Read 工具读权威清单（必做，1 次 Read）

```
Read: _system/market_data/_data_status.json
```

得到（这是**唯一可信**的数据时效事实源）：
- `generated_at` — 清单生成时间。**日期部分必须是今天**，否则 = 今早 fetch 未跑/失败，按"数据严重过期"处理（检查宿主机任务计划，必要时提示用户手动跑 fetcher）
- `markets.{US,HK,CN}.max_last_date` — 各市场最新交易日（直接写进简报"数据校验"行）
- `tickers.{TICKER}.last_row` — 每 ticker 最后一行 OHLCV → 直接构建 `LAST_ROW_OVERRIDE`
- `failures[]` — fetch 失败清单 → 写入 JSON `data_status.missing[]`

**清单缺失/损坏时**（旧数据迁移期或宿主机 fetcher 未升级）：退回附录 A 手动流程，并提示用户跑 `py -3.11 _system/scripts/market_data_fetcher.py --manifest-only` 补建。

### 步骤 0.2：bash 跑机器校验（必做，1 次 bash）

```bash
cd /sessions/*/mnt/Projects && python3 _system/scripts/validate_market_data.py
```

脚本对比清单与 bash/FUSE 视角的全部 CSV 尾行，最后一行输出 `VALIDATION_JSON: {...}`：

| verdict | 含义 | 行动 |
|:---|:---|:---|
| `PASS` | bash 视角与清单完全一致 | bash 可直接跑 pandas 全流程，无需 override |
| `BASH_CACHE_STALE` | bash 落后于清单（`bash_older[]` 列出受影响 ticker） | 对受影响 ticker 注入 `LAST_ROW_OVERRIDE`（数据取自 0.1 的清单）；若受影响 > 1/3 → 整体切 /tmp 工作流（附录 A 方法 A） |
| `DATA_NOT_TODAY` | 清单不是今天生成的 | 同 0.1 的 fetch 失败处理 |
| `MANIFEST_MISSING` | 清单不存在 | 附录 A 手动流程 |

**额外一致性检查（防清单本身被 FUSE 缓存）：** 比对 0.1（Read 视角）与 0.2 脚本输出（bash 视角）的 `manifest_generated_at`。**两者不一致 = 连清单都被缓存了 = 一律按 BASH_CACHE_STALE 处理**，以 Read 视角的清单为准。

### 步骤 0.2b：注册表截断检查（必做）

背景：2026-06-10 事件，bash 读 `portfolio_registry.md` 尾部被 FUSE 截断。

1. 0.2 脚本输出里有 `registry_bash`（bash 视角的行数 / md5 / 末行前 80 字符）
2. 用 Read 工具读注册表**最后 ~10 行**（offset ≈ registry_bash.lines - 10）
3. Read 读到的末行与 `registry_bash.last_line_head` 一致 → bash 可解析注册表；**不一致 / Read 能读到更多行 → 截断确认**，解析注册表必须改用：Read 工具分段读全文 → Write 到 `/tmp/registry_fresh.md` → bash 解析 /tmp 文件
4. 发布前铁律不变：任何被标"研究中/待定/—"的公司，必须 Read 工具核对注册表条目与 `研究档案/`，排除截断读漏

### 步骤 0.3：校验结果记入简报顶部（必做）

```markdown
**数据校验：** ✅ PASS（清单 2026-06-11 08:56 生成；US=6/10 HK=6/10 CN=6/10；49/49 一致）
```

或

```markdown
**数据校验：** ⚠️ BASH_CACHE_STALE（3 ticker bash 偏旧：300054.SZ 等）；已注入 LAST_ROW_OVERRIDE，信号基于清单真实数据
```

---

## 三、其他常见数据陷阱（保留）

### 陷阱 1：fetch_log 显示"成功"≠ bash 能看到新行
fetch_log / 清单反映宿主机写入视角；bash 看不到是缓存问题。判定一律以 Step 0.1 + 0.2 为准。

### 陷阱 2：`dropna(subset=["close"])` 的副作用
缓存陈旧时 dropna 会掩盖问题。先过 Step 0，再决定是否 dropna。

### 陷阱 3：HSI 等单一指数偶尔停 1 天
不触发整体警报，但简报需标注（清单 `indices` 字段可直接看出）。

### 陷阱 4：触发关键信号的 ticker 必须 spot-check
对命中 T1/T2 且当日波动 > 5% 的 ticker，发布前用清单 `last_row.close` 与简报报价二次核对。

### 陷阱 5：注册表尾部截断（详见 Step 0.2b）
判定"某公司是否有条目/评级/估值区间"只信 Read 工具，不信 bash。

---

## 四、对简报的强制要求（不变）

1. "扫描时间"行附近：数据校验结果（Step 0.3 输出）
2. 附录前：当日收盘价表（与清单 `last_row.close` 一致）
3. 附录末：触发条件命中统计 + 数据状态说明

**简报中任何信号判定的"当前价"与清单 `last_row.close` 不一致，必须立即修正。**

---

## 五、Checklist（每日扫描启动后照单执行）

- [ ] **Step 0.1** Read 清单 `_data_status.json`：generated_at 是今天；记录各市场 max_last_date；从 last_row 构建 LAST_ROW_OVERRIDE 备用
- [ ] **Step 0.2** bash 跑 `validate_market_data.py`，按 verdict 行动；比对两个视角的 generated_at
- [ ] **Step 0.2b** 注册表截断检查（registry_bash vs Read 尾部）
- [ ] **Step 0.3** 校验结果记入简报顶部
- [ ] **Step 1** 读取 portfolio_registry.md（解析方式按 0.2b 结论）
- [ ] **Step 2** 基本面新闻扫描
- [ ] **Step 3** 技术面脉搏计算（PASS→直接 pandas；STALE→注入 override）
- [ ] **Step 4** Pulse 完成后 spot-check：抽 2-3 只 ticker，pandas 算出的 last_date/close vs 清单一致
- [ ] **Step 5** T1-T6 触发名生成完整 TA 报告
- [ ] **Step 6** 输出简报（含数据校验段、收盘价表、触发统计）
- [ ] **Step 7** 更新催化剂跟踪 + 写当日 scan_log（见 `_system/scan_log/README.md`）
- [ ] **Step 8** 最终自检：触发信号 ticker 的简报报价 = 清单 last_row.close；"研究中/待定"公司排除截断读漏

**任何一步发现数据不一致都必须停下来修正，不能"先发出来再说"。**

---

## 附录 A：手动双工具交叉验证（退化流程，仅清单不可用时）

> v1.1 的原流程，保留作兜底。

**A.1 双工具交叉验证：** 选 3 只代表性 ticker（1 美股 + 1 港股 + 1 A 股，A 股最易出问题），分别用 Read 工具和 bash `tail -1` 读 CSV 最后一行比对。Read 比 bash 新 = 缓存陈旧。

**A.2 缓存陈旧时的工作流（三选一）：**
- **方法 A（最稳妥）：** Read 读 CSV 全文 → Write 到 `/tmp/csv_fresh/{ticker}.csv` → bash/pandas 处理 /tmp 路径（/tmp 是 sandbox 本地盘，不走 FUSE）
- **方法 B：** Read 读尾部 ~260 行，inline 喂给 `pandas.read_csv(io.StringIO(...))`
- **方法 C：** pulse 跑完后 Read spot-check 2-3 只 ticker 最新日期，不一致则整个 pulse 作废重跑

---

## 六、变更日志

| 日期 | 版本 | 说明 |
|:---|:---|:---|
| 2026-05-13 | v1.0 | 因当日误判事件创建。根因：bash FUSE 缓存陈旧。 |
| 2026-06-10 | v1.1 | 因 601872.SH/300750.SZ 误判，新增注册表尾部截断检查（Step 0.2b + 陷阱 6）。 |
| 2026-06-11 | v2.0 | **清单驱动重构**：fetcher 宿主机写 `_data_status.json`（权威 data_as_of + 每 ticker last_row OHLCV）；新增 `validate_market_data.py` 机器校验。Step 0 从"人工多文件交叉验证"收敛为"1 次 Read + 1 次 bash + 1 个比对"。LAST_ROW_OVERRIDE 数据源改为清单，不再逐个 Read CSV。旧手动流程降级为附录 A 兜底。 |

---

**本文档为强制性流程，每日扫描任务必须遵守。**
