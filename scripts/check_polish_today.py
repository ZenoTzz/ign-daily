"""检查今天是否有润色（用于夜间学习按需触发）"""
import json, datetime, os, sys

date = datetime.datetime.now().strftime('%Y-%m-%d')
p = f'C:/Users/Administrator/.openclaw/workspace/ign-daily/data/{date}/polished/_index.json'

if not os.path.exists(p):
    print('NO_POLISH')
    sys.exit(0)

with open(p, 'r', encoding='utf-8') as f:
    idx = json.load(f)

if not idx or len(idx) == 0:
    print('NO_POLISH')
    sys.exit(0)

print(f'HAS_POLISH:{len(idx)}')
