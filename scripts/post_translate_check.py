"""
Post-translation validation script.
Run after writing translation JSON files to catch common mistakes.

Usage: python3 scripts/post_translate_check.py [YYYY-MM-DD]
Default: today's date (Asia/Shanghai)
"""
import json, os, sys, re
from datetime import datetime, timezone, timedelta
from chinese_punctuation import disallowed_double_quotes
from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio

configure_utf8_stdio()

CST = timezone(timedelta(hours=8))
if len(sys.argv) > 1:
    date_str = sys.argv[1]
else:
    date_str = datetime.now(CST).strftime('%Y-%m-%d')

DAY_DIR = DATA_DIR / date_str
TRANS_DIR = DAY_DIR / 'translations'

errors = []
warnings = []

if not TRANS_DIR.exists():
    print(f"No translations directory for {date_str}")
    sys.exit(0)

# Load index to find which are 'done'
idx_path = DAY_DIR / 'index.json'
if not idx_path.exists():
    print(f"No index.json for {date_str}")
    sys.exit(1)

with open(idx_path, 'r', encoding='utf-8') as f:
    idx = json.load(f)

done_ids = [a['id'] for a in idx['articles'] if a.get('translation_status') == 'done']

for article in idx['articles']:
    index_text = '\n'.join(str(article.get(key) or '') for key in ('cn_title', 'subtitle', 'summary'))
    bad_quotes = disallowed_double_quotes(index_text)
    if bad_quotes:
        rendered = ' '.join(f'U+{ord(char):04X}' for char in bad_quotes)
        errors.append(f"#{article.get('id')}: non-corner double quote in index Chinese text ({rendered}); use「」")

