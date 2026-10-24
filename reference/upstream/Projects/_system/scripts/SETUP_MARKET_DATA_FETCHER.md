# 市场数据自动拉取 — Windows 任务计划程序配置指南

每日 **08:30** 自动跑 `market_data_fetcher.py`，从 yfinance + akshare 拉取投资组合 + 指数的 OHLCV 数据，存到 `_system/market_data/`，供后续 Host_Signals（08:45）和 daily-portfolio-scanner（09:09）使用。

本文档记录如何首次部署。**整个过程只需配置一次。**

---

## 前置条件检查（按顺序）

### ✅ 1. Python 3.11 已安装（路径：`C:\Python311`）

验证：
```powershell
py -3.11 --version
```
应输出 `Python 3.11.9`（或更高 3.11.x）。

### ✅ 2. 依赖包已装好

验证：
```powershell
py -3.11 -m pip show yfinance akshare pandas | Select-String "Name|Version"
```
三个包都要显示出来。如缺失，跑：
```powershell
py -3.11 -m pip install yfinance akshare pandas
```

### ✅ 3. 脚本能手动跑通

验证：
```powershell
cd C:\Users\dbao0\Documents\Claude\Projects\_system\scripts
py -3.11 market_data_fetcher.py
```
应看到一长串 `✅ 个股 ...` 并以 `=== 完成：成功 38 / 失败 0 ===` 结尾。

**以上三项都通过，才进入下一步。**

---

## 配置任务计划程序

### Step 1：打开任务计划程序

`Win + R` → 输入 `taskschd.msc` → 回车

### Step 2：创建基本任务

1. 右侧面板点 **"创建基本任务"**
2. **名称：** `Market_Data_Fetcher`
3. **描述：** `每日 08:30 从 yfinance + akshare 拉取投资组合 OHLCV 数据`
4. 点 "下一步"

### Step 3：触发器（什么时候跑）

1. 选 **"每天"** → 下一步
2. **起始：** 今天的日期
3. **时间：** `08:30:00`
4. **每隔 `1` 天发生一次**
5. 下一步

### Step 4：操作（跑什么）

1. 选 **"启动程序"** → 下一步
2. **程序或脚本：** `C:\Python311\python.exe`
   - **⚠️ 绝对不要写 `py.exe` 或直接指向 `.py` 文件！**
   - 原因：`py.exe` 是 launcher，靠环境变量/注册表判断"3.11 在哪"；直接指向 `.py` 会用系统默认的 Python 文件关联去解释。这两种方式都**脆弱**——Windows 更新、Microsoft Store 推送、其他 Python 安装都可能悄悄改动它们的指向，脚本启动后 `import yfinance` 就会失败 → 退出码 0x1（**2026-07-02 实际踩过一次**：日志显示"缺少 yfinance"但手动 `py -3.11 -c "import yfinance"` OK，说明任务用的解释器不是 Python 3.11）。
   - 硬编码 `C:\Python311\python.exe` 绝对绑定到你确认好依赖的解释器上，最保险。
3. **添加参数（可选）：** `market_data_fetcher.py`
4. **起始于（可选）：** `C:\Users\dbao0\Documents\Claude\Projects\_system\scripts`
   - **⚠️ 这一栏必须填，否则脚本运行时找不到自己的目录**
5. 下一步 → **完成**

### Step 5：精细化设置（必改）

任务创建后还要做几项调整。在任务列表中找到 `Market_Data_Fetcher`，**右键 → 属性**：

#### "常规" 标签
- **安全选项**：选 **"不管用户是否登录都要运行"**（如选这个会提示输密码——这是为了让任务在你没登录电脑时也能跑）
  - 如果不想输密码：保留 "只在用户登录时运行"，但要求 08:30 时你的电脑是开机且登录状态
- ✅ 勾选 **"使用最高权限运行"**（部分网络场景需要）
- **配置：** Windows 11

#### "触发器" 标签
- 双击已有的 "每天 8:30:00" → 弹出"编辑触发器"
- ✅ 勾选 **"延迟任务时间（最长 30 秒）"**——避免和 Windows 启动期资源冲突
- 确定保存

#### "条件" 标签
- ☐ **取消勾选** "只有在计算机使用交流电源时才启动此任务"（笔记本电池供电时也跑）
- ☐ **取消勾选** "如果计算机切换到电池电源，则停止"
- ✅ 勾选 "唤醒计算机以运行此任务"（如果允许计算机睡眠）

#### "设置" 标签
- ✅ 勾选 **"如果错过了计划开始时间，请尽快启动任务"**（电脑没开/睡眠的情况下，开机后自动补跑）
- ✅ 勾选 **"如果任务运行时间超过以下时间，则停止任务"**，设为 **`30 分钟`**（正常 1-2 分钟跑完）
- ✅ 勾选 **"如果请求后任务仍在运行，强制停止任务"**
- **"如果任务已经运行，则适用以下规则："** 选 **"不启动新实例"**

确定保存。

### Step 6：手动测试一次（必做）

在任务列表中右键 `Market_Data_Fetcher` → **"运行"**

等 30-60 秒后检查：

```powershell
# 检查最新的 CSV 是否更新到今天
Get-ChildItem C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\*.csv | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, LastWriteTime

# 看本次拉取日志
Get-Content (Get-Item C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\fetch_log\fetch_log_*.txt | Sort-Object LastWriteTime -Descending | Select-Object -First 1) -Tail 20
```

