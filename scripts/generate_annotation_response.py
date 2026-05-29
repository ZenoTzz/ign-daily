# -*- coding: utf-8 -*-
"""
扫描 learning_log 里所有日期，对比 feedback / response，生成或更新我对用户批注的回复。

调用方法:
  python3 scripts/generate_annotation_response.py [date]
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
NOW_ISO = datetime.now(CST).isoformat()

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
LOG_DIR = os.path.join(REPO, 'data', 'learning_log')


def classify_feedback(text):
    """粗划分成 4 类: confirm / reject / refine / unclear"""
    t = text.strip()
    NEG = ['不需要', '不要', '不对', '不是', '错了', '错误',
           '例外', '是个例', '取消', '不适用', '不适合',
           '不该', '不能', '重新']
    POS = ['这个好', '这样好', '按这样', '按这么', '同意',
           '对的', '可以', '不错', '这个可以',
           '以后都', '一律']

    has_neg = any(w in t for w in NEG)
    has_pos = any(w in t for w in POS)

    if has_neg and not has_pos:
        return 'reject'
    if has_pos and not has_neg:
        return 'confirm'
    if has_neg and has_pos:
        return 'refine'
    if len(t) > 10:
        return 'refine'
    return 'unclear'


def gen_response(rule, feedback_text, kind):
    """生成回复。原则: 短、具体、不嵌套引号、不提术语。"""
    title = rule.get('title') or rule.get('id') or '该规则'

    # 避免嵌套: 标题里已含「」《》『』时，不再外包一层
    if any(ch in title for ch in '「」『』《》'):
        wrapped = title
    else:
        wrapped = f'「{title}」'

    if kind == 'confirm':
        return {
            'kind': 'confirm',
            'text': '✅ 好，后面都这样译。',
        }
    if kind == 'reject':
        return {
            'kind': 'reject',
            'text': f'❌ 收到，{wrapped}不当作通用规则。',
        }
    if kind == 'refine':
        return {
            'kind': 'refine',
            'text': f'✏️ 记下了：{feedback_text}',
        }
    return {
        'kind': 'unclear',
        'text': '🤔 这条我没看懂，可以点「修改」再写详细点。',
    }


def process_date(date):
    log_path = os.path.join(LOG_DIR, f'{date}.json')
    fb_path = os.path.join(LOG_DIR, f'{date}_feedback.json')
    resp_path = os.path.join(LOG_DIR, f'{date}_response.json')

    if not os.path.exists(log_path):
        print(f'  [skip] no log: {log_path}')
        return False
    if not os.path.exists(fb_path):
        print(f'  [skip] no feedback: {fb_path}')
        return False

    log = json.load(open(log_path, encoding='utf-8'))
    feedback = json.load(open(fb_path, encoding='utf-8'))
    response = json.load(open(resp_path, encoding='utf-8')) if os.path.exists(resp_path) else {}

    by_id = {}
    for r in (log.get('rules_confirmed') or []) + (log.get('observations') or []):
        if r.get('id'):
            by_id[r['id']] = r

    changed = 0
    # 强制重写所有 response（这次升级）
    force = os.environ.get('FORCE_REGEN') == '1'

    for rid, fb_text in feedback.items():
        if not rid or not fb_text:
            continue
        existing = response.get(rid) or {}
        old_snapshot = existing.get('feedback_snapshot')

        if not force and old_snapshot == fb_text and existing.get('text'):
            continue

        rule = by_id.get(rid)
        if not rule:
            continue

        kind = classify_feedback(fb_text)
        resp = gen_response(rule, fb_text, kind)
        response[rid] = {
            'kind': resp['kind'],
            'text': resp['text'],
            'feedback_snapshot': fb_text,
            'generated_at': NOW_ISO,
        }
        changed += 1
        print(f'  [{kind}] {rid}: {fb_text[:30]}')

    if changed:
        json.dump(response, open(resp_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'  [OK] {resp_path}: {changed} updated, total {len(response)}')
        return True
    else:
        print(f'  [OK] {date}: nothing to update')
        return False


def main():
    if not os.path.exists(LOG_DIR):
        print(f'[ERR] {LOG_DIR} not found')
        sys.exit(1)

    if len(sys.argv) > 1:
        dates = [sys.argv[1]]
    else:
        dates = []
        for f in os.listdir(LOG_DIR):
            m = re.match(r'^(\d{4}-\d{2}-\d{2})_feedback\.json$', f)
            if m:
                dates.append(m.group(1))
        dates.sort()

    print(f'[*] processing {len(dates)} date(s): {dates}')
    any_changed = False
    for d in dates:
        print(f'\n[date] {d}')
        if process_date(d):
            any_changed = True

    if any_changed:
        print('\n[OK] some responses updated, remember to commit + push')
    else:
        print('\n[OK] nothing to update')


if __name__ == '__main__':
    main()
