---
name: new-company-onboarding
description: "新公司入库脚手架。仅在用户明确说\"加一家新公司\"/\"入库 {TICKER}\"/\"新公司 {TICKER}\"/\"onboard {TICKER}\"时触发。只做脚手架——写 _system/companies.json（全库唯一真相源）、建 companies/{TICKER} {中文名}/ 目录树、自动预取年报/季报原始文件 + 电话会纪要 + EDGAR 财务底稿进 Wiki/raw/、追加 portfolio_registry 条目、补 valuation_registry、跑 rescan 重建 dossier_registry、记 changelog、跑 validate_taxonomy 校验。不选行业目录，不改 fetcher，不跑研究，不调 company-dossier-build orchestrator。原始材料自动下载，但分析一律留给后续 skill。"
---

# 新公司入库脚手架

把一家新公司接进跟踪体系，**只搭架子不做研究**。跑完之后这家公司会：出现在每日扫描名单里、被行情拉取覆盖、在网站上有位置（尚无研究总结 HTML 所以暂不显示卡片）、`validate_taxonomy.py` 0 ERROR。

研究内容一律留白填「研究中」「待完成」。**定期报告原始文件、电话会纪要、EDGAR 财务底稿三样都由第 3 步自动下载**，不必等用户手动上传；管理层访谈、Investor Day 这类没有公开接口的材料才需要用户自己补。分析本身另行触发 `company-dossier-build`。

## 边界

**做：**写 `companies.json` → 建目录树 → **预取原始材料（3a 定期报告 + 3b 电话会纪要 + 3c 财务底稿，三个脚本都跑）** → 追加 `portfolio_registry.md` 条目 → 补 `valuation_registry.json` → 跑 `rescan` → 记 changelog → 跑校验。

**不做：**不跑任何分析 sub-skill；不调 `company-dossier-build`；不生成研究总结 HTML；不填评级/估值区间/催化剂的实质内容。

**已经不需要做（2026-08 分类体系重构后失效，做了反而有害）：**

- ❌ **不要往 `market_data_fetcher.py` 加 ticker** —— `YF_TICKERS` / `AK_TICKERS` 由 `_load_ticker_maps()` 从 `companies.json` 自动生成（A 股 `.SZ`/`.SH`/`.BJ` 走 akshare 用去后缀的 6 位码，其余走 yfinance 用 ticker 本身），手工加条目会在下次读取时被覆盖，且制造"两处名单"的假象
  - ⚠️ **唯一的例外**：`_load_ticker_maps()` 假设 **数据源 symbol == 注册表 ticker**。这个假设不成立时才需要动 fetcher，而且只动这两个表：
    ```python
    YF_SYMBOL_OVERRIDES = {}   # 注册表 ticker ≠ yfinance symbol，如公司改了股票代码
    EXCLUDE_TICKERS = set()    # 未上市 / 无公开报价，不拉行情
    ```
    典型场景：EchoStar 2026-06 把代码从 `SATS` 改成 `ECHO`，注册表还没改名的那段时间靠 `{"SATS": "ECHO"}` 撑着行情没断。**入库后拉不到行情，第一个该看的就是这里。**
- ❌ **不要改 `dossier_orchestrator.py` 的 `COMPANIES` 常量** —— 那个硬编码列表已删除，改为 `load_companies_list()` 读 `companies.json`
- ❌ **不要选行业板块目录** —— 顶层的 `1. SaaS软件` / `9. 其他公司` 这类目录已全部删除，公司目录一律扁平放在 `companies/` 下
- ❌ **不要在 registry 里写 `Folder:` 字段** —— 已从全库删除，路径由 `companies.json` 的 `folder` 提供

---

## 执行步骤

### 1. 写 `_system/companies.json`（第一步，其余都是它的下游）

在 `companies` 对象**末尾**追加。这是全库唯一真相源，被 `build_site.py` / `dossier_orchestrator.py` / `sync_valuations.py` / `market_data_fetcher.py` / `audit_core_conclusions.py` / `build_valuation_comparison.py` 六个脚本读取。文件格式：UTF-8、LF、indent=2、`ensure_ascii=False`——用 `json.dump` 回写时照这个来，别改动其他条目的排版。