如果看到 `=== 完成：成功 38 / 失败 1 ===` 之类的输出 → ✅ 配置成功。

---

## 日常运维

### 每天早上的快速检查（可选，1 分钟）

```powershell
# 一行命令检查今天数据是否拉到位
$today = (Get-Date -Format "yyyy-MM-dd"); $log = "C:\Users\dbao0\Documents\Claude\Projects\_system\market_data\fetch_log\fetch_log_$today.txt"; if (Test-Path $log) { Get-Content $log -Tail 3 } else { Write-Host "❌ 今天 ($today) 还没拉数据，可能任务计划没跑" -ForegroundColor Red }
```

### 周末/节假日

- 周末（美股、港股、A 股都休市）跑一遍不会报错，但 CSV 内容跟周五一样（yfinance/akshare 都不会返回新数据）
- 也可以改成"周一至周五"运行：在 "触发器" 标签里把"每天"改成"每周"，勾选 一/二/三/四/五

### 新增/删除公司

直接编辑 `market_data_fetcher.py` 顶部的 `YF_TICKERS` 或 `AK_TICKERS` 字典：
```python
YF_TICKERS = {
    ...
    "NEW_TICKER": "NEW_TICKER",   # 新增
    ...
}
```
然后同步更新 `portfolio_registry.md` 中的对应公司条目即可。

### 看具体某天的运行历史

任务计划程序 → 选中 `Market_Data_Fetcher` → 下方 "**历史**" 标签会列出每次运行的开始时间、结束时间、退出码（0 = 全部成功；2 = 有失败但脚本完成；其他 = 异常）

---

## 故障排查

### 任务跑了但没有 CSV 输出

最可能原因：**"起始于" 一栏没填**。脚本的 `Path(__file__)` 找不到正确位置。检查任务的 "操作" 标签里 "起始于" 一栏是否填了 `C:\Users\dbao0\Documents\Claude\Projects\_system\scripts`。

### 任务报错 "0x1" 或 "0x2"

**退出码 1**（`sys.exit(1)`）= 依赖 import 失败。日志开头会有"❌ 缺少 yfinance / akshare"。

排查顺序：
1. **先手动验证 Python 3.11 依赖没问题**：PowerShell 里跑 `py -3.11 -c "import yfinance, akshare; print('OK')"`
   - 如果这条也失败 → 真的少依赖 → `py -3.11 -m pip install yfinance akshare`
   - **如果这条 OK 但任务还是 0x1 → 任务用的解释器不是 Python 3.11**（见第 2 步）
2. **检查任务属性 → 操作 → "程序或脚本"**：必须是 **`C:\Python311\python.exe`**。如果被改成了 `py.exe` 或直接指向 `.py` 文件，Windows 会用默认关联去解释，那个关联可能因系统更新、Microsoft Store 推送、装了新 Python 而悄悄换成别的解释器（该解释器可能没装 yfinance）→ 立刻退出 0x1。这是 2026-07-02 的实际根因。
   - 三段式的正确配置：`C:\Python311\python.exe` + `market_data_fetcher.py` + 起始于 `...\_system\scripts`

**退出码 2**（`sys.exit(2)`）= 脚本自己判断"有 ticker 失败"→ 看日志里具体哪只失败。正常情况下应全部成功；偶发失败可重跑或检查数据源。

### 任务一直显示 "正在运行" 没完成

可能是网络问题导致 yfinance 卡住。在 "设置" 标签确认 "如果任务运行时间超过 30 分钟则停止" 已勾选——这是兜底。如果天天卡，检查网络是否稳定（yfinance 需要访问 Yahoo Finance 海外服务器）。

### 我换电脑了

整个 Wind 数据缓存方案完全本地、无云依赖。新电脑需要：
1. 装 Python 3.11
2. `pip install yfinance akshare pandas`
3. 把 `Projects/` 文件夹同步过去
4. 重新配 Windows 任务计划程序（步骤同上）

---

## 文件清单（部署后的最终结构）

```
C:\Users\dbao0\Documents\Claude\Projects\_system\
├── scripts\
│   ├── market_data_fetcher.py          ← 数据拉取脚本（**当前使用**）
│   ├── SETUP_MARKET_DATA_FETCHER.md    ← 本文档
│   ├── wind_fetcher.py                 ← 已废弃（Wind 路线失败，保留备查）
│   └── SETUP_WIND_FETCHER.md           ← 已废弃
├── market_data\                        ← yfinance + akshare 拉取的 CSV
│   ├── APP.csv
│   ├── MSFT.csv
│   ├── 9992.HK.csv
│   ├── 300054.SZ.csv
│   ├── ...                             ← 33 个 ticker
│   ├── indices\
│   │   ├── SPX.csv
│   │   ├── HSI.csv
│   │   ├── CSI300.csv
│   │   └── ...                         ← 6 个指数（SPX/NDX/HSI/CSI300/CSI500/CHINEXT）
│   ├── fetch_log\                      ← 每日运行日志（2026-07-02 起归档到子文件夹）
│   │   ├── fetch_log_2026-07-02.txt
│   │   └── ...
│   └── _data_status.json               ← 权威 data_as_of 清单
├── portfolio_registry.md
└── daily_briefing\
    └── 2026-05-11_daily_briefing.md    ← 9:09 自动调度生成
```

---

*最后更新：2026-05-11 / yfinance + akshare 方案*
