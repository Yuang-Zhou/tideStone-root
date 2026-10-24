"""Codex local lifecycle adapter. Research content is authored by Skills, never synthesized here."""
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
import fcntl
from tidestone_paths import PROJECTS_ROOT as ROOT, SYSTEM_DIR as SYSTEM

SLOTS = ['01_企业文化.md','02_财务分析.md','03_商业模式.md','04_战略决策.md','05_股性分析.md','06_财务预测.md','07_估值分析.md']
SECTORS = {'10':'能源','15':'原材料','20':'工业','25':'可选消费','30':'日常消费','35':'医疗保健','40':'金融','45':'信息技术','50':'通信服务','55':'公用事业','60':'房地产','unknown':'待分类'}


def now():
    return datetime.now(timezone.utc).isoformat()


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S-%fZ')


def read(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8'))


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return str(path.resolve().relative_to(ROOT))


def checked_ticker(ticker):
    ticker = ticker.upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.^-]{0,24}', ticker):
        raise ValueError('公司代码只能含字母、数字、点、连字符或 ^，不能包含路径')
    return ticker


def checked_batch(ts):
    if not re.fullmatch(r'[0-9TZ.\-]+', ts):
        raise ValueError('无效批次编号')
    return ts


def normalize_slots(slots):
    if not slots:
        return SLOTS.copy()
    out=[]
    for s in slots:
        match = next((x for x in SLOTS if x == s or x[:2] == s.zfill(2)), None)
        if not match:
            raise ValueError('未知模块：' + s)
        if match not in out:
            out.append(match)
    return out


def company_dir(ticker):
    ticker=checked_ticker(ticker)
    info=read(SYSTEM/'companies.json').get('companies',{}).get(ticker)
    if info is None:
        raise ValueError('公司尚未入库：'+ticker)
    folder=(ROOT/info['folder']).resolve()
    folder.relative_to(ROOT/'companies')
    return folder


@contextmanager
def lock():
    SYSTEM.mkdir(parents=True, exist_ok=True)
    with (SYSTEM/'.workflow.lock').open('a+') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield


def log(ticker, action, reason='', batch=None, **details):
    path=company_dir(ticker)/'_workflow.json'
    w=read(path, {'state':'registered','history':[]})
    w['updated_at']=now()
    w['history'].append({'action':action,'at':w['updated_at'],'batch':batch,'reason':reason,**details})
    if batch:
        w['last_batch']=batch
    if action=='accept':
        w['state']='accepted';w['last_accepted_batch']=batch
    elif action in ('prepare','revise','finalize'):
        w['state']={'prepare':'drafting','revise':'revising','finalize':'pending_review'}[action]
    elif action=='reject':
        w['state']='returned'
    elif action=='event':
        w['state']='update_required'
    write(path,w)


def init():
    SYSTEM.mkdir(parents=True, exist_ok=True)
    for d in ['companies','基本面分析汇总']:
        (ROOT/d).mkdir(exist_ok=True)
    for d in ['market_data','daily_briefing','positions','position_advice','scan_log','paper_portfolio']:
        (SYSTEM/d).mkdir(exist_ok=True)
    defaults={
      'companies.json':{'schema_version':'1.0','gics_sector_names':SECTORS,'gics_sub_industry_names':{},'vocab':{'confidence':['low','medium','high']},'companies':{}},
      'dossier_registry.json':{'schema_version':'1.0','last_updated':None,'companies':[]},
      'valuation_registry.json':{'schema_version':'1.0','last_updated':None,'companies':{}},
      'three_year_valuation_registry.json':{'schema_version':'2.0','companies':{}},
      'three_year_coverage_waivers.json':{'WAIVERS':{}},
      'position_triggers.json':{'schema_version':'1.0','triggers':[],'acknowledged_deviations':[]},
      'pending_valuation_sync.json':{'pending':[]},
      'research_summary_registry.json':{'reports':[]},
    }
    for name,data in defaults.items():
        if not (SYSTEM/name).exists():
            write(SYSTEM/name,data)
    if not (SYSTEM/'portfolio_registry.md').exists():
        atomic_text(SYSTEM/'portfolio_registry.md','# 潮石公司注册表\n\n当前无公司。由本地入库和估值同步维护。\n')
    return {'projects_root':str(ROOT),'companies':len(read(SYSTEM/'companies.json')['companies'])}


