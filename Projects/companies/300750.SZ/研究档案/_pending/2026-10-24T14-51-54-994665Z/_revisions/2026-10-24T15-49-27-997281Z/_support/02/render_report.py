from pathlib import Path
import json,statistics
P=Path(__file__).resolve().parent
j=json.loads((P/'analysis_inputs_results.json').read_text());D=j['data'];YS=['2021','2022','2023','2024','2025'];T=D['TTM'];L=D['2026_9M'];A=D['2025'];B=D['2024']
def n(v):return 'n/a' if v is None else f'{v:,.1f}'
def ratio(d,a,b):return d[a]/d[b] if a in d and b in d and d[b] else None
def pct(v):return 'n/a' if v is None else f'{v*100:.2f}%'
def x(v):return 'n/a' if v is None else f'{v:.2f}×'
def table(head,rows):return '| '+' | '.join(head)+' |\n|'+ '|'.join([' :-- ']*len(head))+'|\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)+'\n'
def vals(key,inst=False):return [n(D[y].get(key)) for y in YS]+[n((L if inst else T).get(key))]
def derived(d,key):
 if key=='gross':return ratio({'g':d.get('revenue',0)-d.get('cost_of_sales',0),'r':d.get('revenue',0)},'g','r') if 'cost_of_sales' in d else None
 if key=='netcash':return '净现金' if 'net_cash_conservative' in d else 'n/a'
 a,b={'op':('operating_profit','revenue'),'net':('net_profit','revenue'),'ocf':('operating_cash_flow','net_profit'),'fcf':('fcf','revenue'),'capex':('cash_paid_for_long_lived_assets','revenue'),'ppe':('ppe_net','total_assets'),'cashcover':('ending_cash_equivalents','current_portion_of_noncurrent_liabilities'),'current':('current_assets','current_liabilities'),'sbcocf':('sbc','operating_cash_flow')}[key]
 return ratio(d,a,b)
head=['百万元CNY（股数百万股）']+YS+['TTM/2026-09-30']
base='### 0b 脚本生成的数据底座\n\n'
base+=table(head,[[label]+vals(k) for label,k in [('收入','revenue'),('营业成本','cost_of_sales'),('研发','research_and_development_expenses'),('管理费用','admin'),('销售费用','selling_expenses'),('折旧摊销','da'),('CAS营业利润','operating_profit'),('计入损益利息','interest_expensed'),('税前利润','profit_before_tax'),('所得税','income_tax_expense'),('合并净利润','net_profit'),('归母净利润','net_profit_parent'),('扣非归母','parent_adj'),('SBC费用','sbc')]])
base+='\n'+table(head,[[label]+vals(k,True) for label,k in [('现金及等价物','ending_cash_equivalents'),('货币资金（另一口径）','monetary_funds'),('应收账款净额','trade_receivables'),('存货净额','inventories'),('固定资产净值','ppe_net'),('使用权资产','rou'),('商誉','goodwill'),('无形资产','intangibles'),('总资产','total_assets'),('应付账款','ap'),('应付票据','notes_payable'),('合同负债','contract_liabilities'),('有息债务含租赁/代理','debt_proxy'),('合并权益','total_equity'),('有形权益','tangible_equity'),('期末全部A+H股数','shares_outstanding')]])
base+='\n'+table(head,[[label]+vals(k) for label,k in [('经营现金流','operating_cash_flow'),('现金资本开支代理','cash_paid_for_long_lived_assets'),('FCF代理','fcf'),('取得子公司现金净支出','acquisitions'),('回购现金','buyback'),('分红实际现金（已拆利息）','dividends_paid'),('净还债现金','net_debt_repay'),('实付所得税','income_taxes_paid')]])
rr=[]
for label,key,fmt in [('毛利率*','gross',pct),('营业利润率','op',pct),('合并净利率','net',pct),('OCF/合并净利','ocf',x),('FCF代理/收入','fcf',pct),('现金Capex/收入','capex',pct),('固定资产/总资产','ppe',pct),('流动比率','current',x),('SBC/OCF','sbcocf',pct)]:
 rr.append([label]+[fmt(derived(D[y],key)) for y in YS]+[fmt(derived(L if key in ['ppe','current'] else T,key))])
