#!/usr/bin/env python3
"""CATL 06: explicit scenario three-statement model. All amounts CNY million.
No network, no upstream mutation. Run python3 <this path>; outputs in this directory.
Historical evidence: input_preflight/source_manifest/complete_actual_balances.
Forecast parameters below are assumptions, not reported facts.
"""
import json, copy, hashlib, pathlib
P=pathlib.Path(__file__).resolve().parent; B=P.parent.parent
load=lambda f:json.loads((P/f).read_text())
H=json.loads((B/'_support/02/analysis_inputs_results.json').read_text())['data']
BAL=load('complete_actual_balances.json'); E=load('earnings_classification_inputs.json')['periods']
Q=load('actual_quarter_bridges.json')
SHARES=4627.250; CASH_GAP=36416.215; SF=57764.224
DEBT=['short_term_borrowings','long_term_borrowings','bonds_payable','current_portion_of_noncurrent_liabilities','lease_noncurrent']
PROD=['ppe_net','construction','rou','intangibles','long_deferred_expenses']
FINANCIAL=['trading_assets','derivative_assets','equity_method_investments','other_equity_investments','other_noncurrent_financial_assets']
# Explicit modeled operating working assets. Other displayed accounts remain frozen,
# individually, at reported 9/30 values; they are never used as a balancing plug.
OP_ASSET=['notes_receivable','trade_receivables','receivables_financing','prepayments','other_receivables','inventories','contract_assets','other_current_assets']
OP_LIAB=['notes_payable','ordinary_trade_ap','contract_liabilities','employee_liabilities','taxes_payable','other_payables','other_current_liabilities','provisions']
COMMON={'tax_rate':.15,'interest_income_rate':.025,'interest_expense_rate':.022,'associate_yield':.12,'associate_dividend_payout':.5,'parent_payout':.5,'minority_payout':.4,'minority_profit_share':.07,'sbc_revenue':.001,'operating_grants_revenue':.008,'impairment_to_long_assets':.5,'supplier_finance_proxy':SF,'supplier_finance_company_interest_rate':0,'equipment_share_of_non_sf_ap':33641.213/202508.781,'cash_gap_frozen':CASH_GAP,'shares_million':SHARES,'minimum_cash_revenue':.05,'no_new_buyback_or_equity_issue':True}
SC={
 'bear':dict(label='悲观',q4_rev=165000.,q4_gm=.185,q4_opex=.095,q4_capex=.12,q4_ar_enddays=80,q4_inv_enddays=130,q4_taxpressure=.015,growth=[.04,.03,.03,.02,.02],gm=[.185,.19,.195,.20,.20],opex=[.10,.10,.098,.096,.095],capex=[.12,.11,.105,.10,.10],ar_days=[85,83,82,80,80],inv_days=[130,125,120,118,115],payment_days_reduction=30,taxpressure=[.0225,.02,.018,.015,.015],storage_mix=[.205,.22,.23,.24,.25],impairment=[.018]*5,q4_impairment=.018,rnd=[.053]*5),
 'base':dict(label='基准',q4_rev=190000.,q4_gm=.22,q4_opex=.085,q4_capex=.10,q4_ar_enddays=70,q4_inv_enddays=115,q4_taxpressure=.01,growth=[.15,.14,.13,.12,.10],gm=[.225,.23,.23,.23,.23],opex=[.085,.084,.083,.082,.082],capex=[.10,.10,.10,.10,.095],ar_days=[68,67,66,65,65],inv_days=[100,98,96,95,95],payment_days_reduction=10,taxpressure=[.01,.008,.006,.005,.005],storage_mix=[.245,.265,.285,.30,.315],impairment=[.011]*5,q4_impairment=.011,rnd=[.05]*5),
 'bull':dict(label='乐观',q4_rev=210000.,q4_gm=.25,q4_opex=.08,q4_capex=.10,q4_ar_enddays=60,q4_inv_enddays=100,q4_taxpressure=.0025,growth=[.24,.21,.19,.17,.16],gm=[.26,.26,.26,.255,.255],opex=[.08,.079,.078,.078,.078],capex=[.10,.095,.09,.09,.09],ar_days=[55]*5,inv_days=[80]*5,payment_days_reduction=2.5,taxpressure=[.0025,.002,.0015,.001,.001],storage_mix=[.30,.33,.35,.37,.39],impairment=[.008]*5,q4_impairment=.008,rnd=[.048]*5)
}
def opening():
 d=BAL['2026_9M']; a={k:v['value_million'] for k,v in d['assets'].items()}; l={k:v['value_million'] for k,v in d['liabilities'].items()}
 orig=l.pop('ap'); non_sf=orig-SF
 l['supplier_finance_proxy']=SF
 l['equipment_ap_proxy']=non_sf*COMMON['equipment_share_of_non_sf_ap']
 l['ordinary_trade_ap']=non_sf-l['equipment_ap_proxy']
 return dict(assets=a,liabilities=l,parent_equity=d['totals']['parent_equity']['value_million'],minority_equity=d['totals']['minority_equity']['value_million'])
