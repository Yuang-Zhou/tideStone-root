from pathlib import Path
import subprocess, hashlib, json, datetime
root=Path(__file__).parent
sources=[
('ford_20250623.html','2025-06-23','https://www.fromtheroad.ford.com/us/en/articles/2025/ford-owned-american-battery-plant-future-electric-vehicles'),
('ford_20260617.html','2026-06-17','https://www.fromtheroad.ford.com/us/en/articles/2026/blueoval-battery-park-michigan-hiring-and-lfp-production'),
('dod_20260610.pdf','2026-06-10','https://www.govinfo.gov/content/pkg/FR-2026-06-10/pdf/2026-11571.pdf'),
('catl_statement_20260605.html','2026-06-05','https://www.catl.com/en/news/6832.html'),
('catl_swap_20241218.html','2024-12-18','https://www.catl.com/en/news/6342.html'),
('catl_swap_20251230.html','2025-12-30','https://www.catl.com/news/9516.html'),
('catl_carbon_20260817.html','2026-08-17','https://www.catl.com/news/10150.html'),
('byd_wang.html',None,'https://media.byd.com/wang-chuanfu/?lang=eng')]
results=[]
for name,date,url in sources:
 p=root/name
 r=subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time','35',url,'--output',str(p)],capture_output=True,text=True)
 results.append(dict(file=name,url=url,published=date,retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),success=r.returncode==0,sha256=hashlib.sha256(p.read_bytes()).hexdigest() if r.returncode==0 else None,bytes=p.stat().st_size if p.exists() else None,error=r.stderr if r.returncode else None))
(root/'sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2))