def add(ticker, name, market, sector='unknown', currency=None):
    ticker=checked_ticker(ticker)
    if market not in ('US','HK','CN','OTHER'):
        raise ValueError('market 必须为 US/HK/CN/OTHER')
    if sector not in SECTORS:
        raise ValueError('sector 须使用 GICS 一级代码，未知时用 unknown')
    if currency is None:
        currency={'US':'USD','HK':'HKD','CN':'CNY'}.get(market)
    if currency is None:
        raise ValueError('OTHER 市场需用 --currency 明确输入报价币种，例如 EUR')
    if not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('currency 必须为三位大写币种代码，例如 USD/HKD/CNY/EUR')
    cp=SYSTEM/'companies.json';data=read(cp)
    if ticker in data['companies']:
        raise ValueError('公司已存在，不覆盖：'+ticker)
    folder=ROOT/'companies'/ticker
    if folder.exists():
        raise ValueError('目标目录已存在，需先核实，未覆盖：'+str(folder))
    folder.mkdir(parents=True)
    (folder/'研究档案').mkdir()
    (folder/'materials').mkdir()
    entry={'ticker':ticker,'name_cn':name,'name_en':'','market':market,'currency':currency,'folder':relative(folder),'gics':{'sector':sector,'confidence':'low'},'created_at':now()}
    data['companies'][ticker]=entry;write(cp,data)
    write(folder/'_materials.json',{'materials':[]})
    write(folder/'_events.json',{'events':[]})
    write(folder/'_workflow.json',{'state':'registered','updated_at':now(),'history':[]})
    # Identity placeholders carry no rating, price, scenario or position conclusion.
    vp=SYSTEM/'valuation_registry.json';v=read(vp)
    v['companies'][ticker]={'name':name,'sector':SECTORS[sector],'currency':entry['currency'],'rating':'待研究','target_price':'待研究','zones':[],'status':'active'}
    write(vp,v)
    p=SYSTEM/'portfolio_registry.md'
    text=p.read_text(encoding='utf-8').replace('当前无公司。由本地入库和估值同步维护。','由本地入库和估值同步维护。')
    text+=f'\n### {ticker} — {name}\n- **Folder:** `{entry["folder"]}`\n- **Rating:** 待研究\n- **Status:** active\n- **Currency:** {entry["currency"]}\n- **Valuation:**\n  - 情景目标价: 待研究\n\n'
    atomic_text(p,text)
    log(ticker,'add','首次入库，尚无研究结论')
    return entry


def track(ticker, tracking_status, reason):
    """Persist the source registry's active/paused research tracking switch."""
    if tracking_status not in ('active','paused'):
        raise ValueError('跟踪状态必须为 active 或 paused')
    if not reason.strip():
        raise ValueError('变更跟踪状态必须记录用户要求与理由')
    company_dir(ticker)
    vp=SYSTEM/'valuation_registry.json';doc=read(vp)
    entry=doc['companies'].get(ticker)
    if entry is None:raise ValueError('估值注册表缺公司身份条目')
    import sync_valuations
    mp=SYSTEM/'portfolio_registry.md';old_json=vp.read_text(encoding='utf-8');old_md=mp.read_text(encoding='utf-8')
    old_status=entry.get('status')
    entry['status']=tracking_status;entry['tracking_updated_at']=now();entry['tracking_reason']=reason
    try:
        write(vp,doc)
        sync_valuations.cmd_apply([ticker])
        sync_valuations.cmd_check()
    except BaseException:
        atomic_text(vp,old_json);atomic_text(mp,old_md)
        raise
    log(ticker,'track',reason,previous_status=old_status,tracking_status=tracking_status)
    return {'ticker':ticker,'tracking_status':tracking_status,'daily_research_tracking':tracking_status=='active',
            'note':'跟踪状态控制日常扫描池；模拟盘仍须通过资料、行情和策略条件，不代表实际买入'}


