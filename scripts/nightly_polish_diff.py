"""
每晚对比 polished/*.json vs translations/NN.json
- 段落级 + 句子级 diff
- 调用 Claude Opus 4.7 分析改动模式
- 输出到 data/{date}/diff_analysis.json
- 累积到 STYLE_PROFILE.md
- 词库错译写回 game_names_dict.json
"""
import json, os, glob, sys, re, urllib.request, datetime

DATE = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime('%Y-%m-%d')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY_DIR = os.path.join(REPO, 'data', DATE)
PROFILE = os.path.join(REPO, 'STYLE_PROFILE.md')

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def split_sentences(text):
    """中文句子拆分，按 。！？；以及换行"""
    if not text: return []
    parts = re.split(r'(?<=[。！？；])', text)
    return [p.strip() for p in parts if p.strip()]

def diff_paragraphs(my_paras, your_paras):
    """段落级和句子级 diff"""
    out = []
    n = max(len(my_paras), len(your_paras))
    for i in range(n):
        mine = my_paras[i] if i < len(my_paras) else ''
        yours = your_paras[i] if i < len(your_paras) else ''
        if mine == yours: continue
        # 句子级
        my_sents = split_sentences(mine)
        your_sents = split_sentences(yours)
        out.append({
            'index': i,
            'mine': mine,
            'yours': yours,
            'my_sentences': my_sents,
            'your_sentences': your_sents,
        })
    return out

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

    for id_str, filename in polish_index.items():
        article_id = int(id_str)
        pfile = os.path.join(polished_dir, filename)
        if not os.path.exists(pfile):
            print(f'  WARN: polished file not found for #{article_id}: {filename}')
            continue
        polish = load_json(pfile)
        tfile = os.path.join(trans_dir, f'{article_id:02d}.json')
        if not os.path.exists(tfile):
            print(f'  WARN: translation not found for #{article_id}')
            continue
        trans = load_json(tfile)
        
        # 标题对比
        title_diff = None
        if (polish.get('title') or '').strip() != (trans.get('cn_title') or '').strip():
            title_diff = {
                'mine': trans.get('cn_title', ''),
                'yours': polish.get('title', ''),
            }
        
        # 副标题对比
        subtitle_diff = None
        polish_sub = (polish.get('subtitle') or '').strip()
        trans_sub = (trans.get('subtitle') or trans.get('cn_subtitle') or trans.get('summary') or '').strip()
        if polish_sub != trans_sub:
            subtitle_diff = {
                'mine': trans_sub,
                'yours': polish_sub,
            }
        
        # 正文段落对比
        my_paras = [p.get('cn', '') for p in trans.get('paragraphs', [])]
        your_paras = [p.strip() for p in (polish.get('body') or '').split('\n\n') if p.strip()]
        body_diffs = diff_paragraphs(my_paras, your_paras)
        
        if not (title_diff or subtitle_diff or body_diffs):
            continue  # 完全没改
        
        diffs.append({
            'id': article_id,
            'cn_title': trans.get('cn_title'),
            'en_title': trans.get('en_title'),
            'url': trans.get('url'),
            'category': trans.get('category'),
            'title_diff': title_diff,
            'subtitle_diff': subtitle_diff,
            'body_diffs': body_diffs,
        })
    return diffs

def call_claude(prompt):
    """调用工蜂 AI Claude Opus 4.7"""
    # OpenClaw 内置工蜂 AI 端点
    # 注：这里假设主 session 的 model API 可用，但脚本里没有主 session
    # → 降级方案：直接生成文本格式 diff，主 session 读了再分析
    return None

def main():
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
    
    # 保存结构化 diff
    out_path = os.path.join(REPO, 'data', DATE, 'diff_analysis.json')
    save_json(out_path, {
        'date': DATE,
        'generated_at': datetime.datetime.now().isoformat(),
        'total_articles': len(diffs),
        'articles': diffs,
    })
    print(f'\nDiff saved to: {out_path}')
    print('\n→ Now invoke main session (Opus 4.7) to analyze patterns and update STYLE_PROFILE.md')

if __name__ == '__main__':
    main()