```json
"{TICKER}": {
  "name_cn": "中文名或惯用简称",
  "name_en": "官方英文全称",
  "gics": {
    "sector": "45",
    "industry_group": "4510",
    "industry": "451030",
    "sub_industry": "45103010",
    "as_of": "{今天 YYYY-MM-DD}",
    "confidence": "low"
  },
  "folder": "companies/{TICKER} {name_cn}",
  "note": "{今天} 脚手架入库。GICS 按{同业/业务}推定，尚未按声明 GICS 的来源核实，故 confidence=low 待人工核对。"
}
```

⚠️ **schema 1.3（2026-09-11）起，公司条目只有 `name_cn` / `name_en` / `gics` / `folder` / `note` 五项。**
`business_model`、`tier`、`needs_review`、`lifecycle` 四个自定义分类字段已全部删除——**写了会多出 registry 里不存在的字段**，validate 不报错，但会让下一个人以为这些维度还活着。**GICS 四级代码是现在唯一的分类维度**，删除理由见 `companies.json` 顶层 `note`。

**ticker 写法：**美股用裸代码（`INTC`、`NVDA`），**不要加 `.N` / `.O` 后缀**；港股 `3690.HK`；A 股 `300750.SZ` / `601872.SH` / `920186.BJ`。ticker 同时是行情 CSV 的文件名。

**字段约束（`validate_taxonomy.py` 会逐条验）：**

| 字段 | 约束 |
|------|------|
| `folder` | 必须与磁盘上的目录名**逐字一致**（C5 验） |
| `gics.*` | **存代码不存名字**。四级必须逐级前缀包含：`sub[:6]==industry`、`industry[:4]==industry_group`、`industry_group[:2]==sector`（C3 验）。`sector` 必须在 `gics_sector_names` 里（C4 验）——十一个一级板块都在，含 `"10"` 能源 |
| `gics.confidence` | 必须是 `vocab.confidence` 三值之一：high / medium / low（C2 验，2026-09-11 起）。**大小写敏感**，写成 `"High"` 会报 ERROR |
| `note` | 自由文本，但 GICS 的来源 URL、拿到的层级、哪一级是推断的必须写进去——这是唯一的取证留痕，见下文「GICS 怎么查」 |

### 2. 建目录树

```
companies/{TICKER} {中文名}/
├── 研究档案/
│   ├── _history/          （空目录，accept 时写快照）
│   └── _pending/          （空目录，建档产出落这里等人工 accept）
├── 催化剂跟踪/
│   └── 催化剂跟踪_自动化.md
├── 技术分析/              （空目录）
└── {TICKER} Wiki/
    ├── CLAUDE.md          （照抄任一现有公司的 Wiki/CLAUDE.md，替换 ticker 与公司名）
    ├── raw/
    └── wiki/
```

例：`companies/INTC 英特尔/`、`companies/3690.HK 美团/`、`companies/V Visa/`

**不需要选任何行业目录。**目录名只是给人看的标签，**没有任何代码解析它**——行业完全由 `companies.json` 的 `gics` 四级代码承载。

**研究档案下的七个 md 不要预先创建。**`dossier_registry` 靠文件存在性判断 `dossier_status`，建空文件会让一家没做过研究的公司显示成 `complete`。

`催化剂跟踪_自动化.md` 用现有格式建骨架，数值全部留白：

```markdown
# {中文名}（{TICKER}）催化剂跟踪

**最后自动扫描：** —
**当前股价：** —
**估值区间定位：** —
**主导情景目标价：** 待完成估值分析
**投资评级：** 研究中
```

### 3. 预取原始材料（自动执行，**不要问用户**，**三个脚本都跑**）

目录建好之后立刻跑，不需要征求同意——用户已明确要求这步自动做。**漏跑其中任何一个都算没做完**（2026-09-04 ADBE 入库先漏 3b 再漏 3c，被用户两次指出）。跑完后 `raw/` 下应有三块：`SEC/`（或 A 股/港股渠道目录）、`transcripts/`、`财务数据/EDGAR/{TICKER}/`。

#### 3a. 定期报告

```
python _system\scripts\fetch_raw_filings.py {TICKER} --out "companies\{TICKER} {中文名}\{TICKER} Wiki\raw"
```

脚本按 ticker 后缀自动路由市场，只用标准库，产出 `raw/{渠道}/` 下的文件 + `raw/MANIFEST.md` 清单：

