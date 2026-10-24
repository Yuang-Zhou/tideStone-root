"""Pure in-memory financial-display regressions; no formal or trial data is read/written."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'Projects/_system/scripts/render_tables.py'
spec=importlib.util.spec_from_file_location('render_tables_under_test',PATH)
rt=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)


def financials(tag='DebtCurrent'):
    vals={'revenue':100_000_000,'interest_expense':500_000,'interest_income':0,
          'cash_and_equivalents':18_000_000,'short_term_investments':2_000_000,
          'short_term_debt':12_000_000,'debt_due_1y':6_000_000,
          'operating_lease_liab_current':2_000_000,'finance_lease_liab_current':1_000_000,
          'accounts_receivable':90_000_000,'allowance_doubtful_accounts':10_000_000}
    return {'meta':{'tag_map':{'short_term_debt':[tag]}},
            'annual':{k:{'2025':v} for k,v in vals.items()},
            'ttm':{'period_end':'2025-12-31','instant':vals,'flow':vals}}


def row(text,label):
    line=next(x for x in text.splitlines() if x.startswith('| '+label+' |'))
    return [x.strip() for x in line.split('|')[2:-1]]


class RenderTablesTests(unittest.TestCase):
    def test_submillion_interest_is_not_zero(self):
        text=rt.render(financials())
        self.assertEqual(row(text,'利息支出（净）'),['0.5','0.5'])
        self.assertEqual(rt.fmt_money(-500_000,1e6),'-0.5')
        self.assertEqual(rt.fmt_money(0,1e6),'0')
        self.assertEqual(rt.fmt_money(None,1e6),'n/a')
        self.assertNotIn(rt.fmt_money(1,1e6),('0','-0'))

    def test_current_total_adds_both_leases_without_double_counting_due_principal(self):
        text=rt.render(financials())
        self.assertEqual(row(text,'1 年内到期债务（含流动租赁）'),['15','15'])
        self.assertEqual(row(text,'现金+短投 / 1 年内到期债务（含流动租赁）'),['1.3x','1.3x'])
        self.assertEqual(row(text,'长期债务 1 年内到期本金（不含租赁）'),['6','6'])

    def test_short_borrowings_require_current_long_term_principal(self):
        data=financials('ShortTermBorrowings')
        text=rt.render(data)
        self.assertEqual(row(text,'1 年内到期债务（含流动租赁）'),['21','21'])
        self.assertEqual(row(text,'现金+短投 / 1 年内到期债务（含流动租赁）'),['1.0x','1.0x'])

    def test_incomplete_or_ambiguous_scope_is_not_a_complete_coverage_ratio(self):
        for tag in ['LongTermDebtCurrent','LongTermDebtAndCapitalLeaseObligationsCurrent','unknown']:
            with self.subTest(tag=tag):
                text=rt.render(financials(tag))
                self.assertEqual(row(text,'现金+短投 / 1 年内到期债务（含流动租赁）'),['n/a','n/a'])
                self.assertIn('一年内偿债口径待核',text)

    def test_missing_lease_is_not_zero(self):
        data=financials()
        del data['annual']['finance_lease_liab_current']
        del data['ttm']['instant']['finance_lease_liab_current']
        self.assertEqual(row(rt.render(data),'现金+短投 / 1 年内到期债务（含流动租赁）'),['n/a','n/a'])

    def test_period_record_takes_precedence_over_global_tag_map(self):
        data=financials('DebtCurrent')
        data['records']=[{'metric':'short_term_debt','period_end':'2025-12-31','form':'10-K',
                          'tag':'ShortTermBorrowings','value':12_000_000}]
        self.assertEqual(row(rt.render(data),'1 年内到期债务（含流动租赁）'),['21','21'])

    def test_existing_allowance_formula_uses_gross_receivables(self):
        self.assertEqual(row(rt.render(financials()),'坏账准备 / 应收总额'),['10.0%','10.0%'])

    def test_project_and_skill_entry_scripts_match(self):
        self.assertEqual(PATH.read_bytes(),(ROOT/'.agents/skills/financial-analysis/scripts/render_tables.py').read_bytes())


if __name__=='__main__':unittest.main()
