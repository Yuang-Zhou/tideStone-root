"""Read-only source checks + actual-period bridges. No forecast assumptions or scenarios."""
from pathlib import Path
import json,re,hashlib,datetime
P=Path(__file__).resolve().parent; B=P.parents[1]; C=B.parents[2]; R=C/'300750.SZ Wiki/raw'; E=P/'source_extracts';E.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(n,x):(P/n).write_text(json.dumps(x,ensure_ascii=False,indent=2))
J=json.loads((B/'_support/02/analysis_inputs_results.json').read_text()); D=J['data']; records=J['records']; F=json.loads((R/'财务数据/CAS/financials.json').read_text())
CAT={x['id']:x for x in json.loads((C/'_source_catalog.json').read_text())['records']}
TEXT={}
for name in ['annual_2025','q3_2026','interim_2026']:
 parts=re.split(r'=== PDF PAGE (\d+) ===',(R/'TEXT'/f'{name}.txt').read_text());TEXT[name]={int(parts[i]):parts[i+1] for i in range(1,len(parts),2)}
pages={'annual_2025':[111,112,113,116,117,120,121,201,202,203], 'q3_2026':list(range(5,13)), 'interim_2026':[72,73,74,77,78,81,82,127,128,131,141,143,144,145,146,147,148,149,152,156,157,158]}
manifest=[]
for name,ps in pages.items():
 p=E/(name+'.txt');p.write_text('\n'.join(f'=== PDF PAGE {i} ===\n'+TEXT[name][i] for i in ps));cat=CAT[name]
 manifest.append({'id':name,'url':cat['source'],'published_at':cat['published_at'],'retrieved_at':cat['retrieved_at'],'source_file':str((C/cat['file']).resolve()),'source_sha256':sha(C/cat['file']),'source_hash_matches_catalog':sha(C/cat['file'])==cat['sha256'],'physical_pages':ps,'extract_file':str(p.resolve()),'extract_sha256':sha(p)})
dump('source_manifest.json',manifest)
# Existing 02 base is audited line by line without replacing it.
base=json.loads((B/'_support/02/forecast_base_balance.json').read_text());audit=[]
for period,x in base['periods'].items():
 for group in ['assets','liabilities']:
  for k,v in x[group].items():
   if 'residual' in k:
    total=x['total_assets' if group=='assets' else 'total_liabilities'];calc=total-sum(a for z,a in x[group].items() if z!=k);assert abs(calc-v)<1e-6
    audit.append({'period':period,'field':k,'value_million':v,'type':'reported_total_less_explicit_reported_lines','formula':f'total_{group} - sum(explicit lines)','verified':True});continue
   hits=[r for r in records if r['year']==period and r['field']==k and abs(r['value_million']-v)<1e-6];assert hits,(period,k,v)
   for r in hits:assert re.sub(r'\s+','',r['excerpt']) in re.sub(r'\s+','',TEXT[r['source']][r['page']]), r
   audit.append({'period':period,'field':k,'value_million':v,'verified':True,'sources':hits})
 for k,field in [('total_assets','total_assets'),('total_liabilities','total_liabilities'),('equity','total_equity'),('parent_equity','parent_equity'),('minority_equity','minority_equity'),('cash_equivalents_distinct_from_monetary_funds','ending_cash_equivalents')]:
  hits=[r for r in records if r['year']==period and r['field']==field and abs(r['value_million']-x[k])<1e-6];assert hits,(period,k)
  for r in hits:assert re.sub(r'\s+','',r['excerpt']) in re.sub(r'\s+','',TEXT[r['source']][r['page']]), r
  audit.append({'period':period,'field':k,'value_million':x[k],'verified':True,'sources':hits})
 assert abs(sum(x['assets'].values())-x['total_assets'])<1e-6
 assert abs(sum(x['liabilities'].values())-x['total_liabilities'])<1e-6
 assert abs(x['total_assets']-x['total_liabilities']-x['equity'])<=0.00101
 assert abs(x['parent_equity']+x['minority_equity']-x['equity'])<1e-6
