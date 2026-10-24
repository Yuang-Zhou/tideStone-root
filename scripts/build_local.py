#!/usr/bin/env python3
"""Build a local read-only view of actual project files; never generate research claims."""
from pathlib import Path
import csv, datetime, hashlib, html, json, os, re, shutil, sys as pysys
from urllib.parse import quote
ROOT = Path(__file__).resolve().parents[1]
PROJECTS = Path(os.environ.get('TIDESTONE_PROJECTS', ROOT / 'Projects')).resolve()
pysys.path.insert(0, str(ROOT/'Projects/_system/scripts'))
from dossier_orchestrator import approved_slot_errors, scan_company_entry
SLOTS = ['01_企业文化.md','02_财务分析.md','03_商业模式.md','04_战略决策.md','05_股性分析.md','06_财务预测.md','07_估值分析.md']

def load(path, default=None):
    if not path.exists(): return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8-sig'))

def stamp(): return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
def esc(value): return html.escape(str(value))
def inline(s):
    s = esc(s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    return re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" rel="noreferrer" target="_blank">\1</a>', s)

def markdown(text):
    result=[]; code=False; table=False; listing=False
    def close():
        nonlocal table,listing
        if table: result.append('</tbody></table></div>');table=False
        if listing: result.append('</ul>');listing=False
    for line in text.splitlines():
        if line.startswith('```'):
            close();result.append('</code></pre>' if code else '<pre><code>');code=not code;continue
        if code: result.append(esc(line)+'\n');continue
        if line.strip().startswith('|') and line.strip().endswith('|'):
            cells=[s.strip() for s in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-{2,}:?', s or ' ') for s in cells):continue
            if not table:close();result.append('<div class="table-wrap"><table><tbody>');table=True
            result.append('<tr>'+''.join('<td>'+inline(s)+'</td>' for s in cells)+'</tr>');continue
        if re.match(r'^[-*] ',line):
            if table:close()
            if not listing:result.append('<ul>');listing=True
            result.append('<li>'+inline(line[2:])+'</li>');continue
        close()
        m=re.match(r'^(#{1,6})\s+(.*)',line)
        if m: n=len(m[1]);result.append(f'<h{n}>{inline(m[2])}</h{n}>')
        elif line.strip()=='---':result.append('<hr>')
        elif line.strip().startswith('>'):result.append('<blockquote>'+inline(line.lstrip('> '))+'</blockquote>')
        elif line.strip():result.append('<p>'+inline(line)+'</p>')
    close()
    if code:result.append('</code></pre>')
    return '\n'.join(result)

def document(title, body, subtitle='研究记录'):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+' · 潮石</title><link rel="stylesheet" href="../style.css"><body><main class="reading"><a class="back" href="../index.html#reports">← 返回潮石</a><p class="eyebrow">'+esc(subtitle)+'</p><article>'+body+'</article></main></body></html>'

def build():
    sys=PROJECTS/'_system'; out=PROJECTS/'_site';out.mkdir(parents=True, exist_ok=True)
    (out/'documents').mkdir(exist_ok=True)
    for path in (ROOT/'web').iterdir():
        if path.is_file():shutil.copy2(path,out/path.name)
    if (ROOT/'assets').exists():shutil.copytree(ROOT/'assets',out/'assets',dirs_exist_ok=True)
    reports=[]
    def add_doc(path,title,kind,ticker='',batch=''):
        if not path.exists() or not path.read_text(encoding='utf-8').strip():return None
        rel=str(path.relative_to(PROJECTS)); filename=hashlib.sha256(rel.encode()).hexdigest()[:18]+'.html'
        (out/'documents'/filename).write_text(document(title,markdown(path.read_text(encoding='utf-8')),kind+' · '+ticker+' '+batch),encoding='utf-8')
        row={'title':title,'kind':kind,'ticker':ticker,'batch':batch,'url':'documents/'+filename,'path':rel,'updated':datetime.datetime.fromtimestamp(path.stat().st_mtime,datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')}
        reports.append(row);return row
    raw=load(sys/'companies.json'); companies=[]
    dr=load(sys/'dossier_registry.json').get('companies',{})
    if isinstance(dr,list):dr={c['ticker']:c for c in dr}
    vals=load(sys/'valuation_registry.json').get('companies',{})
    t3=load(sys/'three_year_valuation_registry.json').get('companies',{})
    summary_registry=load(sys/'research_summary_registry.json',{'reports':[]}).get('reports',[])
    for ticker,c in raw.get('companies',{}).items():
        folder=(PROJECTS/c['folder']).resolve()
        if not folder.is_relative_to(PROJECTS):raise ValueError('Company folder outside project')
        dossier=folder/'研究档案'; entry=scan_company_entry(ticker,c.get('name_cn',ticker),c.get('gics',{}).get('sector','unknown'),c['folder'])
        modules=[];pending=[]
        for slot in SLOTS:
            errors=approved_slot_errors(dossier,slot)
            doc=add_doc(dossier/slot,slot.removesuffix('.md'),'正式档案',ticker) if not errors else None
            modules.append({'slot':slot,'url':doc['url'] if doc else None,'updated':doc['updated'] if doc else None,'stale':entry.get('documents',{}).get(slot,{}).get('is_stale',False)})
        pending_root=dossier/'_pending'
        if pending_root.exists():
            for batch in sorted(pending_root.iterdir()):
                if not batch.is_dir() or batch.name.startswith('_'):continue
                bundle=load(batch/'_context_bundle.json');meta=load(batch/'_meta.json')
                if not bundle:continue
                docs=[]
                for path in sorted(batch.glob('*.md')):
                    doc=add_doc(path,path.stem,'待审草稿',ticker,batch.name)
                    if doc:docs.append(doc)
                pending.append({'timestamp':batch.name,'trigger':bundle.get('trigger'),'documents':docs,'validation':meta.get('documents',{})})
        for path in sorted(dossier.glob('_history/**/*.md')):add_doc(path,path.stem,'历史档案',ticker,path.parent.name)
        for path in sorted(dossier.glob('_pending/_rejected/**/*.md')):add_doc(path,path.stem,'已退回草稿',ticker,path.parent.name)
        for path in sorted(dossier.glob('_deviation/*.md')):add_doc(path,path.stem,'预测偏差',ticker)


        material_path=folder/'_materials.json'
        materials=load(material_path,[])
        # Count registered evidence only: raw originals, extracted text and their
        # registered copies are not separate material registrations.
        material_files=list(dict.fromkeys(m['file'] for m in materials.get('materials',[]) if m.get('file'))) if isinstance(materials,dict) else []
        events=load(folder/'_events.json').get('events',[])
        for path in sorted((folder/'events').glob('*.json')) if (folder/'events').exists() else []:events.append(load(path))
        for path in [folder/'events.json',dossier/'_events.json']:
            e=load(path,[])
            if isinstance(e,list):events.extend(e)
        def current_valuation(record):
            if not record:return {}
            slot='07_估值分析.md';metadata=load(dossier/'_meta.json').get('documents',{}).get(slot,{})
            errors=approved_slot_errors(dossier,slot)
            if not errors and record.get('source_sha256')==metadata.get('sha256') and record.get('accepted_batch')==metadata.get('accepted_batch'):
                return record
            return {'needs_recheck':True,'recheck_reason':['估值登记未对应当前已接受估值档案，须重新同步；暂不展示旧价。']}
        companies.append({'ticker':ticker,'currency':c.get('currency'),'name':c.get('name_cn',ticker),'sector':raw.get('gics_sector_names',{}).get(c.get('gics',{}).get('sector'),c.get('gics',{}).get('sector') or '待分类'),'status':entry.get('dossier_status','empty'),'modules':modules,'pending':pending,'material_count':len(material_files),'materials':material_files,'events':events,'valuation':current_valuation(vals.get(ticker,{})),'three_year':current_valuation(t3.get(ticker,{})),'note':c.get('note','')})
        for record in [r for r in summary_registry if r.get('ticker')==ticker]:
            artifacts=record.get('files',{});good=True
            for key in ['html','markdown']:
                f=PROJECTS/artifacts.get(key,{}).get('path','')
                if not f.is_file() or not f.resolve().is_relative_to(folder) or hashlib.sha256(f.read_bytes()).hexdigest()!=artifacts.get(key,{}).get('sha256'):good=False
            if not good:continue
            summary=PROJECTS/artifacts['html']['path']
            filename='summary-'+hashlib.sha256(str(summary.relative_to(PROJECTS)).encode()).hexdigest()[:18]+'.html'
            shutil.copy2(summary,out/'documents'/filename)
            reports.append({'title':summary.stem,'kind':'研究总结','ticker':ticker,'batch':'','url':'documents/'+filename,'path':str(summary.relative_to(PROJECTS)),'updated':record.get('generated_at'),'source_batches':record.get('sources',{})})
            add_doc(PROJECTS/artifacts['markdown']['path'],summary.stem+' · 文本','研究总结',ticker)
        formal=[(dossier/s) for s in SLOTS if not approved_slot_errors(dossier,s)]
        if formal:
            combined=''.join('<details open><summary>'+esc(p.stem)+'</summary>'+markdown(p.read_text(encoding='utf-8'))+'</details>' for p in formal)
            title=c.get('name_cn',ticker)+' · 已接受档案合订本'
            fname='dossier-'+hashlib.sha256(ticker.encode()).hexdigest()[:12]+'.html'
            (out/'documents'/fname).write_text(document(title,'<h1>'+esc(title)+'</h1><p>按原七模块顺序汇编。分析内容来自已接受档案；不是重新生成的研究结论。</p>'+combined,'正式档案合订本'),encoding='utf-8')
            companies[-1]['combined_url']='documents/'+fname
    briefings=[]
    for path in sorted((sys/'daily_briefing').glob('*_daily_briefing.md'),reverse=True):
        row=add_doc(path,path.stem,'每日简报')
        if row:briefings.append(row)
    paper_dir=sys/'paper_portfolio';paper={'config':load(paper_dir/'config.json'),'state':load(paper_dir/'state.json'),'summary':load(paper_dir/'summary_latest.json'),'nav':[],'ledger':[],'candidates':[]}
    for fname,key in [('nav_history.csv','nav'),('ledger.csv','ledger')]:
        if (paper_dir/fname).exists():
            with (paper_dir/fname).open(encoding='utf-8-sig') as f:paper[key]=list(csv.DictReader(f))[-100:]
    daily=sorted((paper_dir/'daily').glob('*.json')) if (paper_dir/'daily').exists() else []
    if daily:paper['latest']=load(daily[-1])
    prices={}
    for c in companies:
        p=sys/'market_data'/(c['ticker']+'.csv')
        if p.exists():
            with p.open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            if rows:prices[c['ticker']]=rows[-1]
    model={'built_at':stamp(),'isolated':PROJECTS != ROOT/'Projects','companies':companies,'reports':reports,'briefings':briefings,'paper':paper,'prices':prices,'market_status':load(sys/'market_data'/'_data_status.json'),'pipeline':load(sys/'local_pipeline_status.json'),'scheduler':load(ROOT/'config'/'scheduler_status.json'),'source_commit':load(ROOT/'reference'/'SOURCE_LOCK.json').get('commit')}
    tmp=out/'data.json.tmp';tmp.write_text(json.dumps(model,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(out/'data.json')
    print(json.dumps({'site':str(out),'companies':len(companies),'documents':len(reports),'built_at':model['built_at']},ensure_ascii=False))
    return out
if __name__=='__main__':
    from local_workflow import lock
    with lock():build()
