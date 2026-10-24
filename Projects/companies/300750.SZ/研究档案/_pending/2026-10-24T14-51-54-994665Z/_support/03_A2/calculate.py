import json
inputs = {"2025_EV_battery_TWh_approx": 1.2, "2030_EV_battery_TWh_approx": 3.0, "years": 5}
result = ((inputs["2030_EV_battery_TWh_approx"] / inputs["2025_EV_battery_TWh_approx"]) ** (1 / inputs["years"]) - 1) * 100
print(json.dumps({"inputs": inputs, "implied_CAGR_percent": result, "source": "D2 IEA Global EV Outlook 2026, EV battery demand outlook", "caution": "Approximate scenario endpoints; not CATL revenue forecast. No monetary TAM calculation."}, ensure_ascii=False, indent=2))