dump('base_balance_source_audit.json',audit)
# Complete disclosed balance lines, retaining exact source values and rounding.
asset_labels={'monetary_funds':'货币资金','trading_assets':'交易性金融资产','derivative_assets':'衍生金融资产','notes_receivable':'应收票据','trade_receivables':'应收账款','receivables_financing':'应收款项融资','prepayments':'预付款项','other_receivables':'其他应收款','inventories':'存货','contract_assets':'合同资产','current_noncurrent_assets':'一年内到期的非流动资产','other_current_assets':'其他流动资产','long_receivables':'长期应收款','equity_method_investments':'长期股权投资','other_equity_investments':'其他权益工具投资','other_noncurrent_financial_assets':'其他非流动金融资产','ppe_net':'固定资产','construction':'在建工程','rou':'使用权资产','intangibles':'无形资产','goodwill':'商誉','long_deferred_expenses':'长期待摊费用','dta':'递延所得税资产','other_noncurrent_assets':'其他非流动资产'}
liab_labels={'short_term_borrowings':'短期借款','derivative_liabilities':'衍生金融负债','notes_payable':'应付票据','ap':'应付账款','contract_liabilities':'合同负债','employee_liabilities':'应付职工薪酬','taxes_payable':'应交税费','other_payables':'其他应付款','current_portion_of_noncurrent_liabilities':'一年内到期的非流动负债','other_current_liabilities':'其他流动负债','long_term_borrowings':'长期借款','bonds_payable':'应付债券','lease_noncurrent':'租赁负债','long_payables':'长期应付款','provisions':'预计负债','deferred_income':'递延收益','dtl':'递延所得税负债','other_noncurrent_liabilities':'其他非流动负债'}
def extract(label,name,ps,col=0):
 for pg in ps:
  for line in TEXT[name][pg].splitlines():
   if re.match(r'^\s*'+re.escape(label)+r'\s+[-\d]',line):
    val=re.findall(r'-?\d[\d,]*(?:\.\d+)?',line[len(line)-len(line.lstrip()):].strip()[len(label):])
    if len(val)>col:return {'value_million':float(val[col].replace(',',''))/1000,'source':name,'page':pg,'column':col,'excerpt':line.strip()}
 raise ValueError((label,name,ps,col))
complete={}
for period,name,ps in [('2025','annual_2025',[111,112,113]),('2026_H1','interim_2026',[72,73,74]),('2026_9M','q3_2026',[5,6,7,8])]:
 x={'assets':{},'liabilities':{},'totals':{}}
 for group,labels in [('assets',asset_labels),('liabilities',liab_labels)]:
  for k,label in labels.items():x[group][k]=extract(label,name,ps)
 for k,label in {'assets':'资产总计','liabilities':'负债合计','equity':'所有者权益合计','parent_equity':'归属于母公司所有者权益合计','minority_equity':'少数股东权益'}.items():x['totals'][k]=extract(label,name,ps)
 x['reported_line_rounding_million']={g:x['totals'][g]['value_million']-sum(r['value_million'] for r in x[g].values()) for g in ['assets','liabilities']}
 complete[period]=x
dump('complete_actual_balances.json',complete)
# Flow-only bridges; no balance-sheet subtraction is called a quarterly balance.
flow_sections=['income_statement','cash_flow_statement']; h1=F['reports']['interim_2026']['statements'];flow_keys=[]
for sec in flow_sections:flow_keys += list(h1[sec])
flow_keys=list(dict.fromkeys(flow_keys)); exclude={'opening_cash_equivalents','ending_cash_equivalents'}; bridges={}
for period in ['2025_Q4','2026_Q3']:
 out={}
 for k in flow_keys:
  if k in exclude:continue
  if period=='2025_Q4':
   if k not in D['2025'] or k not in D['2025_9M']:continue
   a,z=D['2025'][k],D['2025_9M'][k];src_a=[r for r in records if r['year']=='2025' and r['field']==k];src_z=[r for r in records if r['year']=='2025_9M' and r['field']==k]
  else:
   if k not in D['2026_9M']:continue
   rr=next((h1[sec][k] for sec in flow_sections if k in h1[sec]),None)
   if not rr or rr.get('current_cny') is None:continue
   a,z=D['2026_9M'][k],float(rr['current_cny'])/1e6;src_a=[r for r in records if r['year']=='2026_9M' and r['field']==k];src_z=[dict(source='interim_2026',page=rr['pdf_page'],value_million=z)]
  out[k]={'value_million':a-z,'formula':'FY2025 - 9M2025' if period=='2025_Q4' else '9M2026 - H1_2026','minuend':a,'subtrahend':z,'source_minuend':src_a,'source_subtrahend':src_z}
 rev=out['revenue']['value_million'];cost=out['cost_of_sales']['value_million'];ocf=out['operating_cash_flow']['value_million'];cap=out['cash_paid_for_long_lived_assets']['value_million']
 out['derived']={'gross_margin':1-cost/rev,'FCF_proxy_million':ocf-cap,'OCF_to_consolidated_profit':ocf/out['net_profit']['value_million'],'FCF_proxy_is_unlevered_FCFF':False}
 if period=='2026_Q3':
  old=json.loads((B/'_support/02/supplemental_calculations.json').read_text())['Q3_standalone']
  for k in ['revenue','cost_of_sales','net_profit_parent','net_profit','operating_cash_flow','cash_paid_for_long_lived_assets']:assert abs(old[k]-out[k]['value_million'])<1e-6
 bridges[period]=out