| 市场 | 渠道 | 取什么 | 落到 |
|------|------|--------|------|
| A 股 `.SZ` `.SH` `.BJ` | 东方财富公告接口（`.SZ` 备用深交所） | 最近 2 份年报 + 2 份半年报 PDF | `raw/EASTMONEY/` 或 `raw/SZSE/` |
| 港股 `.HK` | 披露易 titleSearch | 最近 2 份年报 + 2 份中期报告 PDF | `raw/HKEX/` |
| 美股（裸代码） | SEC EDGAR submissions | 最近 2 份 10-K/20-F + 4 份 10-Q | `raw/SEC/` |

参数：`--years N`（每类各取几份，默认 2）、`--quarterly`（A 股加取一季报/三季报，默认不取）、`--probe`（只列清单不下载，排查渠道用）。

#### 3b. 电话会纪要（美股）

```
python _system\scripts\fetch_transcripts.py {TICKER} --out "companies\{TICKER} {中文名}\{TICKER} Wiki\raw\transcripts" [--limit 8]
```

从 Motley Fool 免费全文抓最近 8 份纪要，转成 Markdown 落 `raw/transcripts/FOOL/{TICKER}_FY{年}Q{季}_{发布日}.md`，清单写 `raw/transcripts/MANIFEST.md`。**仅支持美股**；港股/A 股跑了会直接失败，MANIFEST 会说明，纪要靠用户手补。

- Fool 在电话会后 0–3 天才发布，最近一场可能还没有——MANIFEST 会提示，过几天重跑即可（已有文件自动跳过）。
- 单条 `SSL: UNEXPECTED_EOF` 是偶发，**重跑一次就好**，不算渠道不通。
- Fool 的年份/季度标签偶尔错（AVGO 曾把一份 2026-01 的纪要标成 FY2024Q3），文件名照 Fool 标题取，建档时以正文日期为准。

#### 3c. EDGAR 结构化财务底稿（美股，含 20-F/40-F 外国发行人）

```
python _system\scripts\fetch_edgar_financials.py {TICKER} --out "companies\{TICKER} {中文名}\{TICKER} Wiki\raw\财务数据\EDGAR"
```

从 SEC XBRL companyfacts 取数，落 `raw/财务数据/EDGAR/{TICKER}/`：`financials.json`（统一底稿，每条带 tag/form/filed/accn 指针）+ `annual.csv` / `quarterly.csv` / `ttm.csv` / `capital_allocation.csv`（人读透视）。默认 6 年，`--years N` 可调；币种和 us-gaap/ifrs 自动识别。**只取数不判断**，判断留给 02 财务分析。

- 脚本末尾打「指标 X/78 命中」「勾稽 N 项 M 项未过」「未命中指标」——**未命中不等于失败**，很多科目公司本来就没有（无存货、无少数股东等）；只有勾稽有未过项或 `meta.suspect_metrics` 非空才需要在交接时点出来。
- 港股/A 股没有对应脚本，本步跳过，交接时说明即可。
- 这一步曾写成「归 `company-dossier-build` Step 0 预检③」——**已改归本 skill**。理由：入库当天不拉的话 `raw/` 缺一块，用户看不到底稿就以为没做；建档时再拉一遍纯属重复。dossier-build 预检③ 改为「检查底稿存在且 capabilities 齐全，缺了才补拉」。

#### 执行要点（3a / 3b / 3c 共用）

- **在能联网的那个 shell 里跑。**渠道可达性因机器而异——2026-09-04 实测宿主机 Linux VM 对 `data.sec.gov` 和 `fool.com` 都通（早先记录的"宿主机只通深交所"已过时），云端容器四条线全通。不确定就先 `--probe` 探一把再正式跑，别凭旧记录直接绕去云端。
- **巨潮 `www.cninfo.com.cn` 两处都不可达**（http 502 / https SSL EOF），脚本已完全不依赖它。旧版 skill 里那套巨潮 `hisAnnouncement/query` 写法作废，别照抄。
- **在云端跑的话**，下完用 `SendUserFile` + `device_commit_files` 把文件落回公司目录的 `Wiki/raw/{渠道}/`，别留在容器里——留在容器里等于没下。
- **失败不中断。**单个文件拿不到就记进 MANIFEST 的「自动预取失败项」，继续往下走。一份都没拿到时脚本返回退出码 1，这时如实告诉用户哪条渠道不通，**别假装拿到了**。