def total(x): return sum(x.values())
def nwc(b): return sum(b['assets'][k] for k in OP_ASSET)-sum(b['liabilities'][k] for k in OP_LIAB)
def explicit_debt(b): return sum(b['liabilities'][k] for k in DEBT)
def totals(b):
 return dict(assets=total(b['assets']),liabilities=total(b['liabilities']),equity=b['parent_equity']+b['minority_equity'],parent_equity=b['parent_equity'],minority_equity=b['minority_equity'])
START=opening(); START_RES=total(START['assets'])-total(START['liabilities'])-START['parent_equity']-START['minority_equity']
R0=H['2026_9M']['revenue']*365/273; C0=H['2026_9M']['cost_of_sales']*365/273
# Beginning ratios are observed endpoint/annualized flow ratios, NOT reported days.
ASSET_RATIOS={k:START['assets'][k]/R0 for k in ['notes_receivable','receivables_financing','prepayments','other_receivables','contract_assets','other_current_assets']}
LIAB_RATIOS={k:START['liabilities'][k]/R0 for k in ['contract_liabilities','employee_liabilities','taxes_payable','other_payables','other_current_liabilities']}
NOTES_RATIO=START['liabilities']['notes_payable']/C0
PROVISION_RATIO=START['liabilities']['provisions']/R0

