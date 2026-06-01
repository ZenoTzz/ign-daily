"""
Post-generation dictionary enforcement.
Run after index.json is generated/updated to flag cn_titles that do not match
the active dictionary entries. The active dictionary is normally data/dict.json.

Usage:
    python3 scripts/enforce_dict_titles.py [date]
    (date defaults to today in YYYY-MM-DD format)
"""
import json
import sys
import os
from datetime import datetime, timezone, timedelta
from common_paths import DATA_DIR, dict_path, configure_utf8_stdio

configure_utf8_stdio()

CST = timezone(timedelta(hours=8))

def get_date():
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now(CST).strftime('%Y-%m-%d')

def load_dict(dict_path):
    with open(dict_path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    
    all_terms = {}
    standard_cats = ['games', 'movies_tv', 'companies', 'people', 'terms', 'media']
    for cat_key, cat_val in d.items():
        if cat_key == '_meta':
            continue
        if cat_key in standard_cats:
            for en, info in cat_val.items():
                if isinstance(info, dict) and info.get('cn'):
                    all_terms[en] = info['cn']
        else:
            if isinstance(cat_val, dict) and 'cn' in cat_val:
                all_terms[cat_key] = cat_val['cn']
    
    # Sort by length descending (longer matches first to avoid partial overwrites)
    sorted_terms = sorted(all_terms.items(), key=lambda x: len(x[0]), reverse=True)
    return sorted_terms

def enforce(index_path, dict_terms):
    with open(index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    fixes = []
    for a in data['articles']:
        en_title = a['en_title']
        cn_title = a['cn_title']
        en_lower = en_title.lower()
        new_cn = cn_title
        
        for en_term, cn_term in dict_terms:
            term_lower = en_term.lower()
            # Skip if this is a substring match inside a longer word
            # e.g. "Doom" matching "Doomsday" should be skipped
            pos = en_lower.find(term_lower)
            if pos == -1:
                continue
            
            # Verify it's a proper word boundary match
            end_pos = pos + len(term_lower)
            # Check char before
            if pos > 0 and en_lower[pos-1].isalnum():
                continue
            # Check char after
            if end_pos < len(en_lower) and en_lower[end_pos].isalnum():
                # Allow if next char is common suffix like 's, 'period, colon, etc.
                next_char = en_lower[end_pos]
                if next_char not in ("'", "'", ":", ",", ".", " ", "-", "!"):
                    continue
            
            # cn_term should be in the cn_title
            if cn_term not in new_cn:
                # Try to find what the model used instead and replace it
                # For now, we can't auto-replace arbitrary text in cn_title
                # Just flag it
                fixes.append({
                    'id': a['id'],
                    'en_term': en_term,
                    'expected_cn': cn_term,
                    'current_cn': new_cn
                })
    
    return fixes, data

def main():
    date = get_date()
    active_dict_path = dict_path()
    index_path = DATA_DIR / date / 'index.json'
    
    if not index_path.exists():
        print(f"No index.json for {date}")
        sys.exit(0)
    
    if not active_dict_path.exists():
        print(f"No dictionary found at {active_dict_path}")
        sys.exit(1)
    
    dict_terms = load_dict(active_dict_path)
    fixes, data = enforce(index_path, dict_terms)
    
    if not fixes:
        print("ALL_CLEAR: All cn_titles match dictionary.")
    else:
        print(f"DICT_MISMATCH: {len(fixes)} title(s) may not match dictionary:")
        for fix in fixes:
            print(f"  #{fix['id']}: '{fix['en_term']}' should appear as '{fix['expected_cn']}'")
            print(f"       current: {fix['current_cn']}")
    
    return len(fixes)

if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
