"""Verify publication boundaries using fictional isolated workflow fixtures."""
import json
import subprocess
import sys
import unittest
import test_core
ROOT=test_core.ROOT
SLOTS=test_core.SLOTS


class LocalViews(unittest.TestCase):
    def setUp(self):
        self.workflow=test_core.CoreWorkflow()
        self.workflow.setUp()
        self.workflow.full_accept()
        self.workflow.run_cli('sync','TEST')
        self.folder=self.workflow.projects/'companies/TEST'

    def tearDown(self):self.workflow.tearDown()

    def run_script(self,name,*args,code=0):
        p=subprocess.run([sys.executable,str(ROOT/'scripts'/name),*map(str,args)],env=self.workflow.env,capture_output=True,text=True)
        self.assertEqual(p.returncode,code,p.stdout+p.stderr)
        return p

    def build(self):
        self.run_script('build_local.py')
        return json.loads((self.workflow.projects/'_site/data.json').read_text())

    def test_tampered_dossier_and_stale_registration_are_not_published(self):
        before=self.build()['companies'][0]
        self.assertTrue(before['modules'][6]['url'])
        self.assertTrue(before['valuation']['source_sha256'])
        p=self.folder/'研究档案'/SLOTS[6]
        p.write_text(p.read_text()+'\n未审阅修改，不能成为网页正式结论。')
        after=self.build()['companies'][0]
        self.assertIsNone(after['modules'][6]['url'])
        self.assertNotIn('target_price',after['valuation'])
        self.assertTrue(after['valuation']['needs_recheck'])
        self.assertNotIn('target_price_3y',after['three_year'])

    def test_summary_requires_registration_and_matching_content(self):
        md=self.folder/'研究总结_2026-10-24.md';html=md.with_suffix('.html')
        md.write_text('# 隔离软件测试总结\n仅检查发布约束，不构成研究。')
        html.write_text('<!doctype html><title>隔离软件测试总结</title><p>仅检查发布约束，不构成研究。</p>')
        self.assertFalse([r for r in self.build()['reports'] if r['kind']=='研究总结'])
        self.run_script('register_summary.py','TEST','--markdown',md,'--html',html)
        self.assertEqual(len([r for r in self.build()['reports'] if r['kind']=='研究总结']),2)
        html.write_text(html.read_text()+'<p>未经登记的改动</p>')
        self.assertFalse([r for r in self.build()['reports'] if r['kind']=='研究总结'])
        self.run_script('register_summary.py','TEST','--markdown',md,'--html',html,code=1)


if __name__=='__main__':unittest.main()
