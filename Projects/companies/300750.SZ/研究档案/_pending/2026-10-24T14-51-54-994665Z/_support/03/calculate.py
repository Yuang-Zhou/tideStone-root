"""03基于02已核财报输入的可复算派生值；单位CNY million。"""
import json
from pathlib import Path
p=Path(__file__).resolve().parents[2]
d=json.loads((p/'_support/02/analysis_inputs_results.json').read_text())['data']
out={'source':'02 analysis_inputs_results.json; CAS; same batch','annual':{}}
for y in ['2023','2024','2025']:
 a,b=d[y],d[str(int(y)-1)]
 out['annual'][y]={
  'sga_rnd_rate':sum(a[k] for k in ['selling_expenses','admin','research_and_development_expenses'])/a['revenue'],
  'rnd_rate':a['research_and_development_expenses']/a['revenue'],
  'ar_days_average_net':(a['trade_receivables']+b['trade_receivables'])/2/a['revenue']*365,
  'inventory_days_average_net':(a['inventories']+b['inventories'])/2/a['cost_of_sales']*365,
  'ppe_turnover_average_net':a['revenue']/((a['ppe_net']+b['ppe_net'])/2),
 }
out['annual']['2023']['note']='2022COGS未作质保重分类；本年天数只用2023可比COGS和前后存量'
out['notes']=['应收天数只用应收账款净额，不含应收票据/融资；不是完整回款周期','存货天数以净额平均，不能排除减值或结构影响；未将年末余额/收入称平均周转','固定资产净额周转不含在建工程/无形资产，不等于ROIC']
(Path(__file__).parent/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False,indent=2))
