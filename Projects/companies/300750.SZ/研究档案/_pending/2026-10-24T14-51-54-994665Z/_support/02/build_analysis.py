from pathlib import Path
import json,re,hashlib,statistics
ROOT=Path(__file__).resolve().parents[8]
COMP=ROOT/'Projects/companies/300750.SZ'
RAW=COMP/'300750.SZ Wiki/raw'
OUT=Path(__file__).resolve().parent
f=json.loads((RAW/'财务数据/CAS/financials.json').read_text())
catalog=json.loads((COMP/'_source_catalog.json').read_text())['records']
pages={}
for fn in ['annual_2023','annual_2024','annual_2025','q3_2026']:
 a=re.split(r'=== PDF PAGE (\d+) ===',(RAW/'TEXT'/f'{fn}.txt').read_text()); pages[fn]={int(a[i]):a[i+1] for i in range(1,len(a),2)}
a=re.split(r'=== PDF PAGE (\d+) ===',(OUT.parent.parent/'_evidence/02/annual_2021_text.txt').read_text()); pages['annual_2021']={int(a[i]):a[i+1] for i in range(1,len(a),2)}
records=[]; data={str(y):{} for y in range(2021,2026)}; data['2026_9M']={}; data['2025_9M']={}
for y,fn,col in [('2022','annual_2023','comparative'),('2023','annual_2024','comparative'),('2024','annual_2025','comparative'),('2025','annual_2025','current'),('2026_9M','q3_2026','current'),('2025_9M','q3_2026','comparative')]:
 for st,rows in f['reports'][fn]['statements'].items():
  if y=='2025_9M' and st=='balance_sheet':continue
  for key,r in rows.items():
   data[y][key]=float(r[f'{col}_cny'])/1e6
   records.append(dict(year=y,field=key,value_million=data[y][key],source=fn,page=r['pdf_page'],column=col,excerpt=r['source_excerpt']))

def row(fn,ns,label,key,y1,y0=None):
 for n in ns:
  lines=pages[fn][n].splitlines()
  for j,line in enumerate(lines):
   if re.match(label,line.strip()):
    seg=line
    for k in range(1,4):
     nums=re.findall(r'(?<![\d.])[-]?\d[\d,]*\.?\d*',seg[re.match(label,seg.strip()).end():]) if re.match(label,seg.strip()) else []
     if len(nums)>= (2 if y0 else 1):break
     if j+k<len(lines):seg+=' '+lines[j+k]
    if not nums:return
    scale=.01 if fn in ['annual_2023','annual_2021'] else .001
    for y,num,col in [(y1,nums[0],0)]+([(y0,nums[1],1)] if y0 and len(nums)>1 else []):
     data[y][key]=float(num.replace(',',''))*scale
     records.append(dict(year=y,field=key,value_million=data[y][key],source=fn,page=n,column=col,excerpt=seg))
    return

def manual(y,key,v,fn,n,why):
 data[y][key]=v;records.append(dict(year=y,field=key,value_million=v,source=fn,page=n,extraction='explicit verified input',excerpt=why))

for fn,ns,y1,y0 in [('annual_2023',range(115,118),'2023','2022'),('annual_2024',range(114,117),'2024','2023'),('annual_2025',range(111,114),'2025','2024'),('q3_2026',range(6,9),'2026_9M','2025_bal')]:
 if y0 not in data:data[y0]={}
 for label,key in [('交易性金融资产','trading_assets'),('应收票据','notes_receivable'),('应收款项融资','receivables_financing'),('预付款项','prepayments'),('固定资产','ppe_net'),('在建工程','construction'),('使用权资产','rou'),('无形资产','intangibles'),('商誉','goodwill'),('递延所得税资产','dta'),('应付账款','ap'),('应付票据','notes_payable'),('合同负债','contract_liabilities'),('应付职工薪酬','employee_liabilities'),('租赁负债','lease_noncurrent'),('预计负债','provisions'),('股本','shares_outstanding')]:row(fn,ns,'^'+label+r'\s+',key,y1,y0)
