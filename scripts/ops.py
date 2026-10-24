#!/usr/bin/env python3
"""Local operations; data and logs stay under TideStone. No external publishing."""
from pathlib import Path
import argparse, contextlib, datetime, fcntl, hashlib, importlib.util, json, os, plistlib, shutil, signal, subprocess, sys, tarfile, time, urllib.request, uuid
ROOT=Path(__file__).resolve().parents[1]
PROJECTS=Path(os.environ.get('TIDESTONE_PROJECTS',ROOT/'Projects')).resolve()
SYS=PROJECTS/'_system'
RUNS=ROOT/'runs';RUNS.mkdir(exist_ok=True)
RUNTIME=PROJECTS/'_runtime';RUNTIME.mkdir(parents=True,exist_ok=True)
PYTHON=str(ROOT/'.venv/bin/python') if (ROOT/'.venv/bin/python').exists() else sys.executable
LABEL='local.tidestone.daily'
def now():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
def load(p,default=None):return json.loads(p.read_text()) if p.exists() else ({} if default is None else default)
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2));t.replace(p)
@contextlib.contextmanager
def operation_lock():
    SYS.mkdir(parents=True,exist_ok=True)
    with (SYS/'.operations.lock').open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)
def build():
    subprocess.run([PYTHON,str(ROOT/'scripts/build_local.py')],check=True,cwd=ROOT)
def health(port):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f'http://127.0.0.1:{port}/__health',timeout=1) as f:return json.load(f)
    except Exception:return {}
def start(port):
    state=load(RUNTIME/'server.json');h=health(port)
    if h.get('service')=='tidestone-local':
        if h.get('directory')!=str(PROJECTS/'_site'):raise SystemExit('该端口属于另一潮石资料库，请选择其他端口。')
        print(f'http://127.0.0.1:{port}');return
    build();token=uuid.uuid4().hex
    with (RUNTIME/'server.log').open('ab') as log:
        proc=subprocess.Popen([PYTHON,str(ROOT/'scripts/local_server.py'),'--directory',str(PROJECTS/'_site'),'--port',str(port),'--token',token],stdout=log,stderr=log,start_new_session=True,cwd=ROOT)
    for _ in range(30):
        if health(port).get('token')==token:break
        if proc.poll() is not None:raise SystemExit('启动失败，请查看 '+str(RUNTIME/'server.log'))
        time.sleep(.1)
    else:raise SystemExit('本地服务器未就绪')
    save(RUNTIME/'server.json',{'pid':proc.pid,'port':port,'token':token,'started_at':now()});print(f'http://127.0.0.1:{port}')
def stop():
    state=load(RUNTIME/'server.json')
    if not state:print('本资料库没有正在运行的页面服务');return
    h=health(state['port'])
    if h.get('token')!=state['token']:raise SystemExit('服务身份不匹配，未停止任何进程')
    os.kill(state['pid'],signal.SIGTERM);(RUNTIME/'server.json').unlink();print('已停止本资料库页面服务')
def daily(offline=False):
    with operation_lock():return daily_locked(offline)