def project(prev,scenario,year,prevrev=None):
 s=SC[scenario]; stub=year==2026; i=year-2027; t=92/365 if stub else 1.
 rev=s['q4_rev'] if stub else prevrev*(1+s['growth'][i])
 gm=s['q4_gm'] if stub else s['gm'][i]; opex=s['q4_opex'] if stub else s['opex'][i]; cr=s['q4_capex'] if stub else s['capex'][i]
 pressure=s['q4_taxpressure'] if stub else s['taxpressure'][i]
 impairment_rate=s['q4_impairment'] if stub else s['impairment'][i]
 cogs=rev*(1-gm); capex=rev*cr; impair=rev*impairment_rate; longimp=impair*.5
 # Net tax pressure is embedded once: 40% in observed/modelled GM, 60% in surcharge.
 surcharge=rev*(.007+.6*pressure); gross=rev-cogs; operating_expenses=rev*opex; grants=rev*.008
 ebit=gross-operating_expenses-surcharge-impair+grants
 intinc=max(prev['assets']['monetary_funds']-CASH_GAP,0)*.025*t
 intexp=explicit_debt(prev)*.022*t
 assoc=prev['assets']['equity_method_investments']*.12*t
 assocdiv=assoc*.5
 pbt=ebit+intinc-intexp+assoc; tax=max(ebit+intinc-intexp,0)*.15
 ni=pbt-tax; parent=ni*.93; minority=ni*.07; sbc=rev*.001
 b=copy.deepcopy(prev); a=b['assets']; l=b['liabilities']
 annualrev=H['2026_9M']['revenue']+rev if stub else rev
 annualcogs=H['2026_9M']['cost_of_sales']+cogs if stub else cogs
 if stub:
  a['trade_receivables']=annualrev/365*s['q4_ar_enddays']
  a['inventories']=annualcogs/365*s['q4_inv_enddays']
 else:
  # Smooth closing stock from flow growth; constrain realized average days to H3.
  # Repeated exact-point inversion causes artificial alternating cash releases.
  arband={'bear':(80,95) if i==0 else (75,90),'base':(60,75),'bull':(50,60)}[scenario]
  invband={'bear':(120,150) if i==0 else (110,130),'base':(90,110),'bull':(70,90)}[scenario]
  for k,flow,point,band in [('trade_receivables',rev,s['ar_days'][i],arband),('inventories',cogs,s['inv_days'][i],invband)]:
   begin=prev['assets'][k]; proposed=flow*point/365*(1+s['growth'][i]/2)
   lo=max(0.,2*flow*band[0]/365-begin); hi=2*flow*band[1]/365-begin
   a[k]=max(lo,min(proposed,hi))
 for k,r in ASSET_RATIOS.items(): a[k]=annualrev*r
 for k,r in LIAB_RATIOS.items(): l[k]=annualrev*r
 l['notes_payable']=annualcogs*NOTES_RATIO
 # Provision liability accumulation is explicit: accruals already in COGS/opex;
 # their net change is part of the cash reconciliation, no second expense.
 l['provisions']=annualrev*PROVISION_RATIO
 if stub:
  l['ordinary_trade_ap']=START['liabilities']['ordinary_trade_ap']*annualcogs/C0
 else:
  base_dpo=MODEL[scenario]['2026_Q4']['assumptions']['ordinary_ap_end_days']
  l['ordinary_trade_ap']=annualcogs/365*(base_dpo-s['payment_days_reduction'])
 # No new SF assumed; unchanged 9/30 proxy is a classification sensitivity, not fact.
 # Productive assets: 25% cash capex to CIP, 70% PPE, 5% intangibles.
 # New ROU is NONCASH, equal to ROU depreciation; lease principal paid equally.
 # This assumed replacement keeps ROU and net lease debt flat, not an observed schedule.
 # CIP transfers to PPE at 50% beginning CIP per year; CIP never depreciates.
 transfer=prev['assets']['construction']*.5*t
 a['construction']=prev['assets']['construction']+capex*.25-transfer
 lease_add=prev['assets']['rou']*.20*t
 additions={'ppe_net':capex*.70+transfer,'intangibles':capex*.05,'rou':lease_add,'long_deferred_expenses':0.}
 rates={'ppe_net':.14,'intangibles':.10,'rou':.20,'long_deferred_expenses':.20}
 da=0.; byasset={}
 for k,rate in rates.items():
  dep=prev['assets'][k]*rate*t if k=='rou' else (prev['assets'][k]+additions[k]/2)*rate*t
  byasset[k]=dep; da+=dep; a[k]=prev['assets'][k]+additions[k]-dep
 a['ppe_net']-=longimp
 a['equity_method_investments']=prev['assets']['equity_method_investments']+assoc-assocdiv
 dnwc=nwc(b)-nwc(prev)
 # CAS-like presentation: interest received in investing, interest paid in financing.
 # Long-asset impairment is added back and asset reduced; working-asset impairment
 # is NOT added again because ΔNWC uses NET working-asset balances.
 ocf=ni+da+longimp+sbc-assoc-intinc+intexp-dnwc
 parentdiv=max(parent,0)*.5; ncidiv=max(minority,0)*.4
 cfi=-capex+intinc+assocdiv
 cff=-intexp-parentdiv-ncidiv-lease_add
 provisional_cash=prev['assets']['monetary_funds']+ocf+cfi+cff
 minimum_cash=annualrev*.05+CASH_GAP
 newborrowing=max(minimum_cash-provisional_cash,0)
 l['short_term_borrowings']+=newborrowing; cff+=newborrowing
 a['monetary_funds']=provisional_cash+newborrowing
 b['parent_equity']+=parent-parentdiv+sbc; b['minority_equity']+=minority-ncidiv
 nopat=ebit*(1-.15)
 fcff_cash=nopat+da+longimp+sbc-capex-lease_add-dnwc
 fcff=fcff_cash-sbc # Economic cost of equity remuneration; fixed share count.
 tt=totals(b); res=tt['assets']-tt['liabilities']-tt['equity']
 out={'period':str(year)+'_Q4' if stub else str(year),'classification':'forecast assumption and calculated result','IS':dict(revenue=rev,cost_of_sales=cogs,gross_profit=gross,selling_admin_rnd=operating_expenses,research_and_development=rev*(.05 if stub else s['rnd'][i]),tax_surcharges=surcharge,impairment_total=impair,impairment_long_assets=longimp,operating_grants=grants,operating_EBIT=ebit,interest_income=intinc,interest_expense=intexp,net_forex_finance_other=0.,equity_method_income=assoc,other_investment_fair_value_disposal_nonop=0.,CAS_operating_profit=pbt,profit_before_tax=pbt,income_tax=tax,net_profit=ni,parent_net_profit=parent,minority_net_profit=minority,EPS_parent_current_total_shares=parent/SHARES,SBC_included_in_opex=sbc,NOPAT=nopat),
 'BS':b,'BS_totals':tt,'CF':dict(operating_cash_flow=ocf,investing_cash_flow=cfi,financing_cash_flow=cff,fx_cash_effect=0.,net_change_cash=ocf+cfi+cff,opening_monetary_funds=prev['assets']['monetary_funds'],ending_monetary_funds=a['monetary_funds'],opening_cash_equivalents_proxy=prev['assets']['monetary_funds']-CASH_GAP,ending_cash_equivalents_proxy=a['monetary_funds']-CASH_GAP,DA=da,cash_capex=capex,delta_operating_net_assets=dnwc,associate_cash_dividend=assocdiv,parent_dividend=parentdiv,minority_dividend=ncidiv,interest_received=intinc,interest_paid=intexp,new_short_borrowing=newborrowing,supplier_finance_change=0.,noncash_new_lease_assets=lease_add,lease_principal_paid=lease_add,SBC_non_cash=sbc,FCFF_cash=fcff_cash,FCFF_economic_after_SBC=fcff,levered_OCF_minus_cashcapex=ocf-capex),
 'assumptions':dict(gross_margin=gm,opex_ratio=opex,cashcapex_ratio=cr,net_tax_pressure=pressure,tax_pressure_gm_component=.4*pressure,tax_pressure_surcharge_component=.6*pressure,counterfactual_GM_without_tax_change=gm+.4*pressure,tax_surcharge_rate=.007+.6*pressure,ordinary_ap_end_days=l['ordinary_trade_ap']/annualcogs*365,ar_average_days=None if stub else (prev['assets']['trade_receivables']+a['trade_receivables'])/2/rev*365,inventory_average_days=None if stub else (prev['assets']['inventories']+a['inventories'])/2/cogs*365,storage_revenue_share=None if stub else s['storage_mix'][i],storage_revenue_check=None if stub else rev*s['storage_mix'][i],nonstorage_revenue_check=None if stub else rev*(1-s['storage_mix'][i]),DA_by_asset=byasset,construction_transfer=transfer),
 'checks':dict(balance_identity_residual=res,identity_change_from_rounding=res-START_RES,cash_roll_error=a['monetary_funds']-prev['assets']['monetary_funds']-ocf-cfi-cff,working_assets_nonnegative=min(a.values())>=0,liabilities_nonnegative=min(l.values())>=0,parent_equity_roll_error=b['parent_equity']-prev['parent_equity']-parent+parentdiv-sbc,minority_equity_roll_error=b['minority_equity']-prev['minority_equity']-minority+ncidiv,productive_assets_roll_error=sum(a[k]-prev['assets'][k] for k in PROD)-capex-lease_add+da+longimp,associate_roll_error=a['equity_method_investments']-prev['assets']['equity_method_investments']-assoc+assocdiv)}
 return out

