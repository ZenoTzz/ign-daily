#!/usr/bin/env python3
import json, os, sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 1) Check 05-31 index.json
with open('data/2026-05-31/index.json', encoding='utf-8-sig') as f:
    d = json.loads(f.read())
print("=== 05-31 index.json articles ===")
for a in d['articles']:
    cn = a.get('cn_title','') or ''
    s = a.get('summary','') or ''
    print(f"  id={a['id']} status={a['translation_status']} cn='{cn[:40]}' summary='{s[:60]}'")

# 2) Check a translation file
with open('data/2026-05-31/translations/01.json', encoding='utf-8-sig') as f:
    t = json.loads(f.read())
print("\n=== 01.json translation fields ===")
for k in ['cn_title', 'opus_summary', 'subtitle', 'translated_terms']:
    print(f"  {k}={json.dumps(t.get(k), ensure_ascii=False)[:80]}")

# 3) Check the frontend rendering - does it read cn_title+summary from index.json?
with open('index.html', encoding='utf-8') as f:
    html = f.read()

# Find article rendering parts
import re
# Find the card-title line area
for m in re.finditer(r'card-title[^<]*</h3>', html, re.DOTALL):
    print(f"\n=== Found card-title section ===")
    start = max(0, m.start()-100)
    end = min(len(html), m.end()+100)
    print(html[start:end])
    
for m in re.finditer(r'card-summary[^<]*</p>', html, re.DOTALL):
    print(f"\n=== Found card-summary section ===")
    start = max(0, m.start()-50)
    end = min(len(html), m.end()+50)
    print(html[start:end])

# 4) Check app.js for how articles get rendered
with open('assets/app.js', encoding='utf-8') as f:
    js = f.read()

# Find how templates load index.json data
for marker in ['index.json', 'articles', 'cn_title']:
    idx = js.find(marker)
    if idx >= 0:
        print(f"\n=== '{marker}' at offset {idx} ===")
        print(js[max(0,idx-150):idx+250])