dump('actual_quarter_bridges.json',bridges)
# Supplemental disclosure items: H1 dates do not become Q3 actuals.
notes={
 'supplier_financing':{'unit':'CNY million','2025_yearend':{'electronic_receipts':23902.653,'reverse_factoring':13320.128,'total':37222.781,'supplier_cash_received':30728.127,'source':'annual_2025 p202–203; interim_2026 p158 comparative'},'2026_H1':{'electronic_receipts':20391.072,'reverse_factoring':37373.152,'total':57764.224,'supplier_cash_received':50406.338,'source':'interim_2026 p158'},'2026_9M':None,'Q3_proxy_adjustment_permission':'No assumption chosen; if H1 is used as Q3 proxy, identify as sensitivity, not actual'},
 'payables_composition':{'2025_yearend':{'goods':134821.193,'engineering_equipment':25507.769,'total':160328.962},'2026_H1':{'goods':168867.568,'engineering_equipment':33641.213,'total':202508.781},'source':'interim_2026 p143','supplier_finance_overlap_with_engineering_payables':'not disclosed; cannot independently subtract both totals and assume disjointness'},
 'other_payables_H1':{'accrued_expenses':3931.597,'performance_guarantees_deposits':3381.276,'other':2286.071,'total':9598.945,'rounding':0.001,'source':'interim_2026 p143'},
 'provisions_H1':{'warranty':59131.359,'rebates':39327.759,'abandonment_other':148.125,'total':98607.243,'source':'interim_2026 p148','classification':'predominantly operating long-term obligations; do not treat as ordinary debt or immediately payable NWC without maturity assumptions'},
 'other_current_assets_H1':{'input_VAT':17149.888,'other':1010.565,'total':18160.453,'source':'interim_2026 p131'},
 'other_noncurrent_assets_H1':{'capex_prepayment_net':16374.459,'long_goods_prepayment_and_deposits':8560.053,'long_receivables':941.124,'time_deposits':2669.332,'total':28544.967,'rounding':-0.001,'source':'interim_2026 p141'},
 'other_current_liabilities_H1':{'output_VAT_deferred':2428.737,'input_VAT_to_transfer':6422.166,'total':8850.903,'source':'interim_2026 p146'},
 'other_noncurrent_liabilities_H1':{'sales_advance':4213.371,'source':'interim_2026 p148'},
 'other_receivables_H1':{'net':2618.732,'dividends_receivable':114.195,'employee_gross':248.200,'deposits_gross':738.604,'other_gross':2172.433,'source':'interim_2026 p127–128','warning':'gross components cannot replace net account; residual contains credit provisions and rounding'},
 'taxes_payable_H1':{'income_tax':7639.390,'VAT':867.868,'other':995.224,'total':9502.483,'rounding':0.001,'source':'interim_2026 p145'},
 'cash_definition_H1':{'monetary_funds':372053.275,'excluded_deposits':25256.727,'bank_overdraft_subtracted_in_CE':6210.332,'cash_equivalents':340586.216,'formula':'monetary_funds-excluded_deposits-overdraft=CE','source':'interim_2026 p72,157–158','warning':'assess overlap of overdraft with short borrowings before EV cash-debt adjustment; Q3 decomposition not provided'},
 'cash_definition_9M':{'monetary_funds':369813.786,'cash_equivalents':333397.571,'difference_unclassified':36416.215,'source':'q3_2026 p5,p12','warning':'Do not label whole difference restricted cash or copy H1 proportions'},
 'H1_DA':{'depreciation':14282.273,'rou_depreciation':276.258,'intangibles_amort':258.901,'long_deferred_amort':1021.822,'total':15839.254,'source':'interim_2026 p156','Q3_actual':None},
 'H1_CFO_bridge':{'inventory_change':-37859.085,'operating_receivables_change':-33026.925,'operating_payables_change':71690.439,'source':'interim_2026 p157','warning':'cash-flow working-capital categories not identical to endpoint balance-account differences'}
}
for yy in ['2025_yearend','2026_H1']:
 x=notes['supplier_financing'][yy];assert abs(x['electronic_receipts']+x['reverse_factoring']-x['total'])<1e-6
 a=notes['payables_composition'][yy];assert abs(a['goods']+a['engineering_equipment']-a['total'])<1e-6
 sf=x['total'];equip=a['engineering_equipment'];goods=a['goods'];notes['payables_composition'][yy]['ordinary_goods_payable_ex_supplier_finance_identification_range']=[goods-min(sf,goods),goods-max(0,sf-equip)]
