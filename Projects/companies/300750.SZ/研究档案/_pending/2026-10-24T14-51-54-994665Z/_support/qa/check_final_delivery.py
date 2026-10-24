"""Check this real pending delivery without accepting or syncing any report."""
from pathlib import Path
import hashlib
import json
import sys
from datetime import datetime, timezone

ROOT = Path('/Users/yuangzhou/Desktop/tideStone-root')
PROJECTS = ROOT / 'Projects'
BATCH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECTS / '_system/scripts'))
from handoff_lint import lint_file
from sync_valuations import _extract_registry_payload, _three_year_payload

def read(path):
    return json.loads(path.read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

reports = sorted(BATCH.glob('0[1-7]_*.md'))
assert len(reports) == 7
documents = []
for path in reports:
    errors, warnings = lint_file(path)
    assert not errors and not warnings, (path.name, errors, warnings)
    assert path.stat().st_size > 1000
    documents.append(dict(file=path.name, bytes=path.stat().st_size,
                          sha256=digest(path), lint='passed'))

bundle = read(BATCH / '_context_bundle.json')
materials = read(PROJECTS / 'companies/300750.SZ/_materials.json')['materials']
assert bundle['materials'] == materials
assert all(digest(PROJECTS / m['file']) == m['sha256'] for m in materials)
model = read(BATCH / '_support/06/forecast_model.json')
assert all(digest(BATCH / f) == value for f, value in model['upstream_sha256'].items())
valuation = read(BATCH / '_support/07/valuation_results.json')
assert all(digest(BATCH / f) == value['sha256']
           for f, value in valuation['inputs_sha256'].items())

text = (BATCH / '07_估值分析.md').read_text()
registry, warnings = _extract_registry_payload(text, '300750.SZ')
assert not warnings and registry == valuation['registry']
company = read(PROJECTS / '_system/companies.json')['companies']['300750.SZ']
# This pure validator returns an in-memory status. No returned sync object is saved.
three_year = _three_year_payload(text, company, {})
assert all(three_year[k] == valuation['three_year'][k] for k in valuation['three_year'])
signals = registry['scenario_valuation']['signals']
assert len(signals) == 15
assert {(x['scenario'], x['driver_id']) for x in signals} == {
    (s, d) for s in ['bear', 'base', 'bull'] for d in ['D1', 'D2', 'D3', 'D4', 'D5']}
winning_bucket = {'D1': 'bear', 'D2': 'bear', 'D3': 'base', 'D4': 'bull', 'D5': None}
for signal in signals:
    winner = winning_bucket[signal['driver_id']]
    expected = '无数据' if winner is None else ('命中' if signal['scenario'] == winner else '未命中')
    assert signal['status'] == expected
    assert signal['source'] and signal['action'] and signal['as_of'] == '2026-10-24'
    if signal['driver_id'] == 'D2':
        assert signal.get('applicability'), 'D2 must preserve the positive-net-income gate'
    if signal['driver_id'] == 'D5':
        assert signal['current_value'] is None
assert abs(sum(registry['opportunity_type']['return_split'].values()) - 1) < 1e-12

assert all(not (BATCH.parent.parent / f.name).exists() for f in reports)
formal = read(PROJECTS / '_system/valuation_registry.json')['companies']['300750.SZ']
assert formal['rating'] == '待研究' and formal['target_price'] == '待研究'
assert not formal.get('scenario_valuation') and not formal.get('zones')
assert '300750.SZ' not in read(PROJECTS / '_system/three_year_valuation_registry.json').get('companies', {})

result = dict(checked_at=datetime.now(timezone.utc).isoformat(),
              mode='pending_delivery_check_only_no_accept_no_sync',
              all_pass=True, documents=documents, materials_verified=len(materials),
              source_and_input_hashes_verified=True, both_registry_parsers_pass=True,
              distinct_scenario_signals=15, d2_positive_profit_gate_preserved=True,
              formal_reports_absent=True, ordinary_registry_still_onboarding_placeholder=True,
              three_year_registry_absent=True,
              scope='Integrity and transport checks; financial model and valuation arithmetic reviewed separately in this folder.')
(BATCH / '_support/qa/final_delivery_check.json').write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
