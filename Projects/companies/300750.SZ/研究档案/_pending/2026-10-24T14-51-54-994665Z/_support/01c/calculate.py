import json,pathlib
b=pathlib.Path(__file__).resolve().parents[2]
d=json.loads((b/'_support/02/analysis_inputs_results.json').read_text())['data']
inputs={'price_cny':237.6,'price_date':'2026-10-23','price_evidence':'_support/05/tx_raw.csv; _evidence/05/web_read_snapshot.json','shares_q3':4627249686,'direct_shares':{'李平':197460277,'谭立斌':126128,'蒋理':50639,'郑舒':46166},'cash_salary_2025_cny':{'谭立斌':2642000,'蒋理':1942000,'郑舒':2829000},'zeng_indirect':1019704949,'sbc_million':{'2023':676.7224,'2024':688.995,'2025':-82.524,'2026H1':184.816},'catl_h1_revenue_million':276916.580,'catl_h1_net_parent_million':43284.002,'eve_h1_cny':{'sbc':437458080.48,'revenue':45691465298.91,'net_parent':3301230562.92},'shares':[4399041236,4403466458,4563803488,4627249686],'unrestricted_shares':[3894854493,3902556333,4412488658,4478377261],'buyback_plans':[{'shares':15991524,'cny':2710713907.10},{'shares':15990782,'cny':4385504687.90},{'shares':10945162,'cny':3303000000}],'related_purchases_kcny':[13899432,17066845,199830,1670,4723,3439],'related_sales_kcny':[87340,4551,6248366,1760164,905895]}
r={'management':{n:{'market_value_cny':s*inputs['price_cny'],'pct_total':s/inputs['shares_q3']*100,'value_to_cashsalary':s*inputs['price_cny']/inputs['cash_salary_2025_cny'][n] if n in inputs['cash_salary_2025_cny'] else None} for n,s in inputs['direct_shares'].items()},'zeng_indirect_value_cny':inputs['zeng_indirect']*inputs['price_cny'],'sbc_ratios_pct':{},'capital_yi_cny':{}}
for y in ['2023','2024','2025']:
 r['sbc_ratios_pct'][y]={'revenue':inputs['sbc_million'][y]/d[y]['revenue']*100,'net_parent':inputs['sbc_million'][y]/d[y]['net_profit_parent']*100}
 r['capital_yi_cny'][y]={k:d[y][k]/100 for k in ['cash_paid_for_long_lived_assets','research_and_development_expenses','acquisitions','buyback','net_debt_repay']}
r['sbc_ratios_pct']['2026H1']={'revenue':inputs['sbc_million']['2026H1']/inputs['catl_h1_revenue_million']*100,'net_parent':inputs['sbc_million']['2026H1']/inputs['catl_h1_net_parent_million']*100}
r['sbc_ratios_pct']['EVE2026H1']={k:inputs['eve_h1_cny']['sbc']/inputs['eve_h1_cny'][k]*100 for k in ['revenue','net_parent']}
r['2023plan_2023_2025_cumulative_revenue_yi']=sum(d[y]['revenue'] for y in ['2023','2024','2025'])/100
r['share_increase_2023_Q32026_pct']=(inputs['shares'][-1]/inputs['shares'][0]-1)*100
r['share_increase_2024_2025_pct']=(inputs['shares'][2]/inputs['shares'][1]-1)*100
r['share_increase_2025_Q32026_pct']=(inputs['shares'][3]/inputs['shares'][2]-1)*100
r['buyback_average_cny']=[x['cny']/x['shares'] for x in inputs['buyback_plans']]
r['first_two_buyback_total_yi']=sum(x['cny'] for x in inputs['buyback_plans'][:2])/1e8
r['related_purchases_yi']=sum(inputs['related_purchases_kcny'])/100000
r['related_sales_yi']=sum(inputs['related_sales_kcny'])/100000
r['li_pledge_pct_of_own']=24550000/inputs['direct_shares']['李平']*100
(b/'_support/01c/governance_calculations.json').write_text(json.dumps({'as_of':'2026-10-24','inputs':inputs,'outputs':r},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r,ensure_ascii=False,indent=2))
