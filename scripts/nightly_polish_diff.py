"""
每晚对比 polished/*.json vs translations/NN.json
- 段落级 + 句子级 diff
- 调用 Claude Opus 4.7 分析改动模式
- 输出到 data/{date}/diff_analysis.json
- 累积到 STYLE_PROFILE.md
- 词库错译记录供后续写回 data/dict.json
-
若用户改用 GPT 网页端翻译并只把最终稿贴入腾讯文档，本脚本也会用
sources/NN.json + polished/*.json 提取保守的词库候选，写入学习候选池。
"""
import json, os, glob, sys, re, urllib.request, datetime, hashlib
from learning_quality import align_paragraphs, candidate_quality, promotion_status
from rebuild_translation_memory import rebuild_memory

DATE = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime('%Y-%m-%d')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY_DIR = os.path.join(REPO, 'data', DATE)
PROFILE = os.path.join(REPO, 'STYLE_PROFILE.md')
DATA_DIR = os.path.join(REPO, 'data')
LEARNING_DIR = os.path.join(DATA_DIR, 'learning')
EVIDENCE_PATH = os.path.join(LEARNING_DIR, 'style-evidence.json')
DAILY_LEARNING_DIR = os.path.join(LEARNING_DIR, 'daily')
DICT_CATEGORIES = ('games', 'movies_tv', 'companies', 'people', 'media', 'terms')

STOP_TITLE_WORDS = {
    'A', 'An', 'And', 'Are', 'As', 'At', 'Be', 'But', 'By', 'Can', 'For',
    'From', 'Has', 'Have', 'He', 'Her', 'His', 'How', 'If', 'In', 'Into',
    'Is', 'It', 'Its', 'New', 'No', 'Not', 'Of', 'On', 'Or', 'Our', 'Out',
    'Says', 'See', 'Set', 'Sets', 'Should', 'That', 'The', 'Their', 'This',
    'To', 'Up', 'Was', 'What', 'When', 'Where', 'Who', 'Why', 'Will', 'With',
}

TITLE_VERBS = {
    'Sets', 'Plots', 'Reveals', 'Announces', 'Gets', 'Confirms', 'Shows',
    'Says', 'Adds', 'Launches', 'Returns', 'Delayed', 'Coming', 'Arrives',
}

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

def load_json_default(path, default):
    if not os.path.exists(path):
        return default
    try:
        return load_json(path)
    except Exception:
        return default

def split_sentences(text):
    """中文句子拆分，按 。！？；以及换行"""
    if not text: return []
    parts = re.split(r'(?<=[。！？；])', text)
    return [p.strip() for p in parts if p.strip()]

def diff_paragraphs(my_paras, your_paras):
    """序列对齐后的段落 diff，避免插入/删除导致后续整篇错位。"""
    return align_paragraphs(my_paras, your_paras)

def split_polished_body(value):
    if not value:
        return []
    chunks = [p.strip() for p in re.split(r'\n{2,}', value) if p.strip()]
    if len(chunks) <= 1:
        chunks = [p.strip() for p in value.splitlines() if p.strip()]
    return chunks

def polished_paragraphs(polish):
    paragraphs = polish.get('paragraphs')
    if isinstance(paragraphs, list):
        out = []
        for para in paragraphs:
            if isinstance(para, str):
                text = para
            elif isinstance(para, dict):
                text = str(para.get('cn') or para.get('text') or '')
            else:
                text = ''
            text = text.strip()
            if text:
                out.append(text)
        if out:
            return out
    return split_polished_body(polish.get('body') or '')

def source_paragraphs(source):
    paragraphs = source.get('paragraphs_en')
    if isinstance(paragraphs, list):
        out = [str(p or '').strip() for p in paragraphs if str(p or '').strip()]
        if out:
            return out
    body = str(source.get('body_en') or '').strip()
    if body:
        return [p.strip() for p in re.split(r'\n+', body) if p.strip()]
    return []

def load_source(date, article_id):
    path = os.path.join(REPO, 'data', date, 'sources', f'{article_id:02d}.json')
    if not os.path.exists(path):
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}

def load_dictionary():
    path = os.path.join(REPO, 'data', 'dict.json')
    data = load_json_default(path, {})
    known = set()
    rows = {}
    if not isinstance(data, dict):
        return known, rows
    for cat, items in data.items():
        if cat == '_meta' or not isinstance(items, dict):
            continue
        for en, value in items.items():
            en_text = str(en or '').strip()
            if not en_text:
                continue
            known.add(en_text.casefold())
            rows[en_text.casefold()] = {'en': en_text, 'cat': cat, 'value': value}
    return known, rows

