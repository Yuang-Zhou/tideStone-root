from pathlib import Path
import pandas as pd,numpy as np,json,hashlib,datetime
from scipy import stats
B=Path(__file__).resolve().parents[2];O=B/'_support/07_market';E=B/'_evidence/07_market'
yp=B/'_support/05/yahoo_total_return_input.csv';tp=B/'_support/05/tx_hfq.csv';mp=E/'beta_tencent_csi300_daily.csv'
y=pd.read_csv(yp);y.index=pd.to_datetime(y.Date.str[:10]);y=y.rename(columns={'Close':'catl_split_only','Adj Close':'catl_adj_dividend'})
t=pd.read_csv(tp);t.index=pd.to_datetime(t.date);t=t.rename(columns={'close':'catl_tencent_hfq'})
m=pd.read_csv(mp);m.index=pd.to_datetime(m.date);m=m.rename(columns={'close':'csi300_price'})
d=y[['catl_split_only','catl_adj_dividend']].join(t[['catl_tencent_hfq']],how='outer').join(m[['csi300_price']],how='outer').loc['2021-10-22':'2026-10-23']
assert not d.index.duplicated().any()
assert ((d.dropna()>0).all().all())
daily_date=pd.Series(d.index,index=d.index)
w=d.resample('W-FRI').last()
for c in d:
 w[c+'_date']=daily_date.where(d[c].notna()).resample('W-FRI').last()
same=w['catl_split_only_date'].eq(w['csi300_price_date'])&w['catl_tencent_hfq_date'].eq(w['csi300_price_date'])
w.loc[~same,list(d.columns)]=np.nan
r=w[list(d.columns)].pct_change(fill_method=None)
for c in r:w[c+'_return']=r[c]
w=w.loc[:'2026-10-23'];w.to_csv(O/'beta_weekly_aligned.csv',index_label='week_friday')
results={}
def fit(col,start='2021-10-23'):
 q=w.loc[start:,[col+'_return','csi300_price_return']].dropna();x=q.iloc[:,1].to_numpy();a=q.iloc[:,0].to_numpy()
 z=stats.linregress(x,a);n=len(x);X=np.column_stack([np.ones(n),x]);res=a-(z.intercept+z.slope*x);inv=np.linalg.inv(X.T@X);sc=X*res[:,None];S=sc.T@sc
 for lag in range(1,5):
  gam=sc[lag:].T@sc[:-lag];S+=(1-lag/5)*(gam+gam.T)
 cov=inv@S@inv*n/(n-2);hac=float(np.sqrt(cov[1,1]));crit=float(stats.t.ppf(.975,n-2))
 return {'n_weekly_returns':n,'first_week':str(q.index.min().date()),'last_week':str(q.index.max().date()),'beta':float(z.slope),'alpha_weekly':float(z.intercept),'ols_beta_stderr':float(z.stderr),'beta_95pct_ci_ols':[float(z.slope-crit*z.stderr),float(z.slope+crit*z.stderr)],'r_squared':float(z.rvalue**2),'newey_west_lag4_beta_stderr':hac,'covariance_sample':float(np.cov(x,a,ddof=1)[0,1]),'market_variance_sample':float(np.var(x,ddof=1)), 'max_abs_stock_weekly_return':float(np.max(abs(a))),'max_abs_index_weekly_return':float(np.max(abs(x)))}
for c in ['catl_split_only','catl_adj_dividend','catl_tencent_hfq']:results[c]=fit(c)
assert results['catl_split_only']['n_weekly_returns']>=200
results['catl_split_only_recent_2y']=fit('catl_split_only','2024-10-24')
conflicts=[]
all_rows=[]
for p in E.glob('beta_tencent_sh000300_*.json'):
 raw=p.read_text();j=json.loads(raw[raw.index('=')+1:] if '=' in raw[:30] else raw)
 all_rows.extend(j['data']['sh000300']['day'])
check=pd.DataFrame([v[:3] for v in all_rows],columns=['date','open','close']);conflicts=check.groupby('date').close.nunique();conflicts=conflicts[conflicts>1].to_dict()
out={'cutoff':'2026-10-23','lookback_start':'2021-10-23','baseline_date':'2021-10-22','fetched_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'method':'OLS with intercept: R_CATL = alpha + beta*R_CSI300 + epsilon; beta=sample covariance/market sample variance; simple returns, not log or excess returns; no winsorization',
 'sampling':'Calendar W-FRI, latest actual close in each week, stock/index actual sampling dates required equal; no forward fill; full-holiday week and next unpaired-week return excluded',
 'primary_return_basis':'Yahoo split-adjusted stock Close (cash dividends excluded) against Tencent CSI300 price index Close (cash dividends excluded)',
 'sensitivity_basis':'Yahoo Adj Close and Tencent hfq include vendor cash-dividend adjustments; still compared to price index, not full total-return-index CAPM',
 'daily_rows':len(d),'weekly_levels_complete':int(w[list(d.columns)].notna().all(axis=1).sum()),'weekly_grid_rows':len(w),'missing_or_mismatched_week_labels':[str(x.date()) for x in w.index[~same]],'benchmark_duplicate_date_close_conflicts':conflicts,
 'latest_csi300_close':float(m.loc['2026-10-23','csi300_price']),
 'source_hashes':{str(p.relative_to(B)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [yp,tp,mp]},'regressions':results,
 'limits':['Historical diagnostic, not future beta or investment advice.','Tencent benchmark is price index 000300, not full-return H00300.','No time-varying risk-free rate deducted; OLS and Newey-West uncertainty do not cover data errors or future regime changes.','CATL constitutes part of CSI300; no leave-CATL-out index constructed.','Existing CATL Yahoo/Tencent source differences remain; sensitivity estimates do not validate either history.']}
(O/'beta_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
