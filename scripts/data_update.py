#!/usr/bin/env python3
"""Run the source system's material fetchers and preserve real success/failure records."""
from pathlib import Path
import argparse,datetime,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
P=Path(os.environ.get('TIDESTONE_PROJECTS',ROOT/'Projects')).resolve()
PY=str(ROOT/'.venv/bin/python') if (ROOT/'.venv/bin/python').exists() else sys.executable
p=argparse.ArgumentParser();p.add_argument('ticker');p.add_argument('--probe',action='store_true');a=p.parse_args();a.ticker=a.ticker.upper()
data=json.loads((P/'_system/companies.json').read_text());c=data['companies'].get(a.ticker)
if not c:raise SystemExit('请先入库')
folder=P/c['folder'];raw=folder/(a.ticker+' Wiki')/'raw';raw.mkdir(parents=True,exist_ok=True)
env=dict(os.environ);cfg=ROOT/'config/local.env'
if cfg.exists():
    for line in cfg.read_text().splitlines():
        if line.startswith('SEC_USER_AGENT='):env['SEC_USER_AGENT']=line.split('=',1)[1].strip().strip('"\'')
steps=[('定期报告','fetch_raw_filings.py',[a.ticker,'--out',str(raw)]),('电话会纪要','fetch_transcripts.py',[a.ticker,'--out',str(raw/'transcripts')]),('SEC 财务底稿','fetch_edgar_financials.py',[a.ticker,'--out',str(raw/'财务数据/EDGAR')])]
records=[];started=datetime.datetime.now().astimezone().isoformat()
for title,script,args in steps:
    if c.get('market')!='US' and script!='fetch_raw_filings.py':records.append({'name':title,'status':'not_applicable','detail':'原来源脚本仅适用美国上市公司'});continue
    if a.probe and script=='fetch_edgar_financials.py':records.append({'name':title,'status':'skipped','detail':'该脚本无probe模式'});continue
    try:
        result=subprocess.run([PY,str(ROOT/'Projects/_system/scripts'/script),*args,*(['--probe'] if a.probe else [])],env=env,cwd=ROOT,capture_output=True,text=True,timeout=600)
        record={'name':title,'status':'passed' if result.returncode==0 else 'failed','returncode':result.returncode,'output':result.stdout+'\n'+result.stderr}
    except (OSError,subprocess.TimeoutExpired) as e:record={'name':title,'status':'failed','output':str(e)}
    records.append(record)
if not a.probe:
    for f in sorted(raw.rglob('*')):
        if not f.is_file() or f.stat().st_size==0:continue
        if f.name.upper().startswith('MANIFEST'):continue
        if f.suffix.lower() not in ['.pdf','.md','.html','.json','.csv','.xlsx']:continue
        subprocess.run([PY,str(ROOT/'scripts/tidestone.py'),'material',a.ticker,'--file',str(f),'--source','原取数脚本保存的公开材料；URL和失败项见 '+str(raw/'MANIFEST.md'),'--kind','公开资料'],env=env,cwd=ROOT,capture_output=True,text=True,check=True)
report={'started_at':started,'finished_at':datetime.datetime.now().astimezone().isoformat(),'ticker':a.ticker,'probe':a.probe,'steps':records}
name='fetch-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.json';out=folder/'_fetch_runs';out.mkdir(exist_ok=True);(out/name).write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if any(r['status']=='failed' for r in records) else 0)