MODEL={}
for scenario in SC:
 MODEL[scenario]={}; prev=copy.deepcopy(START); prevrev=None
 for year in range(2026,2032):
  x=project(prev,scenario,year,prevrev); MODEL[scenario][x['period']]=x
  prev=x['BS']; prevrev=H['2026_9M']['revenue']+x['IS']['revenue'] if year==2026 else x['IS']['revenue']
 # 2026E: actual9M plus forecastQ4. Unobserved9M DA and classification FCFF
 # deliberately not manufactured; disclosed actual OCF/CFI/CFF/FX retained.
 q4=MODEL[scenario]['2026_Q4']; h=H['2026_9M']; ei=E['2026_9M']
 actual_to_forecast={'revenue':'revenue','cost_of_sales':'cost_of_sales','net_profit':'net_profit','net_profit_parent':'parent_net_profit','net_profit_minority':'minority_net_profit','profit_before_tax':'profit_before_tax','income_tax_expense':'income_tax','operating_profit':'CAS_operating_profit'}
 fyis={target:h[source]+q4['IS'][target] for source,target in actual_to_forecast.items()}
 fyis.update(gross_profit=fyis['revenue']-fyis['cost_of_sales'],EPS_parent_current_total_shares=fyis['parent_net_profit']/SHARES,
 selling_admin_rnd=h['selling_expenses']+ei['admin']+h['research_and_development_expenses']+q4['IS']['selling_admin_rnd'],
 research_and_development=h['research_and_development_expenses']+q4['IS']['research_and_development'],tax_surcharges=ei['tax_surcharges']+q4['IS']['tax_surcharges'])
 fcf={k:h[src]+q4['CF'][k] for k,src in [('operating_cash_flow','operating_cash_flow'),('investing_cash_flow','investing_cash_flow'),('financing_cash_flow','financing_cash_flow'),('fx_cash_effect','fx_effect_on_cash'),('cash_capex','cash_paid_for_long_lived_assets')]}
 fcf['net_change_cash_equivalents']=sum(fcf[k] for k in ['operating_cash_flow','investing_cash_flow','financing_cash_flow','fx_cash_effect'])
 fcf['opening_cash_equivalents_actual']=h['opening_cash_equivalents']; fcf['ending_cash_equivalents_proxy']=q4['CF']['ending_cash_equivalents_proxy']
 fcf['levered_OCF_minus_cashcapex']=fcf['operating_cash_flow']-fcf['cash_capex']
 fcf['DA_9M_unavailable']=None; fcf['full_year_FCFF_not_observed']=None
 MODEL[scenario]['2026E']={'IS':fyis,'BS':q4['BS'],'BS_totals':q4['BS_totals'],'CF':fcf,'description':'9M disclosed actual + Q4 model; no invented 9M DA or historical FCFF'}