MANIFEST 末尾列的「需人工补充」项——管理层访谈、Investor Day 材料、Seeking Alpha / 万得纪要——没有公开接口拿不到，收尾交接时提醒用户自己拖进 `raw/`。

### 4. 追加 `_system/portfolio_registry.md` 条目

直接在**文件末尾**追加。板块 `##` 标题已全部删除，不需要找位置。

⚠️ **`Valuation:` 块下只写「加权目标价」一行。**多写一行 `- 待完成估值分析` 会被 `sync_valuations.py check` 解析成 1 档估值区间，与 JSON 的 `zones: []` 对不上而报错——它把 Valuation 下所有 `- xxx` 子项都当区间，不认占位文案。

```markdown
### {TICKER} — {中文名}
- **Ticker:** {TICKER} ({NASDAQ|NYSE|HKEX|SZSE|SSE|BSE})
- **Currency:** {USD|HKD|CNY}
- **Status:** active
- **Rating:** 研究中
- **Valuation:**
  - 加权目标价: 待完成估值分析
- **Key Catalysts:**
  1. [P0] 待完成研究
- **Next Key Date:** 待定
- **Last Research:** —
```

同时把头部「**公司总数：** N（活跃）」的 N 加一。

⚠️ **不写 `- **Folder:**` 字段。**

### 5. 补 `_system/valuation_registry.json`

在 `companies` 对象下追加一条。`sector` 填 **GICS 一级板块的中文名**（查 `companies.json` 的 `gics_sector_names`，如 `"45"` → `"信息技术"`），**不是代码**。

```json
"{TICKER}": {
  "name": "{中文名}",
  "sector": "信息技术",
  "status": "active",
  "currency": "USD",
  "rating": "研究中",
  "zones": [],
  "target_price": "待完成估值分析"
}
```

必须与 `portfolio_registry.md` 的 `rating` / `target_price` / `zones` / `status` 保持一致——`sync_valuations.py check` 只比对这四项。

### 6. 重建 `dossier_registry.json`

```
python _system\scripts\dossier_orchestrator.py rescan
```

**不要手改这个文件**，它是生成物（子命令叫 `rescan` 不叫 `scan`；不带 ticker 参数 = 全量）。新公司应显示 `0/6 status=empty folder=✓`。

### 7. 记 `_system/scan_log/registry_changelog.md`

追加一行，四列格式：

```markdown
| {今天} | 新增 | {中文名} ({TICKER}) | {GICS 中文板块名} |
```

⚠️ **别用 `>>` 追加到文件末尾。**表格在文件中段（后面接的是叙事段落），追到尾部会掉在表格外面。用脚本插到最后一条 `| 20xx-` 表格行之后。

### 8. 收尾校验（必做）

```
python _system\scripts\validate_taxonomy.py        # 应 0 ERROR
python _system\scripts\sync_valuations.py check    # 应一致
```

**唯一允许的 ERROR 是 C8「{TICKER} 没有行情 CSV」**——新公司当天还没被拉取过。跑完提示用户：

> 跑一次 `每日自动更新.bat`（或单独跑 `market_data_fetcher.py`）补上行情 CSV，之后 `validate_taxonomy.py` 应完全 0 ERROR。

其余任何 ERROR 都说明前面某步写错了，**修掉再收工**，不要留给用户。遇到与本次入库无关的既有 ERROR（如 C9 旧板块空目录回潮），如实报告、说明不是本次造成的；挂载盘默认无删除权限，空目录让用户手删或申请一次删除权限。

**收尾交接必须列清单**：`raw/` 三块各拿到几份、财务底稿勾稽是否全过、suspect_metrics 是否为空、哪些要人工补。用户看的是这个清单，不是过程叙述。

---

## GICS 怎么查

**判据只有一条：来源文件里必须写明分组依据是 GICS。**看到一列 "Sector" 就当成 GICS 是本 skill 最容易犯、也最难自查的错——2026-08 就因此把高盛 MarketBeta 的一个标签误当一手来源。查不到就诚实标 `confidence: low`，**绝不为了“看起来标准”编一个假权威值**。

### 唯一可靠的路子：SEC 上声明使用 GICS 的基金持仓表