x=notes['cash_definition_H1'];assert abs(x['monetary_funds']-x['excluded_deposits']-x['bank_overdraft_subtracted_in_CE']-x['cash_equivalents'])<1e-6
dump('latest_note_inputs.json',notes)
upstream={str(p.relative_to(B)):sha(p) for p in [B/'01_企业文化.md',B/'02_财务分析.md',B/'03_商业模式.md',B/'_support/02/handoff.json']}
preflight={'as_of':'2026-10-24','scope':'method + actual-input preparation only; no scenario forecasts','currency':'CNY','unit':'million','upstream_hashes':upstream,'04_status':'not consumed; awaiting completed H2/H3/H5 and parent authorization','base_balance_audit':{'audited_fields':len(audit),'all_verified':all(x['verified'] for x in audit),'2026_9M_identity_rounding_million':base['periods']['2026_9M']['identity_rounding_million']},'actual_bridges_ready':['2025_Q4=FY2025-9M2025','2026_Q3=9M2026-H1_2026'],'model_calendar':{'2026E':'9M actual + Q4 forecast; do not annualize 9M','full_forecast_years':[2027,2028,2029,2030,2031],'valuation_price_date':'2026-10-23','latest_balance_as_of':'2026-09-30','balance_to_price_gap_days':23,'remaining_Q4_days':69,'full_Q4_days':92,'cash_asset_for_three_statements_million':369813.786,'cash_flow_cash_equivalents_million':333397.571,'unclassified_cash_basis_difference_million':36416.215,'stub_warning':'Q4 is 2026-10-01 to 12-31, but valuation price date is 10-23. Either provide modeled remaining-period fraction with an explicit convention, or value at 9/30 then bridge cash to 10/23; 10/1–10/23 actual CFO is undisclosed. No past 9M cash flows enter future DCF.'},'hard_guards':['CAS operating profit is not operating EBIT; investment/FV/other income and net finance cost require separate bridges','FCF proxy is not unlevered FCFF','Keep consolidated operating value, associate investments, net financing income, minority interest, and parent profit separate; avoid double counting','Use 4627.250m current total A+H shares only as explicit unweighted proxy; do not use suspect2023 EPS','Do not assume H1 supplier financing is Q3 actual or add it twice to cash/debt/NWC','Do not treat reported residual balance categories as prospective plug accounts','All future drivers and financing/equity policy deferred until04; no weighted forecasts'], 'important_new_fact':'H1 supplier finance57764.224m vs FY202537222.781m; Q3 undisclosed','method_references_read':['financial-forecast/SKILL.md','financial-forecast/references/original.md','tidestone-research/references/local-runtime.md'],'method_additional_references':'Original forecast skill names no other actual reference file; no missing file invented','analyst_snapshot':'Reuse _evidence/valuation_precheck/UOB_20261022 and readme; not a complete rating distribution, analyst price range or independently accessed consensus'}
dump('input_preflight.json',preflight)
print(json.dumps({'source_hashes_pass':all(x['source_hash_matches_catalog'] for x in manifest),'audited_base_fields':len(audit),'quarter_key_results':{k:{f:v[f]['value_million'] for f in ['revenue','cost_of_sales','net_profit_parent','operating_cash_flow','cash_paid_for_long_lived_assets']} for k,v in bridges.items()},'H1_supplier_finance':notes['supplier_financing']['2026_H1'],'complete_balance_rounding':{k:v['reported_line_rounding_million'] for k,v in complete.items()}},ensure_ascii=False,indent=2))