base+='\n'+table(['比率']+YS+['TTM/最新'],rr)
base+='\n2021已由本批原年报p108–120补齐主要报表；仍缺字段n/a。2021–22成本*未经质保重分类；2023起采用后报比较口径。CAS营业利润包含投资收益、其他收益及财务费用，不能直接等同美式EBIT。FCF代理=OCF−购建长期资产现金，不含并购、租赁本金，不区分维持/扩张；不把该代理叫可分配股东现金。2025股份支付负数是转回，不能机械外推。最新债务代理包含一年内长期应付款，略高估债务；2024/25已剔55.0/55.3百万元。短期理财未纳入保守可用现金。\n'
base+='\n'+table(['补充体检（最新完整年报）','2024','2025','最新期末'],[
['现金/一年内到期有息债务',x(B['ending_cash_equivalents']/(B['short_term_borrowings']+B['current_portion_of_noncurrent_liabilities']-55.039)),x(A['ending_cash_equivalents']/(A['short_term_borrowings']+A['current_portion_of_noncurrent_liabilities']-55.291)),x(L['ending_cash_equivalents']/(L['short_term_borrowings']+L['current_portion_of_noncurrent_liabilities']))],
['速动比率',x((B['current_assets']-B['inventories'])/B['current_liabilities']),x((A['current_assets']-A['inventories'])/A['current_liabilities']),x((L['current_assets']-L['inventories'])/L['current_liabilities'])],
['坏账准备/应收毛额','3.95%','3.55%','n/a'],['存货跌价准备/毛额','9.20%','7.55%','n/a'],['固定资产折旧/期末原值','12.04%','9.99%','n/a'],['递延税资产/总资产',pct(B['dta']/B['total_assets']),pct(A['dta']/A['total_assets']),pct(L['dta']/L['total_assets'])],['受限货币资金',n(B['restricted_cash']),n(A['restricted_cash']),'n/a'],['债务3年内本金占比/浮动占比','n/a','n/a','n/a'],['OCF/实付利息','n/a','n/a','n/a']])
base+='\n一次性候选（百万元；按原件核性质，不将反复发生的减值全数加回）：\n\n'+table(['年','科目','金额','性质与处理','原文'],[['2023','归母非经常性净收益','4,029.6','剔除；保留正常减值成本','2025年报p12'],['2024','归母非经常性净收益','5,751.8','剔除','2024年报p228'],['2025','资产处置/金融估值处置/其他非经常项目','788.3/1,362.5/8,704.0','按披露扣税及少数股东后归母净收益7,693.4剔除','2025年报p231'],['2025','资产减值/信用减值','8,660.2/418.6','保留：存货与产线迭代反复发生','2025年报p197–198'],['2025','股份支付转回','82.5','CAS包含，未来不延续负费用；仅作敏感性','2025年报p220']])
base+='\n剔非CAS营业利润：2023 47,909.8、2024 55,522.4、2025 78,634.9；合并扣非净利：41,950.8、47,140.4、67,912.2。以上仍含经常性利息/联营收益，不能视作纯电池利润；TTM扣非归母78,764.4可算，TTM扣非营业/合并利润缺同期明细填n/a。\n'
(P/'data_tables.md').write_text(base)
# Handoff baseline: null explicitly represents an unavailable number.
baseline={}
config=[('revenue_growth','收入增速','pct'),('gross_margin','毛利率*','pct'),('operating_margin','剔非营业利润率','pct'),('net_margin','剔非合并净利率','pct'),('tax_rate','有效税率','pct'),('nwc_to_revenue','经营性营运资金/收入','pct'),('capex_to_revenue','现金Capex代理/收入','pct'),('da_to_revenue','折旧摊销/收入','pct'),('sbc_to_revenue','SBC/收入','pct'),('ocf_to_ni','OCF/剔非合并净利','x'),('share_count_change','稀释股本变动率','pct'),('roic_ex_goodwill','ROIC不含商誉','pct'),('incremental_op_margin','3年增量营业利润率','pct'),('net_debt_to_ebitda','净负债/EBITDA','str'),('interest_coverage','剔非营业利润/利息','x')]
for key,label,fmt in config:
 v={}
 for i,y in enumerate(YS+['TTM']):
  d=D[y];z=None
  if key=='revenue_growth' and y!='TTM' and str(int(y)-1) in D:z=d['revenue']/D[str(int(y)-1)]['revenue']-1
  elif key=='gross_margin':z=derived(d,'gross')
  elif key=='operating_margin':z=ratio(d,'op_adj','revenue')
  elif key=='net_margin':z=ratio(d,'net_adj','revenue')
  elif key=='tax_rate':z=ratio(d,'income_tax_expense','profit_before_tax')
  elif key=='capex_to_revenue':z=ratio(d,'cash_paid_for_long_lived_assets','revenue')
  elif key=='da_to_revenue':z=ratio(d,'da','revenue')
  elif key=='sbc_to_revenue':z=ratio(d,'sbc','revenue')
  elif key=='ocf_to_ni':z=ratio(d,'operating_cash_flow','net_adj')
  elif key=='net_debt_to_ebitda':z='净现金' if (y=='TTM' or 'net_cash_conservative' in d) else None
  elif key=='interest_coverage':z=ratio(d,'op_adj','interest_expensed')
  v[['fy_5','fy_4','fy_3','fy_2','fy_1','ttm'][i]]=z
 v['avg5']=(D['2025']['revenue']/D['2020']['revenue'])**.2-1 if key=='revenue_growth' else (statistics.mean([v[k] for k in ['fy_5','fy_4','fy_3','fy_2','fy_1']]) if key not in ['gross_margin','net_debt_to_ebitda'] and all(isinstance(v[k],(int,float)) for k in ['fy_5','fy_4','fy_3','fy_2','fy_1']) else None);v['trend']='无规律' if key in ['gross_margin','tax_rate','capex_to_revenue','ocf_to_ni','sbc_to_revenue','interest_coverage','revenue_growth'] else ('上行' if key in ['operating_margin','net_margin'] else '无规律')
 v['trend_scope']='仅有可比年度；不包含TTM；不足完整五年'
 baseline[key]=v
