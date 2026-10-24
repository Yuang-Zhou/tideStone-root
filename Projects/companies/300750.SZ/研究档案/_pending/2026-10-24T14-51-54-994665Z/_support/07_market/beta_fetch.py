from pathlib import Path
import yfinance as yf,json,datetime,hashlib,concurrent.futures,subprocess
B=Path(__file__).resolve().parents[2];out=B/'_evidence/07_market'
def fetch(symbol):
 row={'symbol':symbol,'source':'Yahoo Finance via yfinance','url':f'https://finance.yahoo.com/quote/{symbol}/history/','operation':'history(start=2021-10-15,end=2026-10-24,auto_adjust=False,repair=False,actions=True)','fetched_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  t=yf.Ticker(symbol);d=t.history(start='2021-10-15',end='2026-10-24',auto_adjust=False,repair=False,actions=True,timeout=20)
  p=out/f'beta_{symbol}_daily.csv';d.to_csv(p)
  row.update({'rows':len(d),'first':str(d.index.min()),'last':str(d.index.max()),'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'history_metadata':t.history_metadata})
 except Exception as e:row['error']=str(e)
 return row
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:rows=list(ex.map(fetch,['000300.SS','399300.SZ']))
url='https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300factsheet.pdf';p=out/'beta_csi300_factsheet.pdf'
try:
 subprocess.run(['curl','-L','--fail','--silent','--show-error','--max-time','20',url,'-o',str(p)],capture_output=True,check=True)
 rows.append({'url':url,'file':p.name,'fetched_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
except Exception as e:rows.append({'url':url,'error':str(e)})
(out/'beta_sources.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str))
print(json.dumps([{k:r.get(k) for k in ['symbol','rows','first','last','error']} for r in rows],ensure_ascii=False))
