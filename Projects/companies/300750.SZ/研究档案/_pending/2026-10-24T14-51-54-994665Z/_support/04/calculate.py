from pathlib import Path
import json
base = Path(__file__).resolve().parents[2]
data = json.loads((base / "_support/02/analysis_inputs_results.json").read_text())["data"]
results = {"capex_2021_2025_CNY_100m": sum(data[str(y)]["cash_paid_for_long_lived_assets"] for y in range(2021,2026)) / 100, "rnd_2021_2025_CNY_100m": sum(data[str(y)]["research_and_development_expenses"] for y in range(2021,2026)) / 100, "subjective_scenario_points_percent": {"failure":30,"base_success":50,"upside":20}, "scenario_point_sum":sum([30,50,20]), "supplier_finance_H1_CNY_million":20391.072+37373.152, "supplier_finance_delta_from_2025_CNY_million":57764.224-37222.781, "supplier_finance_not_a_Q3_observation":True, "EV_computed":False, "tax_impact_is_explanatory_embedded_parameter_not_extra_deduction":True}
assert results["scenario_point_sum"] == 100
assert abs(results["supplier_finance_H1_CNY_million"] - 57764.224) < 1e-7
(base / "_support/04/calculation_results.json").write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(results,ensure_ascii=False))
