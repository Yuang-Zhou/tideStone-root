from pathlib import Path
import json,re,hashlib
P=Path(__file__).resolve().parent
j=json.loads((P/'analysis_inputs_results.json').read_text());D=j['data'];A=D['2025'];B=D['2024'];L=D['2026_9M'];root=P.parents[7];raw=root/'Projects/companies/300750.SZ/300750.SZ Wiki/raw'
f=json.loads((raw/'财务数据/CAS/financials.json').read_text())
q3={};formula={}
for sec in ['income_statement','cash_flow_statement']:
 for k in ['revenue','cost_of_sales','operating_cash_flow','net_profit_parent','net_profit','cash_paid_for_long_lived_assets']:
  if k in f['reports']['interim_2026']['statements'][sec]:
   r=f['reports']['interim_2026']['statements'][sec][k];h=float(r['current_cny'])/1e6;q3[k]=L[k]-h;formula[k]={'formula':'2026_9M - 2026H1','inputs':[L[k],h],'source_H1_page':r['pdf_page'],'result':q3[k]}
q3['gross_margin']=1-q3['cost_of_sales']/q3['revenue'];q3['fcf_proxy']=q3['operating_cash_flow']-q3['cash_paid_for_long_lived_assets']
calcs={'Q3_standalone':q3,'Q3_formula_inputs':formula,'2025_ocf_less_netprofit':A['operating_cash_flow']-A['net_profit'],'2025_working_capital_cf_bridge':{'inputs':[-39837.988,-16911.542,89965.735],'source':'2025年报p201','result':-39837.988-16911.542+89965.735},'2025_inventory_reserve_ratio':7716.449/102242.688,'2024_inventory_reserve_ratio':6059.183/65894.717,'2025_inventory_finished_plus_delivered_pct':(26077.234+40147.908)/102242.688,'2024_inventory_finished_plus_delivered_pct':(14339.799+24654.769)/65894.717,'2025_receivables_older_1y_ratio':(1321.865+718.820+870.010)/79216.686,'2024_receivables_older_1y_ratio':(1237.842+185.572+774.946)/66776.402,'2025_depreciation_gross_ratio':24322.780/243403.115,'2024_depreciation_gross_ratio':22437.872/186310.991,'cash_capex_output_2023_2025':(A['revenue']-D['2022']['revenue'])/sum(D[y]['cash_paid_for_long_lived_assets'] for y in ['2023','2024','2025']),'10pct_revenue_sensitivity':(A['revenue']-A['cost_of_sales'])*.1/A['operating_profit'],'2pt_margin_sensitivity_profit':A['revenue']*.02,'2025_net_cash_after_supplier_finance_reclassification':A['net_cash_conservative']-A['supplier_finance'],'dupont':{}}
for y in ['2022','2023','2024','2025']:
 a,b=D[y],D[str(int(y)-1)];avgasset=(a['total_assets']+b['total_assets'])/2;avgeq=(a['total_equity']+b['total_equity'])/2;calcs['dupont'][y]={'net_margin':a['net_profit']/a['revenue'],'asset_turnover':a['revenue']/avgasset,'equity_multiplier':avgasset/avgeq,'roe':a['net_profit']/avgeq}
(P/'supplemental_calculations.json').write_text(json.dumps(calcs,ensure_ascii=False,indent=2))
checks=[]
for y in ['2021','2022','2023','2024','2025']:
 d=D[y];err=d['profit_before_tax']-d['income_tax_expense']-d['net_profit'];assert abs(err)<.003;checks.append({'year':y,'check':'pretax-tax=consolidated profit','difference_million':err,'pass':True})
for k,v in j['ttm_formulas'].items():assert abs(v['result']-(v['inputs'][0]+v['inputs'][1]-v['inputs'][2]))<1e-8
assert 'total_assets' not in D['2025_9M'],'2025_9M must not contain FY2025 balance comparison'
forecast={'currency':'CNY','unit':'million','basis':'CAS合并，Other明确为报表已披露总额减已列项目，非预测平衡数','periods':{}}
for y in ['2025','2026_9M']:
 d=D[y];a_keys=['monetary_funds','trading_assets','trade_receivables','inventories','prepayments','ppe_net','construction','rou','intangibles','goodwill','dta'];li_keys=['short_term_borrowings','long_term_borrowings','bonds_payable','current_portion_of_noncurrent_liabilities','lease_noncurrent','ap','notes_payable','contract_liabilities','employee_liabilities','provisions'];aa={k:d[k] for k in a_keys};ll={k:d[k] for k in li_keys};aa['other_assets_disclosed_residual']=d['total_assets']-sum(aa.values());ll['other_liabilities_disclosed_residual']=d['total_liabilities']-sum(ll.values());forecast['periods'][y]={'assets':aa,'total_assets':d['total_assets'],'liabilities':ll,'total_liabilities':d['total_liabilities'],'equity':d['total_equity'],'parent_equity':d['parent_equity'],'minority_equity':d['minority_equity'],'cash_equivalents_distinct_from_monetary_funds':d['ending_cash_equivalents'],'identity_rounding_million':d['total_assets']-d['total_liabilities']-d['total_equity'],'source':'2025年报p111–113' if y=='2025' else '2026Q3p5–8'}
(P/'forecast_base_balance.json').write_text(json.dumps(forecast,ensure_ascii=False,indent=2))
report=P.parent.parent/'02_财务分析.md';s=report.read_text();h=json.loads(re.findall(r'```json\n(.*?)\n```',s,re.S)[-1]);assert h==json.loads((P/'handoff.json').read_text());assert s.rstrip().endswith('<!-- HANDOFF-END v3 -->');assert report.stat().st_size<=40000
v={'scope':'Arithmetic, schema and source-hash checks only; not research truth assurance','checks':checks,'ttm_recomputed_fields':len(j['ttm_formulas']),'handoff_matches_json':True,'report_bytes':report.stat().st_size,'sha256':hashlib.sha256(report.read_bytes()).hexdigest()};(P/'verification.json').write_text(json.dumps(v,ensure_ascii=False,indent=2));print(json.dumps(v,ensure_ascii=False));print(json.dumps(q3,ensure_ascii=False))
