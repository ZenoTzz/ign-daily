"""直接用Python urllib从IGN抓HTML并提取图片URL"""
import urllib.request, re, json, sys, os

def fetch_ign_images(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f'  ERROR: {e}')
        return []

    # 截掉推荐栏（IGN Recommends 之前）
    cut_idx = html.find('IGN Recommends')
    if cut_idx > 0:
        html = html[:cut_idx]

    # 提取所有 assets-prd.ignimgs.com 的 jpg/png/jpeg/webp 图片
    # IGN 用 srcset / data-src / src 各种属性
    img_pattern = re.compile(r'https?://(?:[a-z0-9-]+\.)?ignimgs\.com/[a-zA-Z0-9/_\-\.]+\.(?:jpg|jpeg|png|webp)(?=[\?"\s])', re.I)
    found = img_pattern.findall(html)
    
    # 去重，按出现顺序
    seen = set()
    out = []
    for u in found:
        # 过滤推荐栏/导航栏常见路径
        if u in seen: continue
        if any(bad in u.lower() for bad in ['logo', 'avatar', '/icons/', '/blogroll/', '-blogroll', 'placeholder']):
            continue
        # 跳过太小的（带尺寸后缀如 _80 表明缩略图）
        if re.search(r'_(40|60|80|100)\.', u):
            continue
        seen.add(u)
        out.append(u)

    return out

# 测试
test_urls = {
    '#3': 'https://www.ign.com/articles/the-first-wheel-of-time-board-game-adaptation-has-already-blown-past-its-goals-on-kickstarter',
    '#5': 'https://www.ign.com/articles/dragon-quest-12-beyond-dreams-update',
    '#6': 'https://www.ign.com/articles/steam-deck-price-increase-announced-by-valve',
}

for label, url in test_urls.items():
    print(f'\n{label}: {url}')
    imgs = fetch_ign_images(url)
    print(f'  found {len(imgs)} images:')
    for u in imgs[:6]:
        print(f'    {u}')