def daily_locked(offline=False):
    status={'started_at':now(),'status':'running','mode':'offline' if offline else 'online','steps':[]};save(SYS/'local_pipeline_status.json',status)
    run_id=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
    run_dir=RUNS/run_id;run_dir.mkdir()
    def step(name,script,args=(),skip=None):
        if skip:r={'name':name,'status':'skipped','detail':skip}
        else:
            cmd=[PYTHON,str(ROOT/'Projects/_system'/script),*args]
            try:
                pr=subprocess.run(cmd,cwd=PROJECTS,capture_output=True,text=True,timeout=600,env={**os.environ,'TIDESTONE_PROJECTS':str(PROJECTS),'TZ':'Asia/Shanghai'})
                output=pr.stdout+'\n'+pr.stderr;(run_dir/(str(len(status['steps']))+'.log')).write_text(output)
                r={'name':name,'status':'passed' if pr.returncode==0 else 'failed','returncode':pr.returncode,'detail':output[-800:] if pr.returncode else '完成，详细记录已保存'}
            except (OSError,subprocess.TimeoutExpired) as e:r={'name':name,'status':'failed','detail':str(e)}
        status['steps'].append(r);save(SYS/'local_pipeline_status.json',status);return r['status']=='passed'
    cs=load(SYS/'companies.json').get('companies',{})
    no='公司库为空，无需执行' if not cs else None
    fetched=step('行情获取','scripts/market_data_fetcher.py',skip=no or ('离线运行，仅检查现有文件' if offline else None))
    step('技术信号','host_pipeline/host_signals.py',skip=no or ('行情清单缺失' if not (SYS/'market_data/_data_status.json').exists() else None))
    step('模拟盘记账','scripts/paper_portfolio.py',['--root',str(PROJECTS)],skip=no or ('尚未初始化模拟盘' if not (SYS/'paper_portfolio/config.json').exists() else None))
    valid=step('行情时效校验','scripts/validate_market_data.py',['--strict'],skip=no)
    step('档案状态扫描','scripts/dossier_orchestrator.py',['rescan'])
    step('三年目标覆盖检查','scripts/validate_three_year_coverage.py',skip=no)
    step('历史成果归档','scripts/archive_old.py',['--apply'])
    status['steps'].append({'name':'AI 每日研究扫描','status':'not_run','detail':'在 Codex 调用 daily-portfolio-scanner；宿主任务不生成新闻判断或自动批准研究。'})
    status['finished_at']=now();status['status']='partial' if any(x['status']=='failed' for x in status['steps']) else ('empty_library' if not cs else 'completed_local_steps')
    status['run_dir']=str(run_dir.relative_to(ROOT));save(SYS/'local_pipeline_status.json',status);save(run_dir/'status.json',status);build();print(json.dumps(status,ensure_ascii=False,indent=2))
    return 1 if status['status']=='partial' else 0

def backup():
    sys.path.insert(0,str(ROOT/'Projects/_system/scripts'))
    from local_workflow import lock
    with operation_lock():
        with lock():return backup_locked()

