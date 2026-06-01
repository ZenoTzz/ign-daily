"""find all article.xxx without optional chaining"""
import re

with open('C:/Users/Administrator/.openclaw/workspace/ign-daily/article.html', encoding='utf-8') as f:
    html = f.read()

# find every article.X pattern
for m in re.finditer(r'article\.([a-zA-Z_]+)', html):
    full = m.group()
    pos = m.start()
    # check there's no ? before the dot
    before = html[max(0,pos-4):pos]
    if '?' not in before:
        # get context
        start = max(0, pos-20)
        end = min(len(html), pos+len(full)+20)
        context = html[start:end].replace('\n', ' ')
        print(f'  {context.strip()[:120]}')