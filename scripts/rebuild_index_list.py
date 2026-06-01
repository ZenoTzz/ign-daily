"""根据当前 data/{date}/index.json 重建 index-list.json"""
import json, os, glob
from pathlib import Path
from common_paths import DATA_DIR

ROOT = DATA_DIR
list_path = ROOT / 'index-list.json'

# 找所有日期文件夹
date_dirs = sorted([d for d in ROOT.iterdir() if d.is_dir() and d.name.startswith('2026')], reverse=True)

result = []
for dd in date_dirs:
    idx_file = dd / 'index.json'
    if not idx_file.exists():
        continue
    with open(idx_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    translated = [a for a in data.get('articles', []) if a.get('translation_status') == 'done']
    entry = {
        'date': dd.name,
        'total': data.get('total', len(data.get('articles', []))),
        'translated': len(translated),
        'translatedTitles': [{'id': a['id'], 'cn_title': a['cn_title']} for a in translated]
    }
    result.append(entry)
    print(f'{dd.name}: total={entry["total"]} translated={entry["translated"]}')

with open(list_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f'\nSaved {list_path} ({len(result)} dates)')
