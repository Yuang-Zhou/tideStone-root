# 信号搬宿主机 — 部署与对账清单（阶段 0–2）

**目的：** 把每日扫描的「技术信号计算」从 Cowork 沙箱 bash 搬到 **Windows 宿主机**，
彻底规避 bash/FUSE 缓存「陈旧 / 截断 / 夹 NUL」导致的反复返工。

**核心安全保证（务必先看）**
- 本方案**只新增** `_system/host_pipeline/` 这一个目录里的文件，**不修改**任何现有脚本、数据、注册表，**不删除**任何文件。
- `compute_signals.py / market_data_fetcher.py / render_dashboard.py / 每日自动更新.bat` 一个字节都没动——`host_signals.py` 只是 `import` 引擎来用。
- 新增的计划任务是**独立**的；**停用/删除它 = 立刻回到现状**，其余流程照常。
- 现在处于**阶段 1（影子运行）**：宿主机多产出一个 `_signals_status.json`，Agent 暂时**不读它**，行为零变化。确认连续几天数据一致后，再做阶段 2 的切换。

---

## 文件清单（本目录）

| 文件 | 作用 |
|:---|:---|
| `host_signals.py` | 宿主机计算全部技术信号，产出 `_system/market_data/_signals_status.json` |
| `跑信号.bat` | 供任务计划程序调用 `host_signals.py`，结果写 `host_signals_last_run.log` |
| `README_部署与对账.md` | 本文件 |
| `host_signals_last_run.log` | 每次运行的日志（自动生成） |

**产物：** `_system/market_data/_signals_status.json`
含 `generated_at`、`counts`、`signal_stats`（buy/sell/neutral/strong/escalated/counter_trend/conflict）、
每只 `signals[ticker]`（四族投票完整 dict + `change_pct` + `prev_close`）、`failures[]`。
ticker 全集自动取自 `_data_status.json`（**增删公司自动同步，无硬编码列表**）。

---

## 前置检查（一次性）

宿主机 PowerShell 里跑，三项都要过：

```powershell
py -3.11 --version
py -3.11 -m pip show pandas numpy | Select-String "Name|Version"
cd C:\Users\dbao0\Documents\Claude\Projects\_system\host_pipeline
py -3.11 host_signals.py
```

第三条应看到一串 `- TICKER  买入/中 …`，并以
`[host_signals] wrote _signals_status.json: computed=NN failed=0 …` 结尾。
（前提：当天 `Market_Data_Fetcher` 已跑过、`_data_status.json` 是今天的。）

> 若提示缺包：`py -3.11 -m pip install pandas numpy`（fetcher 已用 pandas，一般都在）。

---

## 阶段 1：建影子计划任务（taskschd.msc）

完全照 `Market_Data_Fetcher` 的套路，只是换程序、换时间。

1. **创建基本任务** → 名称 `Host_Signals`，描述「每日盘前在宿主机计算技术信号，产出 _signals_status.json」。
2. **触发器：** 每天 **08:45**（排在 fetcher 08:30 之后，给它留出拉数时间）。
3. **操作：** 启动程序
   - 程序或脚本：`C:\Users\dbao0\Documents\Claude\Projects\_system\host_pipeline\跑信号.bat`
   - 起始于：`C:\Users\dbao0\Documents\Claude\Projects\_system\host_pipeline`
4. **属性里精调**（同 fetcher）：
   - 常规：不管是否登录都运行 / 最高权限。
   - 条件：取消「仅交流电源」「切电池则停」；勾「唤醒计算机运行」。
   - 设置：勾「错过则尽快补跑」；勾「超过 30 分钟则停止」；「已在运行 → 不启动新实例」。
5. **右键「运行」测一次**，然后看：
   - 日志：`_system/host_pipeline/host_signals_last_run.log` 末尾 `exit code: 0`。
   - 产物：`_system/market_data/_signals_status.json` 的 `generated_at` 是今天。

退出码：`0`=全成功；`2`=个别 ticker 失败（看 `failures[]`，清单仍写出）；`1`=致命（清单缺失等）。

---

## 阶段 1：对账（连续 3–5 个交易日）

每天扫描跑完后，比对「宿主机算的」与「Agent 在简报里算的」是否一致。两边用的是同一个引擎、
同一份数据，**理应逐项相同**。在 PowerShell 跑：

> ⚠️ 两个 PowerShell 坑（都已在下方命令里规避）：
> 1. `$host` 是内置只读变量，不能用作变量名 → 用 `$hf` / `$bf`。
> 2. Windows PowerShell 5.1 的 `Get-Content` 默认按系统 GBK 解码，会把 UTF-8 的
>    `_signals_status.json` 读成乱码并导致 `ConvertFrom-Json` 报「应为":"或"}"」。
>    **文件本身没问题**，加 `-Encoding UTF8` 即可正确读取。

