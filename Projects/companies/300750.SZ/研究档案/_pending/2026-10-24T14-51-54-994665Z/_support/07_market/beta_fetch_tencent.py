from pathlib import Path
import json,datetime,hashlib,concurrent.futures,subprocess,urllib.parse,pandas as pd
B=Path(__file__).resolve().parents[2];out=B/'_evidence/07_market'
def fetch(year):
 params={'_var':'kline_dayqfq','param':f'sh000300,day,{year}-01-01,{year+1}-12-31,640,qfq','r':'0.8205512681390605'}
 url='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?'+urllib.parse.urlencode(params)
 p=out/f'beta_tencent_sh000300_{year}.json';row={'url':url,'file':p.name,'fetched_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  subprocess.run(['curl','-L','--fail','--silent','--show-error','--max-time','20',url,'-o',str(p)],capture_output=True,check=True)
  raw=p.read_bytes();row['sha256']=hashlib.sha256(raw).hexdigest();s=raw.decode();j=json.loads(s[s.index('=')+1:] if '=' in s[:30] else s);d=j['data']['sh000300'];key='day' if 'day' in d else 'qfqday';a=d[key];row['response_key']=key;row['rows']=len(a)
  return row,a
 except Exception as e:row['error']=str(e);return row,[]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:rs=list(ex.map(fetch,range(2021,2027)))
rows=[r for r,a in rs];arr=[v[:6] for r,a in rs for v in a]
if arr:
 d=pd.DataFrame(arr,columns=['date','open','close','high','low','volume']).drop_duplicates('date').sort_values('date');d=d[(d.date>='2021-10-15')&(d.date<='2026-10-23')];d.to_csv(out/'beta_tencent_csi300_daily.csv',index=False)
(out/'beta_tencent_sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False));print('dates',len(d),d.iloc[0].date,d.iloc[-1].date)
