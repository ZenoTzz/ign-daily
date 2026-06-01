"""
IGN Daily Translation Pipeline - 统一自动化管道
==============================================

用法:
  python3 scripts/translate_pipeline.py <date> <article_id> <translation_json_path>

功能:
  1. [PRE] 从文章 URL 抓取 HTML → 提取 og:image → 提取正文图片
  2. [PRE] 加载词库 → 扫描原文匹配专有名词 → 输出命中列表
  3. [POST] 读取已写好的翻译 JSON → 自动补充:
     - cover (从 og:image)
     - images (从正文图片)
     - translated_terms (从词库匹配+译文扫描自动生成)
     - 清理英中间空格
     - 检查 ASCII 双引号
  4. [POST] 同步更新 index.json (translation_status + cover_image)
  5. [POST] 同步更新 index-list.json
  6. [POST] 运行 post_translate_check 验证

两种模式:
  --prep   只做预处理(抓图+词库匹配),输出到 stdout 供翻译参考
  --post   翻译写完后做后处理(补字段+校验+同步)
  无参数   = --prep + --post 全流程

示例:
  # 翻译前: 预处理,看词库命中和图片
  python3 scripts/translate_pipeline.py 2026-05-31 15 --prep

  # 翻译后: 后处理,补字段+校验
  python3 scripts/translate_pipeline.py 2026-05-31 15 --post
"""

import json, os, sys, re, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from common_paths import REPO_ROOT, dict_path, exchange_rates_path, configure_utf8_stdio

configure_utf8_stdio()

CST = timezone(timedelta(hours=8))
IGN_DAILY = REPO_ROOT
DICT_PATH = dict_path()
EXCHANGE_PATH = exchange_rates_path()


def load_dict():
    """加载词库,返回 {english_name: cn_name} 的扁平字典"""
    with open(DICT_PATH, 'r', encoding='utf-8') as f:
        d = json.load(f)
    terms = {}
    for cat in ['games', 'movies_tv', 'companies', 'people', 'media', 'terms']:
        for k, v in d.get(cat, {}).items():
            if isinstance(v, dict):
                terms[k] = v.get('cn', k)
            else:
                terms[k] = v
    return terms