def material(ticker, file, source, kind, period=''):
    folder=company_dir(ticker);src=Path(file).expanduser().resolve()
    if not source.strip():
        raise ValueError('资料必须登记来源（URL 或用户提供说明）')
    if not src.is_file() or src.stat().st_size==0:
        raise ValueError('资料不存在或为空：'+str(src))
    h=digest(src);p=folder/'_materials.json';m=read(p,{'materials':[]})
    same=next((x for x in m['materials'] if x['sha256']==h and x['source']==source),None)
    if same:return same
    ident=stamp();dest=folder/'materials'/(ident+'_'+src.name)
    shutil.copy2(src,dest)
    entry={'id':ident,'file':relative(dest),'sha256':h,'source':source,'kind':kind,'period':period,'added_at':now()}
    m['materials'].append(entry);write(p,m)
    log(ticker,'material','登记研究依据',material_id=ident)
    return entry


def event(ticker,title,source,detail='',slots=None):
    folder=company_dir(ticker);p=folder/'_events.json';events=read(p,{'events':[]})
    if not title.strip() or not source.strip():
        raise ValueError('事件需要标题和来源')
    entry={'id':stamp(),'title':title,'source':source,'detail':detail,'affected_slots':normalize_slots(slots),'status':'open','created_at':now(),'resolved_by_batch':None}
    events['events'].append(entry);write(p,events)
    log(ticker,'event',title,event_id=entry['id'])
    return entry


def snapshot_batch(batch, reason):
    revision=stamp();dest=batch/'_revisions'/revision;dest.mkdir(parents=True)
    for p in batch.iterdir():
        if p.is_file():shutil.copy2(p,dest/p.name)
    write(dest/'_revision.json',{'at':now(),'reason':reason})
    return revision


def revise(ticker,ts,reason):
    if not reason.strip():raise ValueError('修订必须记录依据')
    batch=company_dir(ticker)/'研究档案'/'_pending'/checked_batch(ts)
    if not batch.exists():raise ValueError('待审批次不存在')
    revision=snapshot_batch(batch,reason)
    if (batch/'_meta.json').exists():
        meta=read(batch/'_meta.json');meta['batch_status']='revising';write(batch/'_meta.json',meta)
    log(ticker,'revise',reason,ts,revision=revision)
    return {'batch':ts,'revision':revision,'next':'修改此批次模块后重新 finalize；需要明确接受才能晋升正式档案。'}


def recover(ticker):
    """Rollback a promotion interrupted before its durable commit marker."""
    dd=company_dir(ticker)/'研究档案'
    for path in (dd/'_history').glob('*/_transaction.json'):
        txn=read(path)
        if txn.get('status')!='applying':continue
        before=path.parent/'_before'
        for name in txn['targets']:
            target=dd/name
            if (before/name).exists():
                atomic_text(target,(before/name).read_text(encoding='utf-8'))
            elif target.exists():target.unlink()
        txn['status']='rolled_back';txn['recovered_at']=now();write(path,txn)
        log(ticker,'recover','上次正式保存未完成，已恢复保存前版本',txn['batch'])


