"""CATL07 locked-input valuation. Local outputs only; never registry mutations."""
from pathlib import Path
import json, hashlib, math, statistics
import valuation_core as vc

B = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PINS = json.loads((B/'_support/06/delivery_hashes.json').read_text())
for rel, meta in PINS.items():
    assert hashlib.sha256((B/rel).read_bytes()).hexdigest() == meta['sha256'], rel
M = vc.read_pinned(B/'_support/06/forecast_model.json', PINS['_support/06/forecast_model.json']['sha256'])
H = vc.read_pinned(B/'_support/06/valuation_handoff.json', PINS['_support/06/valuation_handoff.json']['sha256'])
F = json.loads((B/'_support/02/analysis_inputs_results.json').read_text())['data']['TTM']
G = json.loads((B/'_evidence/valuation_precheck/ttm_revenue_growth.json').read_text())
PEERS = json.loads((B/'_support/07_market/market_calculations.json').read_text())
PRICE, SHARES = 237.6, 4627.25
MCAP = PRICE*SHARES
CC = vc.capital_cost(.0164,.0514,1.30,.022,.15,MCAP,189926.135)
CFG = dict(wacc=CC['wacc'],terminal_growth=.025,terminal_incremental_roic=.10,
           exit_ebitda_multiple=8., tax_rate=.15,cash_reserve_scale=1.,cash_gap_recovery=0.,
           associate_value_to_book=.75,financial_value_to_book=.90,nci_equity_fraction=.07,
           supplier_finance_scale=1.,equipment_ap_claim_fraction=1.,long_payables_debt_fraction=0.)
PE = {'bear':14.,'base':18.,'bull':22.}
SCORE = vc.score_drivers(H['drivers'])
assert SCORE['dominant']=='bear' and SCORE['denominator']==4
RESULTS = {}
for s, rows in M['model'].items():
    d = vc.dcf(rows,H['scenarios'][s],M['base_actual'],CFG)
    eps = rows['2027']['IS']['EPS_parent_current_total_shares']
    p = eps*PE[s]
    RESULTS[s] = dict(dcf=d,pe_multiple=PE[s],eps_fy2027=eps,price_pe=p,
                     current_price_forward_pe=PRICE/eps,
                     implied_ps_at_target=PE[s]*rows['2027']['IS']['parent_net_profit']/rows['2027']['IS']['revenue'],
                     current_price_forward_ps=MCAP/rows['2027']['IS']['revenue'],
                     price_change=p/PRICE-1,margin_of_safety=(p-PRICE)/p,
                     dcf_gordon_deviation_from_pe=d['gordon']['per_share']/p-1,
                     dcf_exit_deviation_from_pe=d['exit']['per_share']/p-1)
env = vc.pure_forecaster(B/'_support/06/model.py',PINS['_support/06/model.py']['sha256'])
zero = vc.shifted_forecast(env,'base',0,0)
max_error=0.
for period in zero:
    for section in ['IS','CF']:
        for key,value in M['model']['base'][period][section].items():
            if isinstance(value,(int,float)) and key in zero[period][section]:
                err=abs(zero[period][section][key]-value);max_error=max(max_error,err)
                assert math.isclose(zero[period][section][key],value,rel_tol=1e-10,abs_tol=1e-6),(period,section,key,err)
matrix1 = vc.matrix_wacc_growth(M['model']['base'],H['scenarios']['base'],M['base_actual'],CFG,[-.01,-.005,0,.005,.01])
matrix2 = vc.matrix_growth_margin(env,'base',H['scenarios']['base'],M['base_actual'],CFG,[-.02,-.01,0,.01,.02])
assert math.isclose(matrix1['values'][2][2],RESULTS['base']['dcf']['gordon']['per_share'],abs_tol=1e-8)
assert math.isclose(matrix2['values'][2][2],RESULTS['base']['dcf']['gordon']['per_share'],abs_tol=1e-8)
SENS=[]
for key, levels in [('terminal_incremental_roic',[.08,.10,.12]),('exit_ebitda_multiple',[6,8,10]),
                    ('supplier_finance_scale',[0,.5,1,1.5]),('equipment_ap_claim_fraction',[0,1]),
                    ('long_payables_debt_fraction',[0,1]),('nci_equity_fraction',[0,.07,.15]),
                    ('associate_value_to_book',[0,.75,1]),('financial_value_to_book',[0,.9,1]),
                    ('cash_reserve_scale',[0,1,1.5]),('cash_gap_recovery',[0,1])]:
    for level in levels:
        item={'parameter':key,'value':level,'prices':{}}
        for s in ['bear','base','bull']:
            d=vc.dcf(M['model'][s],H['scenarios'][s],M['base_actual'],{**CFG,key:level})
            item['prices'][s]={'gordon':d['gordon']['per_share'],'exit':d['exit']['per_share']}
        SENS.append(item)