# Valuation roll: all Q4 flows uniformly accrue; cash and net debt roll forward
# by 23/92, and only 69/92 operating FCFF remains after the 10/23 price date.
# Assumed zero dividends/financing outside the modeled uniform Q4 pattern.
BRIDGE={}
for s in SC:
 q4=MODEL[s]['2026_Q4']; f=23/92; g=69/92; cf=q4['CF']; bs=q4['BS']
 monetary=START['assets']['monetary_funds']+f*cf['net_change_cash']; ce=monetary-CASH_GAP
 debt=explicit_debt(START)+f*cf['new_short_borrowing']
 assoc=START['assets']['equity_method_investments']+f*(bs['assets']['equity_method_investments']-START['assets']['equity_method_investments'])
 otherfinancial=sum(START['assets'][k] for k in FINANCIAL if k!='equity_method_investments')
 BRIDGE[s]={'date':'2026-10-23','source_balance_date':'2026-09-30','elapsed_days':23,'quarter_days':92,'remaining_days':69,'accrual_assumption':'all modeled Q4 flows, including dividends/interest/capex, uniformly accrue; no observed October actual; amounts are estimates','elapsed_net_cash_change':f*cf['net_change_cash'],'elapsed_parent_dividends':f*cf['parent_dividend'],'elapsed_minority_dividends':f*cf['minority_dividend'],'monetary_funds_estimate':monetary,'CE_proxy_estimate':ce,'unclassified_monetary_minus_CE_gap':CASH_GAP,'explicit_debt_proxy':debt,'supplier_finance_H1_reference_proxy':SF,'net_cash_CE_less_explicit_debt':ce-debt,'net_cash_CE_less_explicit_debt_less_SF_proxy':ce-debt-SF,'net_cash_SF_sensitivity':{str(v):ce-debt-v for v in [0,SF,SF*1.5]},'monetary_instead_of_CE_uplift_sensitivity':CASH_GAP,'equity_method_asset_estimate':assoc,'other_financial_assets_book_proxy':otherfinancial,'minority_book_equity_estimate':START['minority_equity']+f*(bs['minority_equity']-START['minority_equity']),'Q4_remaining_FCFF_economic':g*cf['FCFF_economic_after_SBC'],'Q4_remaining_FCFF_cash':g*cf['FCFF_cash'],'remaining_parent_dividends':g*cf['parent_dividend'],'FCFF_midpoint_times_years':{'2026_Q4_remaining':34.5/365,**{str(y):69/365+(y-2027)+.5 for y in range(2027,2032)}},'FCFF_yearend_times_years':{'2026_Q4_remaining':69/365,**{str(y):69/365+(y-2026) for y in range(2027,2032)}},'operating_assets_minimum_cash_assumption':.05,'minimum_operating_cash_sensitivity':MODEL[s]['2026E']['IS']['revenue']*.05,'shares_million':SHARES,'FY2027_forward_EPS':MODEL[s]['2027']['IS']['EPS_parent_current_total_shares'],'year3_2029_EPS':MODEL[s]['2029']['IS']['EPS_parent_current_total_shares'],'NCI_warning':'FCFF consolidated. Deduct NCI economic value or isolate parent operating claims; do not both deduct book NCI and a percentage of enterprise value. Associates/non-operating assets excluded from FCFF; add only their attributable value once.'}