美国注册基金的 N-CSR / N-CSRS / NPORT-P 按行业分组，其中一部分在脚注里声明依据 GICS。典型措辞（认这两句）：

> “Industry and/or sector classifications used in this report are generally according to the Global Industry Classification Standard, which was developed by and is the exclusive property and a service mark of MSCI Inc. and Standard & Poor's.”

> “The Global Industry Classification Standard (GICS®) was developed by and/or is the exclusive property of MSCI, Inc. and Standard & Poor's Financial Services LLC.”

**检索式**（用公司英文正式名，不要用 ticker）：

```
https://efts.sec.gov/LATEST/search-index?q=%22Global%20Industry%20Classification%20Standard%22%20%22{公司英文名}%22&startdt=2024-06-01
```

坑：`q=` 里用 `%20` 分隔，用 `+` 会 400；短语太长会 500。人工界面 `https://www.sec.gov/edgar/search/#/q=...`。

命中后打开文件，看这家公司**列在哪个分组标题下**，再用 GICS 结构表把标题名翻成代码。

### 不同基金族给到的层级不同（2026-09-11 实测）

| 基金族 | 主体 / 检索线索 | 分组粒度 | 对 A 股/港股 |
|---|---|---|---|
| **Invesco 共同基金** | AIM INVESTMENT FUNDS、AIM INTERNATIONAL MUTUAL FUNDS（CIK 826644 = Greater China Fund） | **四级子行业名**（Distillers & Vintners、Restaurants、Broadline Retail） | 大盘覆盖好，**唯一能直接拿到 8 位的路子** |
| **AB / AllianceBernstein** | AB Cap Fund（CIK 81443，All China Equity）、AB Active ETFs（CIK 1496608，Disruptors ETF） | 三级行业 | A 股覆盖好，单文件 ~140KB 好读 |
| **Hartford / Schroders China A** | CIK 49905 | 二级行业组 | A 股中盘也有 |
| **Goldman Sachs MarketBeta** | GS ETF Trust / Trust II，**只认 N-CSRS** | 一级 sector（证券名后括号标注） | 最广，含小盘 |

⚠️ **同一只基金，不同表格声明不一样。**高盛 MarketBeta 的 **N-CSRS 含 GICS 声明，单独的 NPORT-P 不含**。引用必须挑对文件，别看见同族就通用。

⚠️ **Invesco 的 ETF 信托（Invesco Exchange-Traded Fund Trust）只到三级**，能到四级的是 AIM 系共同基金。两者别混。

### 已证伪，不要再花时间

| 来源 | 为什么不行 |
|---|---|
| **iShares / BlackRock 持仓 CSV** | 全文无 GICS 声明；Sector 列是 BlackRock 自有标签——腾讯写作 `Communication` 而非 GICS 的 `Communication Services` |
| **Vanguard 板块 ETF 反推**（旧版本推荐过，已废） | Vanguard 持仓表按国家排列且不声明 GICS；板块 ETF 跟踪的是 CRSP 指数不是 GICS |
| **Xtrackers / ASHR** | DBX ETF Trust 提到 GICS 的全是招募书，0 份 N-CSR/NPORT |
| **MSCI 免费 factsheet / ESG 查询页** | factsheet 全文无 GICS 字样，只有 Top10 的缩写标签（`Comm Srvcs`）；ESG 页展示的是 MSCI 自有 ESG 行业 |
| **S&P DJI 个股层** | 指数页声明用 GICS，但只公开 Top10，完整成分清单要登录 |
| Morningstar / Yahoo / Zacks / stockanalysis | 都不是 GICS，且经常与 GICS 相反 |
| Russell 系列 | 用 ICB |
| SEC 的 SIC 码 | 与 GICS 无映射关系 |

**GICS 结构表（代码 ↔ 名称字典，必备）**：`https://www.spglobal.com/spdji/zh/documents/index-policies/methodology-gics-chinese.pdf`（中文方法论）配合 GICS Structure Effective 2023 映射表。拿到子行业**名称**后必须查表转 8 位代码，别凭印象敲。

### A 股 / 港股专用

**A 股**：证监会、申万都与 GICS 无关。**中证行业分类**值得单说——四级制、11 个一级行业（GICS 也是 11 个），一级名称几乎一一对应，但中证官方说明全文不出现 GICS，只写“借鉴国际经验”；二级以下数量对不上（中证 35/98/260 vs GICS 25/74/163）。**只能用一级做近似，二级以下不可映射**，且必须在 note 里写明是“CSI L1 近似，非 GICS 声明”。

