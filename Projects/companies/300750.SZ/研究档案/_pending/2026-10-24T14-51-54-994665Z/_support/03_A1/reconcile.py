from pathlib import Path
import json
rows={
"FY2025":{"total":[423701834,312383297],"动力":[316506369,241064397],"储能":[62439820,45763689],"材料回收":[21860936,15899813],"矿产":[5978096,5305599],"其他（披露）":[16916612,4349799]},
"2026H1":{"total":[276916580,210654890],"动力":[192124890,152492111],"储能":[53260967,40500853],"材料回收及矿产":[18811078,13723882]}}
result={}
for period,items in rows.items():
 total=items["total"]
 items["尾差" if period=="FY2025" else "其他（差额）"]=[total[i]-sum(v[i] for k,v in items.items() if k!="total") for i in range(2)]
 assert [sum(v[i] for k,v in items.items() if k!="total") for i in range(2)]==total
 result[period]={k:{"revenue_million_CNY":v[0]/1000,"COGS_million_CNY":v[1]/1000,"share_pct":v[0]/total[0]*100,"gross_margin_pct":(v[0]-v[1])/v[0]*100 if k!="尾差" else None} for k,v in items.items()}
result["region"]={}
for period,rev,dom,over in [("FY2025",423701834,294060576,129641258),("2026H1",276916580,189787392,87129188)]:
 assert dom+over==rev
 result["region"][period]={"domestic_share_pct":dom/rev*100,"overseas_share_pct":over/rev*100}
result["sales_quantity"]={"FY2025_combined_power_storage_GWh":661,"FY2024_combined_power_storage_GWh":475,"growth_pct":(661/475-1)*100,"FY2025_combined_revenue_per_Wh_CNY":(316506369+62439820)*1000/(661*1e9),"definition":"combined recognized product revenue/sold energy; mix measure, not contract unit quote, not vehicle installation"}
result["concentration"]={"top5_revenue_million":165061533/1000,"share_pct":165061533/423701834*100,"top1_share_pct":58159202/423701834*100}
Path(__file__).with_name("results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False,indent=2))
