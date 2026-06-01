#!/usr/bin/env python3
"""
IGN RSS 增量抓取脚本 — 心跳调用版
与 ign_rss_fetch.py 共享过滤逻辑，但改为增量模式：
- 读取当天 index.json 里已有的 URL
- 只追加新发现的文章
- 输出新文章到 ign_rss_new.json（供心跳翻译标题用）
- 日期归属：8:00 CST 分界（8:00前归昨天，8:00后归今天）
"""
import urllib.request
import xml.etree.ElementTree as ET
import json
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from common_paths import REPO_ROOT, configure_utf8_stdio

configure_utf8_stdio()

CST = timezone(timedelta(hours=8))
IGN_DAILY = str(REPO_ROOT)

# 确定当前日期归属
now = datetime.now(CST)
today_0800 = now.replace(hour=8, minute=0, second=0, microsecond=0)
if now < today_0800:
    # 8:00前，新文章归属今天（窗口是昨天8:00→今天8:00）
    target_date = now.strftime('%Y-%m-%d')
else:
    # 8:00后，新文章归属明天（窗口是今天8:00→明天8:00）
    target_date = (now + timedelta(days=1)).strftime('%Y-%m-%d')

print(f"Target date: {target_date} (now: {now.strftime('%H:%M')})")

# RSS 页面
RSS_PAGES = [
    "https://feeds.feedburner.com/ign/all",
    "https://www.ign.com/rss/articles/feed?start=20&count=20",
    "https://www.ign.com/rss/articles/feed?start=40&count=20",
]

# 过滤关键词（与 ign_rss_fetch.py 保持一致）
FILTER_PATTERNS = [
    r'\bsave \d+%', r'\bsave \$\d', r'\bdrops? to \$', r'\bdrops? to the lowest',
    r'\bbest .+ deals?\b', r'\bon sale\b', r'\bdiscount\b', r'\bcoupon\b',
    r'\bpromo(?:tion)?\b', r'\bmemorial.day\b', r'\bblack.friday\b',
    r'\bprime.day\b', r'\bcyber.monday\b', r'\bamazon.deal\b',
    r'\bbest.buy.deal\b', r'\bwalmart.deal\b', r'\ball-time low\b',
]
FILTER_URL = ['deal', 'sale', 'discount', 'promo', 'memorial-day', 'black-friday',
              'prime-day', 'cyber-monday', 'amazon-deal', 'best-buy-deal',
              'walmart-deal', 'coupon', 'codes-']

def is_promo(title, url):
    t = title.lower()
    for p in FILTER_PATTERNS:
        if re.search(p, t, re.IGNORECASE):
            return True
    u = url.lower()
    for k in FILTER_URL:
        if k in u:
            return True
    return False

# 读取当天已有文章 URL
index_path = os.path.join(IGN_DAILY, 'data', target_date, 'index.json')
existing_urls = set()
existing_articles = []
max_id = 0
if os.path.exists(index_path):
    idx = json.loads(open(index_path, encoding='utf-8').read())
    existing_articles = idx.get('articles', [])
    for a in existing_articles:
        existing_urls.add(a['url'])
        max_id = max(max_id, a.get('id', 0))

# 时间窗口：target_date 前一天的08:00 → target_date 当天的08:00
td = datetime.strptime(target_date, '%Y-%m-%d').replace(tzinfo=CST)
window_end = td.replace(hour=8, minute=0, second=0)
window_start = window_end - timedelta(days=1)
print(f"Window: {window_start.strftime('%Y-%m-%d %H:%M')} → {window_end.strftime('%Y-%m-%d %H:%M')} CST")

# 抓取 RSS
new_articles = []
for rss_url in RSS_PAGES:
    try:
        req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=15)
        data = resp.read().decode('utf-8', errors='replace')
        root = ET.fromstring(data)
        for item in root.iter('item'):
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            pub_str = item.findtext('pubDate') or ''
            
            if not title or not link:
                continue
            if link in existing_urls:
                continue
            
            # 解析时间
            try:
                pub_dt = parsedate_to_datetime(pub_str).astimezone(CST)
            except:
                continue
            
            if pub_dt < window_start or pub_dt >= window_end:
                continue
            
            if is_promo(title, link):
                continue
            
            existing_urls.add(link)
            new_articles.append({
                'title': title,
                'url': link,
                'pubDate_cst': pub_dt.strftime('%Y-%m-%d %H:%M'),
            })
    except Exception as e:
        print(f"  WARN: {rss_url} failed: {e}")

