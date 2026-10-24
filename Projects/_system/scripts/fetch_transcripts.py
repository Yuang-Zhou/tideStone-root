#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_transcripts.py v0.1 —— 电话会纪要预取（美股 / Motley Fool 免费全文）

用法：
  python fetch_transcripts.py {TICKER} --out "{公司目录}/{TICKER} Wiki/raw/transcripts" [--limit 8] [--probe]

发现机制：fool.com/quote/{exchange}/{ticker}/ 页面内嵌 "transcripts":[...] JSON，
含 path / publish_at / headline，覆盖该公司全部已发布纪要；exchange 依次试 nasdaq / nyse。
正文：<div class="article-body transcript-content"> 内的 h2 / p，转成 Markdown。

只用标准库。失败不中断，逐条记进 MANIFEST.md。一份都没拿到返回退出码 1。
边界：仅美股；Fool 通常在电话会后 0–3 天发布，刚开完的那场可能还没有——MANIFEST 会提示。
"""
import argparse, html, json, os, re, sys, time, urllib.request, urllib.error
from datetime import date

VERSION = "0.1"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
MIN_BYTES = 5000  # 小于此值视为拦截页/空页


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def discover(ticker):
    """返回 [(path, publish_at, headline)]，按 publish_at 倒序。"""
    t = ticker.lower()
    last_err = None
    for ex in ("nasdaq", "nyse"):
        url = f"https://www.fool.com/quote/{ex}/{t}/"
        try:
            page = get(url)
        except urllib.error.HTTPError as e:
            last_err = f"{url} HTTP {e.code}"
            continue
        except Exception as e:
            last_err = f"{url} {e}"
            continue
        # 页面里 JSON 被转义成 \"key\":\"value\"，直接正则抠
        items = re.findall(
            r'\\"publish_at\\":\\"([^"\\]+)\\"[^{}]*?\\"path\\":\\"(/earnings/call-transcripts/[^"\\]+)\\"[^{}]*?\\"headline\\":\\"([^"\\]*)\\"',
            page)
        seen, out = set(), []
        for pub, path, head in items:
            if f"-{t}-" not in path or path in seen:
                continue
            seen.add(path)
            out.append((path, pub[:10], html.unescape(head)))
        if out:
            out.sort(key=lambda x: x[1], reverse=True)
            return out, url
        last_err = f"{url} 页面可达但未解析到 transcripts 数组"
    raise RuntimeError(last_err or "unknown")


def parse_fq(path):
    """从 slug 抠财季：...-q2-2026-... → (2026, 2)。抠不到返回 None。"""
    m = re.search(r"-q([1-4])-(20\d\d)-", path)
    return (int(m.group(2)), int(m.group(1))) if m else None


def extract_body(page):
    i = page.find('class="article-body transcript-content"')
    if i < 0:
        return None
    seg = page[i:]
    # 截到正文容器后的推广盒或页脚
    for stop in ('class="article-body-promobox', 'id="article-footer', '<footer'):
        j = seg.find(stop)
        if j > 0:
            seg = seg[:j]
    out = []
    for tag, inner in re.findall(r"<(h2|h3|p|li)[^>]*>(.*?)</\1>", seg, flags=re.S):
        txt = re.sub(r"<br\s*/?>", "\n", inner)
        # 保留加粗（讲话人名 / 要点标题）
        txt = re.sub(r"<(?:strong|b)>(.*?)</(?:strong|b)>", r"**\1**", txt, flags=re.S)
        txt = re.sub(r"<[^>]+>", "", txt)
        txt = html.unescape(txt).strip()
        txt = re.sub(r"[ \t]+", " ", txt)
        if not txt or txt.startswith("Image source:") or "Need a quote from a Motley Fool" in txt:
            continue
        if tag in ("h2", "h3"):
            out.append("## " + txt)
        elif tag == "li":
            out.append("- " + txt)
        else:
            out.append(txt)
    return "\n\n".join(out) if out else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=8, help="最多取几份（默认 8 = 两年）")
    ap.add_argument("--probe", action="store_true", help="只列清单不下载")
    a = ap.parse_args()
    T = a.ticker.upper()
    if "." in T:
        print(f"[fetch_transcripts v{VERSION}] {T} 非美股裸代码，Fool 线只覆盖美股，跳过")
        return 2

    print(f"[fetch_transcripts v{VERSION}] {T} 美股 → Motley Fool")
    try:
        items, src = discover(T)
    except Exception as e:
        print(f"  FAIL 发现阶段：{e}")
        return 1
    print(f"  发现 {len(items)} 份（来源 {src}），取最近 {min(a.limit, len(items))} 份")
    items = items[: a.limit]
    if a.probe:
        for p, d, h in items:
            print(f"  {d}  {h}  https://www.fool.com{p}")
        return 0

    outdir = os.path.join(a.out, "FOOL")
    os.makedirs(outdir, exist_ok=True)
    ok, fail = [], []
    for path, pub, head in items:
        url = "https://www.fool.com" + path
        fq = parse_fq(path)
        tag = f"FY{fq[0]}Q{fq[1]}" if fq else "FYxxQx"
        fname = f"{T}_{tag}_{pub}.md"
        dst = os.path.join(outdir, fname)
        if os.path.exists(dst) and os.path.getsize(dst) > MIN_BYTES:
            print(f"  SKIP 已存在 {fname}")
            ok.append((fname, pub, head, url, "已存在"))
            continue
        try:
            page = get(url)
            if len(page) < MIN_BYTES:
                raise RuntimeError(f"页面仅 {len(page)} 字节，疑为拦截页")
            body = extract_body(page)
            if not body or len(body) < 3000:
                raise RuntimeError("未解析到正文或正文过短（页面结构可能变了）")
            md = (f"# {head}\n\n"
                  f"- 来源：Motley Fool（免费全文）  {url}\n"
                  f"- 发布日期：{pub}\n"
                  f"- 抓取日期：{date.today().isoformat()}  fetch_transcripts v{VERSION}\n"
                  f"- 用途：仅供个人研究（Wiki/raw），**不得进入 website_deploy 对外发布**\n\n---\n\n{body}\n")
            with open(dst, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"  OK   {fname} ({len(md)//1000} KB)")
            ok.append((fname, pub, head, url, "新下载"))
        except Exception as e:
            print(f"  FAIL {fname}: {e}")
            fail.append((fname, url, str(e)))
        time.sleep(1.0)

    # MANIFEST
    os.makedirs(a.out, exist_ok=True)
    mp = os.path.join(a.out, "MANIFEST.md")
    lines = [f"# {T} 电话会纪要清单", "",
             f"**生成：** {date.today().isoformat()}  fetch_transcripts v{VERSION}  发现 {len(items)} 份，成功 {len(ok)}，失败 {len(fail)}",
             "", "| 文件 | 发布日 | 标题 | 来源 | 状态 |", "|---|---|---|---|---|"]
    for fname, pub, head, url, st in ok:
        lines.append(f"| FOOL/{fname} | {pub} | {head} | [Fool]({url}) | {st} |")
    if fail:
        lines += ["", "## 自动预取失败项", ""] + [f"- {f} — {u} — {e}" for f, u, e in fail]
    lines += ["", "## 说明", "",
              "- Fool 通常在电话会后 0–3 天发布；**最近一场若不在上表，过几天重跑本脚本即可**（已存在的文件会跳过）。",
              "- Fool 转录为机器+人工校对，数字以公司 8-K / 10-Q 为准；引用时标注来源。",
              "- 需人工补充：Seeking Alpha / 万得纪要（有账号但无公开接口）、Investor Day、管理层访谈——拖进本目录即可。"]
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  清单：{mp}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

