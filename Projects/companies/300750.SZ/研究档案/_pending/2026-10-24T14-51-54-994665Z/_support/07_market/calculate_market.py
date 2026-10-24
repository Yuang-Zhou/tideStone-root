"""Fact preparation only. All financial values below are currency units, not millions."""
from pathlib import Path
import json, hashlib, datetime
B=Path(__file__).resolve().parents[2]
eve={
 'price':44.33,'shares':2173296935,'currency':'CNY','price_date':'2026-10-23',
 'financial_period':'TTM 2026-09-30','disclosure_date':'2026-10-24',
 'revenue_fy2025':61469630776.09,'revenue_9m2026':73389947997.06,'revenue_9m2025':45001518158.94,
 'revenue_fy2024':48614556525.09,'revenue_9m2024':34049276929.36,
 'net_parent_fy2025':4134303670.89,'net_parent_9m2026':5240214681.64,'net_parent_9m2025':2815688702.22,
 'ocf_fy2025':7492131666.79,'ocf_9m2026':1698054724.76,'ocf_9m2025':4903825467.82,
 'capex_fy2025':10446078262.32,'capex_9m2026':8218743666.50,'capex_9m2025':7458066064.89,
 'sources':{'FY2025':'../03_A3/eve_2025.pdf physical p94 cash-flow, p9 key figures','9M2026':'eve_q3_2026.pdf p1/9/10/11/13','9M2025':'eve_q3_2025.pdf physical p9'}}
for metric in ['revenue','net_parent','ocf','capex']:
 eve[metric+'_ttm']=eve[metric+'_fy2025']+eve[metric+'_9m2026']-eve[metric+'_9m2025']
eve['revenue_prior_ttm']=eve['revenue_fy2024']+eve['revenue_9m2025']-eve['revenue_9m2024']
eve['revenue_growth_pct']=(eve['revenue_ttm']/eve['revenue_prior_ttm']-1)*100
eve['market_cap']=eve['price']*eve['shares']
eve['pe']=eve['market_cap']/eve['net_parent_ttm'];eve['ps']=eve['market_cap']/eve['revenue_ttm']
eve['fcf_ttm']=eve['ocf_ttm']-eve['capex_ttm'];eve['efg']=None
calb={'price':13.55,'price_currency':'HKD','price_date':'2026-10-23','shares':1772301858,
 'shares_basis':'FY2025 annual p68/205; current Yahoo market cap corroborates total but its sharesOutstanding field only H shares',
 'h_shares':761499395,'financial_currency':'CNY','financial_period':'TTM 2026-06-30',
 'revenue_ttm':55066000000,'net_parent_ttm':1945000000,'revenue_growth_pct':73.70,
 'financial_source':'StockAnalysis/S&P income rounded millions, not statutory H1 reconciliation',
 'fx_hkd_per_cny':1.1755,'fx_source':'Investing daily history 2026-10-23 saved web snapshot; non-synchronous with HK equity close',
 'efg':None,'fcf_ttm':None,'fcf_fy2025':-4227000000}
calb['market_cap_hkd_equivalent']=calb['price']*calb['shares']
calb['market_cap_cny_equivalent']=calb['market_cap_hkd_equivalent']/calb['fx_hkd_per_cny']
calb['h_class_cap_hkd']=calb['price']*calb['h_shares']
calb['pe_indicative']=calb['market_cap_cny_equivalent']/calb['net_parent_ttm']
calb['ps_indicative']=calb['market_cap_cny_equivalent']/calb['revenue_ttm']
lges={'price':383000,'shares':234000000,'currency':'KRW','price_date':'2026-10-23','financial_period':'TTM 2026-06-30',
 'revenue_ttm':25218017000000,'net_parent_ttm':-1683059000000,'revenue_growth_pct':0.23,
 'ocf_ttm':2729405000000,'capex_ttm':7975185000000,'financial_source':'StockAnalysis/S&P rounded million KRW; Yahoo crosscheck', 'pe':None,'efg':None}
lges['market_cap']=lges['price']*lges['shares'];lges['ps']=lges['market_cap']/lges['revenue_ttm'];lges['fcf_ttm']=lges['ocf_ttm']-lges['capex_ttm']
sdi={'price_common':490500,'currency':'KRW','price_date':'2026-10-23','financial_period':'TTM 2026-06-30',
 'common_issued':80585530,'preferred_issued':1617896,'common_treasury_q1':3331391,'preferred_treasury_q1':178400,
 'revenue_ttm':14255668000000,'revenue_growth_pct':1.49,'net_parent_ttm_sp':44563000000,'net_parent_ttm_yahoo':-231009026048,
 'ocf_ttm':200182000000,'capex_ttm':2321325000000,'fcf_ttm_sp':-2121144000000,
 'market_cap_all_classes':None,'pe':None,'ps':None,'efg':None,
 'missing':'Current preferred price, current treasury-share movement and TTM net income reconciliation; no blended class PE accepted'}
sdi['common_issued_market_cap']=sdi['price_common']*sdi['common_issued']
sdi['common_outstanding_q1']=sdi['common_issued']-sdi['common_treasury_q1']
sdi['preferred_outstanding_q1']=sdi['preferred_issued']-sdi['preferred_treasury_q1']
catl={'price':237.6,'currency':'CNY','shares':4627250000,'revenue_ttm':582767271000,'net_parent_ttm':87697236000,
 'price_date':'2026-10-23','shares_date':'2026-09-30','market_cap_basis':'A-price equivalent of all A+H shares, not aggregate A/H class market caps',
 'beta_provider_5y':0.47,'beta_source':'StockAnalysis statistics, underlying benchmark/frequency not disclosed; not own regression'}
catl['market_cap']=catl['price']*catl['shares'];catl['pe']=catl['market_cap']/catl['net_parent_ttm'];catl['ps']=catl['market_cap']/catl['revenue_ttm']
out={'asof':'2026-10-24','purpose':'Market facts only; no scenario, target price, fair multiple or rating','catl':catl,'eve':eve,'calb':calb,'lges':lges,'sdi':sdi}
assert eve['fcf_ttm']<0 and lges['fcf_ttm']<0
(B/'_support/07_market/market_calculations.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
hashes=[]
for p in sorted((B/'_evidence/07_market').glob('*')):
 if p.is_file() and p.name!='sha256_manifest.json':
  hashes.append({'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
(B/'_evidence/07_market/sha256_manifest.json').write_text(json.dumps({'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':hashes},ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