def backup_locked():
    dest=ROOT/'backups';dest.mkdir(exist_ok=True)
    name='tidestone-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.tar.gz';archive=dest/name
    paths=['Projects','scripts','web','assets','config','docs','reference','.agents','tests','runs','AGENTS.md','README.md','CONTRIBUTING.md','.github','.gitattributes','启动潮石.command','停止潮石.command','备份潮石.command','.gitignore']
    hashes={}
    with tarfile.open(archive,'w:gz') as tar:
        for rel in paths:
            p=PROJECTS if rel=='Projects' else ROOT/rel
            if not p.exists():continue
            files=[p] if p.is_file() else sorted(p.rglob('*'))
            for f in files:
                if not f.is_file() or f.is_symlink():continue
                r=Path(rel)/f.relative_to(p) if p.is_dir() else Path(rel)
                if any(x in r.parts for x in ['__pycache__','_site','_runtime','.venv']):continue
                if r.parts[0]=='runs' and not (r.parts[1][:8].isdigit() or r.parts[1].startswith('scheduled.')):continue
                content=f.read_bytes()
                hashes[str(r)]=hashlib.sha256(content).hexdigest()
                import io
                info=tarfile.TarInfo(str(r));info.size=len(content);info.mode=f.stat().st_mode & 0o777
                tar.addfile(info,io.BytesIO(content))
    manifest={'created_at':now(),'data_root':str(PROJECTS),'archive':name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':hashes};save(archive.with_suffix('.manifest.json'),manifest);print(str(archive));return archive

def restore(archive,destination):
    archive=Path(archive).resolve();target=Path(destination).resolve()
    if not target.is_relative_to(ROOT):raise SystemExit('恢复目标必须在本项目目录内')
    if target.exists() and any(target.iterdir()):raise SystemExit('恢复目标必须为空；先恢复到独立目录核对，不覆盖现有资料')
    manifest=load(archive.with_suffix('.manifest.json'))
    if manifest.get('sha256')!=hashlib.sha256(archive.read_bytes()).hexdigest():raise SystemExit('备份校验失败')
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        for m in members:
            if not m.isfile() or not (target/m.name).resolve().is_relative_to(target):raise SystemExit('备份含不安全路径')
            content=tar.extractfile(m).read()
            if hashlib.sha256(content).hexdigest()!=manifest.get('files',{}).get(m.name):raise SystemExit('文件校验失败 '+m.name)
        target.mkdir(parents=True,exist_ok=True)
        for m in members:
            p=target/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(tar.extractfile(m).read());p.chmod(m.mode & 0o777)
    print('已校验并恢复到 '+str(target))

def schedule(action):
    cfg=ROOT/'config';path=cfg/(LABEL+'.plist');domain='gui/'+str(os.getuid());service=domain+'/'+LABEL
    registration=Path.home()/'Library/LaunchAgents'/(LABEL+'.plist')
    if action=='prepare':
        plist={'Label':LABEL,'ProgramArguments':[PYTHON,str(ROOT/'scripts/ops.py'),'daily'],'WorkingDirectory':str(ROOT),'EnvironmentVariables':{'TZ':'Asia/Shanghai','TIDESTONE_PROJECTS':str(ROOT/'Projects')},'StartCalendarInterval':{'Hour':8,'Minute':30},'RunAtLoad':True,'StandardOutPath':str(RUNS/'scheduled.stdout.log'),'StandardErrorPath':str(RUNS/'scheduled.stderr.log')}
        path.write_bytes(plistlib.dumps(plist));save(cfg/'scheduler_status.json',{'status':'仅已生成配置，未安装','schedule':'每天本机时间 08:30','prepared_at':now(),'plist':str(path)});print(path);return
    if action=='install':
        if not path.exists():schedule('prepare')
        if registration.is_symlink() and registration.resolve()!=path.resolve():raise SystemExit('已有同名系统登记，未覆盖')
        if registration.exists() and not registration.is_symlink():raise SystemExit('已有同名系统文件，未覆盖')
        registration.parent.mkdir(parents=True,exist_ok=True)
        if not registration.is_symlink():registration.symlink_to(path)
        present=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
        if present.returncode:
            pr=subprocess.run(['launchctl','bootstrap',domain,str(path)],capture_output=True,text=True)
            if pr.returncode:raise SystemExit(pr.stderr or pr.stdout)
        save(cfg/'scheduler_status.json',{'status':'已加载，等待核验运行','installed_at':now(),'schedule':'每天本机时间 08:30','service':service,'login_registration':str(registration),'config_in_project':str(path)});print('已加载并登记登录恢复；需用 schedule status 核对进程及 runs/scheduled.* 日志');return
    if action=='remove':
        pr=subprocess.run(['launchctl','bootout',service],capture_output=True,text=True)
        if pr.returncode:raise SystemExit(pr.stderr or pr.stdout)
        if registration.is_symlink() and registration.resolve()==path.resolve():registration.unlink()
        save(cfg/'scheduler_status.json',{'status':'已停止定时执行','removed_at':now()});print('已卸载该本地定时任务');return
    pr=subprocess.run(['launchctl','print',service],capture_output=True,text=True)
    print(pr.stdout or pr.stderr)
    state=load(cfg/'scheduler_status.json');state['checked_at']=now();state['loaded']=pr.returncode==0
    if pr.returncode==0 and 'last exit code = 0' in pr.stdout:state['status']='已加载；最近一次宿主任务退出成功（详见运行日志）'
    save(cfg/'scheduler_status.json',state)

def main():
    p=argparse.ArgumentParser(description='潮石本地运行工具');sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('build');x=sub.add_parser('start');x.add_argument('--port',type=int,default=8791);sub.add_parser('stop');sub.add_parser('status')
    x=sub.add_parser('daily');x.add_argument('--offline',action='store_true');sub.add_parser('backup')
    x=sub.add_parser('restore');x.add_argument('archive');x.add_argument('--to',required=True)
    x=sub.add_parser('schedule');x.add_argument('action',choices=['prepare','install','status','remove'])
    a=p.parse_args()
    if a.cmd=='build':build()
    elif a.cmd=='start':start(a.port)
    elif a.cmd=='stop':stop()
    elif a.cmd=='status':print(json.dumps({'server':load(RUNTIME/'server.json'),'pipeline':load(SYS/'local_pipeline_status.json'),'scheduler':load(ROOT/'config/scheduler_status.json')},ensure_ascii=False,indent=2))
    elif a.cmd=='daily':return daily(a.offline)
    elif a.cmd=='backup':backup()
    elif a.cmd=='restore':restore(a.archive,a.to)
    elif a.cmd=='schedule':schedule(a.action)
if __name__=='__main__':sys.exit(main() or 0)
