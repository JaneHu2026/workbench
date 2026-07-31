#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
news_fetch.py — 新闻页数据抓取（08:01 cron 调用，输出 workbench/news.json）
数据源（全部为权威官方媒体，直连解析）：
  国内头条：央视网 www.cctv.com 首页
  国际头条：人民网国际频道 world.people.com.cn
  国内要闻：新华网 www.news.cn 首页
成功时无输出（静默）；全部失败时非零退出（触发 cron 告警）。
"""
import html as html_mod
import json, os, re, sys, urllib.request
from datetime import datetime

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'news.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

def get(url, timeout=15):
    """读取页面并按实际 charset 解码（央视等站点是 GB2312，按 UTF-8 解会乱码）"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get('Content-Type', '') or ''
    enc = 'utf-8'
    m = re.search(r'charset=([\w-]+)', ctype, re.I)
    if m:
        enc = m.group(1)
    else:
        head = raw[:2048].decode('ascii', 'ignore')
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        if m:
            enc = m.group(1)
    if enc.lower() in ('gb2312', 'gbk'):
        enc = 'gb18030'
    try:
        return raw.decode(enc, 'ignore')
    except LookupError:
        return raw.decode('utf-8', 'ignore')

def parse_links(html, patterns, limit=12):
    """patterns: [(href 正则, 标题最小长度)]，返回去重后的 [(title, url)]"""
    items = []
    seen = set()
    for href_pat, min_len in patterns:
        for m in re.finditer(href_pat, html):
            url, title = m.group(1), m.group(2).strip()
            title = re.sub(r'\s+', ' ', title)
            if len(title) < min_len or title in seen:
                continue
            seen.add(title)
            items.append((title, url))
            if len(items) >= limit:
                return items
    return items

def article_desc(url):
    """抓文章页，取 meta description 或正文首段作为简要内容"""
    try:
        h = get(url, timeout=8)
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{20,200})', h)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']{20,200})["\'][^>]+name=["\']description["\']', h)
        if m:
            d = html_mod.unescape(re.sub(r'\s+', ' ', m.group(1))).strip()
            if len(d) >= 20:
                return d[:160] + ('…' if len(d) > 160 else '')
        # 正文首段兜底
        ps = re.findall(r'<p[^>]*>([^<]{30,200})</p>', h)
        for p in ps:
            d = html_mod.unescape(re.sub(r'\s+', ' ', p)).strip()
            if len(d) >= 30:
                return d[:160] + ('…' if len(d) > 160 else '')
    except Exception:
        pass
    return ''

def build_group(label, items, cat):
    return {'label': label, 'cat': cat, 'ok': bool(items),
            'items': [{'title': t, 'link': u, 'pubDate': '', 'source': '央视网', 'desc': ''} for t, u in items]}

def with_descs(group, limit=8):
    """为组内前 limit 条抓取简要内容"""
    out = []
    for it in group['items'][:limit]:
        if not it.get('desc'):
            it['desc'] = article_desc(it['link'])
        out.append(it)
    group['items'] = out
    return group

def cctv_group():
    h = get('https://www.cctv.com/')
    items = parse_links(h, [
        (r'<a[^>]*href="(https://(?:news|tv)\.cctv\.com/\d{4}/\d{2}/\d{2}/[^"]+)"[^>]*>([^<]{8,80})</a>', 10),
    ])
    g = build_group('国内头条 · 央视新闻', items, 'gn')
    return with_descs(g)

def people_world_group():
    h = get('https://world.people.com.cn/')
    items = parse_links(h, [
        (r'<a[^>]*href="(https?://world\.people\.com\.cn/n1/\d{4}/[^"]+)"[^>]*>([^<]{8,60})</a>', 10),
    ])
    g = build_group('国际头条 · 人民网', items, 'gj')
    g['items'] = [{'title': t, 'link': u, 'pubDate': '', 'source': '人民网', 'desc': ''} for t, u in items]
    return with_descs(g)

def xinhua_group():
    h = get('https://www.news.cn/')
    items = parse_links(h, [
        (r'<a[^>]*href="(/(?:[a-z]+/)?\d{6,8}/[^"]+\.html)"[^>]*>([^<]{10,60})</a>', 12),
    ])
    out = []
    for t, u in items:
        link = 'https://www.news.cn' + u if u.startswith('/') else u
        out.append({'title': t, 'link': link, 'pubDate': '', 'source': '新华网', 'desc': ''})
    g = {'label': '国内要闻 · 新华网', 'cat': 'gn', 'ok': bool(out), 'items': out}
    return with_descs(g)

def main():
    groups = []
    errors = []
    for name, fn in [('央视', cctv_group), ('人民网国际', people_world_group), ('新华', xinhua_group)]:
        try:
            groups.append(fn())
        except Exception as e:
            groups.append({'label': name, 'ok': False, 'items': []})
            errors.append('%s: %s' % (name, e))

    now = datetime.now()
    payload = {
        'fetchedAt': now.strftime('%H:%M'),
        'fetchedDate': now.strftime('%Y-%m-%d'),
        'source': 'server',
        'items': groups,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    if all(not g['ok'] for g in groups):
        print('NEWS_FETCH_FAIL: %s' % '; '.join(errors))
        sys.exit(1)
    if errors:
        print('NEWS_FETCH_PARTIAL: %s' % '; '.join(errors))

if __name__ == '__main__':
    main()