for fn,ns,y1,y0 in [('annual_2023',range(119,122),'2023','2022'),('annual_2024',range(119,121),'2024','2023'),('annual_2025',range(116,118),'2025','2024'),('q3_2026',range(9,11),'2026_9M','2025_9M')]:
 for label,key in [('管理费用','admin'),('财务费用','finance_cost'),('其中：利息费用','interest_expensed'),('利息收入','interest_income'),('加：其他收益','other_income')]:row(fn,ns,'^'+label+r'\s+',key,y1,y0)
for fn,ns,y1,y0 in [('annual_2023',[201,202],'2023','2022'),('annual_2024',[202],'2024','2023'),('annual_2025',[200,201],'2025','2024')]:
 for label,key in [('固定资产折旧','depreciation'),('使用权资产折旧','rou_depreciation'),('无形资产摊销','intang_amortization'),('长期待摊费用摊销','deferred_amortization')]:row(fn,ns,'^'+label,key,y1,y0)
for fn,ns,y1,y0 in [('annual_2023',range(123,126),'2023','2022'),('annual_2024',range(122,126),'2024','2023'),('annual_2025',range(119,122),'2025','2024'),('q3_2026',[11,12],'2026_9M','2025_9M')]:
 for label,key in [('取得借款收到的现金','borrowing_proceeds'),('偿还债务支付的现金','debt_repaid'),('取得子公司及其他营业单位支付的','acquisitions')]:row(fn,ns,'^'+label,key,y1,y0)
# Fully specified observed supplementary data. Unknown remains null, never zero.
for key,v in [('revenue',130355.7964),('net_profit_parent',15931.3179),('parent_adj',13442.3643),('operating_cash_flow',42908.0087),('total_assets',307666.8609),('parent_equity',84513.2713)]:manual('2021',key,v,'annual_2023',7,'2021比较列，万元×0.01')
for y,v,fn,n in [('2022',28213.0982,'annual_2023',7),('2023',40091.674,'annual_2024',9),('2024',44992.919,'annual_2024',9),('2025',64507.865,'annual_2025',231),('2026_9M',57875.782,'q3_2026',1)]:manual(y,'parent_adj',v,fn,n,'公司披露扣非归母净利润；2025=72201.282-7693.417')
for y,v,fn,n in [('2023',676.7224,'annual_2023',221),('2024',688.995,'annual_2024',219),('2025',-82.524,'annual_2025',220)]:manual(y,'sbc',v,fn,n,'股份支付确认费用')
for y,v,fn,n in [('2022',85.6257,'annual_2023',201),('2023',1823.1055,'annual_2023',201),('2024',1209.018,'annual_2025',200),('2025',4413.337,'annual_2025',200)]:manual(y,'buyback',v,fn,n,'支付股份回购款现金口径')
for y,v in [('2025',10883.724),('2024',8529.408)]:manual(y,'operating_nonrec',v,'annual_2025' if y=='2025' else 'annual_2024',231 if y=='2025' else 228,'税前非经常性合计减其他营业外净额；2025=788.312+1362.488+28.886+8704.038；2024=169.816+664.223+179.608+2.687+8128.318')
manual('2025','net_adj',67912.208,'annual_2025',231,'合并净利-非经常性税前10891.633+税2017.532，含少数股东')
manual('2024','net_adj',47140.390,'annual_2024',228,'54006.794-(8529.408-612.613)+1665.244')
manual('2025','restricted_cash',18890.217,'annual_2025',185,'保证金及质押定期存款')
manual('2024','restricted_cash',23339.555,'annual_2025',185,'比较列')
manual('2025','supplier_finance',37222.781,'annual_2025',203,'融单+反向保理')
manual('2024','supplier_finance',44362.409,'annual_2025',202,'比较列融单')
# FY2021 audited report supplied within this batch by module05; extract both years with bound statement pages.
data['2020']={}
for label,key in [('货币资金','monetary_funds'),('交易性金融资产','trading_assets'),('应收账款','trade_receivables'),('应收票据','notes_receivable'),('应收款项融资','receivables_financing'),('预付款项','prepayments'),('存货','inventories'),('固定资产','ppe_net'),('在建工程','construction'),('使用权资产','rou'),('无形资产','intangibles'),('商誉','goodwill'),('递延所得税资产','dta'),('应付账款','ap'),('应付票据','notes_payable'),('合同负债','contract_liabilities'),('应付职工薪酬','employee_liabilities'),('租赁负债','lease_noncurrent'),('预计负债','provisions'),('股本','shares_outstanding'),('短期借款','short_term_borrowings'),('长期借款','long_term_borrowings'),('应付债券','bonds_payable'),('一年内到期的非流动负债','current_portion_of_noncurrent_liabilities'),('所有者权益合计','total_equity'),('流动资产合计','current_assets'),('流动负债合计','current_liabilities')]:
 row('annual_2021',range(108,112),'^'+label+r'\s+',key,'2021')