baserows=[]
for key,label,fmt in config:
 v=baseline[key];formatter=pct if fmt=='pct' else x if fmt=='x' else lambda q:q or 'n/a'
 baserows.append([label]+[formatter(v[k]) for k in ['fy_5','fy_4','fy_3','fy_2','fy_1']]+[formatter(v['avg5']),v['trend'],formatter(v['ttm'])])
F3table=table(['比率']+YS+['5年','方向†','TTM'],baserows)
cap_fields={'capex':'cash_paid_for_long_lived_assets','rnd':'research_and_development_expenses','ma':'acquisitions','buyback':'buyback','dividend':'dividends_paid','net_debt_repay':'net_debt_repay','sbc':'sbc'}
capital={k:None for k in cap_fields};capital['ocf_total']=sum(D[y]['operating_cash_flow'] for y in YS)
for k,field in cap_fields.items():
 if all(field in D[y] for y in YS):capital[k]=sum(D[y][field] for y in YS)
capital['what_money_says']='从扩产、研发与现金留存转为继续扩产并加强回报；2026供应链支持占用资金，不能只看账面现金。'
capital['comparison_note']='研发支出已影响经营现金流，其金额/OCF仅作投入强度对照；不能与Capex、回购等相加为现金用途100%。'
capital['observed_partial']={k:{'years':[y for y in YS if field in D[y]],'value':(sum(D[y][field] for y in YS if field in D[y]) if any(field in D[y] for y in YS) else None)} for k,field in cap_fields.items()}
(P/'capital_ledger.md').write_text(table(['用途']+YS+['五年累计（完整才给）'],[[k]+[n(D[y].get(field)) for y in YS]+[n(capital[k])] for k,field in cap_fields.items()]))
F4rows=[]
for key,label in [('capex','资本开支代理'),('rnd','研发'),('ma','并购现金（不含未拆购买少数股权）'),('buyback','回购现金'),('dividend','分红实际现金'),('net_debt_repay','净还债'),('sbc','SBC非现金')]:
 o=capital['observed_partial'][key];F4rows.append([label,n(capital[key]),pct(capital[key]/capital['ocf_total']) if capital[key] is not None else 'n/a',('已核'+','.join(o['years'])+'合计'+n(o['value'])) if o['years'] else '缺分红与利息现金拆分'])