# Optional valuation consistency: if 07 treats 5% revenue as operating cash,
# deduct its starting value from surplus cash AND future increases from FCFF.
for scenario in SC:
 previous_required=R0*.05
 for year in ['2026_Q4','2027','2028','2029','2030','2031']:
  x=MODEL[scenario][year]
  annualrev=MODEL[scenario]['2026E']['IS']['revenue'] if year=='2026_Q4' else x['IS']['revenue']
  required=annualrev*.05; increment=required-previous_required
  x['CF']['optional_required_operating_cash']=required
  x['CF']['optional_delta_required_operating_cash']=increment
  x['CF']['FCFF_after_optional_required_cash']=x['CF']['FCFF_economic_after_SBC']-increment
  previous_required=required
 q4=MODEL[scenario]['2026_Q4']['CF']
 br=BRIDGE[scenario]
 br['minimum_operating_cash_sensitivity']=R0*.05+23/92*q4['optional_delta_required_operating_cash']
 br['Q4_remaining_FCFF_after_optional_required_cash']=69/92*q4['FCFF_after_optional_required_cash']
 br['required_cash_consistency_warning']='If subtracting required operating cash from date-bridge cash, also use FCFF_after_optional_required_cash each future period. Do not mix definitions.'
 br['other_financial_assets_related_derivative_liability']=START['liabilities']['derivative_liabilities']
 br['excluded_debt_classification_sensitivity_long_payables']=START['liabilities']['long_payables']
