#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_briefing.py — 把 _system/daily_briefing/ 里的每日简报（Markdown）转成网站页面。

输出（website_deploy/public/briefing/）：
  index.html            简报目录：最新一份在最上面，其余按日期倒序
  YYYY-MM-DD.html       每份简报一页，样式与首页一致

调用方：
  - build_site.py 每次构建前先调本脚本（保证首页卡片指向的目录页存在）
  - _system/推送简报.bat 在扫描器生成当天简报后单独跑一次并 git push

只用标准库。Markdown 转换是针对简报实际用到的语法手写的（标题、引用、加粗、
斜体、行内代码、链接、有序/无序列表、表格、分割线、段落），不是通用解析器；
简报格式若新增语法，这里要跟着补。

退出码：0 成功；1 失败（源目录不存在 / 一份都没转出来 / 写文件失败）。
"""
import html
import os
import re
import sys

from site_chrome import head_links, page_open, page_close   # 2026-10-20 统一页头页脚（同目录）

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "_system", "daily_briefing")
OUT = os.path.join(BASE, "website_deploy", "public", "briefing")
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_daily_briefing\.md$")

CSS = """
  /* 简报页专属；颜色走 site.css 变量 */
  .nav{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}
  .nav a,.nav span{font-size:13px;padding:6px 12px;border-radius:8px;background:var(--panel);border:1px solid var(--line)}
  .nav a:hover{border-color:var(--accent);text-decoration:none}
  .nav span{color:var(--muted)}
  .summary-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 20px}
  .summary-row div{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:12px 16px}
  .summary-row .k{font-size:12px;color:var(--muted)} .summary-row .v{font-size:20px;font-weight:700}
  article{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:22px 26px}
  article h1{font-size:24px;margin:0 0 12px}
  article h2{font-size:18px;margin:26px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
  article h2:first-child{margin-top:0}
  article h3{font-size:15px;margin:18px 0 6px}
  article p{margin:8px 0}
  article blockquote{margin:10px 0;padding:10px 14px;background:var(--paper);border-radius:8px;color:var(--ink)}
  article blockquote p{margin:4px 0}
  article code{font-family:Consolas,Menlo,monospace;font-size:13px;background:var(--paper);border:1px solid var(--line);border-radius:4px;padding:0 4px}
  article ul,article ol{padding-left:24px;margin:8px 0}
  article li{margin:4px 0}
  article hr{border:0;border-top:1px solid var(--line);margin:18px 0}
  .tbl{overflow-x:auto;margin:10px 0;border:1px solid var(--line);border-radius:var(--radius)}
  article table{border-collapse:collapse;font-size:13.5px;min-width:100%}
  article th,article td{border-bottom:1px solid var(--line);padding:8px 10px;vertical-align:top;text-align:left}
  article th{background:var(--paper);color:var(--muted);font-size:12px;font-weight:600;white-space:nowrap}
  article tr:last-child td{border-bottom:0}
  .list{display:grid;gap:10px}
  .item{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:13px 16px;text-decoration:none;color:var(--ink);display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .item:hover{border-color:var(--accent);text-decoration:none;color:var(--ink)}
  .item .d{font-weight:700;font-size:15px;white-space:nowrap}
  .item .s{color:var(--muted);font-size:13px;flex:1;min-width:200px}
  .item.latest{border-color:var(--accent)}
  .item.latest .d::after{content:"最新";font-size:11px;color:#fff;background:var(--accent);border-radius:6px;padding:1px 6px;margin-left:8px;vertical-align:middle}
  @media (max-width:720px){.summary-row{grid-template-columns:repeat(2,1fr)}}
"""


# ---------------------------------------------------------------- inline
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def inline(text):
    """行内语法：先把代码段挖出来，避免里面的 * 和 [ 被当成格式。"""
    codes = []

    def keep(m):
        codes.append(html.escape(m.group(1)))
        return "\x00%d\x00" % (len(codes) - 1)

    text = _INLINE_CODE.sub(keep, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: '<a href="%s">%s</a>' % (html.escape(m.group(2), quote=True), m.group(1)), text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: "<code>%s</code>" % codes[int(m.group(1))], text)
    return text


# ---------------------------------------------------------------- block
_H = re.compile(r"^(#{1,6})\s+(.*)$")
_OL = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_TSEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _aligns(sep):
    out = []
    for c in _split_row(sep):
        l, r = c.startswith(":"), c.endswith(":")
        out.append("center" if l and r else "right" if r else "left")
    return out


def md_to_html(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, i, n = [], 0, len(lines)
    para = []

    def flush():
        if para:
            # 简报里相邻的「关联催化剂 / 估值影响 / 对应操作」各占一行、中间没空行，
            # 按标准 Markdown 会并成一段；这里保留换行，和源文件读起来一致
            out.append("<p>%s</p>" % "<br>".join(inline(s.strip()) for s in para))
            para.clear()

    while i < n:
        line = lines[i]
        if not line.strip():
            flush(); i += 1; continue
        m = _H.match(line)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2).strip()), lvl))
            i += 1; continue
        if _HR.match(line):
            flush(); out.append("<hr>"); i += 1; continue
        if line.lstrip().startswith(">"):
            flush()
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i])); i += 1
            out.append("<blockquote>%s</blockquote>" % md_to_html("\n".join(buf)))
            continue
        if "|" in line and i + 1 < n and _TSEP.match(lines[i + 1]):
            flush()
            heads = _split_row(line); al = _aligns(lines[i + 1]); i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i])); i += 1
            def cell(tag, cells):
                tds = []
                for k, c in enumerate(cells):
                    a = al[k] if k < len(al) else "left"
                    style = ' style="text-align:%s"' % a if a != "left" else ""
                    tds.append("<%s%s>%s</%s>" % (tag, style, inline(c), tag))
                return "<tr>" + "".join(tds) + "</tr>"
            out.append('<div class="tbl"><table><thead>%s</thead><tbody>%s</tbody></table></div>'
                       % (cell("th", heads), "".join(cell("td", r) for r in rows)))
            continue
        if _OL.match(line) or _UL.match(line):
            flush()
            ordered = bool(_OL.match(line))
            pat = _OL if ordered else _UL
            items = []
            while i < n:
                m = pat.match(lines[i])
                if m:
                    items.append(m.group(2) if ordered else m.group(1)); i += 1
                elif lines[i].startswith(("   ", "\t")) and items:   # 续行
                    items[-1] += " " + lines[i].strip(); i += 1
                else:
                    break
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(x) for x in items), tag))
            continue
        para.append(line); i += 1
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------- pages
def page(title, body, crumb_html="", summary="", asof=""):
    return f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(summary, quote=True)}">
{head_links()}<style>{CSS}</style>
</head>
<body>
{page_open("briefing", asof, main_class="site-main read")}
    <div class="crumb"><a href="/">汇总</a> › <a href="/briefing/">每日简报</a>{crumb_html}</div>
{body}
{page_close("简报由每日扫描流程自动生成，行情可能非实时。")}</body>
</html>'''


def first_summary(md):
    """目录页摘要：取「市场脉搏」下面第一段引用的前 90 字；取不到就空。"""
    m = re.search(r"^>\s*(.+)$", md, flags=re.M)
    if not m:
        return ""
    s = re.sub(r"\*\*|`", "", m.group(1)).strip()
    return s[:90] + ("…" if len(s) > 90 else "")


def build():
    if not os.path.isdir(SRC):
        print("ERROR: 简报目录不存在:", SRC)
        return 1
    found = []
    for f in os.listdir(SRC):
        m = NAME_RE.match(f)
        if m:
            found.append((m.group(1), f))
    found.sort(reverse=True)
    if not found:
        print("ERROR: 没有找到任何 *_daily_briefing.md")
        return 1

    os.makedirs(OUT, exist_ok=True)
    entries, written = [], 0
    for idx, (date, fname) in enumerate(found):
        with open(os.path.join(SRC, fname), encoding="utf-8") as fh:
            md = fh.read()
        body = md_to_html(md)
        newer = found[idx - 1][0] if idx > 0 else None
        older = found[idx + 1][0] if idx + 1 < len(found) else None
        nav = ('<div class="nav">'
               + ('<a href="%s.html">‹ 前一天 %s</a>' % (older, older) if older else '<a class="dis">‹ 前一天</a>')
               + '<a href="index.html">目录</a>'
               + ('<a href="%s.html">后一天 %s ›</a>' % (newer, newer) if newer else '<a class="dis">后一天 ›</a>')
               + '</div>')
        summary = first_summary(md)
        doc = page("每日简报 %s" % date, nav + "    <article>\n" + body + "\n    </article>",
                   crumb_html=" › %s" % date, summary=summary, asof="简报 %s" % date)
        with open(os.path.join(OUT, date + ".html"), "w", encoding="utf-8") as fh:
            fh.write(doc)
        written += 1
        entries.append((date, summary))

    # 源 md 被 archive_old.py 归档后仍保留站上的历史页：从已有 html 的 <meta description> 读回摘要
    have = {d for d, _ in entries}
    kept = 0
    for f in sorted(os.listdir(OUT), reverse=True):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", f)
        if m and m.group(1) not in have:
            with open(os.path.join(OUT, f), encoding="utf-8") as fh:
                head = fh.read(4000)
            mm = re.search(r'<meta name="description" content="([^"]*)"', head)
            entries.append((m.group(1), html.unescape(mm.group(1)) if mm else ""))
            kept += 1
    entries.sort(reverse=True)

    items = "".join(
        '      <a class="item%s" href="%s.html"><span class="d">%s</span><span class="s">%s</span></a>\n'
        % (" latest" if k == 0 else "", d, d, html.escape(s))
        for k, (d, s) in enumerate(entries))
    index = page("每日简报 · 目录",
                 '    <div class="titlebar"><div class="eyebrow">Daily Briefing</div><h1>投资组合每日简报</h1>'
                 '<div class="lede">共 %d 份 · 最新 %s · 市场脉搏、催化剂、技术信号、动作建议，每日扫描自动生成</div></div>\n'
                 '    <div class="list">\n%s    </div>'
                 % (len(entries), entries[0][0], items), asof="最新 %s" % entries[0][0])
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(index)

    print("简报页面: %d 份已生成 → %s（最新 %s%s）" % (written, OUT, entries[0][0],
          "; 另保留已归档的历史页 %d 份" % kept if kept else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(build())
