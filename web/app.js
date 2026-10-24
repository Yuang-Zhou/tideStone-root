'use strict';
let data=null;
const titles={overview:'公司总览',reports:'研究报告',targets:'目标价对比',briefings:'每日简报',paper:'模拟盘',status:'运行状态与使用说明'};
const statusNames={empty:'待研究',partial:'研究进行中',complete:'档案完整',stale:'需要更新',folder_missing:'目录缺失'};
const h=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const empty=(title,body)=>`<div class="empty"><div class="empty-mark">＋</div><h2>${h(title)}</h2><p>${h(body)}</p></div>`;
const metric=(n,label)=>`<div class="metric"><b>${h(n)}</b><span>${h(label)}</span></div>`;
const fmt=x=>x===undefined||x===null||x===''?'—':typeof x==='object'?JSON.stringify(x):String(x);
function docRows(docs){return docs.length?`<div class="doc-list">${docs.map(d=>`<div class="doc-row"><div><a href="${h(d.url)}">${h(d.title)} ↗</a><small>${h(d.ticker)} · ${h(d.kind)} · ${h(d.batch||'')} 更新 ${h(d.updated)}</small></div><span class="tag ${d.kind==='待审草稿'?'warn':''}">${h(d.kind)}</span></div>`).join('')}</div>`:empty('还没有研究报告','在 Codex 完成模块分析后，草稿会出现在这里。接受后成为正式档案，旧版会保留。');}
function card(c){return `<div class="card"><div class="card-head"><div><span class="ticker">${h(c.ticker)} / ${h(c.sector)}</span><h3>${h(c.name)}</h3></div><span class="tag ${c.status!=='complete'?'warn':''}">${h(statusNames[c.status]||c.status)}</span></div><p>材料 ${c.material_count} 份 · 待审 ${c.pending.length} 批 · 待处理事件 ${c.events.filter(e=>e.status==='open').length} 条</p><div class="modules">${c.modules.map(m=>m.url?`<a href="${h(m.url)}" title="${h(m.updated)}">${h(m.slot.slice(3,-3))}${m.stale?' · 待更新':''}</a>`:`<span>${h(m.slot.slice(3,-3))} · 缺</span>`).join('')}</div>${c.combined_url?`<a href="${h(c.combined_url)}">阅读已接受档案 →</a>`:''}<details><summary>材料、草稿与待办</summary>${c.material_count?c.materials.map(m=>`<p>材料：${h(m)}</p>`).join(''):'<p>尚未准备原始材料，请在 Codex 发起资料准备。</p>'}${c.pending.map(p=>`<p>待审批次 ${h(p.timestamp)} · ${h(p.trigger)}</p>${p.documents.map(d=>`<p><a href="${h(d.url)}">${h(d.title)}</a></p>`).join('')}`).join('')}${c.events.map(e=>`<p>事件：${h(e.title)} · ${h(e.status==='open'?'待处理':'已处理')}</p>`).join('')}</details></div>`;}
function overview(){let cs=data.companies;return `<div class="metrics">${metric(cs.length,'研究公司')}${metric(cs.filter(c=>c.status==='complete').length,'完整档案')}${metric(cs.reduce((n,c)=>n+c.pending.length,0),'待审批次')}${metric(cs.reduce((n,c)=>n+c.events.filter(e=>e.status==='open').length,0),'待处理事件')}</div><div class="intro"><span class="number">01</span><div><h2>把研究留成可以接着做的档案</h2><p>从材料到分析，从讨论到确认，每次修改都留下依据。</p><span class="say">对 Codex 说：“我想研究某家公司，请按潮石流程开始。”</span></div></div><div class="section-line"><h2>公司档案</h2><input id="search" aria-label="搜索公司" placeholder="搜索名称或股票代码"></div><div id="company-cards" class="cards">${cs.length?cs.map(card).join(''):empty('你的研究库是空白的','先在 Codex 建立第一个标的。这里会显示研究进度、缺少的材料、待审草稿和正式报告。')}</div>`;}
function number(value){
  if(typeof value==='number')return Number.isFinite(value)?value:null;
  if(typeof value!=='string'||!/^[-+]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/.test(value.trim()))return null;
  const n=Number(value.trim().replace(/,/g,''));return Number.isFinite(n)?n:null;
}
function priceNumber(value){
  if(typeof value!=='string')return number(value);
  return number(value.trim().replace(/^(?:USD|CNY|HKD|RMB|US\$|HK\$|\$|¥|￥)\s*/i,'').replace(/\s*(?:美元|港元|元)$/,''));
}
const decimal=(value,digits=2)=>{const n=number(value);return n===null?'—':n.toLocaleString('zh-CN',{maximumFractionDigits:digits});};
const percent=(value,signed=true)=>{const n=number(value);return n===null?'—':`${signed&&n>0?'+':''}${(n*100).toFixed(n!==0&&Math.abs(n)<0.001?2:1)}%`;};
const money=(value,currency='')=>number(value)===null?'—':`${decimal(value)}${currency?' '+currency:''}`;
const returnRate=(target,price)=>target!==null&&target>=0&&price!==null&&price>0?target/price-1:null;
const rateCell=value=>`<span class="numeric ${number(value)===null?'muted':value>0?'positive':value<0?'negative':''}">${h(percent(value))}</span>`;
const array=value=>Array.isArray(value)?value:[];
const texts=value=>Array.isArray(value)?value.filter(Boolean).map(String):value?[String(value)]:[];
const scenarioLabels={bear:'悲观',base:'基准',bull:'乐观',below_bear:'低于悲观',above_bull:'高于乐观',between:'档间'};
function targetRow(c){
  const v=c.valuation||{},t=c.three_year||{},p=data.prices?.[c.ticker]||{},sc=v.scenario_valuation?.scenarios||{};
  const dominant=v.scenario_valuation?.dominant,explicitTarget=priceNumber(v.target_price);
  const price=number(p.close),target=explicitTarget??priceNumber(sc[dominant]?.price),three=number(t.target_price_3y),anchor=number(t.anchor_price);
  const targetBasis=explicitTarget===null&&target!==null?`主导情景登记值 · ${scenarioLabels[dominant]||dominant}`:null;
  const currency=v.currency||c.currency||'',priceCurrency=p.currency||c.currency||v.currency||'';
  const threeCurrency=t.currency||({'$':'USD','US$':'USD','HK$':'HKD','¥':'CNY','￥':'CNY'}[t.currency_symbol])||currency;
  const sameCurrency=!!currency&&currency===priceCurrency;
  const sameThreeCurrency=!!threeCurrency&&threeCurrency===priceCurrency;
  const total=sameThreeCurrency?returnRate(three,price):null;
  const anchorTotal=returnRate(three,anchor);
  const valuationModule=array(c.modules).find(m=>m.slot?.startsWith('07_'));
  const missing=[];
  if(price===null||price<=0)missing.push('缺有效现价');
  if(!p.date)missing.push('缺行情日期');
  if(!currency)missing.push('缺报价币种');
  if(currency&&priceCurrency!==currency)missing.push('现价与研究目标币种不同');
  if(threeCurrency&&priceCurrency&&priceCurrency!==threeCurrency)missing.push('现价与三年目标币种不同');
  if(target===null)missing.push(v.target_price&&!/^(待|无|—)/.test(v.target_price)?'研究目标并非单一数值，未计算目标空间':'缺研究目标价');
  if(three===null)missing.push('缺三年目标价');
  if(!t.target_year)missing.push('缺三年目标年份');
  if(!t.valuation_method)missing.push('缺三年估值方法');
  if(!t.anchor_date||anchor===null)missing.push('缺完整建锚记录');
  if(['bear','base','bull'].some(k=>priceNumber(sc[k]?.price)===null))missing.push('三情景价格不完整');
  if(!valuationModule?.url)missing.push('缺已接受估值报告');
  const review=[...texts(t.recheck_reason),...texts(v.recheck_reason)];
  if(valuationModule?.stale)review.push('估值报告已标记需要更新');
  if((t.needs_recheck||v.needs_recheck)&&!review.length)review.push('登记表标记待复核');
  return {c,v,t,p,sc,price,target,targetBasis,three,anchor,currency,priceCurrency,threeCurrency,missing,review,valuationModule,
    upside:sameCurrency?returnRate(target,price):null,total,
    cagr:total===null?null:Math.pow(1+total,1/3)-1,
    anchorCagr:anchorTotal===null?null:Math.pow(1+anchorTotal,1/3)-1,
    recheck:!!(t.needs_recheck||v.needs_recheck||review.length),red:t.recheck_level==='red'||v.recheck_level==='red'};
}
function targetTable(rows){
  if(!rows.length)return empty('没有匹配的公司','调整名称、行业或资料筛选，或点击重置。');
  return `<div class="table-wrap"><table class="target-table"><caption class="sr-only">公司目标价、回报与资料状态比较</caption><thead><tr><th>公司 / 行业</th><th>现价 / 日期</th><th>研究目标价</th><th>目标空间</th><th>三年目标价</th><th>三年总回报</th><th>三年 CAGR</th><th>锚点起算 CAGR</th><th>悲观 / 基准 / 乐观</th><th>评级</th><th>三年估值锚</th><th>资料与复核</th></tr></thead><tbody>${rows.map(r=>`<tr>
    <td><strong>${h(r.c.name)}</strong><small>${h(r.c.ticker)} · ${h(r.c.sector)}</small></td>
    <td class="nowrap">${h(money(r.price,r.priceCurrency))}<small>${h(r.p.date||'无行情日期')}</small></td>
    <td class="target-source">${h(r.target===null?fmt(r.v.target_price):money(r.target,r.currency))}${r.targetBasis?`<small>${h(r.targetBasis)}</small>`:""}${r.v.target_price&&r.targetBasis?`<details><summary>原登记说明</summary><p>${h(r.v.target_price)}</p></details>`:""}${r.valuationModule?.url?`<small><a href="${h(r.valuationModule.url)}">估值报告 ↗</a></small>`:''}</td>
    <td>${rateCell(r.upside)}</td><td class="nowrap">${h(r.three===null?'待补录':money(r.three,r.threeCurrency))}<small>${h(r.t.target_year?`${r.t.target_year} 年`:'年份待补')}${(r.t.scenario||r.t.scenario_nearest)?' · '+h(scenarioLabels[r.t.scenario||r.t.scenario_nearest]||(r.t.scenario||r.t.scenario_nearest)):''}</small></td>
    <td>${rateCell(r.total)}</td><td>${rateCell(r.cagr)}</td><td>${rateCell(r.anchorCagr)}<small>${h(money(r.anchor,r.threeCurrency))}<br>${h(r.t.anchor_date||'建锚日期待补')}</small></td>
    <td class="nowrap">${['bear','base','bull'].map(k=>`<span class="scenario-price">${h(scenarioLabels[k])} ${h(money(priceNumber(r.sc[k]?.price),r.currency))}</span>`).join('')}</td>
    <td>${h(r.v.rating||'待评估')}</td><td class="target-source">${h(r.t.valuation_method||'待补录')}${number(r.t.target_multiple)!==null?`<small>倍数 ${h(decimal(r.t.target_multiple))}</small>`:''}</td>
    <td class="data-notes">${r.red?'<span class="tag danger">口径红旗</span>':r.recheck?'<span class="tag warn">待复核</span>':''}${r.missing.length?`<details><summary>缺项 ${r.missing.length} 项</summary><ul>${r.missing.map(x=>`<li>${h(x)}</li>`).join('')}</ul></details>`:'<span class="tag">资料齐备</span>'}${r.review.length?`<details><summary>复核依据</summary><ul>${r.review.map(x=>`<li>${h(x)}</li>`).join('')}</ul></details>`:''}</td>
  </tr>`).join('')}</tbody></table></div>`;
}
function targets(){
  const rows=data.companies.map(targetRow),sectors=[...new Set(data.companies.map(c=>c.sector||'待分类'))].sort((a,b)=>a.localeCompare(b,'zh'));
  return `<p class="muted">现价来自本地行情快照，目标价来自研究登记表。只用明确单值或已登记的主导情景价计算；原登记说明可展开核对，区间文字不自动取中值。</p>
    <div class="metrics">${metric(rows.length,'覆盖公司')}${metric(rows.filter(r=>r.target!==null).length,'可计算研究目标')}${metric(rows.filter(r=>r.three!==null).length,'已有三年目标')}${metric(rows.filter(r=>r.recheck).length,'登记表待复核')}</div>
    <div class="filter-bar" role="search" aria-label="筛选目标价"><label>公司或代码<input id="target-search" type="search" placeholder="名称或股票代码"></label><label>行业<select id="target-sector"><option value="">全部行业</option>${sectors.map(s=>`<option value="${h(s)}">${h(s)}</option>`).join('')}</select></label><label>资料状态<select id="target-coverage"><option value="">全部资料状态</option><option value="complete">已有三年目标价</option><option value="missing3y">三年目标价待补</option><option value="missing">任何资料缺项</option><option value="flagged">仅看口径红旗</option><option value="recheck">仅看待复核</option></select></label><button id="target-reset" type="button" class="quiet-button">重置</button></div>
    <p class="muted" id="target-count" aria-live="polite">${rows.length} 家公司</p><div id="target-results">${rows.length?targetTable(rows):empty('尚无可比较的目标价','完成公司研究并接受估值分析后，这里会列出目标价、三种情景和数据日期。')}</div>
    <details class="method-note"><summary>计算口径与缺项处理</summary><p>目标空间＝研究目标价÷现价−1；三年总回报＝三年目标价÷现价−1；三年 CAGR＝（三年目标价÷现价）的三分之一次方−1。锚点起算 CAGR 使用登记的建锚价格。均未计股息、费用或汇率变化。</p><p>沿用原站固定三年的比较口径，不按今天距目标年份的剩余时间重算。研究目标价不统一称为“12 个月目标”；它与三年目标可能使用不同日期和假设。只有同一报价币种才计算现价回报，缺项不会从文字或其他公司猜补。</p><p>待复核和红旗来自登记表及档案更新状态。拆股、ADS 比例变化、增发或回购后，应先在 Codex 核对每股口径。</p></details>`;
}
function bindTargetFilters(){
  const search=document.getElementById('target-search');if(!search)return;
  const sector=document.getElementById('target-sector'),coverage=document.getElementById('target-coverage');
  const apply=()=>{
    const query=search.value.trim().toLocaleLowerCase(),filter=coverage.value;
    const rows=data.companies.map(targetRow).filter(r=>(!query||`${r.c.name} ${r.c.ticker}`.toLocaleLowerCase().includes(query))&&(!sector.value||r.c.sector===sector.value)&&(!filter||({complete:r.three!==null,missing3y:r.three===null,missing:!!r.missing.length,flagged:r.red,recheck:r.recheck}[filter])));
    document.getElementById('target-count').textContent=`${rows.length} 家公司`;
    document.getElementById('target-results').innerHTML=targetTable(rows);
  };
  search.addEventListener('input',apply);sector.addEventListener('change',apply);coverage.addEventListener('change',apply);
  document.getElementById('target-reset').addEventListener('click',()=>{search.value='';sector.value='';coverage.value='';apply();});
}
function navChart(rows,benchmark){
  const points=array(rows).map(r=>({date:r.date,time:Date.parse(r.date),nav:number(r.nav_usd),bm:number(r.benchmark_close)})).filter(r=>Number.isFinite(r.time)).sort((a,b)=>a.time-b.time);
  const hasBenchmark=!!benchmark&&points.some(r=>r.nav>0&&r.bm>0);
  const base=points.find(r=>r.nav>0&&(!hasBenchmark||r.bm>0));
  if(!base)return empty('尚无可绘制的净值','生成有效的净值记录后，这里会显示模拟盘与基准的变化。');
  const plotted=points.filter(r=>r.time>=base.time),last=plotted[plotted.length-1],values=[];
  plotted.forEach(r=>{r.n=r.nav!==null&&r.nav>=0?r.nav/base.nav:null;r.b=hasBenchmark&&r.bm>0?r.bm/base.bm:null;if(r.n!==null)values.push(r.n);if(r.b!==null)values.push(r.b);});
  const low=Math.min(...values,1),high=Math.max(...values,1),pad=Math.max((high-low)*.15,.005),lo=low-pad,hi=high+pad;
  const width=860,height=270,left=68,right=22,top=18,bottom=38;
  const x=time=>left+(time-base.time)/(last.time-base.time||1)*(width-left-right),y=value=>top+(hi-value)/(hi-lo)*(height-top-bottom);
  const series=(key,klass)=>{
    let paths=[],segment=[];
    const finish=()=>{if(segment.length)paths.push(`<polyline class="${klass}" points="${segment.join(' ')}"/>`);segment=[];};
    plotted.forEach(r=>{if(r[key]===null){finish();return;}segment.push(`${x(r.time).toFixed(1)},${y(r[key]).toFixed(1)}`);});finish();
    return paths.join('')+plotted.filter(r=>r[key]!==null).map(r=>`<circle class="${klass}-point" cx="${x(r.time).toFixed(1)}" cy="${y(r[key]).toFixed(1)}" r="2.4"><title>${h(r.date)} · ${h(key==='n'?'模拟盘':benchmark)} ${h(percent(r[key]-1))}</title></circle>`).join('');
  };
  const grid=Array.from({length:5},(_,i)=>{const value=lo+(hi-lo)*i/4,py=y(value);return `<line class="chart-grid" x1="${left}" x2="${width-right}" y1="${py}" y2="${py}"/><text x="${left-10}" y="${py+4}" text-anchor="end">${h(percent(value-1))}</text>`;}).join('');
  return `<div class="chart-card"><div class="chart-legend"><span><i class="legend-line"></i>模拟盘</span>${hasBenchmark?`<span><i class="legend-line benchmark"></i>${h(benchmark)}</span>`:'<span class="muted">基准行情待补</span>'}</div><svg class="nav-chart" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="nav-chart-title nav-chart-description"><title id="nav-chart-title">模拟盘${hasBenchmark?'与 '+h(benchmark):''}的净值变化</title><desc id="nav-chart-description">以 ${h(base.date)} 可见记录为共同起点比较回报，缺失数据不连线。</desc>${grid}${hasBenchmark?series('b','chart-benchmark'):''}${series('n','chart-nav')}<text x="${left}" y="${height-10}">${h(base.date)}</text><text x="${width-right}" y="${height-10}" text-anchor="end">${h(last.date)}</text></svg><p class="muted">图中以 ${h(base.date)} 的记录同时归一为 0%，展示当前可见区间；与账户从初始化起的累计收益口径可能不同。缺失点断线，不补行情。</p></div>`;
}
function holdingsTable(p){
  const latest=p.latest||{},state=p.state||{};
  const complete=Array.isArray(latest.holdings);
  const rows=complete?latest.holdings:Object.entries(state.holdings||{}).map(([ticker,r])=>({...r,ticker,status:'缺当日持仓快照'}));
  if(!rows.length)return empty('当前没有持仓','模拟盘已初始化；是否建仓由真实估值、行情和策略条件决定。');
  return `${complete?'':'<p class="muted">仅有账户记录；当日价格、权重和损益留空，待运行生成持仓快照。</p>'}<div class="table-wrap"><table><thead><tr><th>公司</th><th>权重 / 目标</th><th>股数</th><th>价格 / 日期</th><th>持仓盈亏</th><th>上行 / 下行</th><th>上行下行比</th><th>三年 CAGR</th><th>建仓日</th><th>状态</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${h(r.ticker)}</strong><small>${h(r.name||'')}</small></td><td class="nowrap">${h(percent(r.weight,false))}<small>目标 ${h(percent(r.target_weight,false))}</small></td><td>${h(decimal(r.qty,6))}</td><td class="nowrap">${h(money(r.price_local,r.currency))}<small>${h(r.price_date||'日期待补')}</small></td><td>${rateCell(r.pnl_pct)}</td><td class="nowrap">${h(percent(r.upside))} / ${h(percent(number(r.downside)===null?null:-number(r.downside)))}</td><td>${h(decimal(r.b))}</td><td>${rateCell(r.cagr_3y)}</td><td class="nowrap">${h(r.entered||'—')}</td><td>${h(r.status||'—')}</td></tr>`).join('')}</tbody></table></div>`;
}
function candidatesTable(p){
  const rows=Array.isArray(p.latest?.candidates)?p.latest.candidates:array(p.candidates);
  if(!rows.length)return empty('尚无候选评估记录','执行模拟盘日常评估后，这里显示入选结果与每家公司的未入选原因。');
  return `<div class="table-wrap"><table><thead><tr><th>公司</th><th>目标权重</th><th>现价 / 日期</th><th>上行</th><th>三年 CAGR</th><th>上行下行比</th><th>主导情景 / 置信</th><th>评估结果与原因</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${h(r.ticker)}</strong><small>${h(r.name||'')}</small></td><td>${h(percent(r.target_weight,false))}</td><td class="nowrap">${h(money(r.price,r.currency))}<small>${h(r.price_date||'日期待补')}</small></td><td>${rateCell(r.upside)}</td><td>${rateCell(r.cagr_3y)}</td><td>${h(decimal(r.rr??r.b))}</td><td>${h(scenarioLabels[r.dominant]||r.dominant||'—')} / ${h(r.confidence||'—')}</td><td><span class="tag ${r.eligible?'':'warn'}">${r.eligible===true?'符合条件':r.eligible===false?'未入选':'待评估'}</span><small>${h(r.reason||'未记录原因')}</small></td></tr>`).join('')}</tbody></table></div>`;
}
function ledgerTable(rows){
  if(!array(rows).length)return empty('暂无成交记录','没有满足条件的交易时保持空白；相同日期重跑不会在页面补造交易。');
  return `<div class="table-wrap"><table><thead><tr><th>日期</th><th>标的</th><th>方向</th><th>股数</th><th>成交价</th><th>金额 USD</th><th>依据</th></tr></thead><tbody>${rows.slice(-40).reverse().map(r=>`<tr><td class="nowrap">${h(r.date)}</td><td>${h(r.ticker)}</td><td>${h({BUY:'买入',SELL:'卖出'}[r.side]||r.side)}</td><td>${h(decimal(r.qty,6))}</td><td class="nowrap">${h(money(r.price_local,r.currency))}</td><td>${h(decimal(r.amount_usd))}</td><td>${h(r.reason||'未记录依据')}</td></tr>`).join('')}</tbody></table></div>`;
}
function paperRules(cfg){
  if(!Object.keys(cfg).length)return '<p class="muted">策略配置尚未保存。初始化后将展示实际使用的规则与交易假设。</p>';
  const list=(object,suffix)=>Object.entries(object||{}).map(([key,value])=>`${key} ${decimal(value,6)}${suffix}`).join('；')||'待补';
  return `<details class="method-note"><summary>当前策略规则与交易假设</summary><p>主导情景：${h(array(cfg.require_dominant).map(x=>scenarioLabels[x]||x).join('、')||'待补')}；到基准价上行至少 ${h(percent(cfg.min_upside_to_base,false))}；到悲观价下行不超过 ${h(percent(cfg.max_downside_to_bear,false))}；三年 CAGR 至少 ${h(percent(cfg.min_cagr_3y,false))}。持仓退出线：上行低于 ${h(percent(cfg.exit_upside_to_base,false))} 或三年 CAGR 低于 ${h(percent(cfg.exit_cagr_3y,false))}。</p><p>配置方式：${h({equal:'等权',risk_reward:'按上行下行比'}[cfg.sizing]||cfg.sizing||'待补')}；单票上限 ${h(percent(cfg.max_weight,false))}；总投入上限 ${h(percent(cfg.max_gross,false))}；滑点 ${h(percent(cfg.slippage,false))}。整手：${h(list(cfg.lot_size,' 股'))}。固定汇率（兑 USD）：${h(list(cfg.fx_to_usd,''))}。</p><p>行情用于成交的最长间隔 ${h(fmt(cfg.max_trade_staleness_days))} 个自然日，另外仍需满足市场基准日期检查。以上为当前配置，不代表真实账户已接通。</p></details>`;
}
function paper(){
  const p=data.paper||{},state=p.state||{},summary=p.summary||{},latest=p.latest||{},cfg=p.config||{};
  if(!Object.keys(state).length&&!Object.keys(latest).length)return empty('模拟盘尚未启用','先形成有来源的三情景估值、三年目标与新鲜行情，再对 Codex 说“初始化潮石模拟盘，使用多少虚拟资金”。正式账户不会被连接。')+`<div class="card paper-rules"><h3>策略准备</h3><p>模拟盘依据研究中的基准与悲观情景、三年回报和行情日期评估候选。初始化时请核对虚拟资金、仓位上限、整手、滑点与汇率。</p>${paperRules(cfg)}</div>`;
  const benchmark=latest.benchmark||cfg.benchmark||'',nav=number(summary.nav)??number(latest.nav_usd),cash=number(latest.cash_usd)??number(state.cash_usd);
  const holdings=number(summary.holds)??Object.keys(state.holdings||{}).length;
  return `<div class="notice">这是虚拟记账。结果取决于行情、估值与策略配置，并不代表真实可成交收益。</div><div class="section-line"><div><h2>${h(cfg.name||'策略模拟盘')}</h2><p class="muted">起始 ${h(state.start_date||cfg.start_date||'待补')} · 初始资金 ${h(money(cfg.start_capital_usd,'USD'))} · 最近记账 ${h(summary.asof||latest.date||state.last_run||'尚未运行')}<br>持仓最旧行情 ${h(summary.px_asof||'未记录')} · 基准行情 ${h(latest.benchmark_date||'未记录')}</p></div></div>
    <div class="metrics paper-metrics">${metric(money(nav,'USD'),'账户净值')}${metric(percent(summary.ret),'初始化以来收益')}${metric(percent(summary.bm_ret),`${benchmark||'市场基准'} 同期收益`)}${metric(percent(summary.mdd),'最大回撤')}${metric(percent(summary.cash_pct,false),`现金 · ${money(cash,'USD')}`)}${metric(holdings,'持仓数量')}</div>
    ${number(summary.stale)>0||number(summary.blocked)>0?`<div class="notice">${h(fmt(summary.stale))} 只持仓行情过期；${h(fmt(summary.blocked))} 次交易被拦截。${texts(summary.blocked_lines).map(x=>`<p>${h(x)}</p>`).join('')}</div>`:''}
    ${navChart(p.nav,benchmark)}<div class="section-line"><h2>持仓</h2><span class="muted">快照 ${h(latest.date||'待补')}</span></div>${holdingsTable(p)}<div class="section-line"><h2>候选池与未入选原因</h2></div>${candidatesTable(p)}<div class="section-line"><h2>最近 40 笔成交</h2></div>${ledgerTable(p.ledger)}${paperRules(cfg)}<details class="method-note"><summary>查看净值原始记录</summary>${records(array(p.nav))}</details>`;
}
function records(rows){if(!rows.length)return empty('暂无记录','运行后会保留真实生成的记录。');let keys=Object.keys(rows[0]);return `<div class="table-wrap"><table><thead><tr>${keys.map(k=>`<th>${h(k)}</th>`).join('')}</tr></thead><tbody>${rows.slice(-30).reverse().map(r=>`<tr>${keys.map(k=>`<td>${h(fmt(r[k]))}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function systemStatus(){let p=data.pipeline,s=data.scheduler;return `<div class="intro"><div><h2>从“我想研究某家公司”开始</h2><p>在此项目的 Codex 聊天中提出问题。你可以随时讨论、修订、接受或退回，换一段聊天也能从文件继续。</p></div></div><div class="small-grid"><div class="card"><h3>可以对 Codex 说</h3><p>“为这家公司准备公开资料，并告诉我缺什么。”</p><p>“按原七模块分析，先生成待审草稿。”</p><p>“这项预测太乐观，请解释依据并修订。”</p><p>“接受这一批草稿，生成研究总结。”</p><p>“公司出了新财报，先对照原预测，再评估哪些模块需要更新。”</p></div><div class="card"><h3>当前能力</h3><p>研究推理：在 Codex 中调用项目 Skills。</p><p>本地阅读：公司、报告、目标价、简报与模拟盘。</p><p>行情和公告：按来源可达性及依赖实测；缺失会保留提示。</p><p>定时状态：${h(s.status||'未启用')}。</p><p>固定原方法版本：${h(data.source_commit?.slice(0,12))}。</p></div></div><div class="section-line"><h2>最近一次日常任务</h2></div>${Object.keys(p).length?`<div class="card"><p>执行时间：${h(p.finished_at||p.started_at)} · ${h(p.status)}</p>${(p.steps||[]).map(x=>`<p>${h(x.name)}：${h(x.status)} ${h(x.detail||'')}</p>`).join('')}</div>`:empty('尚未运行日常任务','可以对 Codex 说“执行一次潮石日常更新，并说明哪些步骤成功、哪些没有接通”。')}`;}
function render(){if(!data)return;let tab=location.hash.slice(1)||'overview';if(!titles[tab])tab='overview';document.getElementById('page-title').textContent=titles[tab];document.querySelectorAll('[data-tab]').forEach(a=>a.classList.toggle('active',a.dataset.tab===tab));document.getElementById('test-banner').hidden=!data.isolated;let content=document.getElementById('content');if(tab==='overview')content.innerHTML=overview();if(tab==='reports')content.innerHTML=`<div class="section-line"><p class="muted">草稿、正式版本与历史记录分别标注。</p><select id="report-filter" aria-label="报告类型"><option>全部</option><option>待审草稿</option><option>正式档案</option><option>研究总结</option><option>历史档案</option><option>预测偏差</option></select></div><div id="report-list">${docRows(data.reports.filter(d=>d.kind!=='每日简报'))}</div>`;if(tab==='targets'){content.innerHTML=targets();bindTargetFilters();}if(tab==='briefings')content.innerHTML=`<p class="muted">日常扫描的事实、需要复核的判断与运行缺口。没有执行分析的日期不会自动生成研究简报。</p>${data.briefings.length?docRows(data.briefings):empty('还没有每日简报','完成首次研究后，可在 Codex 运行每日扫描。当地任务只负责数据和运行检查，不会伪造新闻判断。')}`;if(tab==='paper')content.innerHTML=paper();if(tab==='status')content.innerHTML=systemStatus();document.getElementById('updated').textContent='视图生成于 '+data.built_at;document.getElementById('search')?.addEventListener('input',e=>{let q=e.target.value.toLowerCase();let cs=data.companies.filter(c=>(c.ticker+c.name).toLowerCase().includes(q));document.getElementById('company-cards').innerHTML=cs.length?cs.map(card).join(''):empty('没有匹配的公司','请试试名称或股票代码。');});document.getElementById('report-filter')?.addEventListener('change',e=>{document.getElementById('report-list').innerHTML=docRows(data.reports.filter(d=>d.kind!=='每日简报'&&(e.target.value==='全部'||d.kind===e.target.value)));});}
async function refresh(){try{let r=await fetch('data.json',{cache:'no-store'});if(!r.ok)throw new Error(r.status);data=await r.json();render();}catch(e){document.getElementById('content').innerHTML=empty('本地数据暂时不可读取','请让 Codex 运行本地数据更新，然后刷新。错误：'+e.message);}}
window.addEventListener('hashchange',render);document.getElementById('refresh').addEventListener('click',refresh);refresh();
