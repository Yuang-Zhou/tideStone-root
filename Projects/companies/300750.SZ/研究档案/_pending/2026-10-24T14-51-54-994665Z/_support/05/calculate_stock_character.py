"""Reproduce stock-character metrics. No prices or financial results are invented."""
from pathlib import Path
import hashlib, json, math
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent
y = pd.read_csv(ROOT / 'yahoo_total_return_input.csv')
y['date'] = y['Date'].str[:10]
y = y.set_index('date')
t = pd.read_csv(ROOT / 'tx_raw.csv', index_col='date')
h = pd.read_csv(ROOT / 'tx_hfq.csv', index_col='date')
# Tencent full date inventory; Yahoo uses split-adjusted Close, not original raw Close.
out = y[['Close', 'Adj Close', 'Dividends', 'Stock Splits']].reindex(t.index)
out['source'] = 'Yahoo'
fills = []
for day in t.index.difference(y.index):
    prior = y.loc[y.index < day].iloc[-1]
    after = y.loc[y.index > day].iloc[0]
    f1, f2 = prior['Adj Close']/prior['Close'], after['Adj Close']/after['Close']
    assert abs(f1-f2) < 1e-6, 'Missing date crosses adjustment factor change'
    close = t.loc[day, 'close'] / 1.8
    out.loc[day, ['Close', 'Adj Close', 'Dividends', 'Stock Splits']] = [close, close*f1, 0, 0]
    out.loc[day, 'source'] = 'Tencent raw / 1.8 * adjacent Yahoo dividend adjustment factor'
    fills.append({'date':day,'raw_close':t.loc[day,'close'],'factor':f1,'next_factor':f2,'adjusted_close':close*f1})
assert out['Adj Close'].gt(0).all() and len(out) == 2030
out['log_adjusted_close'] = np.log(out['Adj Close'])
out['index_ipo_100'] = out['Adj Close']/out.iloc[0]['Adj Close']*100
out.to_csv(ROOT/'daily_log_series.csv',index_label='date')
intervals = [('2018-06-11','2019-12-31'),('2019-12-31','2021-12-02'),('2021-12-02','2024-01-30'),('2024-01-30','2024-10-08'),('2024-10-08','2025-04-09'),('2025-04-09','2026-05-06'),('2026-05-06','2026-10-23')]
segments=[]
for start,end in intervals:
    a,b=float(out.loc[start,'Adj Close']),float(out.loc[end,'Adj Close'])
    years=(pd.Timestamp(end)-pd.Timestamp(start)).days/365.25
    g=out.loc[start:end,'Adj Close']; ret=g.pct_change().dropna()
    segments.append({'start':start,'end':end,'start_adjusted':a,'end_adjusted':b,'return_pct':100*(b/a-1),'annualized_pct':100*((b/a)**(1/years)-1),'log_slope_per_year':math.log(b/a)/years,'annualized_daily_vol_pct':100*ret.std()*math.sqrt(244),'tencent_hfq_change_pct':100*(h.loc[end,'close']/h.loc[start,'close']-1)})
# All values below are explicit original-report inputs, unit CNY million, million shares.
# 2018-2020: annual_2020.pdf p6 and shares p53; 2018 shares annual2018 p65.
# 2021: annual_2021_eastmoney.pdf p8 and p90; 2022-2026: this batch 02 inputs.
fin = {
 '2018':dict(revenue=29611.26543422,profit=3387.03520764,shares=2195.0174),
 '2019':dict(revenue=45788.02064241,profit=4560.30743271,shares=2208.3997),
 '2020':dict(revenue=50319.48769720,profit=5583.33871038,shares=2329.474028),
 '2021':dict(revenue=130355.7964,profit=15931.3179,shares=2330.8512),
 '2022':dict(revenue=328593.9875,profit=30729.1635,shares=2442.5145),
 '2023':dict(revenue=400917.045,profit=44121.248,shares=4399.041),
 '2024':dict(revenue=362012.554,profit=50744.682,shares=4403.466),
 '2025':dict(revenue=423701.834,profit=72201.282,shares=4563.803),
}
cross=[]
for year,v in fin.items():
    price=float(t.loc[t.index.str[:4]==year,'close'].iloc[-1]); split=1.8 if int(year)<2023 else 1
    cross.append(dict(year=year,**v,yearend_raw_close=price,pe_ex_post=price*v['shares']/v['profit'],ps_ex_post=price*v['shares']/v['revenue'],earnings_per_yearend_share_split_adjusted=v['profit']/v['shares']/split))
last=237.6; shares=4627.250
current={'as_of':'2026-10-23','close_cny':last,'shares_mn':shares,'a_price_equivalent_equity_mn':last*shares,'profit_ttm_mn':72201.282-49034.109+64530.063,'core_profit_ttm_mn':64507.864-43619.225+57875.782,'revenue_ttm_mn':423701.834-283071.987+442137.424}
current['pe_ttm']=current['a_price_equivalent_equity_mn']/current['profit_ttm_mn']
current['core_pe_ttm']=current['a_price_equivalent_equity_mn']/current['core_profit_ttm_mn']
current['ps_ttm']=current['a_price_equivalent_equity_mn']/current['revenue_ttm_mn']
current['pe_fy2025']=current['a_price_equivalent_equity_mn']/72201.282
rawdiff=(y['Close']*np.where(y.index<'2023-04-26',1.8,1)-t['close'].reindex(y.index)).abs()
prices=out['Adj Close'];drawdown=prices/prices.cummax()-1
events=[]
for d in ['2020-02-03','2020-02-04','2024-09-24','2024-09-30','2025-05-20','2026-10-21','2026-10-22','2026-10-23']:
    pos=t.index.get_loc(d);events.append({'date':d,'close':float(t.iloc[pos]['close']),'one_day_pct':100*(t.iloc[pos]['close']/t.iloc[pos-1]['close']-1)})
hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in ROOT.glob('*.csv')}
res={'as_of':'2026-10-24 Asia/Shanghai','source_hashes':hashes,'fills':fills,'validation':{'rows':len(out),'yahoo_rows':len(y),'nonpositive':int((prices<=0).sum()),'raw_source_difference_over_002':int((rawdiff>.02).sum()),'max_raw_relative_difference_pct':float((rawdiff/t['close'].reindex(y.index)).max()*100)},'segments':segments,'annual_cross_sections':cross,'current':current,'events':events,'full_period':{'return_pct':100*(prices.iloc[-1]/prices.iloc[0]-1),'annualized_pct':100*((prices.iloc[-1]/prices.iloc[0])**(365.25/(pd.Timestamp(prices.index[-1])-pd.Timestamp(prices.index[0])).days)-1),'max_drawdown_pct':float(100*drawdown.min()),'max_drawdown_date':drawdown.idxmin()},'notes':['Returns are vendor-adjusted-price changes, not independently audited tax-adjusted dividend reinvestment returns.','Annual P/E uses full-year realized profit: ex-post research statistic, NOT point-in-time tradable trailing P/E.','A-price-equivalent equity values all A/H shares at the A price, NOT combined exchange market capitalization.','2023 reported EPS conflict deliberately bypassed via profit / year-end total shares.']}
(ROOT/'calculation_results.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
print(json.dumps(res,ensure_ascii=False,indent=2))