def compact_spaces(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()

def clean_english_candidate(text):
    value = compact_spaces(text)
    value = re.sub(r'\s+([:,&/])\s+', r'\1 ', value)
    value = re.sub(r'\s+([,.!?])$', '', value)
    value = value.strip(" -—:;,.!?\"'“”‘’[]()")
    return value

def likely_english_candidate(text):
    value = clean_english_candidate(text)
    if len(value) < 2 or len(value) > 80:
        return False
    if value in STOP_TITLE_WORDS:
        return False
    if not re.search(r'[A-Za-z]', value):
        return False
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'.-]*", value)
    if not words:
        return False
    if len(words) == 1 and words[0] in STOP_TITLE_WORDS:
        return False
    if len(words) > 9:
        return False
    lower = value.lower()
    if any(x in lower for x in ('http', 'twitter', 'photo by', 'box office total', 'mainstream movies')):
        return False
    return True

def source_title_candidates(title):
    title = compact_spaces(title)
    out = []
    if not title:
        return out
    for m in re.finditer(r"\b([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\s+Says\b", title):
        candidate = clean_english_candidate(m.group(1))
        if likely_english_candidate(candidate):
            out.append(candidate)
    # Prefer the leading work/person name before common headline verbs.
    tokens = title.split()
    for i, token in enumerate(tokens):
        clean = token.strip(" -—:;,.!?\"'“”‘’[]()")
        if i > 0 and clean in TITLE_VERBS:
            candidate = clean_english_candidate(' '.join(tokens[:i]))
            if ':' in candidate and likely_english_candidate(candidate):
                out.append(candidate)
            break
    return drop_prefix_duplicates(unique_keep_order(out))

def extract_english_candidates(text):
    source = compact_spaces(text)
    candidates = []
    patterns = [
        r"\b[A-Z][A-Za-z0-9'.-]+(?:\s*:\s*[A-Z0-9][A-Za-z0-9'.-]+)+(?:\s+[0-9IVX]+)?",
        r"\b[A-Z][A-Za-z0-9'.-]+(?:\s+[A-Z0-9][A-Za-z0-9'.-]+){1,5}\b",
        r"\b[A-Z]{2,}(?:/[A-Z][A-Za-z]+)?\b",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, source):
            value = clean_english_candidate(m.group(0))
            if likely_english_candidate(value):
                candidates.append(value)
    return unique_keep_order(candidates)

def extract_chinese_titles(text):
    return unique_keep_order(m.strip() for m in re.findall(r'《([^》]{2,40})》', text or '') if m.strip())

def leading_chinese_name(text):
    value = str(text or '').strip()
    m = re.match(r'^([\u4e00-\u9fff]{1,8}·[\u4e00-\u9fff]{1,5})(?=[:：])', value)
    return m.group(1) if m else ''

def drop_prefix_duplicates(items):
    values = unique_keep_order(items)
    out = []
    for item in values:
        key = item.casefold()
        if any(other.casefold() != key and other.casefold().startswith(key + ' ') for other in values):
            continue
        if any(other.casefold() != key and other.casefold().startswith(key + ':') for other in values):
            continue
        out.append(item)
    return out

def unique_keep_order(items):
    out = []
    seen = set()
    for item in items:
        value = str(item or '').strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out

def infer_category(article, en, cn):
    category = str((article or {}).get('category') or '').lower()
    looks_like_work = ':' in en or '：' in cn or re.search(r'\d', en)
    if re.search(r'[\u4e00-\u9fff]+·[\u4e00-\u9fff]+', cn):
        return 'people'
    if any(x in category for x in ('影视', '电影', 'tv', 'movie', 'film', 'anime')):
        if cn.startswith('《') or '《' in cn or looks_like_work:
            return 'movies_tv'
        return 'people' if re.search(r'\s', en) else 'terms'
    if any(x in category for x in ('游戏', 'game')):
        return 'games'
    if cn.startswith('《') or '《' in cn:
        return 'media'
    return 'terms'

def dict_candidate_id(en, cn=None):
    # Identity is the English entity. Competing Chinese mappings must collide
    # in one evidence record so contradictions remain visible.
    digest = hashlib.sha1(en.casefold().encode('utf-8')).hexdigest()[:12]
    slug = re.sub(r'[^a-z0-9]+', '_', en.lower()).strip('_')[:40] or 'term'
    return f'dict_candidate_{slug}_{digest}'

def source_text_for_candidate(source):
    return '\n'.join([
        str(source.get('title_en') or source.get('en_title') or ''),
        str(source.get('summary_en') or ''),
        *source_paragraphs(source),
    ])

def add_candidate(candidates, seen, *, date, article_id, article, en, cn, evidence,
                  confidence='medium', source_text='', origin='heuristic'):
    en = clean_english_candidate(en)
    cn = str(cn or '').strip('《》 \t\r\n')
    if not likely_english_candidate(en) or not cn:
        return
    if en.casefold() in seen['dict']:
        return
    quality = candidate_quality(en, cn, source_text=source_text, origin=origin)
    if not quality['accepted_as_evidence']:
        return
    key = (en.casefold(), cn)
    if key in seen['candidates']:
        return
    seen['candidates'].add(key)
    cat = infer_category(article, en, cn)
    rule_id = dict_candidate_id(en, cn)
    candidates.append({
        'id': rule_id,
        'category': 'dictionary',
        'type': 'dictionary_candidate',
        'dict_category': cat if cat in DICT_CATEGORIES else 'terms',
        'en': en,
        'cn': cn,
        'title': f'词库候选：{en} → {cn}',
        'rule': f'建议将「{en}」加入词库，译为「{cn}」。',
        'status': 'observed',
        'semantic_review': 'pending',
        'quality': quality,
        'confidence': confidence,
        'date': date,
        'article_id': article_id,
        'article_title': article.get('cn_title') or article.get('title') or '',
        'url': article.get('url') or '',
        'evidence': evidence,
    })

def extract_dictionary_candidates(date, article_id, article, polish, source, known_dict):
    candidates = []
    seen = {'dict': known_dict, 'candidates': set()}
    source_title = str(source.get('title_en') or source.get('en_title') or article.get('en_title') or '')
    polish_title = str(polish.get('title') or polish.get('cn_title') or '')
    source_paras = source_paragraphs(source)
    polish_paras = polished_paragraphs(polish)

    title_cns = extract_chinese_titles(polish_title)
    title_ens = source_title_candidates(source_title)
    for en in title_ens:
        if title_cns:
            add_candidate(
                candidates, seen,
                date=date, article_id=article_id, article=article,
                en=en, cn=title_cns[0],
                evidence='英文标题开头专名与中文标题书名号对应。',
                confidence='medium', source_text=source_text_for_candidate(source), origin='headline_pair',
            )
    title_cn_name = leading_chinese_name(polish_title)
    if title_cn_name:
        for en in title_ens:
            if ':' in en:
                continue
            add_candidate(
                candidates, seen,
                date=date, article_id=article_id, article=article,
                en=en, cn=title_cn_name,
                evidence='英文标题人名与中文标题冒号前译名对应。',
                confidence='medium', source_text=source_text_for_candidate(source), origin='headline_pair',
            )

    # Tencent/polished files may carry pending_dict generated by article page.
    for item in polish.get('pending_dict') or article.get('pending_dict') or []:
        if not isinstance(item, dict):
            continue
        add_candidate(
            candidates, seen,
            date=date, article_id=article_id, article=article,
            en=item.get('en') or '', cn=item.get('cn') or '',
            evidence='来自文章页未确认新词候选。',
            confidence='high', source_text=source_text_for_candidate(source), origin='pending_dict',
        )

    return candidates[:25]

def merge_evidence(candidates):
    if not candidates:
        return False
    evidence = load_json_default(EVIDENCE_PATH, {'version': 1, 'rules': {}})
    if not isinstance(evidence, dict):
        evidence = {'version': 1, 'rules': {}}
    rules = evidence.setdefault('rules', {})
    changed = False
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
    for cand in candidates:
        rid = cand['id']
        existing = rules.get(rid)
        example = {
            'date': cand['date'],
            'article_id': cand['article_id'],
            'before': cand['en'],
            'after': cand['cn'],
            'evidence': cand.get('evidence', ''),
        }
        if not isinstance(existing, dict):
            rules[rid] = {
                'id': rid,
                'title': cand['title'],
                'rule': cand['rule'],
                'category': 'dictionary',
                'type': 'dictionary_candidate',
                'dict_category': cand.get('dict_category', 'terms'),
                'scope': 'all',
                'status': 'observed',
                'semantic_review': 'pending',
                'days': [cand['date']],
                'days_seen': 1,
                'articles_seen': 1,
                'contradictions': 0,
                'alternatives': {cand['cn']: 1},
                'examples': [example],
                'created_at': now,
                'last_seen': cand['date'],
                'confidence': 0.65 if cand.get('confidence') == 'medium' else 0.8,
                'latest_evidence_summary': cand.get('evidence', ''),
                'candidate_payload': {
                    'en': cand['en'],
                    'cn': cand['cn'],
                    'cat': cand.get('dict_category', 'terms'),
                    'source': 'user',
                },
            }
            changed = True
            continue

        if cand['cn'] != (existing.get('candidate_payload') or {}).get('cn'):
            alternatives = existing.setdefault('alternatives', {})
            alternatives[cand['cn']] = int(alternatives.get(cand['cn'], 0)) + 1
            existing['contradictions'] = max(1, len(alternatives) - 1)
            existing['status'] = 'observed'
            changed = True
        days = existing.setdefault('days', [])
        if cand['date'] not in days:
            days.append(cand['date'])
            existing['days_seen'] = len(set(days))
            changed = True
        examples = existing.setdefault('examples', [])
        if not any(e.get('date') == example['date'] and e.get('article_id') == example['article_id'] for e in examples if isinstance(e, dict)):
            examples.append(example)
            existing['articles_seen'] = len({(e.get('date'), e.get('article_id')) for e in examples if isinstance(e, dict)})
            existing['last_seen'] = cand['date']
            existing['latest_evidence_summary'] = cand.get('evidence', '')
            changed = True
        existing['status'] = promotion_status(
            days_seen=int(existing.get('days_seen', 0) or 0),
            articles_seen=int(existing.get('articles_seen', 0) or 0),
            contradictions=int(existing.get('contradictions', 0) or 0),
            semantic_review=str(existing.get('semantic_review') or 'pending'),
        )
    if changed:
        save_json(EVIDENCE_PATH, evidence)
    return changed

def update_daily_learning(date, candidates):
    if not candidates:
        return False
    path = os.path.join(DAILY_LEARNING_DIR, f'{date}.json')
    daily = load_json_default(path, {
        'date': date,
        'observer': 'codex',
        'model': 'codex',
        'status': 'observed',
        'signals': [],
        'candidates': [],
        'notes': [],
    })
    if not isinstance(daily, dict):
        daily = {'date': date, 'observer': 'codex', 'model': 'codex', 'status': 'observed', 'signals': [], 'candidates': [], 'notes': []}
    existing_ids = {c.get('id') for c in daily.get('candidates', []) if isinstance(c, dict)}
    changed = False
    for cand in candidates:
        if cand['id'] in existing_ids:
            continue
        daily.setdefault('candidates', []).append({
            'id': cand['id'],
            'category': 'dictionary',
            'type': 'dictionary_candidate',
            'title': cand['title'],
            'rule': cand['rule'],
            'status': 'observed',
            'semantic_review': 'pending',
            'confidence': cand.get('confidence', 'medium'),
            'examples': [{
                'date': cand['date'],
                'article_id': cand['article_id'],
                'before': cand['en'],
                'after': cand['cn'],
                'evidence': cand.get('evidence', ''),
            }],
            'contradiction': '',
        })
        changed = True
    if changed:
        daily['candidate_count'] = len(daily.get('candidates', []))
        daily['updated_at'] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
        note = 'Added source+polished dictionary candidates for GPT/Tencent workflow.'
        notes = daily.setdefault('notes', [])
        if note not in notes:
            notes.append(note)
        save_json(path, daily)
    return changed

def collect_diffs(date):
    polished_dir = os.path.join(REPO, 'data', date, 'polished')
    trans_dir = os.path.join(REPO, 'data', date, 'translations')
    if not os.path.isdir(polished_dir):
        print(f'No polished/ folder at {polished_dir}')
        return []
    
    diffs = []
    # 只看 _index.json 中有记录的 id（被重置的不计入）
    index_path = os.path.join(polished_dir, '_index.json')
    if not os.path.exists(index_path):
        print(f'No _index.json at {index_path} — nothing to learn from')
        return []
    try:
        polish_index = load_json(index_path)
    except Exception as e:
        print(f'Failed reading {index_path}: {e}')
        return []
    if not polish_index:
        print('_index.json is empty — nothing to learn from')
        return []

    print(f'Found {len(polish_index)} polished articles in _index.json: ids={sorted(map(int, polish_index.keys()))}')
    known_dict, _ = load_dictionary()

    for id_str, filename in polish_index.items():
        article_id = int(id_str)
        pfile = os.path.join(polished_dir, filename)
        if not os.path.exists(pfile):
            print(f'  WARN: polished file not found for #{article_id}: {filename}')
            continue
        polish = load_json(pfile)
        tfile = os.path.join(trans_dir, f'{article_id:02d}.json')
        trans = {}
        if os.path.exists(tfile):
            trans = load_json(tfile)
        else:
            print(f'  INFO: translation not found for #{article_id}; using source+polished for dictionary candidates')
        source = load_source(date, article_id)
        article_meta = {
            'id': article_id,
            'cn_title': polish.get('title') or polish.get('cn_title') or trans.get('cn_title') or '',
            'en_title': polish.get('en_title') or trans.get('en_title') or source.get('title_en') or source.get('en_title') or '',
            'url': polish.get('url') or trans.get('url') or source.get('url') or '',
            'category': polish.get('category') or trans.get('category') or source.get('category') or '',
            'pending_dict': polish.get('pending_dict') or trans.get('pending_dict') or [],
        }
        dictionary_candidates = extract_dictionary_candidates(date, article_id, article_meta, polish, source, known_dict) if source else []
        
        # 标题对比
        title_diff = None
        if trans and (polish.get('title') or '').strip() != (trans.get('cn_title') or '').strip():
            title_diff = {
                'mine': trans.get('cn_title', ''),
                'yours': polish.get('title', ''),
            }
        
        # 副标题对比
        subtitle_diff = None
        polish_sub = (polish.get('subtitle') or '').strip()
        trans_sub = (trans.get('subtitle') or trans.get('cn_subtitle') or trans.get('summary') or '').strip()
        if trans and polish_sub != trans_sub:
            subtitle_diff = {
                'mine': trans_sub,
                'yours': polish_sub,
            }
        
        # 正文段落对比
        my_paras = [p.get('cn', '') for p in trans.get('paragraphs', [])]
        your_paras = polished_paragraphs(polish)
        body_diffs = diff_paragraphs(my_paras, your_paras) if trans else []
        
        if not (title_diff or subtitle_diff or body_diffs or dictionary_candidates):
            continue  # 完全没改
        
        diffs.append({
            'id': article_id,
            'cn_title': article_meta.get('cn_title'),
            'en_title': article_meta.get('en_title'),
            'url': article_meta.get('url'),
            'category': article_meta.get('category'),
            'has_translation': bool(trans),
            'title_diff': title_diff,
            'subtitle_diff': subtitle_diff,
            'body_diffs': body_diffs,
            'dictionary_candidates': dictionary_candidates,
        })
    return diffs

def call_claude(prompt):
    """调用工蜂 AI Claude Opus 4.7"""
    # OpenClaw 内置工蜂 AI 端点
    # 注：这里假设主 session 的 model API 可用，但脚本里没有主 session
    # → 降级方案：直接生成文本格式 diff，主 session 读了再分析
    return None

def main():
    rebuild_memory()
    print(f'Analyzing diffs for {DATE}...')
    diffs = collect_diffs(DATE)
    if not diffs:
        print('No polished articles or no diffs.')
        return
    
    print(f'Found {len(diffs)} articles with edits:')
    for d in diffs:
        print(f'  #{d["id"]} {d["cn_title"]}')
        if d['title_diff']:
            print(f'    Title: 「{d["title_diff"]["mine"]}」→「{d["title_diff"]["yours"]}」')
        if d['subtitle_diff']:
            print(f'    Sub: 「{d["subtitle_diff"]["mine"][:30]}」→「{d["subtitle_diff"]["yours"][:30]}」')
        if d['body_diffs']:
            print(f'    Body: {len(d["body_diffs"])} paragraph(s) changed')
        if d.get('dictionary_candidates'):
            print(f'    Dict candidates: {len(d["dictionary_candidates"])}')

    dictionary_candidates = []
    for d in diffs:
        dictionary_candidates.extend(d.get('dictionary_candidates') or [])
    evidence_changed = merge_evidence(dictionary_candidates)
    daily_changed = update_daily_learning(DATE, dictionary_candidates)
    
    # 保存结构化 diff
    out_path = os.path.join(REPO, 'data', DATE, 'diff_analysis.json')
    save_json(out_path, {
        'date': DATE,
        'generated_at': datetime.datetime.now().isoformat(),
        'total_articles': len(diffs),
        'dictionary_candidate_count': len(dictionary_candidates),
        'dictionary_candidates': dictionary_candidates,
        'learning_evidence_updated': bool(evidence_changed),
        'daily_learning_updated': bool(daily_changed),
        'articles': diffs,
    })
    print(f'\nDiff saved to: {out_path}')
    print('\n→ Now invoke main session (Opus 4.7) to analyze patterns and update STYLE_PROFILE.md')

if __name__ == '__main__':
    main()