def prepare(engine,ticker,slots,trigger='manual'):
    recover(ticker)
    slots=normalize_slots(slots)
    engine.rescan_one(ticker)
    reg=engine.load_registry();c=engine.find_company(reg,ticker);dd=engine.dossier_dir(c)
    ts=stamp();pending=dd/'_pending'/ts;pending.mkdir(parents=True)
    folder=company_dir(ticker)
    events=[x for x in read(folder/'_events.json',{'events':[]})['events'] if x['status']=='open']
    bundle={'ticker':ticker,'company_name':c['company_name'],'sector':c['sector'],'timestamp':ts,'trigger':trigger,'dossier_dir':relative(dd),'pending_dir':relative(pending),'materials':read(folder/'_materials.json',{'materials':[]})['materials'],'event_ids':[x['id'] for x in events],'events':events,'slots':[], 'baseline_sha256':{s:digest(dd/s) if (dd/s).exists() else None for s in SLOTS}}
    # Same-batch dependencies take precedence over accepted but older source files.
    for s in slots:
        deps=engine.SLOT_DEPENDENCIES[s]
        paths=[('PENDING_IN_BATCH: '+relative(pending/d)) if d in slots else relative(dd/d) if c['documents'].get(d,{}).get('exists') else 'MISSING: '+d for d in deps]
        bundle['slots'].append({'slot':s,'sub_skills':engine.SLOT_TO_SUB_SKILLS[s],'dependencies':deps,'dependency_paths':paths,'output_path':relative(pending/s),'status':'pending'})
    write(pending/'_context_bundle.json',bundle)
    log(ticker,'prepare',trigger,ts)
    engine.rescan_one(ticker)
    return bundle


def validate_batch(engine,ticker,batch,bundle):
    from handoff_lint import lint_file
    errors={}; warnings={}
    mats=bundle.get('materials',[])
    material_errors=[]
    current_mats=read(company_dir(ticker)/'_materials.json',{'materials':[]})['materials']
    if current_mats != mats:
        material_errors.append('准备批次后材料清单发生变化，请重新 prepare 以纳入新依据')
    if not mats:material_errors.append('尚未登记任何研究材料')
    for m in mats:
        f=ROOT/m['file']
        if not f.is_file() or digest(f)!=m['sha256']:
            material_errors.append('登记材料缺失或哈希变化：'+m['file'])
    requested=[x['slot'] for x in bundle['slots']]
    dd=batch.parent.parent
    for info in bundle['slots']:
        s=info['slot'];p=batch/s;errs=material_errors.copy();warns=[]
        if not p.is_file():errs.append('研究模块尚未生成')
        else:
            try:
                text=p.read_text(encoding='utf-8')
                if len(text.strip())<80:errs.append('模块为空或仅有占位内容（正文不足 80 字符）')
                if '\x00' in text:errs.append('模块含 NUL 字符，疑似文件损坏')
                le,lw=lint_file(p,s);errs.extend(le);warns.extend(lw)
            except UnicodeError:errs.append('模块必须为 UTF-8 Markdown')
        for dep in info['dependencies']:
            if dep in requested:
                target=batch/dep
                if not target.is_file() or not target.read_text(encoding='utf-8').strip():
                    errs.append('缺少同批上游模块：'+dep)
            else:
                upstream_errors=engine.approved_slot_errors(dd,dep)
                if upstream_errors:
                    errs.append('上游不是完整已接受模块：'+dep+'；'+'；'.join(upstream_errors))
        errors[s]=errs;warnings[s]=warns
    return errors,warnings