F2=[['债务规模：净负债/EBITDA','净现金180,328.5','净现金代理143,471.4','无规律','仅现金等价物减债务，理财未加','无'],['偿付：利息覆盖/FCF债务','28.76×/75.98%','n/a/31.47%','无规律','剔非CAS营业利润，非纯EBIT','无'],['流动性：现金/一年债务','8.54×','5.87×（代理）','无规律','只计可随时支付现金','无'],['到期与利率：3年/浮动','n/a/n/a','n/a/n/a','无规律','到期表仅2–5年，不能硬拆3年','缺口'],['表外：租赁/担保/或有','租赁付款4,029.0；外保4,663.5','本稿核2025年报，H1未逐项刷新','无规律','另有资本承诺13,726.0；集团内担保另列','无'],['商誉无形：资产占比/headroom','1.65%/n/a','1.43%/n/a','无规律','商誉减值47.5已确认','无'],['应收：增速差/准备率','+2.09pt/3.55%','同年初+47.78%，非同比','无规律','账龄>1年3.67%，上年3.29%','黄'],['存货：增速差/产成品占比','+40.94pt/25.50%','年初+53.15%，非同比','无规律','含发出商品占64.77%；上年59.18%','黄'],['软资产：研发资本化/DTA','0%/2.89%','n/a/2.82%','无规律','2025全部研发费用化；折旧率下行待跟踪','无']]
flags=['存货扩张、产成品与发出商品占比增加且跌价准备率下降','应收准备率下降且一年以上账龄占比略升，尚不构成坏账失真判断','2026Q3单季FCF代理转负，供应链支持和验收周期拖累现金转化']
claims=[{'who':'2026-10-20官方业绩会p2','claim':'库存增长主要为发出商品，周转相对稳定，没有销售不畅','data_says':'2025存货增57.98%而收入增17.04%；2026Q3存货较年初增53.15%，缺单季结构及同季存量','verdict':'数据不足'}, {'who':'2026-10-20官方业绩会p3','claim':'缩短账期、预付款支持供应商，现金流阶段承压后恢复','data_says':'前三季OCF降23.60%；Q3单季OCF14.09亿元、预付款年初升85.26%，支持已发生的承压方向；未来恢复尚未验证','verdict':'数据不足'}, {'who':'2026-07-24官方业绩会p2与10-20 p1','claim':'长期单位盈利稳定，Q3受产品结构及税费影响','data_says':'9M毛利率25.31%→22.72%、Q3毛利率20.69%说明短期利润率承压；长期元/Wh盈利缺同口径销量及利润构成，不能据单季率值判证伪','verdict':'数据不足'}, {'who':'2025年报p31','claim':'资产和信用减值不具可持续性','data_says':'2023–25资产减值58.54/84.23/86.60亿元，均有大额减值','verdict':'不一致'}]
judgments=[{'claim':'销售规模扩张仍能盈利，但单位经济已承压','why':'2026Q3毛利率20.69%，单季收入增58.58%而归母增14.54%','wrong_if':'连续两个季度同口径毛利率恢复≥25%，扣非归母率≥15%，且不是补贴/估值收益','owner':'03/06/下季财报'}, {'claim':'现金优势能吸收现有扩产，但历史现金转化不可照搬','why':'最新已列债务口径净现金代理1434.71亿元；Q3 FCF代理-156.86亿元','wrong_if':'未来两个季度OCF/合并净利仍<1且债务增加超过现金增加，转入融资约束情景','owner':'04/06'}, {'claim':'存货是最值得验证的资产质量环节','why':'2025存货增速超过收入40.94pt，跌价率9.20%→7.55%','wrong_if':'库存/收入回落且发出商品转化为收入和现金，同时没有大额新增跌价','owner':'03/下季财报'}, {'claim':'利润率上沿受税费、产品结构和客户分担能力约束','why':'2025扣非归母率15.22%高于2026Q3单季11.42%，规模扩大未抵消压力','wrong_if':'连续两季扣非归母率≥15%且经营现金流同步恢复，则上沿约束打开；若<12%持续则下修基线','owner':'03/06/07'}]
H={'handoff_version':3,'fiscal_years':['FY'+y for y in YS],'ttm_end':'2026-09-30','basis':'CAS; reported plus explicitly adjusted; no IFRS mixing','restated':True,'one_offs_removed':['2023–25按公司非经常性损益表剔除处置、估值及其他非经常收益；资产减值保留','TTM仅扣非归母具备完整计算输入；扣非CAS营业与合并净利为null；CAS营业利润含财务费用、投资及公允价值/其他收益，不是DCF经营EBIT，FCF代理不是去杠杆FCFF'],'company_type':{'asset':'重','stage':'成长','cashflow':'周期'},'numbers_only_profile':'研发密集、供应链融资支持的规模制造；利润增长已快于现金兑现','financial_safety':{'verdict':'未发现12个月偿债红旗；最新已列债务口径净现金代理143471.436百万元，存货和账期是主要黄旗','net_debt_to_ebitda':{'fy_1':'净现金','latest':'净现金','trend':'无规律'},'interest_coverage':{'fy_1':A['op_adj']/A['interest_expensed'],'ttm':None,'trend':'无规律'},'fcf_to_debt':{'fy_1':A['fcf']/A['debt_proxy'],'ttm':T['fcf']/L['debt_proxy']},'cash_to_debt_due_1y':{'latest':L['ending_cash_equivalents']/(L['short_term_borrowings']+L['current_portion_of_noncurrent_liabilities'])},'debt_due_3y_pct':None,'floating_rate_pct':None,'off_balance_sheet':'FY2025租赁付款4028.984、外部担保4663.512、资本承诺13726.018百万元；集团内担保49555.686未重复加债','goodwill_intangibles_to_assets':{'fy_1':(A['goodwill']+A['intangibles'])/A['total_assets'],'latest':(L['goodwill']+L['intangibles'])/L['total_assets'],'trend':'无规律'},'impairment_headroom_min_pct':None,'tangible_equity':L['tangible_equity'],'receivables_growth_gap_pt':{'fy_2':(B['trade_receivables']/D['2023']['trade_receivables']-B['revenue']/D['2023']['revenue'])*100,'fy_1':(A['trade_receivables']/B['trade_receivables']-A['revenue']/B['revenue'])*100},'bad_debt_reserve_pct':.0355,'inventory_growth_gap_pt':{'fy_2':(B['inventories']/D['2023']['inventories']-B['revenue']/D['2023']['revenue'])*100,'fy_1':(A['inventories']/B['inventories']-A['revenue']/B['revenue'])*100},'capitalization_ratio':{'fy_5':None,'fy_1':0},'red_flags':[],'yellow_flags':flags,'watch_12m':'未来两个季度OCF/合并净利<1且净现金下降；若现金/一年债务<1升级流动性预警'},'base_year':{'currency':'CNY','unit':'million','fy_1':{'revenue':A['revenue'],'op_income_adj':A['op_adj'],'net_income_adj':A['net_adj'],'parent_net_income_adj':A['parent_adj'],'da':A['da'],'capex':A['cash_paid_for_long_lived_assets'],'ocf':A['operating_cash_flow'],'sbc':A['sbc']},'ttm':{'revenue':T['revenue'],'op_income_adj':None,'net_income_adj':None,'parent_net_income_adj':T['parent_adj'],'da':None,'capex':T['cash_paid_for_long_lived_assets'],'ocf':T['operating_cash_flow'],'sbc':None},'balance_latest':{'cash':L['ending_cash_equivalents'],'debt_incl_leases':L['debt_proxy'],'debt_is_conservative_proxy':False,'tangible_equity':L['tangible_equity'],'diluted_shares':None,'shares_outstanding':L['shares_outstanding']}},'baseline':baseline,'capital_allocation_5y':capital,'claims_vs_numbers':claims,'judgments':judgments,'anomalies':['EPS2023原报11.79与后报10.06冲突未解决，禁止EPS估值','Q3现金利润背离；库存准备率降低与结构变化需验证'],'data_gaps':['五年主要三表已补；完整资本配置仍缺分红现金/少数股权收购/2022SBC','完整经营营运资金分类、ROIC及再投资率缺；不以缺项当零','五年实际分红、少数股权收购与实付所得税未拆分','最新债务到期细分/浮动利率/契约余量及最新受限现金缺','TTM折旧、SBC和扣非CAS营业/合并净利缺；股数稀释追溯缺','2026Q3应收账龄、存货结构与减值明细缺']}
(P/'handoff.json').write_text(json.dumps(H,ensure_ascii=False,indent=2))
(P/'handoff_tables.json').write_text(json.dumps({'F2':F2,'F3':F3table,'F4':F4rows,'claims':claims,'judgments':judgments},ensure_ascii=False,indent=2))
# Report composition in a separate template permits review of prose and generated tables.
text=(P/'report_body.md').read_text().replace('{{BASE}}',base).replace('{{F2}}',table(['维度','FY2025','TTM/最新','方向','参照','旗'],F2)).replace('{{F3}}',F3table).replace('{{F4}}',table(['用途','5年累计','占5年OCF','已核范围/趋势'],F4rows)).replace('{{LEDGER}}',(P/'capital_ledger.md').read_text())
text=text.replace('{{CLAIMS}}',table(['谁在说','说法','数字怎么说','核对'],[[c['who'],c['claim'],c['data_says'],c['verdict']] for c in claims])).replace('{{JUDGMENTS}}',table(['判断','为什么','推翻条件','谁验证'],[[v['claim'],v['why'],v['wrong_if'],v['owner']] for v in judgments]))
absrows=[]
for label,key in [('收入','revenue'),('剔非CAS营业利润','op_income_adj'),('剔非合并净利润','net_income_adj'),('扣非归母净利（补充）','parent_net_income_adj'),('折旧摊销','da'),('现金资本开支代理','capex'),('经营现金流','ocf'),('SBC','sbc')]:absrows.append([label,n(H['base_year']['fy_1'][key]),n(H['base_year']['ttm'][key])])
for label,key in [('现金及等价物','ending_cash_equivalents'),('有息债务含租赁/代理','debt_proxy'),('有形权益','tangible_equity'),('期末A+H全部股数（补充）','shares_outstanding')]:absrows.append([label,n(A[key]),n(L[key])])
absrows.append(['稀释加权股数','n/a','n/a'])
text=text.replace('{{ABS}}',table(['百万元CNY/百万股','FY2025','TTM/最新'],absrows)).replace('{{JSON}}',json.dumps(H,ensure_ascii=False,separators=(',',':')))
OUT=P.parent.parent/'02_财务分析.md';OUT.write_text(text); print('report_bytes',OUT.stat().st_size,'base_bytes',len(base.encode()));assert OUT.stat().st_size<=40000;assert len(base.encode())<=10000
