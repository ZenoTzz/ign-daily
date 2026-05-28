"""把今天5/28的数据导出到 ign-daily/data/2026-05-28/"""
import json
import os
import shutil
from datetime import datetime

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
INDEX = r'C:\Users\Administrator\.openclaw\workspace\ign_daily_index.json'
DICT_SRC = r'C:\Users\Administrator\.openclaw\workspace\game_names_dict.json'

DATE = '2026-05-28'

with open(INDEX, 'r', encoding='utf-8') as f:
    raw = json.load(f)

# 促销过滤
def is_promo(art):
    title_en = (art.get('en_title','') or '').lower()
    title_cn = art.get('cn_title','') or ''
    url = (art.get('url','') or '').lower()
    
    url_keys = ['deal', 'sale', 'discount', 'memorial-day', 'black-friday', 
                'prime-day', 'amazon-deal', 'best-buy-deal', 'coupon']
    for k in url_keys:
        if k in url:
            return True
    
    promo_en = ['save $', 'all-time low', 'drops to', 'lowest price']
    for k in promo_en:
        if k in title_en:
            return True
    
    cn_promo = ['降价', '史低', '纪念日特卖', '直降', '降至', '特卖', '会员日', '今日精选']
    for k in cn_promo:
        if k in title_cn:
            if '涨到' in title_cn or '涨价' in title_cn:
                continue
            return True
    return False

# 分类排序：others先按id，roundup次之，review末尾
review = [a for a in raw['articles'] if a.get('category') == '评测评分']
roundup = [a for a in raw['articles'] if a.get('category') == '盘点推荐']
others = [a for a in raw['articles'] if a.get('category') not in ('评测评分', '盘点推荐')]

others_filtered = [a for a in others if not is_promo(a)]
roundup_filtered = [a for a in roundup if not is_promo(a)]
review_filtered = [a for a in review if not is_promo(a)]

push_order = others_filtered + roundup_filtered + review_filtered

# 已翻译的 json id（今天用户选了10篇）
translated_json_ids = {10, 11, 15, 21, 22, 23, 33, 34, 44, 45}

emoji_map = {
    '游戏新闻': '🎮', '评测评分': '⭐', '影视资讯': '🎬',
    '人物新闻': '🌟', '行业动态': '💼', '科技新闻': '🔬',
    '盘点推荐': '📋',
}

# 推送编号 1开始（剔除促销后）
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
        'publish_time_cn': a.get('publish_time_cn', '') or a.get('publish_time', ''),
        'translation_status': 'done' if a.get('id') in translated_json_ids else 'none',
        'translation_path': f'translations/{idx:02d}.json' if a.get('id') in translated_json_ids else None,
    }
    articles.append(art)

# 保存当日 index.json
out_dir = os.path.join(REPO, 'data', DATE)
os.makedirs(out_dir, exist_ok=True)
os.makedirs(os.path.join(out_dir, 'translations'), exist_ok=True)

index = {
    'date': DATE,
    'window': raw.get('window', ''),
    'total': len(articles),
    'articles': articles,
}
with open(os.path.join(out_dir, 'index.json'), 'w', encoding='utf-8') as f:
    json.dump(index, f, ensure_ascii=False, indent=2)
print(f'Saved index.json with {len(articles)} articles')

# 复制词库
shutil.copy(DICT_SRC, os.path.join(REPO, 'data', 'dict.json'))
print('Copied dict.json')

# 生成 index-list.json (历史清单，目前只有今天)
hist = [{
    'date': DATE,
    'total': len(articles),
    'translated': sum(1 for a in articles if a['translation_status'] == 'done'),
    'translatedTitles': [
        {'id': a['id'], 'cn_title': a['cn_title']}
        for a in articles if a['translation_status'] == 'done'
    ],
}]
with open(os.path.join(REPO, 'data', 'index-list.json'), 'w', encoding='utf-8') as f:
    json.dump(hist, f, ensure_ascii=False, indent=2)
print('Saved index-list.json')

print('\n推送编号 → 标题 → 翻译状态')
for a in articles[:15]:
    s = '✅' if a['translation_status'] == 'done' else '⚪'
    print(f"{s} #{a['id']} [{a['category']}] {a['cn_title']}")
print(f'... (共 {len(articles)} 条)')
