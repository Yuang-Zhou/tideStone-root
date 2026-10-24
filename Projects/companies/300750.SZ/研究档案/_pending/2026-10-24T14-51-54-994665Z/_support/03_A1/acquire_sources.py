from pathlib import Path
import urllib.request,hashlib,json,re,concurrent.futures,subprocess
from bs4 import BeautifulSoup
root=Path('/Users/yuangzhou/Desktop/tideStone-root')
company=root/'Projects/companies/300750.SZ'
batch=company/'研究档案/_pending/2026-10-24T14-51-54-994665Z'
ev=batch/'_evidence/03_A1'; sup=batch/'_support/03_A1'
ev.mkdir(parents=True,exist_ok=True);sup.mkdir(parents=True,exist_ok=True)
urls=[('bmw_20220909.pdf','2022-09-09','https://www.press.bmwgroup.com/united-kingdom/article/attachment/T0403568EN_GB/566314'),('stellantis_20241210.html','2024-12-10','https://www.stellantis.com/en/news/press-releases/2024/december/stellantis-and-calt-to-invest-up-to-4-1-billion-in-joint-venture-for-large-scale-lfp-battery-plant-in-spain'),('ford_20230213.html','2023-02-13','https://www.fromtheroad.ford.com/us/en/articles/2023/ford-taps-michigan-for-new-lfp-battery-plant--new-battery-chemis'),('nio_20240314.html','2024-03-14','https://www.nio.com/news/NIO-Joins-Hands-With-CATL'),('hyperstrong_200gwh.html','2025-11-12','https://www.hyperstrong.com/en/news/company-news/77'),('catl_hyperstrong_60gwh.html','2026-05-06','https://www.catl.com/en/news/6812.html')]
def fetch(x):
 name,date,url=x
 try:
  b=subprocess.check_output(['curl','--fail','--location','--silent','--show-error','--max-time','30',url]);(ev/name).write_bytes(b)
  if name.endswith('.html'): (ev/(name+'.txt')).write_text(BeautifulSoup(b,'html.parser').get_text('\n',strip=True))
  return dict(id=name,published_at=date,url=url,retrieved_at='2026-10-24',sha256=hashlib.sha256(b).hexdigest(),bytes=len(b),file=str(ev/name))
 except Exception as e:return dict(id=name,url=url,error=str(e))
records=list(concurrent.futures.ThreadPoolExecutor(max_workers=6).map(fetch,urls))
catalog=json.loads((company/'_source_catalog.json').read_text())['records']
sel={'annual_2025':[14,15,24,25,26,28,151,195,209],'interim_2026':[16,162],'ir_20260309':[2],'ir_20260724':[1,2,3],'ir_20261020':[2]}
for n,pages in sel.items():
 record=next(x for x in catalog if x['id']==n);s=(company/record['text_file']).read_text();parts=re.split(r'=== PDF PAGE (\d+) ===',s);d={int(parts[i]):parts[i+1] for i in range(1,len(parts),2)}
 f=ev/(n+'_selected_pages.txt');f.write_text('\n'.join('=== PDF PAGE '+str(p)+' ===\n'+d[p] for p in pages));records.append(dict(id=n,url=record['source'],published_at=record['published_at'],retrieved_at=record['retrieved_at'],source_sha256=record['sha256'],source_file=str(company/record['file']),selected_pages=pages,snapshot=str(f),snapshot_sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
(ev/'manifest.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
print(json.dumps([dict(id=x['id'],bytes=x.get('bytes'),error=x.get('error')) for x in records],ensure_ascii=False))