def finalize(engine,ticker,ts):
    recover(ticker)
    dd=company_dir(ticker)/'研究档案';batch=dd/'_pending'/checked_batch(ts)
    bundle=read(batch/'_context_bundle.json')
    if not bundle:raise ValueError('待审批次缺少 context bundle')
    if (batch/'_meta.json').exists():snapshot_batch(batch,'再次 finalize 前保留上次校验版本')
    errs,warns=validate_batch(engine,ticker,batch,bundle)
    docs={};diff=[f'# {ticker} 待审变更 — {ts}\n',f'触发依据：{bundle["trigger"]}\n']
    import difflib
    for info in bundle['slots']:
        s=info['slot'];p=batch/s
        docs[s]={'last_updated':now(),'trigger':bundle['trigger'],'approval_status':'failed' if errs[s] else 'pending','error_messages':errs[s],'warnings':warns[s],'sha256':digest(p) if p.exists() else None,'sub_skills_used':info['sub_skills']}
        diff.extend([f'## {s}\n', '\n'.join('错误：'+x for x in errs[s]), '\n'.join('提示：'+x for x in warns[s])])
        old=(dd/s).read_text(encoding='utf-8').splitlines() if (dd/s).exists() else []
        new=p.read_text(encoding='utf-8').splitlines() if p.exists() else []
        diff.extend(['```diff','\n'.join(difflib.unified_diff(old,new,fromfile='当前正式版',tofile='本批草稿',lineterm='')),'```'])
    ready=not any(errs.values())
    meta={'schema_version':'1.1','ticker':ticker,'batch_timestamp':ts,'trigger':bundle['trigger'],'finalized_at':now(),'batch_status':'ready_for_review' if ready else 'failed','documents':docs,'materials_sha256':digest(company_dir(ticker)/'_materials.json')}
    write(batch/'_meta.json',meta);atomic_text(batch/'_diff_summary.md','\n\n'.join(diff)+'\n')
    log(ticker,'finalize', '校验通过，等待审阅' if ready else '校验失败，尚不可接受', ts)
    if not ready:
        wp=company_dir(ticker)/'_workflow.json';w=read(wp);w['state']='validation_failed';write(wp,w)
    engine.rescan_one(ticker)
    return meta


def accept(engine,ticker,ts=None,reason='用户明确接受'):
    if not reason.strip():raise ValueError('接受必须记录用户审阅依据')
    recover(ticker)
    dd=company_dir(ticker)/'研究档案';pending=dd/'_pending'
    batches=sorted(p.name for p in pending.iterdir() if p.is_dir() and not p.name.startswith('_')) if pending.exists() else []
    if ts is None:
        if len(batches)!=1:raise ValueError('请明确要接受的批次编号，避免接受错误版本')
        ts=batches[0]
    batch=pending/checked_batch(ts);meta=read(batch/'_meta.json');bundle=read(batch/'_context_bundle.json')
    if meta.get('batch_status')!='ready_for_review':raise ValueError('批次未通过 finalize，不能接受')
    errs,_=validate_batch(engine,ticker,batch,bundle)
    if any(errs.values()):raise ValueError('批次再次校验失败：'+json.dumps(errs,ensure_ascii=False))
    if digest(company_dir(ticker)/'_materials.json')!=meta.get('materials_sha256'):
        raise ValueError('材料清单在 finalize 后变化，请重新 prepare/finalize，确保草稿使用最新依据')
    docs=meta['documents']
    for s,m in docs.items():
        if m.get('approval_status')!='pending' or digest(batch/s)!=m.get('sha256'):
            raise ValueError('草稿在 finalize 后被修改，须重新 finalize：'+s)
    for s,h in bundle['baseline_sha256'].items():
        current=digest(dd/s) if (dd/s).exists() else None
        if current!=h:raise ValueError('正式档案在准备此批次后已改变，请重建草稿以避免覆盖新版本：'+s)
    current=read(dd/'_meta.json',{'documents':{}})
    has_formal=any(not engine.approved_slot_errors(dd,s) for s in SLOTS)
    if not has_formal and set(docs)!=set(SLOTS):
        raise ValueError('首次正式建档必须七模块齐全；当前可保存草稿但不能冒充完整档案')
    hist=dd/'_history'/stamp();before=hist/'_before';before.mkdir(parents=True)
    targets=list(docs)+['_meta.json']
    for name in targets:
        if (dd/name).exists():shutil.copy2(dd/name,before/name)
    shutil.copytree(batch,hist/'_accepted_batch')
    txn={'batch':ts,'status':'applying','targets':targets,'reason':reason,'at':now()};write(hist/'_transaction.json',txn)
    try:
        merged=dict(current.get('documents',{}))
        for s,m in docs.items():
            atomic_text(dd/s,(batch/s).read_text(encoding='utf-8'))
            merged[s]={**m,'approval_status':'approved','approved_at':now(),'accepted_batch':ts}
        write(dd/'_meta.json',{'schema_version':'1.1','ticker':ticker,'company_name':bundle['company_name'],'sector':bundle['sector'],'documents':merged})
        txn['status']='committed';txn['committed_at']=now();write(hist/'_transaction.json',txn)
    except Exception:
        recover(ticker)
        raise
    # Keep the complete accepted draft and review trail; removal from pending is a move.
    accepted=pending/'_accepted';accepted.mkdir(exist_ok=True)
    shutil.move(str(batch),str(accepted/ts))
    log(ticker,'accept',reason,ts,history_path=relative(hist))
    ep=company_dir(ticker)/'_events.json';events=read(ep,{'events':[]})
    for event in events['events']:
        if event['id'] in bundle.get('event_ids',[]) and set(event['affected_slots'])<=set(docs):
            event['status']='resolved';event['resolved_by_batch']=ts
    write(ep,events)
    engine.rescan_one(ticker)
    fresh=engine.find_company(engine.load_registry(),ticker)
    engine._handle_accept_automation(ticker,docs,fresh)
    if '07_估值分析.md' in docs:engine._warn_missing_three_year_target(ticker)
    return {'ticker':ticker,'accepted_batch':ts,'accepted_slots':list(docs),'history':relative(hist)}


