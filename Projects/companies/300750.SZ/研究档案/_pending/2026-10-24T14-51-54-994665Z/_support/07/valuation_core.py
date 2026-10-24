"""Pure calculation scaffold for CATL 07. No prices or scenario decisions on import.

All amounts are CNY million, shares million; output per-share prices are CNY.
No network, registry operations, upstream writes, or import of the 06 write runner.
Use only after the parent confirms that 06 has passed review and pins its hash.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import json
import math
from pathlib import Path


def read_pinned(path: Path, expected_sha256: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Upstream changed after review: {path.name}")
    return json.loads(raw)


def capital_cost(rf, erp, beta_forward, kd, tax, equity, debt):
    assert 0 <= tax < 1 and equity > 0 and debt >= 0
    ke = rf + beta_forward * erp
    wd = debt / (equity + debt)
    return dict(rf=rf, erp=erp, beta_forward_assumption=beta_forward,
                kd=kd, tax=tax, ke=ke, equity_weight=1-wd, debt_weight=wd,
                wacc=ke*(1-wd)+kd*(1-tax)*wd)


def price_change_bridge(current_price, current_eps, target_eps, forward_pe):
    """EPS-multiple exact identity; dividends excluded from price returns."""
    assert min(current_price, current_eps, target_eps, forward_pe) > 0
    current_pe = current_price/current_eps
    e = target_eps/current_eps
    m = forward_pe/current_pe
    earnings = e-1
    multiple = e*(m-1)
    change = target_eps*forward_pe/current_price-1
    assert math.isclose(earnings+multiple, change, abs_tol=1e-12)
    split = None if abs(change) < 1e-10 else dict(earnings=earnings/change,
                                                   multiple=multiple/change, yield_=0.)
    if split is not None:
        split['yield'] = split.pop('yield_')
        assert math.isclose(sum(split.values()), 1., abs_tol=1e-12)
    return dict(earnings_factor=e, multiple_factor=m, current_pe=current_pe,
                earnings_contribution=earnings, multiple_contribution=multiple,
                yield_price_contribution=0., total_price_change=change,
                return_split=split,
                label='下行／价格变动贡献' if change < 0 else '上行／价格变动贡献')


def score_drivers(drivers):
    """Consume upstream classified observations; never invent a signal."""
    counts = {s: 0 for s in ('bull', 'base', 'bear')}
    valid = [x for x in drivers if x['latest_bucket'] in counts]
    for d in valid:
        counts[d['latest_bucket']] += 1
    if not valid:
        raise ValueError('No scored observation; cannot manufacture denominator')
    rates = {s: n/len(valid) for s, n in counts.items()}
    leaders = [s for s, rate in rates.items() if rate == max(rates.values())]
    # Conservative tie-break required by original method. Confidence still needs
    # qualitative counterevidence assessment in the report, not just this score.
    dominant = next(s for s in ('bear', 'base', 'bull') if s in leaders)
    return dict(counts=counts, denominator=len(valid), potential=len(drivers),
                rates=rates, dominant=dominant,
                forced_low_confidence=len(leaders)>1 or len(valid)<len(drivers)/2,
                excluded=[d['id'] for d in drivers if d not in valid])


def claim_bridge(operating_ev, bridge, opening_balance, cfg):
    """Explicit assumed economic claims; book proxies are never called fair values.

    cfg.nci_equity_fraction is an assumption on total consolidated equity, not a
    measured ownership ratio. Never simultaneously deduct book NCI.
    """
    required = bridge['minimum_operating_cash_sensitivity'] * cfg['cash_reserve_scale']
    ce = bridge['CE_proxy_estimate']
    gap_add = bridge['unclassified_monetary_minus_CE_gap'] * cfg['cash_gap_recovery']
    available = ce + gap_add - required
    assoc = bridge['equity_method_asset_estimate'] * cfg['associate_value_to_book']
    other_assets = bridge['other_financial_assets_book_proxy'] * cfg['financial_value_to_book']
    derivative = bridge['other_financial_assets_related_derivative_liability']
    explicit_debt = bridge['explicit_debt_proxy']
    sf = bridge['supplier_finance_H1_reference_proxy'] * cfg['supplier_finance_scale']
    equipment_ap = opening_balance['liabilities']['equipment_ap_proxy'] * cfg['equipment_ap_claim_fraction']
    long_payables = bridge['excluded_debt_classification_sensitivity_long_payables'] * cfg['long_payables_debt_fraction']
    consolidated_equity = operating_ev+available+assoc+other_assets-derivative-explicit_debt-sf-equipment_ap-long_payables
    nci = consolidated_equity * cfg['nci_equity_fraction']
    parent_equity = consolidated_equity-nci
    return dict(operating_ev=operating_ev, ce_proxy=ce, cash_gap_conditional_add=gap_add,
                required_operating_cash=required, surplus_cash_proxy=available,
                associate_assumed_value=assoc, financial_assumed_value=other_assets,
                derivative_liability_deduction=derivative, explicit_debt=explicit_debt,
                supplier_finance_claim=sf, equipment_ap_claim=equipment_ap,
                long_payables_debt_claim=long_payables,
                consolidated_equity_before_nci=consolidated_equity,
                nci_equity_fraction_assumption=cfg['nci_equity_fraction'], nci_assumed_claim=nci,
                parent_equity=parent_equity, shares=bridge['shares_million'],
                per_share=parent_equity/bridge['shares_million'])


def dcf(rows, bridge, opening_balance, cfg):
    """Current-date DCF with a stub, explicit future operating cash, and reinvestment.

    terminal_incremental_roic INCLUDING minimum operating cash is an assumed
    sustainable return, not observed ROIC. Hence no second terminal cash-growth
    deduction: g/ROIC already covers all incremental operating invested capital.
    """
    wacc, g = cfg['wacc'], cfg['terminal_growth']
    roic = cfg['terminal_incremental_roic']
    if not (wacc > g >= 0 and roic > g):
        raise ValueError('Need WACC>g>=0 and incremental terminal ROIC>g')
    tmap = bridge['FCFF_yearend_times_years']  # explicit year-end convention
    scale = cfg['cash_reserve_scale']
    stub = bridge['Q4_remaining_FCFF_economic']
    stub_cash_delta = stub-bridge['Q4_remaining_FCFF_after_optional_required_cash']
    cashflows = [dict(period='2026_Q4_remaining', t=tmap['2026_Q4_remaining'],
                     economic_fcff=stub, required_cash_delta=stub_cash_delta*scale,
                     distributable_fcff=stub-stub_cash_delta*scale)]
    for year in range(2027, 2032):
        row = rows[str(year)]
        fcff = row['CF']['FCFF_economic_after_SBC']
        delta = row['CF']['optional_delta_required_operating_cash']*scale
        cashflows.append(dict(period=str(year), t=tmap[str(year)],
                              economic_fcff=fcff, required_cash_delta=delta,
                              distributable_fcff=fcff-delta))
    for row in cashflows:
        row['discount_factor'] = (1+wacc)**(-row['t'])
        row['pv'] = row['distributable_fcff']*row['discount_factor']
    explicit_pv = sum(row['pv'] for row in cashflows)
    terminal = rows['2031']
    terminal_nopat_next = terminal['IS']['operating_EBIT']*(1+g)*(1-cfg['tax_rate'])
    reinvestment_rate = g/roic
    # ROIC is defined at the 06 baseline cash requirement. If the cash-reserve
    # assumption changes, carry that change into perpetuity as well as years 1–5.
    terminal_cash_reinvestment_delta = terminal['IS']['revenue'] * bridge['operating_assets_minimum_cash_assumption'] * g * (scale-1)
    terminal_reinvestment = terminal_nopat_next*reinvestment_rate+terminal_cash_reinvestment_delta
    terminal_fcff_next = terminal_nopat_next-terminal_reinvestment
    terminal_ev = terminal_fcff_next/(wacc-g)
    end_t = tmap['2031']
    terminal_pv = terminal_ev/(1+wacc)**end_t
    gor = claim_bridge(explicit_pv+terminal_pv, bridge, opening_balance, cfg)
    ebitda = terminal['IS']['operating_EBIT']+terminal['CF']['DA']
    exit_ev = ebitda*cfg['exit_ebitda_multiple']
    exit_pv = exit_ev/(1+wacc)**end_t
    ex = claim_bridge(explicit_pv+exit_pv, bridge, opening_balance, cfg)
    return dict(config=cfg, cashflows=cashflows, explicit_pv=explicit_pv,
                terminal_nopat_next=terminal_nopat_next,
                terminal_reinvestment_rate=reinvestment_rate,
                terminal_reinvestment=terminal_reinvestment,
                terminal_cash_reinvestment_delta=terminal_cash_reinvestment_delta,
                terminal_fcff_next=terminal_fcff_next,
                gordon_terminal_ev=terminal_ev, gordon_terminal_pv=terminal_pv,
                gordon_terminal_pv_share=terminal_pv/(explicit_pv+terminal_pv),
                terminal_ebitda=ebitda, exit_terminal_ev=exit_ev,
                exit_terminal_pv=exit_pv, gordon=gor, exit=ex)


def pure_forecaster(model_path: Path, expected_sha256: str):
    """Load ONLY 06 definitions before MODEL={}, excluding all output/runner code.

    This preserves the upstream accounting engine in a sensitivity calculation.
    No monkey-patching files and no 06 output writing. A locked source hash is
    compulsory. If upstream structure changes, fail rather than execute runner.
    """
    raw = model_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('06 accounting source changed; re-review before sensitivity')
    parsed = ast.parse(raw, filename=str(model_path))
    prefix = []
    for node in parsed.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='MODEL' for t in node.targets):
            break
        prefix.append(node)
    else:
        raise ValueError('06 MODEL boundary not found')
    if any(isinstance(x, (ast.For, ast.While)) for x in prefix):
        raise ValueError('Unexpected top-level runner before MODEL boundary')
    env = {'__file__': str(model_path), '__name__': '_read_only_06_sensitivity'}
    exec(compile(ast.Module(body=prefix, type_ignores=[]), str(model_path), 'exec'), env)
    if not all(k in env for k in ('project', 'SC', 'START', 'H')):
        raise ValueError('Missing pure forecast interface')
    return env


def shifted_forecast(env, scenario, growth_delta, margin_delta):
    """Annual-growth pp shift + EBIT-margin pp shift via COGS; rerun all accounts.

    Q4 assumptions unchanged. No valuation or opportunity decisions here.
    """
    params = copy.deepcopy(env['SC'])
    s = params[scenario]
    s['growth'] = [v+growth_delta for v in s['growth']]
    s['gm'] = [v+margin_delta for v in s['gm']]
    if min(s['growth']) <= -1 or min(s['gm']) <= 0 or max(s['gm']) >= 1:
        raise ValueError('Invalid shifted economic assumption')
    original = env['SC']
    try:
        env['SC'] = params
        env['MODEL'] = {scenario: {}}
        previous = copy.deepcopy(env['START']); previous_revenue = None
        for year in range(2026, 2032):
            row = env['project'](previous, scenario, year, previous_revenue)
            env['MODEL'][scenario][row['period']] = row
            previous = row['BS']
            previous_revenue = env['H']['2026_9M']['revenue']+row['IS']['revenue'] if year==2026 else row['IS']['revenue']
        rows = copy.deepcopy(env['MODEL'][scenario])
        prior_required = env['R0']*env['COMMON']['minimum_cash_revenue']
        for period in ['2026_Q4']+[str(y) for y in range(2027,2032)]:
            row = rows[period]
            annualrev = env['H']['2026_9M']['revenue']+row['IS']['revenue'] if period=='2026_Q4' else row['IS']['revenue']
            required = annualrev*env['COMMON']['minimum_cash_revenue']
            delta = required-prior_required
            row['CF']['optional_delta_required_operating_cash'] = delta
            row['CF']['optional_required_operating_cash'] = required
            row['CF']['FCFF_after_optional_required_cash'] = row['CF']['FCFF_economic_after_SBC']-delta
            prior_required = required
        return rows
    finally:
        env['SC'] = original


def matrix_wacc_growth(rows, bridge, opening_balance, cfg, offsets):
    values=[]
    for dw in offsets:
        line=[]
        for dg in offsets:
            c={**cfg,'wacc':cfg['wacc']+dw,'terminal_growth':cfg['terminal_growth']+dg}
            line.append(dcf(rows,bridge,opening_balance,c)['gordon']['per_share'])
        values.append(line)
    return dict(wacc=[cfg['wacc']+v for v in offsets],
                terminal_growth=[cfg['terminal_growth']+v for v in offsets],values=values)


def matrix_growth_margin(env, scenario, bridge, opening_balance, cfg, offsets):
    values=[]
    for dg in offsets:
        line=[]
        for dm in offsets:
            rows=shifted_forecast(env,scenario,dg,dm)
            line.append(dcf(rows,bridge,opening_balance,cfg)['gordon']['per_share'])
        values.append(line)
    return dict(annual_growth_pp_shifts=offsets,operating_margin_pp_shifts=offsets,values=values)


if __name__ == '__main__':
    print('Prepared pure valuation functions only; waiting for reviewed 06 and explicit parameter configuration. No valuation was run.')
