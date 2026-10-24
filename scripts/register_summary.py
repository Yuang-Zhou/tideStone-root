#!/usr/bin/env python3
"""Register an actual summary and the accepted dossier versions it summarizes."""
import argparse,hashlib,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Projects/_system/scripts'))
import local_workflow as local
import dossier_orchestrator as dossier
p=argparse.ArgumentParser();p.add_argument('ticker');p.add_argument('--markdown',required=True);p.add_argument('--html',required=True);a=p.parse_args();a.ticker=local.checked_ticker(a.ticker)
with local.lock():
    folder=local.company_dir(a.ticker);dd=folder/'研究档案'
    errors={s:dossier.approved_slot_errors(dd,s) for s in local.SLOTS}
    if any(errors.values()):raise SystemExit('总结依据必须是七份已接受完整档案：'+json.dumps(errors,ensure_ascii=False))
    paths={'markdown':Path(a.markdown).resolve(),'html':Path(a.html).resolve()}
    for key,path in paths.items():
        if path.parent!=folder or not path.name.startswith('研究总结_') or not path.is_file() or path.is_symlink() or path.stat().st_size==0:raise SystemExit('总结必须是公司目录内实际非空成品：'+str(path))
    if paths['markdown'].suffix!='.md' or paths['html'].suffix!='.html' or paths['markdown'].stem!=paths['html'].stem:raise SystemExit('HTML与Markdown必须同名，使用相应扩展名')
    registry=local.SYSTEM/'research_summary_registry.json';r=local.read(registry,{'reports':[]})
    item={'ticker':a.ticker,'generated_at':local.now(),'title':paths['markdown'].stem,'files':{k:{'path':local.relative(v),'sha256':local.digest(v)} for k,v in paths.items()},'sources':{s:{'sha256':local.digest(dd/s),'accepted_batch':local.read(dd/'_meta.json')['documents'][s]['accepted_batch']} for s in local.SLOTS}}
    existing=next((x for x in r['reports'] if x['files']['html']['path']==item['files']['html']['path']),None)
    if existing:
        if existing['files']==item['files'] and existing['sources']==item['sources']:print('已登记，无变化');raise SystemExit(0)
        raise SystemExit('此总结路径已经登记。请恢复原文件，并用新的时间后缀保存修订版，不能覆盖历史。')
    r['reports'].append(item);local.write(registry,r);local.log(a.ticker,'summary','登记从已接受档案生成的实际总结',summary=item['title'])
    print(json.dumps(item,ensure_ascii=False,indent=2))