def reject(engine,ticker,ts=None,reason='用户退回，待修订'):
    if not reason.strip():raise ValueError('退回必须记录原因')
    dd=company_dir(ticker)/'研究档案';pending=dd/'_pending'
    if ts is None:
        batches=sorted(p.name for p in pending.iterdir() if p.is_dir() and not p.name.startswith('_'))
        if len(batches)!=1:raise ValueError('请明确要退回的批次编号')
        ts=batches[0]
    batch=pending/checked_batch(ts)
    if not batch.is_dir():raise ValueError('待审批次不存在')
    write(batch/'_review_decision.json',{'decision':'rejected','reason':reason,'at':now()})
    dest=pending/'_rejected'/ts;dest.parent.mkdir(exist_ok=True)
    shutil.move(str(batch),str(dest));log(ticker,'reject',reason,ts)
    engine.rescan_one(ticker)
    return {'ticker':ticker,'rejected_batch':ts,'archive':relative(dest)}


def status(engine,ticker=None):
    entries=read(SYSTEM/'companies.json')['companies']
    for t in entries:
        if ticker is None or ticker==t:recover(t)
    engine.rescan_all()
    rows=engine.load_registry()['companies']
    result=[]
    for c in rows:
        if ticker and c['ticker']!=ticker:continue
        folder=company_dir(c['ticker'])
        c['materials']=read(folder/'_materials.json',{'materials':[]})['materials']
        c['events']=read(folder/'_events.json',{'events':[]})['events']
        c['workflow']=read(folder/'_workflow.json')
        c['tracking_status']=read(SYSTEM/'valuation_registry.json').get('companies',{}).get(c['ticker'],{}).get('status')
        c['daily_research_tracking']=c['tracking_status']=='active'
        c['missing_modules']=[s for s in SLOTS if not c['documents'].get(s,{}).get('exists')]
        c['pending_valuation_sync']=any(x['ticker']==c['ticker'] for x in read(SYSTEM/'pending_valuation_sync.json',{'pending':[]})['pending'])
        result.append(c)
    if ticker and not result:raise ValueError('公司尚未入库：'+ticker)
    return {'projects_root':str(ROOT),'companies':result}
