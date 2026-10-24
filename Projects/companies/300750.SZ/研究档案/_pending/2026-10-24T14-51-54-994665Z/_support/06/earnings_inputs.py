"""Observed CAS earnings classification/quarter bridges, not a forecast or final valuation EBIT."""
from pathlib import Path
import json
P=Path(__file__).resolve().parent;B=P.parents[1];D=json.loads((B/'_support/02/analysis_inputs_results.json').read_text())['data'];F=json.loads((B.parents[2]/'300750.SZ Wiki/raw/财务数据/CAS/financials.json').read_text())['reports']['interim_2026']['statements']['income_statement']
fields=['tax_surcharges','admin','finance_cost_net','interest_expensed','interest_income','other_income','investment_income','equity_method_income','fair_value_income','credit_impairment_signed','asset_impairment_signed','disposal_income','nonoperating_income','nonoperating_expense']
raw={
'2025':[2832322,11666741,-7939863,2734017,10594657,10600477,7970552,7353106,974079,-418585,-8660164,174640,463520,455611],
'2025_9M':[1843066,8231715,-7015786,2183477,8060682,7693237,5236818,4943750,878537,-377141,-4077847,89212,372284,212195],
'2026_H1':[1324939,6019599,-630793,1392225,4887257,4589631,6152679,5722218,1240685,-464365,-1883748,22053,200160,98060],
'2026_9M':[3539029,9315309,-1446905,2528779,7412521,6388126,9065705,8435673,2489533,-642154,-3595279,80161,274749,179805]}
source={'2025':{'source':'annual_2025','pages':[116,117],'column':'current'},'2025_9M':{'source':'q3_2026','pages':[9,10],'column':'comparative'},'2026_H1':{'source':'interim_2026','pages':[77,78],'column':'current'},'2026_9M':{'source':'q3_2026','pages':[9,10],'column':'current'}}
out={}
for period,values in raw.items():
 x=dict(zip(fields,[v/1000 for v in values]));a=D[period] if period!='2026_H1' else {k:float(v['current_cny'])/1e6 for k,v in F.items() if v.get('current_cny') is not None}
 for k in ['revenue','cost_of_sales','selling_expenses','research_and_development_expenses','operating_profit','profit_before_tax','income_tax_expense','net_profit','net_profit_parent','net_profit_minority']:x[k]=a[k]
 # Defined exclusion bridge, not assumed economically recurring margin.
 x['core_excluding_finance_investment_FV_other_disposal']=x['revenue']-x['cost_of_sales']-x['tax_surcharges']-x['selling_expenses']-x['admin']-x['research_and_development_expenses']+x['credit_impairment_signed']+x['asset_impairment_signed']
 cas=x['core_excluding_finance_investment_FV_other_disposal']-x['finance_cost_net']+x['other_income']+x['investment_income']+x['fair_value_income']+x['disposal_income']
 x['CAS_operating_reconciliation_rounding']=x['operating_profit']-cas;assert abs(x['CAS_operating_reconciliation_rounding'])<=.00201
 x['core_margin_exclusion_definition']=x['core_excluding_finance_investment_FV_other_disposal']/x['revenue'];x['source']=source[period];out[period]=x
for period,l,r in [('2025_Q4','2025','2025_9M'),('2026_Q3','2026_9M','2026_H1')]:
 out[period]={k:out[l][k]-out[r][k] for k in out[l] if isinstance(out[l][k],(int,float)) and k!='core_margin_exclusion_definition'};out[period]['core_margin_exclusion_definition']=out[period]['core_excluding_finance_investment_FV_other_disposal']/out[period]['revenue'];out[period]['formula']=f'{l} - {r}'
payload={'unit':'CNY million','definition':'Exclusion bridge strips whole net finance expense, investment, FV, other income and disposal; retained asset/credit losses. This is a defined historical reconciliation, not final operating EBIT or recurring earnings judgment. Future model must decide inclusion and cash nature explicitly; associate income is separately valued if equity stake added to EV.','periods':out}
(P/'earnings_classification_inputs.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2));print({k:round(v['core_excluding_finance_investment_FV_other_disposal'],3) for k,v in out.items()})