for label,key in [('其中：营业收入','revenue'),('其中：营业成本','cost_of_sales'),('管理费用','admin'),('销售费用','selling_expenses'),('研发费用','research_and_development_expenses'),('财务费用','finance_cost'),('其中：利息费用','interest_expensed'),('利息收入','interest_income'),('加：其他收益','other_income'),('三、营业利润','operating_profit'),('减：所得税费用','income_tax_expense'),('五、净利润','net_profit')]:
 row('annual_2021',[114,115],'^'+label,key,'2021','2020')
manual('2021','profit_before_tax',19887.1291,'annual_2021',115,'利润总额1988712.91万元')
for label,key in [('取得借款收到的现金','borrowing_proceeds'),('偿还债务支付的现金','debt_repaid'),('取得子公司及其他营业单位支付','acquisitions'),('购建固定资产、无形资产和其他','cash_paid_for_long_lived_assets'),('六、期末现金及现金等价物余额','ending_cash_equivalents')]:
 row('annual_2021',[119,120],'^'+label,key,'2021')
for label,key in [('固定资产折旧','depreciation'),('使用权资产折旧','rou_depreciation'),('无形资产摊销','intang_amortization'),('长期待摊费用摊销','deferred_amortization')]:row('annual_2021',[205],'^'+label,key,'2021')
manual('2021','sbc',286.7502,'annual_2021',224,'本期股份支付费用28675.02万元')
manual('2021','buyback',45.7064,'annual_2021',205,'支付股份回购款4570.64万元')

# Fix blank comparative acquisition cell; retain absence rather than borrowing the next row.
data['2022'].pop('acquisitions',None)
records=[r for r in records if not(r['year']=='2022' and r['field']=='acquisitions')]
manual('2025','parent_adj',64507.864,'annual_2025',11,'公司摘要披露；减法64507.865差0.001百万元属舍入')
manual('2025_9M','parent_adj',11829.172+15368.296+16421.757,'annual_2025',12,'2025前三季度扣非归母加总，保留输入11829.172+15368.296+16421.757')
manual('2023','operating_nonrec',-235.944+73.029+62.339+5909.090,'annual_2025',12,'2023比较非经常性税前分项剔其他营业外195.751')
manual('2023','net_adj',46761.034-(-235.944+73.029+62.339+195.751+5909.090)+1194.027,'annual_2025',12,'合并口径扣除税后非经常损益，含少数股东')
for y in ['2021','2022','2023','2024','2025','2026_9M','2025_9M']:
 d=data[y]
 if all(k in d for k in ['depreciation','rou_depreciation','intang_amortization','deferred_amortization']): d['da']=sum(d[k] for k in ['depreciation','rou_depreciation','intang_amortization','deferred_amortization'])
 if all(k in d for k in ['operating_cash_flow','cash_paid_for_long_lived_assets']):d['fcf']=d['operating_cash_flow']-d['cash_paid_for_long_lived_assets']
 if all(k in d for k in ['operating_profit','operating_nonrec']):d['op_adj']=d['operating_profit']-d['operating_nonrec']
 if all(k in d for k in ['total_equity','goodwill','intangibles']):d['tangible_equity']=d['total_equity']-d['goodwill']-d['intangibles']
 if all(k in d for k in ['short_term_borrowings','long_term_borrowings','bonds_payable','current_portion_of_noncurrent_liabilities','lease_noncurrent']):
  d['debt_proxy']=sum(d[k] for k in ['short_term_borrowings','long_term_borrowings','bonds_payable','current_portion_of_noncurrent_liabilities','lease_noncurrent'])
  if y=='2025':d['debt_proxy']-=55.291
  if y=='2024':d['debt_proxy']-=55.039
  d['net_cash_conservative']=d['ending_cash_equivalents']-d['debt_proxy']
 if all(k in d for k in ['borrowing_proceeds','debt_repaid']):d['net_debt_repay']=d['debt_repaid']-d['borrowing_proceeds']-(3207.0714 if y=='2021' else 0)-(5000 if y=='2022' else 0)-(49984.68 if y=='2026_9M' else 0)