beta_sens=[]
for beta in [1.,1.3,1.6]:
    cc=vc.capital_cost(.0164,.0514,beta,.022,.15,MCAP,189926.135)
    beta_sens.append({'beta_forward_assumption':beta,'wacc':cc['wacc'],
      'bear_gordon_price':vc.dcf(M['model']['bear'],H['scenarios']['bear'],M['base_actual'],{**CFG,'wacc':cc['wacc']})['gordon']['per_share']})
eps_ttm=F['net_profit_parent']/SHARES
bridge=vc.price_change_bridge(PRICE,eps_ttm,RESULTS['bear']['eps_fy2027'],PE['bear'])
cash=333397.571;debt=189926.135;sf=57764.224;ev=MCAP+debt-cash
current=dict(price=PRICE,shares_million=SHARES,market_cap=MCAP,financial_period='TTM 2026-09-30',
             revenue=F['revenue'],net_parent=F['net_profit_parent'],eps=eps_ttm,core_parent=F['parent_adj'],
             core_eps=F['parent_adj']/SHARES,pe=MCAP/F['net_profit_parent'],core_pe=MCAP/F['parent_adj'],
             ps=MCAP/F['revenue'],ocf=F['operating_cash_flow'],capex=F['cash_paid_for_long_lived_assets'],fcf=F['fcf'],
             cash_equivalents_proxy=cash,explicit_debt=debt,net_debt=debt-cash,net_debt_with_sf=debt+sf-cash,
             ev=ev,ev_with_sf=ev+sf,ev_fcf=ev/F['fcf'],ev_fcf_with_sf=(ev+sf)/F['fcf'],
             revenue_prior_ttm=G['2025Q3_TTM_revenue'],revenue_growth_pct=G['TTM_revenue_growth_percent'],
             efg=(ev/F['fcf'])/G['TTM_revenue_growth_percent'],efg_with_sf=((ev+sf)/F['fcf'])/G['TTM_revenue_growth_percent'],
             ttm_da=None,ttm_operating_ebitda=None,ev_ebitda=None)
base2029=M['model']['base']['2029']
debt_keys=['short_term_borrowings','current_portion_of_noncurrent_liabilities','long_term_borrowings','bonds_payable','lease_noncurrent']
debt2029=sum(base2029['BS']['liabilities'][k] for k in debt_keys)
ce2029=base2029['CF']['ending_cash_equivalents_proxy']
third=dict(target_year=2029,target_date='2029-10-23',currency='CNY',scenario='base',valuation_method='FY2029年度归母利润参考PE 18x',valuation_type='equity',
           metric_value_b=base2029['IS']['parent_net_profit']/1000,target_multiple=18.,net_debt_b=(debt2029-ce2029)/1000,
           share_equivalent_b=SHARES/1000,target_market_cap_b=base2029['IS']['parent_net_profit']*18/1000,
           target_price_3y=base2029['IS']['EPS_parent_current_total_shares']*18,
           anchor_price=PRICE,anchor_date='2026-10-23',financial_period='FY2029',balance_date='2029-12-31 forecast',
           source='本批06 _support/06/forecast_model.json model.base.2029；本批07 _support/07/valuation_results.json three_year。净债为FY2029年末显性债务减CE代理，不参与equity法价格公式，非目标日现金事实。',
           note='条件化基准情景2029-10-23价格；当前主导为悲观，二者不是同一收益路径；无回购缩股假设，非摊薄EPS。')
