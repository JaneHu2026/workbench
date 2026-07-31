#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
study_fetch.py — 学习页数据抓取（08:00 cron 调用，输出 workbench/study.json）
数据源：
  1. 抖音 AI·科技热点   — 抖音热榜 API（免登录），AI/科技/学习关键词过滤
  2. 小红书 热门视频     — explore 页 SSR + 详情页正文（主要内容）
  3. 即梦 AI 灵感广场    — 即梦首页 SSR（生成提示词=主要内容）
  4. YouTube AI 学习     — 频道 RSS（rss2json 中转）+ 详情页描述（jina reader 中转）
  5. TikTok AI 热点      — 推荐流 API（经 allorigins，国内网络可能不可达）
成功时无输出（静默）；全部失败时非零退出（触发 cron 告警）。
"""
import json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'study.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
AI_KEYS = ['ai', '人工智能', '机器', '智能', '模型', 'gpt', '大模型', '数字人', '芯片', '科技', '手机', '电脑',
           '互联网', '软件', '机器人', '汽车', '新能源', '数码', '苹果', '华为', '小米', 'openai', '算法',
           '自动驾驶', '无人机', '算力', '学习', '教程', '教学', '课程', '干货', '编程', '代码', '开发']
# 抖音热榜过滤用（强 AI 关键词，宁缺毋滥，避免"苹果香"歌曲等误伤）
AI_TECH_KEYS = ['ai', '人工智能', '机器', '智能', '模型', 'gpt', '大模型', 'llm', '数字人', '芯片',
                'openai', '算法', '自动驾驶', '机器人', '算力', 'ai眼镜', 'agent', '智能体', '大语言模型', '深度学习']

def get(url, timeout=20, referer=None, extra=None):
    headers = dict(UA)
    if referer:
        headers['Referer'] = referer
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')

def rss2json(feed, limit=10, retries=2):
    """rss2json 中转（连续请求会被限流，需重试+间隔）"""
    api = 'https://api.rss2json.com/v1/api.json?rss_url=' + urllib.parse.quote(feed, safe='')
    for _ in range(retries):
        try:
            j = json.loads(get(api, timeout=20))
            if j.get('status') == 'ok' and j.get('items'):
                return j['items'][:limit]
        except Exception:
            pass
        time.sleep(3)
    return []

def extract_script_json(html, var_name):
    m = re.search(r'window\.' + re.escape(var_name) + r'\s*=\s*', html)
    if not m:
        return None
    start = html.find('{', m.end())
    depth = 0; in_str = False; esc = False
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i + 1])
                    except Exception:
                        return None
    return None

def extract_initial_state(html):
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace('undefined', 'null'))
    except Exception:
        return None

def rel_pub(pub):
    """pubDate -> 相对时间文案"""
    try:
        t = datetime.fromisoformat(pub.replace('Z', '+00:00').replace(' ', 'T'))
        now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
        diff = (now - t).total_seconds()
        if diff < 3600: return '%d分钟前' % max(1, int(diff / 60))
        if diff < 86400: return '%d小时前' % int(diff / 3600)
        if diff < 7 * 86400: return '%d天前' % int(diff / 86400)
        return t.strftime('%m月%d日')
    except Exception:
        return ''

def clean_desc(d, limit=180):
    d = re.sub(r'[…]{2,}\s*more\s*$', '', d.strip())
    d = re.sub(r'\.{2,}\s*more\s*$', '', d.strip())
    d = re.sub(r'\s+', ' ', d).strip()
    return d[:limit] + ('…' if len(d) > limit else '')

def zh_translate(text, limit=120):
    """英文简介 → 中文简要（Google 免费接口，失败回退 MyMemory；已是中文则原样返回）"""
    if not text:
        return ''
    ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(1, len(text))
    if ascii_ratio < 0.6:
        return text  # 已是中文为主
    src = text[:limit]
    # Google translate gtx（免 key）
    try:
        q = urllib.parse.quote(src)
        j = json.loads(get('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=' + q, timeout=10))
        parts = [seg[0] for seg in (j[0] or []) if seg and seg[0]]
        if parts:
            return ''.join(parts).strip()[:200]
    except Exception:
        pass
    # MyMemory 兜底
    try:
        q = urllib.parse.quote(src)
        j = json.loads(get('https://api.mymemory.translated.net/get?q=' + q + '&langpair=en|zh-CN', timeout=10))
        t = (j.get('responseData') or {}).get('translatedText') or ''
        if t:
            return t.strip()[:200]
    except Exception:
        pass
    return text

# ---------- 抖音 ----------
def douyin_group():
    url = 'https://www.douyin.com/aweme/v1/web/hot/search/list/?detail_list=1'
    j = json.loads(get(url, referer='https://www.douyin.com/hot'))
    wl = (j.get('data') or {}).get('word_list') or []
    items = []
    for w in wl:
        word = w.get('word') or ''
        if not word or not any(k in word.lower() for k in AI_TECH_KEYS):
            continue
        cover = ''
        ul = ((w.get('word_cover') or {}).get('url_list')) or []
        if ul:
            cover = ul[0]
        items.append({
            'title': word,
            'link': 'https://www.douyin.com/search/' + urllib.parse.quote(word) + '?type=general',
            'cover': cover, 'source': '抖音热榜', 'author': '',
            'meta': '🔥 %d' % (w.get('hot_value') or 0),
            'desc': '热门话题「%s」：相关视频 %d 条 · 讨论 %d 条。点击前往抖音查看话题视频。' % (
                word, w.get('video_count') or 0, w.get('discuss_video_count') or 0),
        })
    return {'label': '抖音 AI · 科技热点', 'ok': bool(items), 'items': items[:10]}

# ---------- 小红书 ----------
def xhs_cover_url(note):
    c = note.get('cover') or {}
    if c.get('url'):
        return c['url']
    for il in (c.get('infoList') or []):
        if il.get('url'):
            return il['url']
    return ''

def xhs_group():
    html = get('https://www.xiaohongshu.com/explore')
    st = extract_initial_state(html)
    if not st:
        return {'label': '小红书 热门视频', 'ok': False, 'items': []}
    feeds = (st.get('feed') or {}).get('feeds') or []
    videos = []
    for f in feeds:
        note = f.get('noteCard') or {}
        if note.get('type') != 'video':
            continue
        nid = f.get('id')
        if not nid:
            continue
        videos.append({
            'id': nid, 'token': f.get('xsecToken') or '',
            'title': note.get('displayTitle') or '',
            'cover': xhs_cover_url(note),
            'author': (note.get('user') or {}).get('nickName') or '',
            'likes': (note.get('interactInfo') or {}).get('likedCount') or 0,
        })
    # 只保留 AI/学习相关视频（宁缺毋滥），命中不足则不显示该组
    ai_vids = [v for v in videos if any(k in v['title'].lower() for k in AI_KEYS)]
    picked = ai_vids
    if not picked:
        return {'label': '小红书 AI 学习', 'ok': False, 'items': []}
    items = []
    for v in picked[:6]:
        desc = ''
        try:
            link = 'https://www.xiaohongshu.com/explore/%s?xsec_token=%s&xsec_source=pc_feed' % (
                v['id'], urllib.parse.quote(v['token'] or ''))
            page = get(link, referer='https://www.xiaohongshu.com/')
            st2 = extract_initial_state(page)
            if st2:
                ndm = (st2.get('note') or {}).get('noteDetailMap') or {}
                for k, val in ndm.items():
                    desc = (val.get('note') or {}).get('desc') or ''
                    if desc:
                        break
        except Exception:
            pass
        time.sleep(0.4)
        items.append({
            'title': v['title'] or '小红书视频',
            'link': 'https://www.xiaohongshu.com/explore/%s?xsec_token=%s&xsec_source=pc_feed' % (
                v['id'], urllib.parse.quote(v['token'] or '')),
            'cover': v['cover'], 'source': '小红书', 'author': v['author'],
            'meta': '❤️ %s' % v['likes'] if v['likes'] else '',
            'desc': clean_desc(desc, 220) or '（未获取到正文）',
        })
    return {'label': '小红书 AI 学习', 'ok': bool(items), 'items': items}

# ---------- 即梦 ----------
def extract_prompt(item):
    for key in ['aigc_image_params', 'aigc_flow']:
        v = item.get(key)
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except Exception:
                continue
        if isinstance(v, dict):
            for k2 in ['text2image_params', 'text2video_params']:
                p = (v.get(k2) or {}).get('prompt')
                if p:
                    return p
    s = json.dumps(item, ensure_ascii=False)
    m = re.search(r'"prompt"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
    if m:
        try:
            return json.loads('"' + m.group(1) + '"')
        except Exception:
            return m.group(1)
    return ''

def jimeng_group():
    html = get('https://jimeng.jianying.com/ai-portal/tools/video', referer='https://jimeng.jianying.com/')
    j = extract_script_json(html, '__get_explore_result')
    if not j:
        return {'label': '即梦 AI 灵感广场', 'ok': False, 'items': []}
    item_list = ((j.get('data') or {}).get('item_list')) or []
    items = []
    for it in item_list[:10]:
        ca = it.get('common_attr') or {}
        w_id = ca.get('id') or ''
        prompt = clean_desc(extract_prompt(it), 160)
        stat = it.get('statistic') or {}
        auth = it.get('author') or {}
        items.append({
            'title': ca.get('title') or 'AI 作品',
            'link': 'https://jimeng.jianying.com/ai-tool/ai-work-detail/%s' % w_id if w_id else 'https://jimeng.jianying.com/',
            'cover': ca.get('cover_url') or '', 'source': '即梦AI',
            'author': auth.get('name') or '',
            'meta': '⭐ %d 收藏' % (stat.get('favorite_num') or 0),
            'desc': '【生成提示词】' + (prompt or '（无提示词）'),
        })
    return {'label': '即梦 AI 灵感广场', 'ok': bool(items), 'items': items}

# ---------- YouTube（直连 RSS，带 consent cookie；均为 AI 模型/Agent/学习/应用方向） ----------
YT_CHANNELS = [
    ('Andrej Karpathy', 'UCXUPKJO5MZQN11PqgIvyuvQ'),          # LLM 深度学习教学
    ('3Blue1Brown', 'UCYO_jab_esuFRV4b17AJtAw'),              # 深度学习可视化
    ('Two Minute Papers', 'UCbfYPyITQ-7l4upoX8nvctg'),        # AI 论文/新模型解读
    ('跟李沐学AI', 'UCDz_bzi6t_iY2GIJTHnxH6Q'),               # 中文 AI 深度学习教学
    ('AI Explained', 'UC_HhOkzorAO4_rRsTiiHZ_w'),             # 新模型/Agent 资讯解读
    ('1littlecoder', 'UCpV_X0VrL8-jg3t6wYGS-1g'),             # Agent/本地模型实战教程
    ('sentdex', 'UCfzlCWGWYyIQ0aLC5w48gBQ'),                  # Python AI 编程实战
]
YT_NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
         'media': 'http://search.yahoo.com/mrss/'}

def yt_feed_direct(cid, limit=3):
    url = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + cid
    txt = get(url, timeout=15, extra={'Cookie': 'CONSENT=YES+cb.20210328-17-p0.en+FX+417'})
    root = ET.fromstring(txt)
    out = []
    for e in root.findall('a:entry', YT_NS)[:limit]:
        vid = (e.findtext('yt:videoId', default='', namespaces=YT_NS) or '').strip()
        if not vid:
            continue
        th = e.find('media:group/media:thumbnail', YT_NS)
        cover = th.get('url') or '' if th is not None else ''
        out.append({
            'title': e.findtext('a:title', default='', namespaces=YT_NS) or '',
            'link': 'https://www.youtube.com/watch?v=' + vid,
            'cover': cover,
            'author': e.findtext('a:author/a:name', default='', namespaces=YT_NS) or '',
            'meta': rel_pub(e.findtext('a:published', default='', namespaces=YT_NS) or ''),
            'pub': e.findtext('a:published', default='', namespaces=YT_NS) or '',
            'desc': clean_desc(e.findtext('media:group/media:description', default='', namespaces=YT_NS) or '', 200),
        })
    return out

def youtube_group():
    all_items = []
    for name, cid in YT_CHANNELS:
        try:
            items = yt_feed_direct(cid)
        except Exception:
            items = rss2json('https://www.youtube.com/feeds/videos.xml?channel_id=' + cid, limit=4)
        for it in items:
            if not it.get('author'):
                it['author'] = name
            if not it.get('meta'):
                it['meta'] = it.get('pub', '')[:10]
            all_items.append(it)
        time.sleep(1)
    all_items.sort(key=lambda x: x.get('pub', ''), reverse=True)
    out = all_items[:8]
    for it in out:
        desc = re.sub(r'https?://\S+', '', it.get('desc', ''))  # 去掉链接/推广行
        desc = re.sub(r'\s+', ' ', desc).strip(' -·–|❤️ ')
        it['desc'] = zh_translate(desc)
        time.sleep(0.5)  # 错峰避免翻译接口限流
    return {'label': 'YouTube AI 学习', 'ok': bool(out), 'items': out}

# ---------- 主流程 ----------
def main():
    groups = []
    errors = []
    for name, fn in [('抖音', douyin_group), ('小红书', xhs_group), ('YouTube', youtube_group)]:
        try:
            g = fn()
            if g.get('note'):
                errors.append('%s: %s' % (name, g['note']))
            groups.append(g)
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
        print('STUDY_FETCH_FAIL: %s' % '; '.join(errors))
        sys.exit(1)
    if errors:
        print('STUDY_FETCH_PARTIAL: %s' % '; '.join(errors))

if __name__ == '__main__':
    main()
