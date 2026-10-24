---
name: value-growth-paper-monitor
description: 「低估+增长 策略模拟盘」每日监测。在设备上重跑 paper_portfolio.py 复核净值，把看板发布到既有 artifact，并发一段不超过 7 行的摘要通知。纸面组合，只读、不下单、不改估值、不碰真实持仓。用户说「跑模拟盘监测」「刷新低估+增长模拟盘」时使用。
---

<!--
导出自定时任务「低估+增长 策略模拟盘监测」
任务 ID：trig_012Hypssos51KasM3gFb9u1v
时间表：CRON_TZ=Asia/Shanghai 55 9 * * 2-6（周二到周六 09:55）
模型：claude-fable-5-1
连接的文件夹：任务没有预先绑定文件夹（步骤 0 会按需申请）
通知：推送开、邮件关
任务最后修改：2026-10-04T08:00:20Z；导出时间：2026-10-10
以下正文是任务的提示词原文。
-->

每天为「低估+增长 策略模拟盘」刷新看板并通知用户。这是一个与用户真实账户完全独立的纸面组合（起点 2026-09-30、名义本金 $126,376.38），用来检验"价格短期被低估 + 业务长期有增长"这条策略在本系统估值数据上的实际战绩；只读、不下单、不改估值、不碰真实持仓。入选规则：主导情景=基准、现价→基准价上行 ≥25%、跌到悲观价空间 ≤30%、三年目标价年化 ≥15%；入选标的等权（每票 min(80%/N, 15%)），不用 Kelly、不用概率；权重偏离 >3 个百分点才调仓；持仓退出有迟滞线；成交只用新鲜收盘价（≤3 个自然日且不落后于本市场指数 SPX/HSI/CSI300），否则当天只重估不交易。参数在 _system/paper_portfolio/config.json。

引擎 _system/scripts/paper_portfolio.py 已由本地 daily_pipeline.bat 第 [3/8] 步在 08:30 左右跑过一次（依赖同一条链前面刚拉好的行情），同一条链的 [7/8]/[8/8] 会把看板发布到网站 flyfishcapital.cc/value-growth.html——本任务不碰网站、不 git push。本任务是在它之后做"复核 + 发布 artifact + 通知"。脚本同日重跑是安全的：只重估净值，不重复交易、不改 ledger（唯一例外：早先一次运行因旧价拦下交易时，行情补齐后的同日重跑可以补做交易判定，这是设计行为）。

步骤：

0. 若 device_bash 报"No folders are connected"，先调用一次 device_request_folder_access，paths=["C:\\Users\\dbao0\\Documents\\Claude\\Projects"]，reason 写"每日模拟盘复核需要运行 paper_portfolio.py"；获批后继续。被拒或无响应就按第 3 步失败处理。

1. 用 device_bash 在设备 flyfish 上就地运行（它会读 valuation_registry / three_year_valuation_registry / market_data，写 _system/paper_portfolio/ 下的 state.json、ledger.csv、nav_history.csv、daily/<date>.json、summary_latest.json、dashboard.html）：

   命令：cd "$HOME/mnt/Projects" && python3 _system/scripts/paper_portfolio.py 2>&1

   记下 stdout 里的 [paper] 摘要行：asof、px_asof、days、nav、ret、bm_ret、mdd、cash_pct、holds、stale、trades_today、blocked、top；以及 "[paper] trades_today=" 行（当日全部成交明细，读自 ledger，含 08:30 主跑的成交）和 "[paper] blocked=" 行（因旧价被拦下的交易）。
   注意：摘要里的 `trades` 只是"本次运行"的成交，复核重跑几乎总是 0——通知里一律用 `trades_today`，不要用 `trades`。

2. 当天就绪校验：`asof` 必须等于今天（Asia/Shanghai）的日期；`px_asof` 应不早于 3 个自然日前（美股收盘是昨天，周一允许到上周五）。若 `stale` > 0 或 `px_asof` 过旧，说明当天行情拉取失败（通常是 yfinance 限流，可查 _system/last_run.log 的 [1/8] 段）——看板照常发，但摘要里必须明说"行情停在 <px_asof>，净值未真实推进"。`blocked` > 0 同理要在摘要里列出。

3. 失败处理：若 device_bash 报错、没有 [paper] 行、或 Traceback——最多重试 2 次；仍失败就用一句话说明原因（设备没连 / 脚本报错 + 错误首行），不要生成空产出、不要更新 artifact，用 PushNotification 发这句话后结束。

4. 从设备 stage 当天看板：device_stage_files 传 device 路径

   C:\Users\dbao0\Documents\Claude\Projects\_system\paper_portfolio\dashboard.html

5. 用 Artifact 工具更新既有 artifact（**必须带 url，否则会新建一个、用户书签失效**）：

   Artifact(file_path="<第 4 步 stage 后的容器内路径>", url="https://claude.ai/artifact/Anh39RF2oDDFYnE4sPBBkT", label="<asof> 模拟盘")

   不要传 icon（首发已设 chart），不要改标题。若首次发布被拒并提示"hadn't viewed the live version"：线上版本只是前一天脚本自动生成的看板、没有人工编辑，当天看板是完整替换，确认后用同样参数再发布即可（必要时发两次）。

6. 用 SendUserMessage 发一段 ≤7 行的摘要，并用 PushNotification 发同样内容（包在 <routine_summary> 里；这就是用户的每日提醒）：
   第 1 行：<asof> 低估+增长模拟盘 · 净值 $<nav> · 累计 <ret%> · 同期 SPX <bm_ret%> · 超额 <ret−bm_ret>
   第 2 行：最大回撤 <mdd%> · 现金 <cash_pct%> · 持仓 <holds> 只 · 今日成交 <trades_today> 笔
   第 3 行：持仓权重/盈亏：<top 原样转述>
   第 4 行（仅当 trades_today>0）：成交明细：<trades_today 行原样转述，含触发原因>
   第 5 行（仅当 blocked>0）：⚠ 旧价拦下 <blocked> 笔：<blocked 行原样转述>
   第 6 行（仅当 stale>0 或行情过旧）：⚠ 行情停在 <px_asof>，今日净值未真实推进
   末行：看板已更新（artifact）。纸面组合、按收盘价成交、不计冲击成本、非交易单。

不要展开方法论、不要给投资建议、不要评论策略好坏；用户要的是每天一眼看到数字。
