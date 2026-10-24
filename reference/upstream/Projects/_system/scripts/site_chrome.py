# -*- coding: utf-8 -*-
"""
site_chrome.py — 网站共用页头 / 页脚 / <head> 片段（2026-10-20 改版）。

四个生成脚本（build_site / build_valuation_comparison / build_briefing，以及 build_site 给
研究总结页、模拟盘页套皮时）都从这里拿同一条顶栏和同一段页脚，样式在 public/site.css。
只用标准库；没有副作用。

用法：
    from site_chrome import head_links, topbar, footer, page_open, page_close
    html = f"<head>...{head_links()}...</head><body>{page_open('home', '现价更新至 2026-10-19 收盘')}...{page_close(FOOT_NOTE)}</body>"

active 取值：home / valuation / paper / briefing / research（research 不高亮任何入口）。
"""
import html as _html

NAV = (
    ("home", "/", "汇总"),
    ("valuation", "/组合三年估值看板.html", "目标价对比"),
    ("paper", "/value-growth.html", "模拟盘"),
    ("briefing", "/briefing/index.html", "每日简报"),
)

DISCLAIMER = "本站为个人投资研究记录，所有内容仅供参考，<b>非投资建议</b>。"


def head_links(fonts=True):
    """favicon + site.css（+ Inter 字体）。放在 <head> 里、页面自己的 <style> 之前。"""
    out = (
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">\n'
        '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">\n'
        '<link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
    )
    if fonts:
        out += (
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">\n'
        )
    out += '<link rel="stylesheet" href="/site.css">\n'
    return out


def topbar(active="", asof=""):
    links = ""
    for key, href, label in NAV:
        cls = ' class="on"' if key == active else ""
        links += f'<a href="{href}"{cls}>{label}</a>'
    asof_html = f'<div class="asof">{_html.escape(asof)}</div>' if asof else ""
    return (
        '<header class="site-top"><div class="in">'
        '<a class="logo" href="/"><img src="/logo.svg" alt="Flyfish"></a>'
        f'<nav aria-label="站点导航">{links}</nav>{asof_html}'
        '</div></header>\n'
    )


def footer(note=""):
    extra = f" {note}" if note else ""
    return f'<footer class="site-foot"><div class="in">{DISCLAIMER}{extra}</div></footer>\n'


def page_open(active="", asof="", main_class="site-main"):
    """<body> 后紧接：外层容器 + 顶栏 + <main>。"""
    return f'<div class="site-page">\n{topbar(active, asof)}<main class="{main_class}">\n'


def page_close(note=""):
    """</body> 前：关 <main> + 页脚 + 关容器。"""
    return f'</main>\n{footer(note)}</div>\n'