# Latest public same-period score inputs; no 2027 annual metric scored before due.
B25=BAL['2025']; H1=BAL['2026_H1']; B9=BAL['2026_9M']
def val(d,section,k):return d[section][k]['value_million']
h1rev=E['2026_H1']['revenue']; h1cogs=E['2026_H1']['cost_of_sales']
obs={'gross_margin':{'2026_H1':1-h1cogs/h1rev,'2026_Q3':1-Q['2026_Q3']['cost_of_sales']['value_million']/Q['2026_Q3']['revenue']['value_million']},'cash_conversion':{'2026_H1':60216.851/47030.638,'2026_Q3':1408.636/22467.815},'ar_average_days':{'2026_H1':(val(B25,'assets','trade_receivables')+val(H1,'assets','trade_receivables'))/2/h1rev*181,'2026_Q3':(val(H1,'assets','trade_receivables')+val(B9,'assets','trade_receivables'))/2/Q['2026_Q3']['revenue']['value_million']*92},'inventory_average_days':{'2026_H1':(val(B25,'assets','inventories')+val(H1,'assets','inventories'))/2/h1cogs*181,'2026_Q3':(val(H1,'assets','inventories')+val(B9,'assets','inventories'))/2/Q['2026_Q3']['cost_of_sales']['value_million']*92}}
DRIVERS=[
 dict(id='D1',name='同口径合并毛利率',source='04 H2; H3第3/9行',bear='x<21%',base='21%<=x<25%',bull='x>=25%',latest=obs['gross_margin'],latest_bucket='bear',latest_period='2026_Q3',frequency='每季；Q4/H1后另检查连续两季联合强确认',actual_source='2026H1 p77–78; Q3 p9–10; quarter bridges',reason='成本/税费/组合共同结果；24–25%过渡带归基准预警，不改变H2基准21–24强确认'),
 dict(id='D2',name='单季经营现金流/合并净利润',source='04 H2; H3第8行上游代理',bear='x<1.0',base='1.0<=x<1.4',bull='x>=1.4',latest=obs['cash_conversion'],latest_bucket='bear',latest_period='2026_Q3',frequency='每季；H1目前仅半年累计作前期参照，不冒称Q2',actual_source='2026H1 p77–78,80–81; Q3 p9–13; quarter bridges',reason='周转/供应商支付/预付与其他现金调整代理；利润<=0时不可评分，须单列负利润风险'),
 dict(id='D3',name='净存货平均周转天数',source='04 H2; H3第7行',bear='x>120日',base='90日<x<=120日',bull='x<=90日',latest=obs['inventory_average_days'],latest_bucket=None,latest_period='2026_Q3',frequency='每季；平均期初期末净存货/同期间成本×天数',actual_source='H1 p72–74,77–78; Q3 p5–10',reason='110–120日过渡归基准预警；不把库存高低直接等同滞销或回款'),
 dict(id='D4',name='净应收账款平均周转天数',source='04 H2; H3第6行',bear='x>80日',base='60日<x<=80日',bull='x<=60日',latest=obs['ar_average_days'],latest_bucket=None,latest_period='2026_Q3',frequency='每季；平均净应收/同期间收入×天数',actual_source='H1 p72–74,77–78; Q3 p5–10',reason='75–80日过渡归基准预警；应收款项融资另入模型，不混入该AR指标'),
 dict(id='D5',name='FY2027全年收入同比',source='04 H2; H3第1行',bear='x<12%',base='12%<=x<20%',bull='x>=20%',latest={'2027_FY':None},latest_bucket='unscorable',latest_period='2027_FY_not_due',frequency='2027年报后；季度/2026高增长不可代替',actual_source='未来2027年报；截止日无数据',reason='8–12%及18–20%为过渡分箱；强确认仍按H2原条件，超过28%属于上行桶另查质量'),
 dict(id='D6',name='资本现金投入/收入',source='04 H3第5行',bear='x>11%',base='9%<=x<=11%',bull='x<9%',latest={'2026_H1':25072.772/h1rev,'2026_Q3':17094.7/Q['2026_Q3']['revenue']['value_million']},latest_bucket='base',latest_period='2026_Q3',frequency='每季并看滚动年；现金购买长期资产/收入',actual_source='H1 p80–81; Q3 p11–13',reason='仅资本效率代理；H3上行早期也可9–11%，因此该行独自不证明上行/失败；<9%需另查产能欠投风险')]
