"""CATL onboarding: fetch public originals; preserve source/date/hash and PDF checks.
Local intake adapter only; no investment conclusions or accepted dossier writes.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib, json, subprocess
from pypdf import PdfReader

COMPANY = Path(__file__).resolve().parents[1]
RAW = COMPANY / '300750.SZ Wiki/raw'
SOURCES = [
    ('annual_2025', '宁德时代2025年年度报告', '年报', '2025', '2026-03-10', 'https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF'),
    ('annual_2024', '宁德时代2024年年度报告', '年报', '2024', '2025-03-15', 'https://static.cninfo.com.cn/finalpage/2025-03-15/1222806982.PDF'),
    ('annual_2023', '宁德时代2023年年度报告', '年报', '2023', '2024-03-16', 'https://static.cninfo.com.cn/finalpage/2024-03-16/1219313047.PDF'),
    ('interim_2026', '宁德时代2026年半年度报告', '半年报', '2026H1', '2026-07-25', 'https://static.cninfo.com.cn/finalpage/2026-07-25/1225441586.PDF'),
    ('interim_2025', '宁德时代2025年半年度报告', '半年报', '2025H1', '2025-07-31', 'https://static.cninfo.com.cn/finalpage/2025-07-31/1224342874.PDF'),
    ('q1_2026', '宁德时代2026年第一季度报告', '季报', '2026Q1', '2026-04-16', 'https://static.cninfo.com.cn/finalpage/2026-04-16/1225107946.PDF'),
    ('q3_2026', '宁德时代2026年第三季度报告', '季报', '2026Q3', '2026-10-21', 'https://static.cninfo.com.cn/finalpage/2026-10-21/1225613175.PDF'),
    ('ir_20260309', '2026年3月9日投资者关系活动记录表', '业绩交流', 'FY2025', '2026-03-10', 'https://static.cninfo.com.cn/finalpage/2026-03-10/1225002708.PDF'),
    ('ir_20260415', '2026年4月15日投资者关系活动记录表', '业绩交流', '2026Q1', '2026-04-16', 'https://static.cninfo.com.cn/finalpage/2026-04-16/1225109217.PDF'),
    ('ir_20260724', '2026年7月24日投资者关系活动记录表', '业绩交流', '2026H1', '2026-07-26', 'https://static.cninfo.com.cn/finalpage/2026-07-26/1225442224.PDF'),
    ('ir_20261020', '2026年10月20日投资者关系活动记录表', '业绩交流', '2026Q3', '2026-10-21', 'https://static.cninfo.com.cn/finalpage/2026-10-21/1225613436.PDF'),
    ('hk_prospectus_2025', '宁德时代H股全球发售招股章程', '招股书', '2025 IPO', '2025-05-12', 'https://www.hkexnews.hk/listedco/listconews/sehk/2025/0512/2025051200006_c.pdf'),
    ('accounting_basis_2026', '关于统一采用中国企业会计准则编制财务报告的公告', '会计口径公告', '2025起', '2026-01-09', 'https://disc.static.szse.cn/disc/disk03/finalpage/2026-01-09/2f8167c5-682f-4153-871a-9633214a4a98.PDF'),
    ('gics_cambria_20260531', 'Cambria Global EW ETF投资明细及GICS声明', '分类证据', '2026-05-31', '2026-08-04', 'https://www.cambriafunds.com/assets/docs/GEW_Q2_Schedule_of_Investments_Annual.pdf'),
]

def one(item):
    key,title,kind,period,date,url=item
    directory='transcripts/OFFICIAL_IR' if kind=='业绩交流' else 'OFFICIAL'
    path=RAW/directory/(key+'.pdf');path.parent.mkdir(parents=True,exist_ok=True)
    record=dict(id=key,title=title,kind=kind,period=period,published_at=date,source=url,retrieved_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
    if not path.exists():
        partial=path.with_suffix('.download')
        result=subprocess.run(['curl','--fail','--silent','--show-error','--location','--connect-timeout','15','--max-time','100',url,'--output',str(partial)],capture_output=True,text=True)
        if result.returncode:
            record.update(status='failed',error=result.stderr[-1500:]);partial.unlink(missing_ok=True);return record
        if not partial.read_bytes().startswith(b'%PDF'):
            record.update(status='failed',error='Response is not a PDF');partial.unlink(missing_ok=True);return record
        partial.replace(path)
    try:
        pdf=PdfReader(path)
        pages=[p.extract_text() or '' for p in pdf.pages]
        if not pages or not any(x.strip() for x in pages):raise ValueError('PDF has no extractable text')
        extract=RAW/'TEXT'/(key+'.txt');extract.parent.mkdir(exist_ok=True)
        extract.write_text('\n\n'.join(f'=== PDF PAGE {n+1} ===\n'+text for n,text in enumerate(pages)),encoding='utf-8')
        record.update(status='downloaded',file=str(path.relative_to(COMPANY)),text_file=str(extract.relative_to(COMPANY)),pages=len(pages),bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),first_page_excerpt=pages[0][:160])
    except Exception as error:record.update(status='failed_validation',error=str(error))
    return record

if __name__=='__main__':
    records=list(ThreadPoolExecutor(max_workers=4).map(one,SOURCES))
    result=dict(as_of='2026-10-24',timezone='Asia/Shanghai',ticker='300750.SZ',records=records)
    (COMPANY/'_source_catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    run=COMPANY/'_fetch_runs'/('direct-intake-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')+'.json')
    run.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in records:print(r['id'],r['status'],r.get('pages',''),r.get('error',''),flush=True)