for aid in done_ids:
    fname = f"{aid:02d}.json"
    fpath = TRANS_DIR / fname
    
    if not fpath.exists():
        errors.append(f"#{aid}: translation file {fname} MISSING but status=done")
        continue
    
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Check 1: cover must not be empty
    if not data.get('cover'):
        errors.append(f"#{aid}: MISSING cover image (og:image not extracted)")
    elif '?' in data['cover']:
        warnings.append(f"#{aid}: cover still has query params: {data['cover'][-40:]}")
    
    # Check 2: translated_terms must exist
    if not data.get('translated_terms'):
        errors.append(f"#{aid}: MISSING translated_terms snapshot")
    
    # Check 3: paragraphs must not be empty
    if not data.get('paragraphs') or len(data['paragraphs']) == 0:
        errors.append(f"#{aid}: paragraphs is EMPTY")
    
    # Check 4: subtitle must exist AND follow style rules
    subtitle = data.get('subtitle', '')
    if not subtitle:
        errors.append(f"#{aid}: MISSING subtitle (2-15字创意口语短句)")
    else:
        # Rule: 2-15 chars
        if len(subtitle) > 15:
            errors.append(f"#{aid}: subtitle TOO LONG ({len(subtitle)}字 > 15字上限): 「{subtitle}」")
        elif len(subtitle) < 2:
            errors.append(f"#{aid}: subtitle TOO SHORT ({len(subtitle)}字)")
        # Rule: should not contain comma/period (sign of being a sentence, not a punch phrase)
        if '，' in subtitle and len(subtitle) > 10:
            warnings.append(f"#{aid}: subtitle 含逗号且偏长，建议确认是否仍像短句: 「{subtitle}」")
        # Rule: should not duplicate cn_title content
        cn_title = ''
        for a in idx['articles']:
            if a['id'] == aid:
                cn_title = a.get('cn_title', '')
                break
        if cn_title and subtitle in cn_title:
            errors.append(f"#{aid}: subtitle 是 cn_title 的子串，不能重复标题内容")
        # Rule: detect "news summary" anti-patterns
        bad_patterns = [
            # Contains specific large numbers that signal summary not creativity
            (r'\d{3,}', '含大数字，像新闻摘要不像创意短句'),
            # Contains 「」quotes around long content (quoting article, not being punchy)
            (r'「.{8,}」', '内嵌长引用，像在复述文章内容'),
            # Contains person name with middle dot (e.g. 阿萨·夏尔玛)
            (r'[一-鿿]+·[一-鿿]+', '含人名，像新闻标题不像情绪短句'),
        ]
        import re as _re
        for pattern, reason in bad_patterns:
            if _re.search(pattern, subtitle):
                warnings.append(f"#{aid}: subtitle {reason}: 「{subtitle}」")
                break
        # Rule: should feel oral/colloquial — warn if all chars are formal
        # Good subtitles often have: !, ！, ~, emoji, 谐音, 口语词
        # If it reads like a complete grammatical sentence with subject+verb+object, flag it
        if len(subtitle) > 8 and not any(c in subtitle for c in '！？!?~') and '的' in subtitle and '了' in subtitle:
            warnings.append(f"#{aid}: subtitle 读起来像完整句子，建议更口语化: 「{subtitle}」")
    
    # Check 5: opus_summary must exist
    if not data.get('opus_summary'):
        errors.append(f"#{aid}: MISSING opus_summary")
    else:
        summary_len = len(re.sub(r'\s+', '', data.get('opus_summary', '')))
        if summary_len < 60 or summary_len > 110:
            errors.append(f"#{aid}: opus_summary LENGTH {summary_len}, target 70-80, allowed 60-110")
    
    # Check 6: Chinese text must use corner quotes, not straight/curly double quotes
    cn_texts = [data.get('cn_title', ''), data.get('opus_summary', '')]
    for p in data.get('paragraphs', []):
        if isinstance(p, dict):
            cn_texts.append(p.get('cn', ''))
    for txt in cn_texts:
        bad_quotes = disallowed_double_quotes(txt)
        if bad_quotes:
            rendered = ' '.join(f'U+{ord(char):04X}' for char in bad_quotes)
            errors.append(f"#{aid}: non-corner double quote in Chinese text ({rendered}); use「」")
            break
    
    # Check 7: currency amounts have CNY conversion
    for p in data.get('paragraphs', []):
        if isinstance(p, dict):
            cn = p.get('cn', '')
            # Find dollar/euro/yen amounts without CNY
            money_patterns = re.findall(r'(\d[\d,.]*)\s*(美元|欧元|日元|英镑)', cn)
            for amount, currency in money_patterns:
                if '人民币' not in cn and '元)' not in cn:
                    warnings.append(f"#{aid}: {amount}{currency} may lack CNY conversion")
                    break

# Check 8: AGENT_HANDOFF.md sync reminder
# Detect if app.js or index.html were modified today
import subprocess
try:
    result = subprocess.run(
        ['git', 'log', '--oneline', '--since=today', '--', 'assets/app.js', 'index.html', 'article.html', 'sw.js', 'manifest.json'],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    code_changes = result.stdout.strip()
    
    result2 = subprocess.run(
        ['git', 'log', '--oneline', '--since=today', '--', 'AGENT_HANDOFF.md'],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    doc_changes = result2.stdout.strip()
    
    if code_changes and not doc_changes:
        warnings.append("⚠️  Code files changed today but AGENT_HANDOFF.md NOT updated! Sync required.")
except Exception:
    pass  # git not available, skip

# Output
print(f"\n{'='*50}")
print(f"POST-TRANSLATE CHECK: {date_str}")
print(f"Translations checked: {len(done_ids)}")
print(f"{'='*50}")

if errors:
    print(f"\n🔴 ERRORS ({len(errors)}):")
    for e in errors:
        print(f"  ❌ {e}")

if warnings:
    print(f"\n🟡 WARNINGS ({len(warnings)}):")
    for w in warnings:
        print(f"  ⚠️  {w}")

if not errors and not warnings:
    print("\n✅ ALL CHECKS PASSED")
    sys.exit(0)
elif errors:
    print(f"\n🚫 BLOCKED: Fix {len(errors)} error(s) before pushing.")
    sys.exit(1)
else:
    print(f"\n⚠️  {len(warnings)} warning(s) — review before pushing.")
    sys.exit(0)
