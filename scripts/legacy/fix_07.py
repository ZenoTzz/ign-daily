"""把 #7 的 Skyward 和 Ghostbloods 改回保留英文"""
import json
import os

p = r'C:\Users\Administrator\.openclaw\workspace\ign-daily\data\2026-05-28\translations\07.json'
with open(p, 'r', encoding='utf-8') as f:
    d = json.load(f)

for para in d['paragraphs']:
    cn = para['cn']
    # 去掉《Skyward（天际旅人）》→ Skyward
    cn = cn.replace('《Skyward（天际旅人）》', 'Skyward')
    cn = cn.replace('《Skyward》', 'Skyward')
    # 去掉《Ghostbloods（鬼血）》→ Ghostbloods
    cn = cn.replace('《Ghostbloods（鬼血）》', 'Ghostbloods')
    cn = cn.replace('《Ghostbloods》', 'Ghostbloods')
    para['cn'] = cn

with open(p, 'w', encoding='utf-8') as f:
    json.dump(d, f, ensure_ascii=False, indent=2)
print('Done. Sample:')
for para in d['paragraphs']:
    if 'Skyward' in para['cn'] or 'Ghostbloods' in para['cn']:
        print('  -', para['cn'][:80] + '...')
