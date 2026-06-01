"""add url and en_title to translate_pipeline --post output"""
path = 'C:/Users/Administrator/.openclaw/workspace/ign-daily/scripts/translate_pipeline.py'

with open(path, encoding='utf-8') as f:
    content = f.read()

# 找到 --post 模式写 data 的地方 - 找 data['cover'] 附近
idx = content.find("data['cover']")
if idx >= 0:
    before = content[max(0,idx-200):idx]
    print(f'Before cover write:\n{before}')
    print(f'---')
    after = content[idx:idx+300]
    print(f'Cover write:\n{after}')