third_growth=dict(price_change=third['target_price_3y']/PRICE-1,cagr=(third['target_price_3y']/PRICE)**(1/3)-1)
targets={s:RESULTS[s]['price_pe'] for s in PE}
main=targets['bear']
reg=dict(rating='强烈卖出',target_year=2026,target_date='2026-10-23',
    horizon='2026-10-23当前公允价值，采用FY2027下一完整年度归母利润的估值日forward PE；12个月仅复核窗口，不是未来一年目标价',
    target_price=f'CNY {main:.2f}（当前公允价值；主导=悲观，主锚=FY2027情景归母PE 14x；乐观{targets["bull"]:.2f}/基准{targets["base"]:.2f}/悲观{main:.2f}；估值日2026-10-23，资料截止2026-10-24）',
    zones=[{'label':'买入观察区','range':f'≤ CNY {main*.75:.2f}，需信号与假设仍成立'},
           {'label':'价值复核区','range':f'CNY {main*.85:.2f}–{main*1.15:.2f}'},
           {'label':'减持／卖出观察区','range':f'≥ CNY {main:.2f}；> CNY {main*1.30:.2f}为强烈卖出估值档'}],
    opportunity_type=dict(business_track='周期型',price_pattern='台阶（自身触发）',
       label='周期型业务 · 自身触发台阶型股价 · 当前价格下行主要来自盈利下修',return_split=bridge['return_split'],holding_style='按周期进出',
       regime_switch='04 H4：连续两年独立许可/服务收入≥5%或经营利润≥10%，且支持成本后现金为正；达成后撤销本业务类型判定并重新核对新引擎与定价锚，不自动升为相变型。'),
    scenario_valuation=dict(anchor_method='估值日/FY2027情景归母EPS的PE；排除偶发收益但非跨周期中枢，05确认盈利兑现主导，04 H4新锚条件未确认。',
       scenarios={s:{'price':round(targets[s],6),'thesis':{'bear':'利润率与现金承压延续；FY2027 EPS×14','base':'量增长、周转修复且税费压力部分吸收；FY2027 EPS×18','bull':'产品/区域结构及规模降本实现，现金同步兑现；FY2027 EPS×22'}[s]} for s in ['bull','base','bear']},
       dominant='bear',confidence='中',judged_at='2026-10-24',as_of='2026-10-23',financial_period='FY2027',
       rationale='D1–D5：乐观1/4、基准1/4、悲观2/4；D5未到期不计分母。毛利率与现金拖累领先，存货基准及应收乐观是反例；未达到未来连续两季强确认。',
       signals=[{'scenario':s,'signal':f'D1毛利率{H["drivers"][0][s]}；D2 OCF/合并净利{H["drivers"][1][s]}；其余沿06 D3–D5，季报后逐项计分',
                 'status':{'bear':'D1/D2命中','base':'D3命中','bull':'D4命中'}[s],
                 'action':f'仅在全表重新计分反超后改锚CNY {targets[s]:.2f}；驱动假设被推翻则重跑06/07'} for s in ['bull','base','bear']]))
result=dict(unit='CNY million except per-share, ratios and explicitly _b fields',cutoff='2026-10-24',as_of='2026-10-23',
            inputs_sha256=PINS,parameters=CFG,capital_cost=CC,score=SCORE,current=current,scenarios=RESULTS,
            sensitivity_wacc_g_base=matrix1,sensitivity_growth_margin_base=matrix2,claim_and_terminal_sensitivity=SENS,
            forward_beta_sensitivity=beta_sens,return_bridge=bridge,three_year=third,three_year_growth=third_growth,registry=reg,
            validation={'zero_shock_IS_CF_max_error_million':max_error,'both_matrix_centers_match_base':True,
                        'upstream_hashes_verified':True,'return_bridge_exact':True},
            conditional_peer_median={'pe_n':2,'pe':statistics.median([PEERS['eve']['pe'],PEERS['calb']['pe_indicative']]),
                                     'ps_n':3,'ps':statistics.median([PEERS['eve']['ps'],PEERS['calb']['ps_indicative'],PEERS['lges']['ps']])})
(OUT/'valuation_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'capital_cost':CC,'scenario_prices':{s:{'PE':r['price_pe'],'DCF_G':r['dcf']['gordon']['per_share'],'DCF_exit':r['dcf']['exit']['per_share']} for s,r in RESULTS.items()},'return_bridge':bridge,'three_year':third,'current':current,'validation':result['validation']},ensure_ascii=False,indent=2))
