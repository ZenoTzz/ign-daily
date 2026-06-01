#!/usr/bin/env python3
"""
sync_translation_to_index.py

把 translations/NN.json 里的 cn_title + opus_summary 同步回 index.json，
这样首页就能直接显示已翻译的中文标题和摘要。

用法:
  python scripts/sync_translation_to_index.py <date> [<id>]
  
  不加 id: 扫描 translations/ 下所有 done 状态的文章，同步
  加 id: 只同步指定 id
"""

import json, os, sys, glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def sync(date, article_id=None):
    index_path = os.path.join(REPO, 'data', date, 'index.json')
    trans_dir = os.path.join(REPO, 'data', date, 'translations')
    
    if not os.path.exists(index_path):
        print(f"[ERR] index.json not found: {index_path}")
        return False
    
    with open(index_path, 'r', encoding='utf-8-sig') as f:
        index = json.loads(f.read())
    
    updated = 0
    articles_map = {}
    for a in index['articles']:
        articles_map[a['id']] = a
    
    if article_id:
        ids_to_check = [article_id]
    else:
        # 自动扫描 translations/ 下所有 translation_status=done 的文章
        ids_to_check = [a['id'] for a in index['articles'] if a.get('translation_status') == 'done']
    
    for aid in ids_to_check:
        trans_file = os.path.join(trans_dir, f'{aid:02d}.json')
        if not os.path.exists(trans_file):
            print(f"  [SKIP] #{aid}: no translation file {aid:02d}.json")
            continue
        
        with open(trans_file, 'r', encoding='utf-8-sig') as f:
            trans = json.loads(f.read())
        
        if aid not in articles_map:
            print(f"  [SKIP] #{aid}: not in index.json")
            continue
        
        art = articles_map[aid]
        cn_title = trans.get('cn_title', '')
        summary = trans.get('opus_summary', '')
        publish_time_cn = trans.get('publish_time_cn', '')
        cover = trans.get('cover', '')
        
        changed = False
        if cn_title and art.get('cn_title') != cn_title:
            art['cn_title'] = cn_title
            changed = True
        if summary and art.get('summary') != summary:
            art['summary'] = summary
            changed = True
        if publish_time_cn and art.get('publish_time_cn') != publish_time_cn:
            art['publish_time_cn'] = publish_time_cn
            if not art.get('pub_date'):
                art['pub_date'] = publish_time_cn
            changed = True
        if cover and not art.get('cover_image'):
            art['cover_image'] = cover
            changed = True
        
        if changed:
            print(f"  [SYNC] #{aid}: cn_title='{cn_title[:40]}' summary='{summary[:40]}...'")
            updated += 1
        else:
            print(f"  [OK] #{aid}: already in sync")
    
    if updated > 0:
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] Updated {updated} articles in data/{date}/index.json")
    else:
        print(f"\n[OK] No updates needed")
    
    return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/sync_translation_to_index.py <date> [<id>]")
        sys.exit(1)
    
    date = sys.argv[1]
    article_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sync(date, article_id)
