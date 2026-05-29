"""
通用版 build_today.py - 把 ign_daily_index.json 发布到 ign-daily/data/{today}/
不依赖具体日期常量。

修订:
- DATE 自动取当天
- translation_status 全部 'none'（早报阶段还没翻译）
- index-list.json: 读取已有列表，**追加/更新**今天那条，不是覆写
"""
import json
import os
import shutil
from datetime import datetime, timezone, timedelta

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
INDEX = r'C:\Users\Administrator\.openclaw\workspace\ign_daily_index.json'
DICT_SRC = r'C:\Users\Administrator\.openclaw\workspace\game_names_dict.json'

# 北京时间
CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).strftime('%Y-%m-%d')

with open(INDEX, 'r', encoding='utf-8') as f:
    raw = json.load(f)

# 排序: 普通新闻 → 盘点 → 评测
review = [a for a in raw['articles'] if a.get('category') == '评测评分']
roundup = [a for a in raw['articles'] if a.get('category') == '盘点推荐']
others = [a for a in raw['articles'] if a.get('category') not in ('评测评分', '盘点推荐')]
push_order = others + roundup + review

emoji_map = {
    '游戏新闻': '🎮', '评测评分': '⭐', '影视资讯': '🎬',
    '人物新闻': '🌟', '行业动态': '💼', '科技新闻': '🔬',
    '盘点推荐': '📋',
}

articles = []
for idx, a in enumerate(push_order, 1):
    art = {
        'id': idx,
        'json_id': a.get('id'),
        'category': a.get('category', ''),
        'emoji': emoji_map.get(a.get('category', ''), '📄'),
        'en_title': a.get('en_title', ''),
        'cn_title': a.get('cn_title', ''),
        'summary': a.get('summary', ''),
        'url': a.get('url', ''),
        'publish_time_cn': a.get('pubDate_cst', '') or a.get('publish_time_cn', '') or a.get('publish_time', ''),
        'translation_status': 'none',
        'translation_path': None,
    }
    articles.append(art)

# 写当日 index.json
out_dir = os.path.join(REPO, 'data', TODAY)
os.makedirs(out_dir, exist_ok=True)
os.makedirs(os.path.join(out_dir, 'translations'), exist_ok=True)

index_obj = {
    'date': TODAY,
    'window': raw.get('window', ''),
    'total': len(articles),
    'articles': articles,
}
with open(os.path.join(out_dir, 'index.json'), 'w', encoding='utf-8') as f:
    json.dump(index_obj, f, ensure_ascii=False, indent=2)
print(f'[OK] data/{TODAY}/index.json  ({len(articles)} articles)')

# 复制词库
shutil.copy(DICT_SRC, os.path.join(REPO, 'data', 'dict.json'))
print('[OK] data/dict.json')

# 更新历史清单 index-list.json（追加/更新今天）
hist_path = os.path.join(REPO, 'data', 'index-list.json')
if os.path.exists(hist_path):
    with open(hist_path, 'r', encoding='utf-8') as f:
        hist = json.load(f)
    if not isinstance(hist, list):
        hist = []
else:
    hist = []

today_entry = {
    'date': TODAY,
    'total': len(articles),
    'translated': 0,
    'translatedTitles': [],
}

# 删除旧的今天条目，再追加新的
hist = [h for h in hist if h.get('date') != TODAY]
hist.append(today_entry)
# 按日期降序
hist.sort(key=lambda x: x.get('date', ''), reverse=True)

with open(hist_path, 'w', encoding='utf-8') as f:
    json.dump(hist, f, ensure_ascii=False, indent=2)
print(f'[OK] data/index-list.json  (total {len(hist)} dates)')

# 简要打印
print(f'\n推送顺序 (前 10):')
for a in articles[:10]:
    print(f"  #{a['id']:2d} {a['emoji']} [{a['category']}] {a['cn_title']}")
if len(articles) > 10:
    print(f'  ... 共 {len(articles)} 条')

# 统计
from collections import Counter
c = Counter(a['category'] for a in articles)
print(f'\n分类: {dict(c)}')

print(f'\n下一步: cd {REPO} && git add -A && git commit -m "{TODAY} daily news" && git push')
