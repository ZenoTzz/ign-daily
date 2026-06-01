"""检查今天是否有润色（用于夜间学习按需触发）"""
import json, datetime, os, sys
from common_paths import DATA_DIR

date = datetime.datetime.now().strftime('%Y-%m-%d')
p = DATA_DIR / date / 'polished' / '_index.json'

if not p.exists():
    print('NO_POLISH')
    sys.exit(0)

with open(p, 'r', encoding='utf-8') as f:
    idx = json.load(f)

if not idx or len(idx) == 0:
    print('NO_POLISH')
    sys.exit(0)

print(f'HAS_POLISH:{len(idx)}')