# This CAS package had no supplied TTM: build once, retain formula and each operand.
flows=['parent_adj','revenue','cost_of_sales','selling_expenses','admin','research_and_development_expenses','finance_cost','interest_expensed','interest_income','operating_profit','profit_before_tax','income_tax_expense','net_profit','net_profit_parent','operating_cash_flow','cash_paid_for_long_lived_assets','fcf']
ttm={};ttm_formulas={}
for k in flows:
 if all(k in data[y] for y in ['2025','2026_9M','2025_9M']):
  a,b,c=(data[y][k] for y in ['2025','2026_9M','2025_9M']);ttm[k]=a+b-c;ttm_formulas[k]={'formula':'FY2025 + 2026_9M - 2025_9M','inputs':[a,b,c],'result':ttm[k]}
data['TTM']=ttm
# Print extracted inputs for verification.
result={'as_of':'2026-10-24','fetched_at':f['as_of'],'currency':'CNY','unit':'million','ttm_end':'2026-09-30','source_schema':'local CAS finite extraction; no EDGAR capabilities advertised','capabilities':sorted(set(k for d in data.values() for k in d)),'suspect_metrics':['2023_basic_eps'],'data':data,'records':records,'ttm_formulas':ttm_formulas,'limitations':['FY2021 completed from original annual report mirrored by Eastmoney; 2020 revenue comparative for CAGR','2022 cost and selling expenses before warranty reclassification','2023 EPS11.79 vs10.06 quarantined','TTM parent adjusted net profit calculated from FY2025 and observed nine-month periods; 0.001m rounding allowed','FY2025/FY2024 debt excludes noninterest current long-term payable; latest debt proxy includes it conservatively','cash paid long-lived assets used as cash capex proxy; no maintenance/growth split','TTM adjusted consolidated/op profit, DA and SBC unavailable without 2025Q3 details; never annualize']}
(OUT/'analysis_inputs_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
evid=[]
for c in catalog:
 if c['id'] in pages or c['id'] in ['interim_2026','ir_20260309','ir_20260724','ir_20261020']:
  raw=COMP/c['file']; assert hashlib.sha256(raw.read_bytes()).hexdigest()==c['sha256']
  evid.append({k:c[k] for k in ['id','source','published_at','retrieved_at','file','sha256']})
evid.append({'id':'annual_2021','source':'https://pdf.dfcfw.com/pdf/H2_AN202204211560705495_1.pdf','published_at':'2022-04-21','retrieved_at':'2026-10-24','file':'../05/annual_2021_eastmoney.pdf','sha256':hashlib.sha256((OUT.parent.parent/'_evidence/05/annual_2021_eastmoney.pdf').read_bytes()).hexdigest(),'note':'公司原年报镜像，非媒体摘数；逐字段页码见records'})
huada=OUT.parent.parent/'_evidence/01a/huada_2026_inquiry.pdf'
evid.append({'id':'huada_2026_inquiry','source':'https://static.cninfo.com.cn/finalpage/2026-07-25/1225441536.PDF','published_at':'2026-07-25','retrieved_at':'2026-10-24','file':'../01a/huada_2026_inquiry.pdf','pages':[28],'sha256':hashlib.sha256(huada.read_bytes()).hexdigest(),'note':'供应商独立申报：90天后取得6个月融单，不是90天现金付款'})
(OUT.parent.parent/'_evidence/02/source_manifest.json').write_text(json.dumps(evid,ensure_ascii=False,indent=2))
print(json.dumps(data,ensure_ascii=False,indent=2))