# 输出新文章到 ign_rss_new.json（供心跳翻译标题用）
# 同时写入 index.json + need_titles.json 队列
output_path = os.path.join(IGN_DAILY, 'ign_rss_new.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump({
        'target_date': target_date,
        'new_count': len(new_articles),
        'next_id': max_id + 1,
        'articles': new_articles
    }, f, ensure_ascii=False, indent=2)

# 如果有新文章，追加到 index.json 并写入 need_titles.json 队列
if new_articles:
    # 1) 追加到 index.json
    
    # 读取或创建 index.json
    if os.path.exists(index_path):
        idx = json.loads(open(index_path, encoding='utf-8').read())
    else:
        os.makedirs(os.path.join(IGN_DAILY, 'data', target_date), exist_ok=True)
        os.makedirs(os.path.join(IGN_DAILY, 'data', target_date, 'translations'), exist_ok=True)
        idx = {'date': target_date, 'articles': [], 'total': 0}
    
    # 追加新文章
    for a in new_articles:
        max_id += 1
        new_art = {
            'id': max_id,
            'category': '游戏新闻',
            'emoji': '🎮',
            'en_title': a['title'],
            'cn_title': a['title'],  # 临时英文，心跳替换
            'summary': '',
            'url': a['url'],
            'publish_time_cn': a['pubDate_cst'],
            'pub_date': a['pubDate_cst'],
            'cover_image': '',
            'translation_status': 'none',
        }
        idx['articles'].append(new_art)
        print(f"  [+] #{max_id} {a['title'][:60]}")
    
    idx['total'] = len(idx['articles'])
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    
    # 2) 更新 index-list.json
    hist_path = os.path.join(IGN_DAILY, 'data', 'index-list.json')
    if os.path.exists(hist_path):
        hist = json.loads(open(hist_path, encoding='utf-8').read())
        if not isinstance(hist, list):
            hist = []
    else:
        hist = []
    found = False
    for h in hist:
        if h.get('date') == target_date:
            h['total'] = idx['total']
            found = True
            break
    if not found:
        hist.append({'date': target_date, 'total': idx['total'], 'translated': 0, 'translatedTitles': []})
    hist.sort(key=lambda x: x.get('date', ''), reverse=True)
    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    
    # 3) 写入 need_titles.json 队列（供心跳翻译标题用）
    need_path = os.path.join(IGN_DAILY, 'data', target_date, 'need_titles.json')
    need_queue = []
    if os.path.exists(need_path):
        need_queue = json.loads(open(need_path, encoding='utf-8').read())
    for a in new_articles:
        aid = max_id - (len(new_articles) - new_articles.index(a)) + 1
        if any(q['url'] == a['url'] for q in need_queue):
            continue
        need_queue.append({
            'id': aid,
            'url': a['url'],
            'en_title': a['title'],
            'pub_date': a['pubDate_cst'],
        })
    with open(need_path, 'w', encoding='utf-8') as f:
        json.dump(need_queue, f, ensure_ascii=False, indent=2)
    print(f"\n[QUEUE] {len(new_articles)} articles queued for title translation")
    
    # 4) git add+commit+push
    # GitHub Actions sets IGN_DAILY_SKIP_GIT=1 and handles validation/commit itself.
    if os.environ.get('IGN_DAILY_SKIP_GIT') == '1':
        print("[SKIP_GIT] RSS files updated; caller will validate and commit.")
        sys.exit(0)

    import subprocess
    os.chdir(IGN_DAILY)
    add = subprocess.run(['git', 'add', '-A'], capture_output=True, text=True)
    if add.returncode != 0:
        print(f"[ERR] git add failed: {add.stderr}")
        sys.exit(add.returncode)
    commit = subprocess.run(['git', 'commit', '-m', f'feat: incremental RSS {len(new_articles)} new articles for {target_date}'], capture_output=True, text=True)
    if commit.returncode != 0 and 'nothing to commit' not in (commit.stdout + commit.stderr).lower():
        print(f"[ERR] git commit failed: {commit.stderr}")
        sys.exit(commit.returncode)
    push_script = os.path.join(IGN_DAILY, 'scripts', 'git_push.py')
    if os.path.exists(push_script):
        push = subprocess.run([sys.executable, push_script], capture_output=True, text=True)
        if push.returncode != 0:
            print(push.stdout)
            print(push.stderr)
            sys.exit(push.returncode)
else:
    print("📭 No new articles")