**港股**：恒生用 HSICS（12/31/114 三级），官方手册全文不提 GICS，只含糊说“可映射到国际分类系统”，**没有公开对照表**。只能自己按语义推。

**北交所**：不在沪深港通北向标的内，美国注册基金几乎不持有，**永远查不到一手来源**。直接标 `low`，别反复搜。

**沪深港通标的显著更容易查到**——外资基金持仓集中在北向标的上。`"Kweichow Moutai"` 能搜到 200+ 份，非标的小盘股常年零命中。

### confidence 按“拿到第几级”定，不是按感觉

| 等级 | 条件 |
|---|---|
| `high` | **四级子行业**由声明 GICS 的来源直接给出 |
| `medium` | 只拿到一/二/三级，四级靠该层下子行业消去法推得；或只有旁证（无 GICS 声明的持仓表标签） |
| `low` | 四级全部业务推断，无任何声明 GICS 的来源 |

**note 里必须写清三样**：来源文件 URL、拿到的是第几级、哪一级是推断的。这样下次复核不用重查，也不会把推断误读成结论。

### 归类原则：按最终收入来源，不按商业模式、技术形态或下游客户

这条经常反直觉，凭直觉填必错：

- 多邻国是**教育服务**不是软件
- Planet Labs 是**研究与咨询服务**不是航空航天
- 美团是 **Restaurants**（餐饮，25301040）不是互联网零售
- 鼎龙股份是**原材料**不是半导体
- 泡泡玛特是 **Specialty Retail**（专营零售）不是休闲用品——自营门店/机器人商店的零售属性被视为主导
- 招商轮船是**能源**（Oil & Gas Storage & Transportation，10102040）不是工业——GICS 把原油油轮运营商归能源
- 贵州茅台是 **Distillers & Vintners**（30201020）不是 Brewers（30201010）——2026-09-11 查出的实际错误，当时还标着 `high`

最后一条是教训：**同一个 industry 下的相邻子行业最容易填错，而且错了看起来一点都不像错的。**拿到子行业名之后，把该 industry 下的全部子行业列出来逐个排除，别看见一个像的就填。

---

## 常见错误

| 错误 | 后果 |
|------|------|
| 目录名与 `companies.json` 的 `folder` 不一致 | `validate_taxonomy` C5 报 ERROR；orchestrator 找不到目录 |
| ticker 带 `.N` / `.O` 后缀 | 行情 CSV 文件名对不上，网站现价空白 |
| `gics.confidence` 写成 `"High"` / `"unknown"` | C2 报 ERROR（2026-09-11 起该字段才被校验，以前会一路静默） |
| 仍然写 `business_model` / `tier` / `needs_review` / `lifecycle` | schema 1.3 已删除这四个字段，写了不报错但会误导下一个人 |
| 预先创建七个空的研究档案 md | `dossier_status` 误判为 `complete`，掩盖“这家还没做研究” |
| `valuation_registry.sector` 填了代码 `"45"` | 与全库口径不一致（应填 `"信息技术"`） |
| 编造 GICS 代码充数 | 比标 `low` 有害得多——`confidence` 一旦写成 high 就没人再回头核 |
| 把没有 GICS 声明的持仓表当一手来源 | 2026-08 高盛 MarketBeta 的 Sector 标签就这么被误采信过；iShares 的 CSV 同理 |
| 拿到子行业名后凭印象敲代码 | 相邻子行业极易错（茅台 Brewers vs Distillers & Vintners），必须查 GICS 结构表 |
| 手改 `dossier_registry.json` | 下次 `rescan` 全部覆盖，白改 |
| 往 fetcher 手工加 ticker | 下次读取被自动生成覆盖；真正该改的是 `YF_SYMBOL_OVERRIDES`（且仅当 symbol ≠ ticker） |
| 忘了跑收尾校验 | 错误留给用户在几天后的扫描告警里发现 |
| 预取前先问用户“要不要下载” | 用户已明确要求这步自动做，多一次确认就是多一次打断 |
| **只跑 3a，漏 3b 纪要或 3c 财务底稿** | 档案 `raw/` 缺块，用户得回头催；2026-09-04 ADBE 连翻两次 |
| 把 3c 的「未命中指标」当失败重跑或报错 | 未命中多是公司本无该科目；只看勾稽未过项和 suspect_metrics |
| 在不通的 shell 里跑预取，然后报告成功 | 反爬拦截页也返回 200，脚本靠“小于 5000 字节即判失败”拦；别绕过这个判断，也别把失败说成成功 |
| registry 的 Valuation 块留 `- 待完成估值分析` 占位行 | `sync_valuations.py check` 当成 1 档区间，与 JSON `zones: []` 不一致报错 |
| changelog 用 `>>` 追加到文件尾 | 表格在文件中段，追到尾部会掉出表格外 |

