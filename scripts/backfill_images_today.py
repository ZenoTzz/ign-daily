# -*- coding: utf-8 -*-
"""
为 2026-05-29 已翻译的 8 篇补 cover + images
- cover: 用 og:image (从 _today_extracted 拿)
- images: 从原 HTML 里抽 <img src=> （只取 ignimgs.com / cloudinary 等 IGN 图床的）
"""
import json
import os
import re
from html import unescape

TODAY = '2026-05-29'
DONE_IDS = [2, 6, 7, 10, 11, 12, 13, 18]

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
TRANS_DIR = os.path.join(REPO, 'data', TODAY, 'translations')
INDEX_DIR = os.path.join(REPO, 'data', TODAY)
RAW_DIR = r'C:\Users\Administrator\.openclaw\workspace\scripts\_today_raw'
EXTRACTED_DIR = r'C:\Users\Administrator\.openclaw\workspace\scripts\_today_extracted'

# IGN 图床域名白名单
IMG_HOST_OK = re.compile(r'(assets-?prd\.ignimgs\.com|assets\.ign\.com|cloudinary\.com|paramount\.tech|youtube\.com|i\.ytimg\.com|cdn\.cms-twdigitalassets\.com)')


def clean_url(u):
    """规范化 url，去除 HTML 实体、查询参数后保留主体"""
    u = unescape(u)
    # 去掉 IGN 那些 ?width=&format=&auto= 让原图更大；或保留全 URL（保留更稳）
    return u


def extract_imgs_from_html(html):
    """抓 <img src=...>，只要 IGN 图床的"""
    imgs = []
    seen = set()
    # img src
    for m in re.finditer(r'<img[^>]+(?:src|data-src)="([^"]+)"', html, re.IGNORECASE):
        url = m.group(1).strip()
        if not url:
            continue
        url = clean_url(url)
        if not url.startswith('http'):
            continue
        if not IMG_HOST_OK.search(url):
            continue
        # 过滤 logo / avatar / icon 类
        if re.search(r'(avatar|logo|icon|sprite|favicon|/profile_)', url, re.IGNORECASE):
            continue
        # 去重 (按 path 去重避免不同尺寸重复)
        key = re.sub(r'\?.*$', '', url)
        if key in seen:
            continue
        seen.add(key)
        imgs.append(url)
    # 也抓 picture > source srcset（取 srcset 里第一个）
    for m in re.finditer(r'<source[^>]+srcset="([^"]+)"', html, re.IGNORECASE):
        srcset = m.group(1).strip()
        first = srcset.split(',')[0].strip().split()[0] if srcset else ''
        if first.startswith('http') and IMG_HOST_OK.search(first):
            first = clean_url(first)
            key = re.sub(r'\?.*$', '', first)
            if key not in seen and not re.search(r'(avatar|logo|icon|sprite|favicon)', first, re.IGNORECASE):
                seen.add(key)
                imgs.append(first)
    return imgs


def main():
    # 也更新 index.json 的 cover_image 字段（首页缩略图用）
    idx_path = os.path.join(INDEX_DIR, 'index.json')
    idx = json.load(open(idx_path, encoding='utf-8'))
    art_by_id = {a['id']: a for a in idx['articles']}

    for pid in DONE_IDS:
        # cover
        ext_path = os.path.join(EXTRACTED_DIR, f'{pid:02d}.json')
        ext = json.load(open(ext_path, encoding='utf-8'))
        cover = ext.get('meta', {}).get('og_image')
        if cover:
            cover = clean_url(cover)

        # images from html
        html_path = os.path.join(RAW_DIR, f'{pid:02d}.html')
        html = open(html_path, encoding='utf-8', errors='ignore').read()
        imgs = extract_imgs_from_html(html)
        # 把 cover 也放进 images 第一个（如果还没在）
        if cover and cover not in imgs:
            imgs.insert(0, cover)

        # 写回 translation
        tpath = os.path.join(TRANS_DIR, f'{pid:02d}.json')
        t = json.load(open(tpath, encoding='utf-8'))
        t['cover'] = cover
        t['images'] = imgs
        json.dump(t, open(tpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

        # 同步更新 index.json 的 cover_image 字段
        if pid in art_by_id and cover:
            art_by_id[pid]['cover_image'] = cover

        print(f'[OK] #{pid:02d}: cover={cover[:80] if cover else None}  images={len(imgs)}')

    # 保存 index.json
    json.dump(idx, open(idx_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'\n[OK] {idx_path} updated with cover_image')


if __name__ == '__main__':
    main()
