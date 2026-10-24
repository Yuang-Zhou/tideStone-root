"""Isolated workflow regressions. Fixtures are fictional and never touch Projects/companies."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import date

ROOT=Path(__file__).resolve().parents[1]
CLI=ROOT/'scripts/tidestone.py'
sys.path.insert(0,str(ROOT/'Projects/_system/scripts'))
import paper_portfolio
SLOTS=['01_企业文化.md','02_财务分析.md','03_商业模式.md','04_战略决策.md','05_股性分析.md','06_财务预测.md','07_估值分析.md']


class CoreWorkflow(unittest.TestCase):
    def setUp(self):
        test_root=ROOT/'runs'/'tests'/'core'
        test_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='tidestone-test-',dir=test_root)
        self.projects=Path(self.temp.name)/'Projects'
        self.env={**os.environ,'TIDESTONE_PROJECTS':str(self.projects)}
        self.run_cli('init')
        self.run_cli('add','TEST','--name','隔离测试公司','--market','US','--sector','45')
        self.source=Path(self.temp.name)/'source.txt'
        self.source.write_text('虚构测试资料，禁止用于投资判断。销售额由100增至110，现金流由12增至13；所有数字仅为软件验证。')
        self.run_cli('material','TEST','--file',str(self.source),'--source','test:fictional-material','--kind','测试材料')

    def tearDown(self):self.temp.cleanup()

    def run_cli(self,*args,code=0):
        p=subprocess.run([sys.executable,str(CLI),*args],env=self.env,text=True,capture_output=True)
        self.assertEqual(p.returncode,code,p.stdout+p.stderr)
        return p.stdout

    def prepare(self,*slots):
        args=['prepare','TEST']
        if slots:args+=['--slots',*slots]
        bundle=json.loads(self.run_cli(*args))
        self.batch=self.projects/bundle['pending_dir'];self.ts=bundle['timestamp']
        return bundle

    def write_slots(self,bundle):
        for info in bundle['slots']:
            s=info['slot']
            text=f'# {s}\n\n这是与正式库隔离的软件验证材料，所有数字为虚构值，禁止用于投资判断。\n\n依据已登记测试材料，收入从100增至110，增长10%；经营现金流由12增至13，但仅靠两期数据不能证明持续竞争优势。需要长期客户留存、现金流和资本开支证据才能确定质量。\n\n来源：test:fictional-material。\n'
            if s.startswith('04'):
                text+='## 交接块\n### H1\n测试目的战略，不形成投资结论。\n### H2\n|情景|判定|\n|---|---|\n|乐观|增长继续|\n|基准|待证|\n|悲观|增长逆转|\n### H3\n预测须保留不确定性。\n### H4\n估值须与证据对应。\n### H5\n下一期资料验证。\n<!-- HANDOFF-END v1 -->\n'
            if s.startswith('06'):text+='## 三情景分歧驱动表\n尚无长期数据，不能据此推定增速。\n'
            if s.startswith('07'):
                payload={'rating':'待研究','target_price':'悲观80 / 基准100 / 乐观120（仅虚构测试）','zones':[],'scenario_valuation':{'dominant':'base','signals':[]},'opportunity_type':'test'}
                text+='### 4.8 valuation_registry 登记块\n```json\n'+json.dumps(payload,ensure_ascii=False)+'\n```\n'
                text+='### three_year_valuation_registry 登记块\n```json\n'+json.dumps(self.three_payload(),ensure_ascii=False)+'\n```\n'
            (self.batch/s).write_text(text)

    def three_payload(self):
        return {'target_year':2029,'currency':'USD','scenario':'base',
                'valuation_method':'PE（虚构测试）','valuation_type':'equity',
                'metric_value_b':0.1,'target_multiple':20,'net_debt_b':0,
                'share_equivalent_b':0.02,'target_market_cap_b':2,'target_price_3y':100,
                'anchor_price':80,'anchor_date':'2026-10-23','target_date':'2029-10-23',
                'source':'本测试07与06；虚构数据，不用于投资判断'}

    def replace_three(self,payload):
        path=self.batch/SLOTS[6];text=path.read_text().split('### three_year_valuation_registry 登记块')[0]
        if payload is not None:
            text+='### three_year_valuation_registry 登记块\n```json\n'+json.dumps(payload,ensure_ascii=False)+'\n```\n'
        path.write_text(text)


    def full_accept(self):
        bundle=self.prepare();self.write_slots(bundle)
        self.run_cli('finalize','TEST',self.ts)
        self.run_cli('accept','TEST',self.ts,'--reason','测试审阅通过')
        return bundle

    def test_add_currency_defaults_override_and_other_requires_explicit_code(self):
        for ticker,market,currency,args in [('HKT','HK','HKD',[]),('CNT','CN','CNY',[]),
                ('EUT','OTHER','EUR',['--currency','EUR']),('ALT','US','CAD',['--currency','CAD'])]:
            with self.subTest(market=market):
                entry=json.loads(self.run_cli('add',ticker,'--name','虚构币种测试','--market',market,*args))
                self.assertEqual(entry['currency'],currency)
                stored=json.loads((self.projects/'_system/valuation_registry.json').read_text())['companies'][ticker]
                self.assertEqual(stored['currency'],currency)
        for ticker,args in [('MISSING',[]),('LOWER',['--currency','eur']),('SHORT',['--currency','EU'])]:
            self.run_cli('add',ticker,'--name','无效入库','--market','OTHER',*args,code=1)
            self.assertFalse((self.projects/'companies'/ticker).exists())
        self.assertEqual(json.loads((self.projects/'_system/companies.json').read_text())['companies']['TEST']['currency'],'USD')

    def test_accept_messages_use_current_paths_and_only_missing_downstream(self):
        b=self.prepare();self.write_slots(b);self.run_cli('finalize','TEST',self.ts)
        output=self.run_cli('accept','TEST',self.ts,'--reason','检查同批完整交接提示')
        self.assertNotIn('未在同批覆盖',output)
        self.assertNotIn('基本面分析汇总',output)
        self.assertIn('/companies/TEST/研究总结_',output)
        self.assertIn('scripts/register_summary.py TEST',output)
        self.assertIn('scripts/tidestone.py sync TEST',output)
        b=self.prepare('04','06');self.write_slots(b);self.run_cli('finalize','TEST',self.ts)
        output=self.run_cli('accept','TEST',self.ts,'--reason','检查07单独待对齐提示')
        self.assertIn('--slots 07_估值分析.md --trigger catalyst',output)
        self.assertNotIn('--slots 06_财务预测.md',output)

    def test_tracking_defaults_active_and_can_pause_before_research(self):
        state=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(state['tracking_status'],'active')
        self.assertEqual(state['exists_count'],0)
        self.assertTrue(state['daily_research_tracking'])
        entry=json.loads((self.projects/'_system/valuation_registry.json').read_text())['companies']['TEST']
        self.assertEqual(entry['rating'],'待研究')
        self.run_cli('track','TEST','--status','paused','--reason','测试用户暂停跟踪')
        state=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(state['tracking_status'],'paused')
        self.assertFalse(state['daily_research_tracking'])
        self.assertIn('- **Status:** paused',(self.projects/'_system/portfolio_registry.md').read_text())
        self.run_cli('track','TEST','--status','active','--reason','测试用户恢复跟踪')
        state=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(state['tracking_status'],'active')
        self.assertTrue(state['daily_research_tracking'])
        self.assertEqual(state['workflow']['history'][-1]['action'],'track')
        self.assertEqual(state['workflow']['history'][-1]['previous_status'],'paused')
        self.assertEqual(state['exists_count'],0)
        self.assertFalse((self.projects/'_system/paper_portfolio/state.json').exists())

    def test_paper_candidate_rejects_missing_or_invalid_currency_rate(self):
        for rate in [None,0,-1,float('nan'),float('inf'),True]:
            with self.subTest(rate=rate):
                cfg={**paper_portfolio.DEFAULT_CONFIG,'fx_to_usd':{'EUR':rate}}
                c=paper_portfolio.evaluate('EUROTEST',{'currency':'EUR'}, {},cfg,self.projects,date(2026,10,23))
                self.assertFalse(c.eligible)
                self.assertEqual(c.reason,'缺少该币种有效汇率')

    def test_paper_existing_holding_without_valid_fx_cannot_write_nav(self):
        pdir=self.projects/'_system/paper_portfolio'
        (pdir/'config.json').write_text(json.dumps({**paper_portfolio.DEFAULT_CONFIG,'fx_to_usd':{'USD':1}}))
        (pdir/'state.json').write_text(json.dumps({'cash_usd':100,'holdings':{'EUROTEST':{'currency':'EUR','qty':1,'last_px_usd':30}},'last_run':'2026-10-22'}))
        (pdir/'nav_history.csv').write_text('date,nav_usd\n2026-10-22,130\n')
        (pdir/'summary_latest.json').write_text('{"asof":"2026-10-22","nav":130}')
        before={p.name:p.read_bytes() for p in pdir.iterdir() if p.is_file()}
        self.assertEqual(paper_portfolio.run(self.projects,date(2026,10,23),False,False),1)
        self.assertEqual({p.name:p.read_bytes() for p in pdir.iterdir() if p.is_file()},before)

    def test_materials_drafts_and_arbitrary_legacy_names_are_never_formal(self):
        folder=self.projects/'companies/TEST'
        for rel in ['materials/business-and-governance.md','raw/financial-analysis.md',
                    'business-model.md','old-notes/strategic-decision.md',
                    '研究档案/_pending/example/06_财务预测.md',
                    '研究档案/_history/example/07_估值分析.md',
                    'unlisted-folder/stock-character.md']:
            path=folder/rel;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('这是研究材料或草稿，不能成为用户已接受的研究结论。'*10)
        c=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(c['exists_count'],0)
        self.assertEqual(c['dossier_status'],'empty')
        self.assertTrue(all(not d['exists'] and d['legacy_source'] is None for d in c['documents'].values()))
        self.assertFalse(any(d.get('canonical_missing') for d in c['documents'].values()))

    def test_unapproved_canonical_file_is_not_complete_or_a_dependency(self):
        d=self.projects/'companies/TEST/研究档案'
        (d/SLOTS[1]).write_text('即使文件名与正式档案相同，未经用户接受也只能视为非正式内容。'*8)
        (d/'_meta.json').write_text(json.dumps({'documents':{SLOTS[1]:{'approval_status':'pending'}}}))
        c=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(c['exists_count'],0)
        self.assertFalse(c['dossier_initialized'])
        b=self.prepare('03');self.write_slots(b)
        self.assertEqual(b['slots'][0]['dependency_paths'],['MISSING: '+SLOTS[1]])
        self.run_cli('finalize','TEST',self.ts,code=1)

    def test_formal_content_hash_and_approval_are_required_on_rescan(self):
        self.full_accept()
        d=self.projects/'companies/TEST/研究档案';path=d/SLOTS[1];original=path.read_text()
        path.write_text(original+'\n未经审阅的直接更改。')
        c=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(c['exists_count'],6)
        self.assertFalse(c['documents'][SLOTS[1]]['exists'])
        self.assertIn('哈希',c['documents'][SLOTS[1]]['integrity_errors'][0])
        path.write_text(original)
        c=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(c['exists_count'],7)
        meta=json.loads((d/'_meta.json').read_text());meta['documents'][SLOTS[1]]['approval_status']='pending'
        (d/'_meta.json').write_text(json.dumps(meta))
        c=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(c['exists_count'],6)

    def test_empty_and_unfinalized_cannot_be_accepted(self):
        b=self.prepare()
        self.run_cli('accept','TEST',self.ts,'--reason','试图绕过',code=1)
        for s in SLOTS:(self.batch/s).touch()
        out=json.loads(self.run_cli('finalize','TEST',self.ts,code=1))
        self.assertEqual(out['batch_status'],'failed')
        self.run_cli('accept','TEST',self.ts,'--reason','试图接受空模块',code=1)
        self.assertFalse((self.projects/'companies/TEST/研究档案/_meta.json').exists())

    def test_change_after_finalize_requires_refinalize(self):
        b=self.prepare();self.write_slots(b);self.run_cli('finalize','TEST',self.ts)
        p=self.batch/SLOTS[0];p.write_text(p.read_text()+'\n修改后的新判断。')
        self.run_cli('accept','TEST',self.ts,'--reason','测试',code=1)
        self.run_cli('finalize','TEST',self.ts)
        self.run_cli('accept','TEST',self.ts,'--reason','复核新判断')
        d=self.projects/'companies/TEST/研究档案'
        self.assertTrue((d/SLOTS[0]).read_text().endswith('修改后的新判断。'))

    def test_update_history_event_and_restart(self):
        self.full_accept()
        d=self.projects/'companies/TEST/研究档案';old=(d/SLOTS[1]).read_text();untouched=(d/SLOTS[0]).read_bytes()
        self.run_cli('event','TEST','--title','新财报','--source','test:new-report','--slots','02','06','07')
        b=self.prepare('02','06','07');self.write_slots(b)
        self.run_cli('finalize','TEST',self.ts)
        self.run_cli('revise','TEST',self.ts,'--reason','审阅要求补充现金流解释')
        p=self.batch/SLOTS[1];p.write_text(p.read_text()+'\n修订：现金流增长8.33%，低于收入10%；样本太短，暂不能断言质量恶化。')
        self.run_cli('accept','TEST',self.ts,'--reason','尚未重新校验',code=1)
        self.run_cli('finalize','TEST',self.ts)
        self.run_cli('accept','TEST',self.ts,'--reason','已核对修订与材料')
        status=json.loads(self.run_cli('status','TEST','--json'))['companies'][0]
        self.assertEqual(status['exists_count'],7)
        self.assertEqual(status['events'][0]['status'],'resolved')
        self.assertEqual(status['workflow']['last_accepted_batch'],self.ts)
        self.assertEqual((d/SLOTS[0]).read_bytes(),untouched)
        self.assertTrue(any(p.read_text()==old for p in (d/'_history').glob('*/_before/02_财务分析.md')))
        self.assertTrue(any((d/'_pending/_accepted'/self.ts/'_revisions').iterdir()))
        self.run_cli('sync','TEST')
        queue=json.loads((self.projects/'_system/pending_valuation_sync.json').read_text())
        self.assertEqual(queue['pending'],[])

    def test_missing_material_or_upstream_blocks_finalize(self):
        b=self.prepare('03');self.write_slots(b)
        self.run_cli('finalize','TEST',self.ts,code=1)
        self.run_cli('reject','TEST',self.ts,'--reason','缺少财务模块，退回补齐')
        self.assertTrue((self.batch.parent/'_rejected'/self.ts).exists())
        b=self.prepare();self.write_slots(b)
        mat=self.projects/b['materials'][0]['file'];mat.write_text('材料被改动')
        self.run_cli('finalize','TEST',self.ts,code=1)

    def test_same_batch_upstream_and_stale_baseline(self):
        self.full_accept()
        b1=self.prepare('02','03');self.write_slots(b1);ts1=self.ts
        deps=next(s for s in b1['slots'] if s['slot']==SLOTS[2])['dependency_paths']
        self.assertTrue(deps[0].startswith('PENDING_IN_BATCH:'))
        self.run_cli('finalize','TEST',ts1)
        b2=self.prepare('02');self.write_slots(b2)
        p=self.batch/SLOTS[1];p.write_text(p.read_text()+'\n第二批补充内容改变正式版本。')
        self.run_cli('finalize','TEST',self.ts);self.run_cli('accept','TEST',self.ts,'--reason','接受第二批')
        self.run_cli('accept','TEST',ts1,'--reason','不能覆盖新正式版',code=1)

    def test_three_year_sync_records_same_accepted_source_and_retains_missing_queue(self):
        self.full_accept();first=self.ts;self.run_cli('sync','TEST')
        registry=self.projects/'_system/three_year_valuation_registry.json'
        ordinary=self.projects/'_system/valuation_registry.json'
        entry=json.loads(registry.read_text())['companies']['TEST']
        self.assertEqual(entry['target_price_3y'],100)
        self.assertEqual(entry['accepted_batch'],first)
        self.assertEqual(entry['source_sha256'],json.loads(ordinary.read_text())['companies']['TEST']['source_sha256'])
        b=self.prepare('07');self.write_slots(b);self.replace_three(None)
        self.run_cli('finalize','TEST',self.ts);self.run_cli('accept','TEST',self.ts,'--reason','测试接受含三年缺口的报告')
        self.run_cli('sync','TEST',code=1)
        queue=json.loads((self.projects/'_system/pending_valuation_sync.json').read_text())['pending'][0]
        self.assertEqual(queue['valuation_status'],'synced')
        self.assertEqual(queue['three_year_status'],'pending')
        self.assertIn('three_year_valuation_registry',queue['errors'][0])
        doc=json.loads(registry.read_text())
        self.assertIsNone(doc['companies']['TEST']['target_price_3y'])
        self.assertEqual(doc['companies']['TEST']['accepted_batch'],self.ts)
        self.assertEqual(doc['history'][0]['entry']['accepted_batch'],first)

    def test_three_year_currency_year_math_and_batch_errors_remain_pending(self):
        self.full_accept()
        invalid=[('currency','EUR','币种'),('target_year',2028,'target_year'),
                 ('target_market_cap_b',3,'市值算术'),('target_price_3y',101,'每股目标价算术'),
                 ('accepted_batch','another-batch','另一批次'),('scenario','bull','基准情景')]
        for field,value,error in invalid:
            with self.subTest(field=field):
                b=self.prepare('07');self.write_slots(b);payload=self.three_payload();payload[field]=value
                self.replace_three(payload)
                self.run_cli('finalize','TEST',self.ts);self.run_cli('accept','TEST',self.ts,'--reason','独立验证错误登记不会被同步')
                self.run_cli('sync','TEST',code=1)
                queue=json.loads((self.projects/'_system/pending_valuation_sync.json').read_text())['pending'][0]
                self.assertEqual(queue['three_year_status'],'pending')
                self.assertTrue(any(error in e for e in queue['errors']),queue['errors'])

    def test_sync_rejects_unaccepted_pending_source(self):
        b=self.prepare();self.write_slots(b)
        queue=self.projects/'_system/pending_valuation_sync.json'
        queue.write_text(json.dumps({'pending':[{'ticker':'TEST','slot07_path':b['pending_dir']+'/'+SLOTS[6]}]}))
        self.run_cli('sync','TEST',code=1)
        entry=json.loads(queue.read_text())['pending'][0]
        self.assertEqual(entry['valuation_status'],'pending')
        self.assertEqual(entry['three_year_status'],'pending')
        self.assertEqual(json.loads((self.projects/'_system/three_year_valuation_registry.json').read_text())['companies'],{})


    def test_interrupted_promotion_restores_previous_files(self):
        self.full_accept()
        d=self.projects/'companies/TEST/研究档案';p=d/SLOTS[0];old=p.read_text()
        h=d/'_history'/'interrupted';(h/'_before').mkdir(parents=True)
        (h/'_before'/SLOTS[0]).write_text(old)
        (h/'_transaction.json').write_text(json.dumps({'status':'applying','batch':'test','targets':[SLOTS[0]]}))
        p.write_text('中断留下的半成品')
        self.run_cli('status','TEST','--json')
        self.assertEqual(p.read_text(),old)
        self.assertEqual(json.loads((h/'_transaction.json').read_text())['status'],'rolled_back')


if __name__=='__main__':unittest.main()