## 相关

- 字段规范与重构背景：`_system/分类体系重构_影响面清单与方案.md`
- 校验工具：`_system/scripts/validate_taxonomy.py`（九类检查）
- 预取脚本：`_system/scripts/fetch_raw_filings.py`（三市场定期报告，3a）、`_system/scripts/fetch_transcripts.py`（美股 Motley Fool 纪要，3b）、`_system/scripts/fetch_edgar_financials.py`（美股 XBRL 财务底稿 v0.4.1，3c）
- 研究阶段：`company-dossier-build`（建档/迁移/全量重建）、`research-event-update`（事件驱动局部刷新）

## 版本

- **v3.3**（2026-09-11）：① **同步 schema 1.3**——`business_model` / `tier` / `needs_review` / `lifecycle` 四个自定义分类字段已从 registry 删除，GICS 四级代码成为唯一分类维度；JSON 模板、字段约束表、常见错误表全部跟改；`gics.confidence` 改由 C2 校验（此前无人管，写错会静默通过）；`gics_sector_names` 补齐 `"10"` 能源。② **「GICS 怎么查」整节重写**：判据收紧为“文件里必须有 GICS 声明”，给出 EDGAR 检索式与四个基金族的层级对照（Invesco AIM 系到四级、AB 到三级、Hartford 到二级、GS MarketBeta 到一级且只认 N-CSRS）；新增 A 股/港股/北交所专节（HSICS 无官方对照表、中证只能用一级、北交所永远查不到）；**废除 Vanguard 板块 ETF 反推**（不声明 GICS）并列出 iShares/Xtrackers/MSCI factsheet 等已证伪来源；confidence 改按“拿到第几级”定义，note 必须留 URL + 层级 + 推断边界。③ 归类原则补三个实测反直觉案例（美团=Restaurants、泡泡玛特=Specialty Retail、招商轮船=能源）和一个实际错误（茅台曾被记成 Brewers 且标 high）。
- **v3.2**（2026-09-04）：第 3 步再加 3c——`fetch_edgar_financials.py` 财务底稿改归本 skill 自动跑，不再推给 dossier-build 预检③（ADBE 入库第二次被指出漏项）。收尾交接强制列 raw 三块清单。
- **v3.1**（2026-09-04）：第 3 步拆成 3a 定期报告 + 3b 电话会纪要，接入 `fetch_transcripts.py v0.1`（2026-09-04 新增，AVGO 首用；ADBE 入库因 skill 未更新而漏跑，由用户指出）。补 `tier` 必填字段（schema 1.1）。更新宿主机渠道可达性实测（SEC / Fool 均通）。GICS 查到一手来源时明确写 high 并在 note 记 adsh。收尾校验补「与本次无关的既有 ERROR 如何处理」。
- **v3.0**（2026-08-31）：合并两条分叉。以分类体系重构版（companies.json 真相源 / GICS / tier / validate_taxonomy）为底，把 v2.1 的「预取原始材料」重新接回来，但**改成自动执行、不再先问用户**，且换掉实现——原 v2.1 依赖的 `mcp__workspace__web_fetch` 与巨潮 API 在当前环境都不可用，改为调 `_system/scripts/fetch_raw_filings.py`（东方财富 / 披露易 / EDGAR 三线，实测跑通）。同时吸收两处实跑偏差：registry 占位行会被 `sync_valuations` 误判为估值区间、changelog 表格在文件中段不能 `>>` 追加。
- **v2.1**（2026-08-29，已作废）：加了预取但从未安装；且不含分类体系重构，仍要求改 `market_data_fetcher.py` 与 `COMPANIES` 常量——这两项现在做了有害。