```powershell
$d = Get-Date -Format "yyyy-MM-dd"
$hf = "C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\_signals_status.json"
$bf = "C:\Users\dbao0\Documents\Claude\Projects\_system\daily_briefing\briefing_data_$d.json"
if (!(Test-Path $hf)) { Write-Host "❌ 还没有 _signals_status.json，先跑一次 跑信号.bat" -ForegroundColor Red; return }
$h = (Get-Content $hf -Raw -Encoding UTF8 | ConvertFrom-Json).signal_stats
Write-Host "host  buy/sell/neutral/escalated: $($h.buy.Count)/$($h.sell.Count)/$($h.neutral.Count)/$($h.escalated.Count)"
if (Test-Path $bf) {
  $b = (Get-Content $bf -Raw -Encoding UTF8 | ConvertFrom-Json).signal_stats
  Write-Host "brief buy/sell/neutral/escalated: $($b.buy.Count)/$($b.sell.Count)/$($b.neutral.Count)/$($b.escalated.Count)"
} else {
  Write-Host "ⓘ 今天($d)的简报还没生成，等扫描跑完再对账（host 这侧已就绪）" -ForegroundColor Yellow
}
```

两行数字一致 = 等价性确认。若不一致，多半是数据时效差异（fetcher 与扫描中间又拉了一次），
对一下两份文件的 `generated_at` / `source_manifest_generated_at` 即可解释。**对账期间不改任何东西。**

---

## 阶段 2：切换信号源 ✅ 已完成（2026-06-28）

> **状态：已上线。** 扫描技能（daily-portfolio-scanner SKILL）已通过 `update_scheduled_task`
> 加入 **Step 3a-0 优先路径** + **永久契约第 9 条**：每日先读 `_signals_status.json`，
> 可信（generated_at=今天 且 source_manifest_generated_at 对得上）就直接采用、跳过 bash；
> 不可信则自动退回 Step 3a-1/3a-2 的 bash 流程并在 scan_log 记原因。bash 兜底永久保留。
>
> **下次扫描验证：** 跑完后看 `scan_log/{date}.md` 是否出现"技术信号采用宿主机
> `_signals_status.json`"。若反而出现"已回退 bash"，说明当天宿主机任务没赶在扫描前跑完，
> 查 `Host_Signals` 是否 08:45 正常执行。
>
> **回滚：** SKILL 在受保护目录、文件工具改不动，回滚需让 Claude 用 `update_scheduled_task`
> 把 prompt 改回"无第 9 条 / 无 Step 3a-0"的旧版（旧版全文 Claude 处留有备份）。
> 或更省事：停用 `Host_Signals` 任务——`_signals_status.json` 不再更新→次日起判定"不是今天"
> →扫描自动走 bash 兜底，等效回滚，且不动 SKILL。

<details><summary>（存档）阶段 2 当初的改法说明</summary>

把扫描技能（daily-portfolio-scanner SKILL）的 **Step 3** 改成：

> **优先**用 Read 工具读 `_system/market_data/_signals_status.json`：
> 若其 `generated_at` 是今天且 `source_manifest_generated_at` 与 `_data_status.json` 一致 →
> 直接采用其中的 `signals` 与 `signal_stats`，**跳过 bash 跑 compute_signals**。
> 否则（文件缺失 / 不是今天 / 来源对不上）→ **自动退回**现有 bash 计算流程（清单 override 那套）。

要点：
- 这一步**只改 SKILL 文字**，不动代码；反悔把文字改回去即可。
- **保留 bash 兜底**——宿主机任务哪天没跑，扫描仍能自给自足，不会断。
- 从此正常日子 Agent 不再在 bash 里碰 CSV/pandas，FUSE 顽疾对「信号」这条线失效。

> 阶段 3（看板渲染搬宿主机）暂不做，待阶段 2 稳定后另议。

</details>

> 阶段 3（看板渲染搬宿主机）暂不做，待阶段 2 稳定后另议。

---

## 回滚（任何阶段都适用）

1. 任务计划程序里**停用或删除** `Host_Signals` 任务 → 宿主机不再产出 `_signals_status.json`。
2. （阶段 2 若已切）把 SKILL 的 Step 3 文字改回原样 → Agent 回到纯 bash 计算。
3. 可选：删除 `_system/host_pipeline/` 整个目录。

以上任一步都不影响 fetcher、扫描、建站推送等现有流程——它们从头到尾没被改过。