def fetch_og_image_and_images(url):
    """从文章 URL 抓取 og:image 和正文图片"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  ⚠️ Failed to fetch {url}: {e}")
        return None, []

    # og:image
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    cover = None
    if m:
        raw = m.group(1).replace('&amp;', '&')
        parsed = urllib.parse.urlparse(raw)
        cover = parsed._replace(query='', fragment='').geturl()

    # 正文图片
    cut_idx = html.find('IGN Recommends')
    body = html[:cut_idx] if cut_idx > 0 else html
    pattern = re.compile(
        r'https?://(?:[a-z0-9-]+\.)?ignimgs\.com/[a-zA-Z0-9/_\-\.]+\.(?:jpg|jpeg|png|webp)',
        re.I
    )
    seen = set()
    inline = []
    for u in pattern.findall(body):
        u_clean = u.split('?')[0]
        if u_clean in seen:
            continue
        if any(b in u.lower() for b in ['logo', 'avatar', '/icons/', 'placeholder']):
            continue
        if re.search(r'_(40|60|80|100)\.', u):
            continue
        seen.add(u_clean)
        inline.append(u_clean)

    # 合并
    images = []
    img_seen = set()
    if cover:
        images.append({"url": cover, "caption": ""})
        img_seen.add(cover)
    for u in inline:
        if u not in img_seen:
            images.append({"url": u, "caption": ""})
            img_seen.add(u)

    return cover, images


def match_dict_terms(english_text, terms_dict):
    """在英文文本中查找词库匹配,按长度降序"""
    hits = []
    for en, cn in sorted(terms_dict.items(), key=lambda x: -len(x[0])):
        if en in english_text:
            hits.append((en, cn))
    return hits


def clean_spacing(text):
    """去除英文和中文之间的空格"""
    # 英文/数字后接中文前的空格
    text = re.sub(r'([a-zA-Z0-9\)\]\}\>]) ([一-鿿《》「」(])', r'\1\2', text)
    # 中文后接英文/数字前的空格
    text = re.sub(r'([一-鿿《》「」)]) ([a-zA-Z0-9\(])', r'\1\2', text)
    return text


def check_ascii_quotes(text):
    """检查中文文本中是否有 ASCII 双引号残留"""
    # 去掉明显的英文上下文
    cn_only = re.sub(r'[a-zA-Z0-9\s.,;:!?\'()\[\]{}/@#$%^&*+=<>~`|\\-]', '', text)
    return '"' in cn_only


def generate_translated_terms(paragraphs, cn_title, opus_summary, terms_dict, pending_dict):
    """自动生成 translated_terms 快照"""
    # 收集所有英文原文
    all_en = ' '.join([p.get('en', '') for p in paragraphs if isinstance(p, dict)])
    # 收集所有中文译文
    all_cn = cn_title + ' ' + (opus_summary or '') + ' ' + ' '.join(
        [p.get('cn', '') for p in paragraphs if isinstance(p, dict)]
    )

    translated_terms = {}
    for en, cn in sorted(terms_dict.items(), key=lambda x: -len(x[0])):
        if en in all_en:
            # 判断译文里是保留英文还是意译
            if cn in all_cn:
                translated_terms[en] = cn
            elif en in all_cn:
                translated_terms[en] = en
            # 如果都不在,可能是更短的词被覆盖了,跳过

    # 补充 pending_dict 里的词
    for item in (pending_dict or []):
        en = item.get('en', '')
        cn = item.get('cn', '')
        if en and en not in translated_terms:
            if cn and cn != en and cn in all_cn:
                translated_terms[en] = cn
            elif en in all_cn:
                translated_terms[en] = en

    return translated_terms


def update_index_list(data_dir):
    """更新 index-list.json"""
    index_list_path = IGN_DAILY / 'data' / 'index-list.json'
    
    # 扫描所有日期文件夹
    data_path = IGN_DAILY / 'data'
    dates = []
    for d in sorted(data_path.iterdir(), reverse=True):
        if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name):
            idx_file = d / 'index.json'
            if idx_file.exists():
                with open(idx_file, 'r', encoding='utf-8') as f:
                    idx = json.load(f)
                articles = idx.get('articles', [])
                total = len(articles)
                translated = sum(1 for a in articles if a.get('translation_status') == 'done')
                translated_titles = [a.get('cn_title', '') for a in articles if a.get('translation_status') == 'done']
                dates.append({
                    "date": d.name,
                    "total": total,
                    "translated": translated,
                    "translatedTitles": translated_titles[:5]  # 最多5个预览
                })
    
    with open(index_list_path, 'w', encoding='utf-8') as f:
        json.dump(dates, f, ensure_ascii=False, indent=2)
    
    return len(dates)


def resolve_article(articles, article_ref):
    """Resolve either a numeric id or the stable URL stored in requests.json."""
    ref = str(article_ref)
    if ref.isdigit():
        article_id = int(ref)
        return article_id, next((a for a in articles if a.get('id') == article_id), None)
    art = next((a for a in articles if a.get('url') == ref), None)
    return (art.get('id') if art else None), art


def prep_mode(date_str, article_ref):
    """预处理模式: 抓图+词库匹配"""
    idx_path = IGN_DAILY / 'data' / date_str / 'index.json'
    if not idx_path.exists():
        print(f"❌ index.json not found for {date_str}")
        return False

    with open(idx_path, 'r', encoding='utf-8') as f:
        idx = json.load(f)

    article_id, art = resolve_article(idx['articles'], article_ref)
    if not art:
        print(f"❌ Article {article_ref} not found in index")
        return False

    url = art.get('url', '')
    print(f"\n{'='*60}")
    print(f"PREP: #{article_id} - {art['en_title'][:60]}")
    print(f"URL: {url}")
    print(f"{'='*60}")

    # 1. 抓图
    print("\n📷 Fetching images...")
    cover, images = fetch_og_image_and_images(url)
    print(f"  Cover: {cover or '❌ NOT FOUND'}")
    print(f"  Images: {len(images)} found")
    for img in images[:5]:
        print(f"    - {img['url'][:80]}")

    # 2. 词库匹配
    print("\n📖 Dictionary matching...")
    terms = load_dict()
    
    # 用标题+摘要做初步匹配
    en_text = art.get('en_title', '') + ' ' + art.get('summary', '')
    hits = match_dict_terms(en_text, terms)
    if hits:
        print(f"  Found {len(hits)} matches in title/summary:")
        for en, cn in hits:
            print(f"    ✅ {en} → {cn}")
    else:
        print("  No matches in title/summary (will need full article text)")

    # 3. 输出模板
    print(f"\n📝 Template JSON fields to fill:")
    print(f'  "cover": "{cover or ""}"')
    print(f'  "images": {json.dumps(images[:3], ensure_ascii=False)}')
    print(f"  // (还需要: paragraphs, opus_summary, subtitle, translated_terms, pending_dict)")

    return True


def post_mode(date_str, article_ref):
    """后处理模式: 补字段+清理+校验+同步"""
    idx_path = IGN_DAILY / 'data' / date_str / 'index.json'

    if not str(article_ref).isdigit():
        with open(idx_path, 'r', encoding='utf-8') as f:
            idx_for_url = json.load(f)
        resolved_id, art_for_url = resolve_article(idx_for_url['articles'], article_ref)
        if not art_for_url:
            print(f"鉂?Article {article_ref} not in index")
            return False
        return post_mode(date_str, str(resolved_id))

    article_id = int(article_ref)
    trans_path = IGN_DAILY / 'data' / date_str / 'translations' / f'{article_id:02d}.json'

    if not trans_path.exists():
        print(f"❌ Translation file not found: {trans_path}")
        return False

    with open(trans_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(idx_path, 'r', encoding='utf-8') as f:
        idx = json.load(f)

    art = next((a for a in idx['articles'] if a['id'] == article_id), None)
    if not art:
        print(f"❌ Article #{article_id} not in index")
        return False

    url = art.get('url', '')
    if data.get('url') and data.get('url') != url:
        print(f"ERROR: Translation URL mismatch for #{article_id}")
        print(f"  index: {url}")
        print(f"  json : {data.get('url')}")
        return False
    if data.get('en_title') and data.get('en_title') != art.get('en_title'):
        print(f"ERROR: Translation title mismatch for #{article_id}")
        print(f"  index: {art.get('en_title')}")
        print(f"  json : {data.get('en_title')}")
        return False
    changed = False
    print(f"\n{'='*60}")
    print(f"POST: #{article_id} - {data.get('cn_title', '')[:40]}")
    print(f"{'='*60}")

    # 1. 补 cover
    if not data.get('cover'):
        print("\n📷 Cover missing, fetching...")
        cover, images = fetch_og_image_and_images(url)
        if cover:
            data['cover'] = cover
            changed = True
            print(f"  ✅ Cover set: {cover[:60]}")
        else:
            print("  ⚠️ Could not fetch cover!")
    else:
        cover = data['cover']
        # 检查压缩参数
        if '?' in cover:
            parsed = urllib.parse.urlparse(cover)
            data['cover'] = parsed._replace(query='', fragment='').geturl()
            changed = True
            print(f"  🔧 Stripped query params from cover")

    # 2. 补 images
    if not data.get('images') or len(data['images']) == 0:
        if not data.get('cover'):
            print("  ⚠️ No cover to use as image")
        else:
            data['images'] = [{"url": data['cover'], "caption": ""}]
            changed = True
            print(f"  ✅ Added cover to images array")

    # 3. 自动生成 translated_terms
    if not data.get('translated_terms'):
        print("\n📖 Generating translated_terms...")
        terms = load_dict()
        tt = generate_translated_terms(
            data.get('paragraphs', []),
            data.get('cn_title', ''),
            data.get('opus_summary', ''),
            terms,
            data.get('pending_dict', [])
        )
        data['translated_terms'] = tt
        changed = True
        print(f"  ✅ Generated {len(tt)} terms")
    else:
        print(f"\n📖 translated_terms exists ({len(data['translated_terms'])} terms)")

    # 4. 清理英中间空格
    space_fixes = 0
    for p in data.get('paragraphs', []):
        if isinstance(p, dict) and 'cn' in p:
            cleaned = clean_spacing(p['cn'])
            if cleaned != p['cn']:
                p['cn'] = cleaned
                space_fixes += 1
    if data.get('cn_title'):
        cleaned = clean_spacing(data['cn_title'])
        if cleaned != data['cn_title']:
            data['cn_title'] = cleaned
            space_fixes += 1
    if data.get('opus_summary'):
        cleaned = clean_spacing(data['opus_summary'])
        if cleaned != data['opus_summary']:
            data['opus_summary'] = cleaned
            space_fixes += 1
    if space_fixes > 0:
        changed = True
        print(f"\n🔧 Cleaned {space_fixes} spacing issues")

    # 5. ASCII 双引号检查
    quote_issues = []
    all_cn_texts = [data.get('cn_title', ''), data.get('opus_summary', '')]
    all_cn_texts += [p.get('cn', '') for p in data.get('paragraphs', []) if isinstance(p, dict)]
    for i, txt in enumerate(all_cn_texts):
        if check_ascii_quotes(txt):
            quote_issues.append(i)
    if quote_issues:
        print(f"\n⚠️ ASCII double quotes found in {len(quote_issues)} fields! Manual fix needed.")

    # 6. 保存翻译文件
    if changed:
        with open(trans_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Saved {trans_path.name}")

    # 7. 同步 index.json
    idx_changed = False
    for a in idx['articles']:
        if a['id'] == article_id:
            if a.get('translation_status') != 'done':
                a['translation_status'] = 'done'
                idx_changed = True
            if a.get('translation_path') != f'translations/{article_id:02d}.json':
                a['translation_path'] = f'translations/{article_id:02d}.json'
                idx_changed = True
            if data.get('cover') and a.get('cover_image') != data['cover']:
                a['cover_image'] = data['cover']
                idx_changed = True
            for meta_key in ('translator', 'translator_provider', 'translator_model'):
                if data.get(meta_key) and a.get(meta_key) != data[meta_key]:
                    a[meta_key] = data[meta_key]
                    idx_changed = True
            break

    if idx_changed:
        with open(idx_path, 'w', encoding='utf-8') as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        print(f"  ✅ index.json synced")

    # 8. 同步 index-list.json
    n_dates = update_index_list(date_str)
    print(f"  ✅ index-list.json updated ({n_dates} dates)")

    # 9. 最终校验总结
    issues = []
    if not data.get('cover'):
        issues.append("MISSING cover")
    if not data.get('translated_terms'):
        issues.append("MISSING translated_terms")
    if not data.get('subtitle'):
        issues.append("🚨 MISSING subtitle (2-15字创意短句，必须手动写入)")
    else:
        sub = data['subtitle']
        if len(sub) > 15:
            issues.append(f"🚨 subtitle TOO LONG ({len(sub)}字>​15): 「{sub}」")
        if '，' in sub and len(sub) > 10:
            issues.append(f"🚨 subtitle 含逗号且偏长，太像句子: 「{sub}」")
        # Detect news-summary anti-patterns
        import re as _re
        if _re.search(r'\d{3,}', sub):
            issues.append(f"🚨 subtitle 含大数字，像摘要不像创意短句: 「{sub}」")
        if _re.search(r'「.{8,}」', sub):
            issues.append(f"🚨 subtitle 内嵌长引用: 「{sub}」")
    if not data.get('opus_summary'):
        issues.append("MISSING opus_summary")
    if not data.get('paragraphs'):
        issues.append("EMPTY paragraphs")
    if quote_issues:
        issues.append(f"ASCII quotes in {len(quote_issues)} fields")

    if issues:
        print(f"\n🟡 Remaining issues: {', '.join(issues)}")
        return False
    else:
        print(f"\n✅ Article #{article_id} fully validated!")
        return True


def main():
    args = sys.argv[1:]
    
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    
    date_str = args[0]
    article_ref = args[1]
    mode = args[2] if len(args) > 2 else '--all'
    
    if mode == '--prep':
        prep_mode(date_str, article_ref)
    elif mode == '--post':
        success = post_mode(date_str, article_ref)
        sys.exit(0 if success else 1)
    else:
        # Full pipeline
        prep_mode(date_str, article_ref)
        print("\n" + "="*60)
        print("⏸️  Now write the translation JSON, then run with --post")
        print("="*60)


if __name__ == '__main__':
    main()
