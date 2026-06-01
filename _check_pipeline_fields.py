"""check translate_pipeline writes url and en_title"""
with open('C:/Users/Administrator/.openclaw/workspace/ign-daily/scripts/translate_pipeline.py', encoding='utf-8') as f:
    content = f.read()

# look for url and en_title in the write section
import re
for kw in ['"url"', '"en_title"']:
    idx = 0
    found = []
    while True:
        idx = content.find(kw, idx)
        if idx < 0:
            break
        start = max(0, idx - 40)
        end = min(len(content), idx + 50)
        found.append(content[start:end].strip()[:100])
        idx += 1
    if found:
        print(f'{kw}:')
        for f in found:
            print(f'  {f}')
        print()
    else:
        print(f'{kw}: NOT FOUND in pipeline script')