#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_briefing.py -- one-shot check of the daily scanner's outputs.

Usage: python3 _system/scripts/validate_briefing.py 2026-10-09 [--no-dashboard]
Exit code 0 = all pass; 1 = at least one FATAL. Prints one line per check and a
final line "BRIEFING_VALIDATION {json}".

Run it BEFORE publishing the dashboard. It checks local files only: it cannot prove the
remote dashboard was updated -- confirm that from the publish tool's own result.
"""
import json, os, re, sys, glob

from tidestone_paths import PROJECTS_ROOT
ROOT = str(PROJECTS_ROOT)
os.chdir(ROOT)
D = sys.argv[1]
fatal, warn = [], []


def chk(ok, msg, level="FATAL"):
    print(("OK    " if ok else level + " ") + msg)
    if not ok:
        (fatal if level == "FATAL" else warn).append(msg)


comp = json.load(open("_system/companies.json", encoding="utf-8"))["companies"]
vreg = json.load(open("_system/valuation_registry.json", encoding="utf-8"))["companies"]
all_comp = comp
no_reg = [t for t in all_comp if t not in vreg or not vreg[t].get("status")]
skipped = [t for t in all_comp if t in vreg and vreg[t].get("status") and vreg[t]["status"] != "active"]
comp = {t: v for t, v in all_comp.items() if t not in skipped}   # today's scan list
print("SCAN LIST %d of %d; skipped (not active): %s; missing from valuation registry: %s" % (len(comp), len(all_comp), skipped, no_reg))
md_path = "_system/daily_briefing/%s_daily_briefing.md" % D
js_path = "_system/daily_briefing/briefing_data_%s.json" % D

# ---- markdown
s = open(md_path, encoding="utf-8").read() if os.path.exists(md_path) else ""
chk(bool(s), "markdown exists")
if s:
    order = ["## 一、", "## 二、催化剂动态", "## 三、", "## 四、", "## 五、", "## 六、"]
    pos = [s.find(h) for h in order]
    chk(all(p >= 0 for p in pos), "sections 1-6 all present %s" % pos)
    chk(pos == sorted(pos), "sections in order")
    a, b, c = s.count("**关联催化剂：**"), s.count("**估值影响：**"), s.count("**对应操作：**")
    no_event = "今日无 高/中 重要性事件" in s
    chk((a == b == c and a >= 1) or (no_event and a == b == c == 0), "event cards complete (%d/%d/%d)" % (a, b, c))
    chk(len(s.encode("utf-8")) <= 51200, "markdown size %d <= 51200" % len(s.encode("utf-8")))
    chk("…" not in s, "no ellipsis truncation mark")
    chk("更正" not in s, "no correction narrative")
    cn = {t: v["name_cn"] for t, v in comp.items() if t[0].isdigit()}
    bad = [t for t, n in cn.items()
           if re.search(r"(?<![\w.])" + re.escape(t) + r"(?! " + re.escape(n) + r")(?![\w])", s)]
    chk(not bad, "numeric tickers carry Chinese name %s" % bad)

# ---- json
j = None
try:
    j = json.load(open(js_path, encoding="utf-8"))
    chk(True, "json loads")
except Exception as e:
    chk(False, "json loads: %s" % e)
if j:
    cs = j.get("companies", [])
    tk = [c["ticker"] for c in cs]
    chk(sorted(tk) == sorted(comp.keys()), "companies[] matches today's scan list (%d vs %d)" % (len(tk), len(comp)))
    sl = (j.get("data_status") or {}).get("scan_list") or {}
    chk(sorted(sl.get("skipped_inactive") or []) == sorted(skipped) and sorted(sl.get("missing_in_valuation_registry") or []) == sorted(no_reg),
        "data_status.scan_list records skipped %s and registry gaps %s" % (skipped, no_reg))
    chk(all(c.get("name_cn") for c in cs), "every company has name_cn")
    chk(os.path.getsize(js_path) <= 300 * 1024, "json size %d KB <= 300" % (os.path.getsize(js_path) // 1024))
    zones = {"买入区", "持有区", "减持区", "卖出区", "未标定"}
    badz = [c["ticker"] for c in cs if (c.get("snapshot") or {}).get("valuation_zone") not in zones]
    chk(not badz, "valuation_zone is one of the 5 standard values %s" % badz[:8])
    nullp = [c["ticker"] for c in cs if (c.get("snapshot") or {}).get("price") is None]
    chk(not nullp, "no null price %s" % nullp, "WARN ")
    vr = j.get("valuation_review")
    chk(isinstance(vr, list), "valuation_review[] present")
    if isinstance(vr, list):
        badv = [x.get("ticker") for x in vr if x.get("verdict") not in ("now", "wait", "stale") or not x.get("reason")
                or (x.get("verdict") == "wait" and not x.get("wait_for"))]
        chk(not badv, "valuation_review entries well-formed %s" % badv)
    ss = j.get("signal_stats") or {}
    stray = [t for k in ss for t in ss[k] if t not in tk]
    chk(not stray, "signal_stats tickers all in companies[] %s" % stray)
    ds = j.get("data_status") or {}
    pe = [x.get("ticker") for x in ds.get("path_errors") or []]
    deferred = (ds.get("escalation_policy") or {}).get("deferred") or []
    miss = [c["ticker"] for c in cs if (c.get("technical") or {}).get("escalate_full_ta")
            and not (c.get("links") or {}).get("ta_report") and c["ticker"] not in pe and c["ticker"] not in deferred]
    chk(not miss, "escalated tickers have TA report / path_error / deferred %s" % miss)
    for k in ("publish_health", "news_coverage", "catalyst_write_log"):
        chk(k in ds, "data_status.%s present" % k)
    # catalyst files
    stale, noanchor = [], []
    log = {x["ticker"]: x for x in ds.get("catalyst_write_log") or []}
    for t, v in comp.items():
        f = os.path.join(v["folder"], "催化剂跟踪", "催化剂跟踪_自动化.md")
        if not os.path.exists(f):
            if t not in pe: stale.append(t)
            continue
        txt = open(f, encoding="utf-8").read()
        if not re.search(r"最后自动扫描.*" + re.escape(D), txt): stale.append(t)
        if (log.get(t) or {}).get("events_appended") and ("### " + D) not in txt: noanchor.append(t)
    chk(not stale, "every catalyst file stamped today %s" % stale)
    chk(not noanchor, "appended events have today's anchor %s" % noanchor)
    # event-by-event sync: events[] is the single list of 高/中 events
    ev = j.get("events")
    chk(isinstance(ev, list), "events[] present")
    if isinstance(ev, list):
        sec2 = s[s.find("## 二、"):s.find("## 三、")] if s else ""
        ids = [e.get("id") for e in ev]
        chk(len(ids) == len(set(ids)) and all(ids), "event ids unique")
        bad_shape, nocard, nodrop, nofile, dupfile, bad_now = [], [], [], [], [], []
        for e in ev:
            t, title = e.get("ticker"), (e.get("title") or "").strip()
            if t not in comp or e.get("level") not in ("高", "中") or not title or not isinstance(e.get("verified"), bool) \
                    or not isinstance(e.get("in_briefing"), bool):
                bad_shape.append(e.get("id")); continue
            lab = (t + " " + comp[t]["name_cn"]) if t[0].isdigit() else t
            head = "### " + lab + " — " + title
            if e["in_briefing"]:
                if sec2.count(head) != 1: nocard.append(e["id"])
            else:
                if "未进表" not in sec2 or title not in sec2[sec2.find("未进表"):]: nodrop.append(e["id"])
            f = os.path.join(comp[t]["folder"], "催化剂跟踪", "催化剂跟踪_自动化.md")
            txt = open(f, encoding="utf-8").read() if os.path.exists(f) else ""
            a0 = txt.rfind("\n### " + D)
            block = txt[a0:] if a0 >= 0 else ""
            n = block.count("#### " + title)
            if e["verified"] and t not in pe and n < 1: nofile.append(e["id"])
            if n > 1: dupfile.append(e["id"])
        chk(not bad_shape, "events well-formed %s" % bad_shape)
        chk(not nocard, "each in-briefing event has exactly one card with its title %s" % nocard)
        chk(not nodrop, "each event dropped for size is listed under 未进表 %s" % nodrop)
        chk(not nofile, "each verified event is in its company catalyst file %s" % nofile)
        chk(not dupfile, "no event appended twice in a catalyst file %s" % dupfile)
        ncards = len(re.findall(r"^### .+ — ", sec2, re.M))
        chk(ncards == sum(1 for e in ev if e.get("in_briefing")), "card count %d equals in-briefing events" % ncards)
        unv = {e["ticker"] for e in ev if e.get("verified") is False}
        ver = {e["ticker"] for e in ev if e.get("verified") is True}
        bad_now = [x["ticker"] for x in (j.get("valuation_review") or []) if x.get("verdict") == "now"
                   and x["ticker"] in unv and x["ticker"] not in ver and set(x.get("criteria") or []) <= {1, 2, 3}]
        chk(not bad_now, "no `now` verdict resting only on unverified events %s" % bad_now)
        # bullets and events agree per company
        pat = re.compile(r"^(高|中)(（待确认）)?：")
        mism = [c["ticker"] for c in cs
                if sum(1 for b in c.get("news_bullets") or [] if pat.match(str(b))) != sum(1 for e in ev if e.get("ticker") == c["ticker"])]
        chk(not mism, "高/中 bullets match events[] per company %s" % mism)
    dup = []
    for t, v in comp.items():
        f = os.path.join(v["folder"], "催化剂跟踪", "催化剂跟踪_自动化.md")
        if os.path.exists(f) and open(f, encoding="utf-8").read().count("\n### " + D + "\n") > 1: dup.append(t)
    chk(not dup, "no duplicated date block in catalyst files %s" % dup)
    chk(os.path.exists("_system/scan_log/%s.md" % D), "scan_log written")
    reg = open("_system/portfolio_registry.md", encoding="utf-8").read()
    m = re.search(r"^\*\*最后更新：\*\*.*$", reg, re.M)
    chk(bool(m) and D in m.group(0) and len(m.group(0)) <= 140, "registry last-updated line is today, one line")

# ---- dashboard
if "--no-dashboard" not in sys.argv:
    for f in ("dashboard_rendered.html", "dashboard_artifact.html"):
        p = "_system/daily_briefing/" + f
        if not os.path.exists(p):
            chk(False, f + " exists"); continue
        b = open(p, "rb").read(); t = b.decode("utf-8", "replace")
        chk(b"\x00" not in b and "__WINDOW_DATA__" not in t and ('"date": "%s"' % D) in t, f + " has today, no NUL, no placeholder")
        if f == "dashboard_rendered.html":
            chk(t.rstrip().endswith("</html>"), f + " ends with </html>")
        else:
            chk(not re.search(r"<!doctype|<html|<body", t, re.I) and t.rstrip().endswith("</script>"), f + " has no skeleton tags")

print("BRIEFING_VALIDATION " + json.dumps({"date": D, "fatal": fatal, "warn": warn}, ensure_ascii=False))
sys.exit(1 if fatal else 0)