# Capex signal is deliberately removed: H3 bull and base ranges overlap, so a
# mechanical less-than-9 score would invent strategic distinctions. Keep 5 drivers.
DRIVERS=DRIVERS[:5]
for d in DRIVERS:
 if d['id']=='D3':
  v=d['latest']['2026_Q3'];d['latest_bucket']='bull' if v<=90 else 'base' if v<=120 else 'bear'
 if d['id']=='D4':
  v=d['latest']['2026_Q3'];d['latest_bucket']='bull' if v<=60 else 'base' if v<=80 else 'bear'

VALID=[]
for s,years in MODEL.items():
 for y,x in years.items():
  if 'checks' not in x:continue
  for k,v in x['checks'].items():
   good=bool(v) if isinstance(v,bool) else abs(v)<.01
   VALID.append({'scenario':s,'period':y,'check':k,'value':v,'pass':good})
assert all(r['pass'] for r in VALID),[r for r in VALID if not r['pass']]
assert all(x['IS']['SBC_included_in_opex']>=0 for years in MODEL.values() for x in years.values() if 'checks'in x)
INPUT_MANIFEST={f:hashlib.sha256((B/f).read_bytes()).hexdigest() for f in ['01_企业文化.md','02_财务分析.md','03_商业模式.md','04_战略决策.md']}
OUTPUT={'cutoff':'2026-10-24','price_date':'2026-10-23','unit':'CNY million unless ratio/EPS/days','facts_sources':load('source_manifest.json'),'upstream_sha256':INPUT_MANIFEST,'base_actual':START,'base_actual_rounding_residual':START_RES,'common_assumptions':COMMON,'scenario_assumptions':SC,'operating_asset_keys':OP_ASSET,'operating_liability_keys':OP_LIAB,'historical_ratio_assumptions':dict(asset_ratios=ASSET_RATIOS,liability_ratios=LIAB_RATIOS,notes_payable_cogs=NOTES_RATIO,provisions_revenue=PROVISION_RATIO),'model':MODEL,'valuation_bridge':BRIDGE,'divergence_drivers':DRIVERS,'validation':dict(check_count=len(VALID),all_pass=True,checks=VALID),'missing_data':['Q3 supplier finance, equipment-payables intersection, restricted cash/overdraft breakdown','9M actual DA and complete cash-flow reconciliation; no fabricated 2026 full-year historical FCFF','No reliable analyst rating distribution/target range; Bloomberg profit consensus is second-hand quality-limited','No independent licensing profit/cash flows; no separate licensing asset value','NCI ownership by cash-flow-generating unit unavailable; use 7% profit proxy only as assumption']}
for name,obj in [('forecast_model.json',OUTPUT),('valuation_handoff.json',{'unit':'CNY million','price_date':'2026-10-23','scenarios':BRIDGE,'drivers':DRIVERS,'model_file':'forecast_model.json'}),('model_validation.json',OUTPUT['validation'])]:
 (P/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(VALID),'all_pass':True,'base_identity_rounding':START_RES,'summary':{s:{y:{k:round(x['IS'][k],3) for k in ['revenue','parent_net_profit','EPS_parent_current_total_shares']} for y,x in years.items()}for s,years in MODEL.items()},'latest_drivers':{d['id']:[d['latest'],d['latest_bucket']] for d in DRIVERS}},ensure_ascii=False,indent=2))
