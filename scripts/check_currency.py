"""
Post-translation currency check.
Scans all translation JSONs for a given date, finds monetary amounts
(美元/欧元/英镑/日元) that are NOT followed by a CNY conversion,
and reports them. Run after translating to catch missed conversions.

Usage: python3 scripts/check_currency.py [YYYY-MM-DD]
Default: today's date.
"""
import json, re, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

WORKSPACE = Path(r'C:\Users\Administrator\.openclaw\workspace')
TRANS_BASE = WORKSPACE / 'ign-daily' / 'data'

# Determine date
if len(sys.argv) > 1:
    date_str = sys.argv[1]
else:
    cst = timezone(timedelta(hours=8))
    date_str = datetime.now(cst).strftime('%Y-%m-%d')

TRANS_DIR = TRANS_BASE / date_str / 'translations'
if not TRANS_DIR.exists():
    print(f"No translations dir for {date_str}")
    sys.exit(0)

# Load exchange rates
rates_path = WORKSPACE / 'exchange_rates.json'
if rates_path.exists():
    with open(rates_path, 'r') as f:
        rates_data = json.load(f)
    rates = rates_data.get('rates_to_cny', {})
else:
    rates = {}

# Regex: find currency amounts NOT followed by conversion
currency_re = re.compile(r'([\d,.]+)\s*(美元|欧元|英镑|日元)')
issues = []

for f in sorted(TRANS_DIR.glob('*.json')):
    with open(f, 'r', encoding='utf-8') as fh:
        d = json.load(fh)
    
    for i, p in enumerate(d.get('paragraphs', [])):
        cn = p.get('cn', '')
        for m in currency_re.finditer(cn):
            end = m.end()
            # Check next 40 chars for conversion
            after = cn[end:end+40]
            if '约合' not in after and '人民币' not in after:
                # Exception: if amount is in a quote context or repeated mention
                # Check if it's the first occurrence in this article
                amount_str = m.group(1)
                currency = m.group(2)
                
                # Suggest conversion
                try:
                    num = float(amount_str.replace(',', ''))
                    rate_key = {'美元': 'USD', '欧元': 'EUR', '英镑': 'GBP', '日元': 'JPY_100'}.get(currency, '')
                    rate = rates.get(rate_key, 0)
                    if '日元' in currency:
                        cny = int(num / 100 * rate)
                    else:
                        cny = int(num * rate)
                    suggestion = f"{amount_str}{currency}(约合人民币{cny}元)"
                except:
                    cny = '?'
                    suggestion = f"{amount_str}{currency}(约合人民币?元)"
                
                issues.append({
                    'file': f.name,
                    'para': i,
                    'found': m.group(),
                    'suggestion': suggestion,
                    'context': cn[max(0, m.start()-10):end+30]
                })

if issues:
    print(f"⚠️ CURRENCY_CHECK: {len(issues)} amount(s) missing CNY conversion:")
    for iss in issues:
        print(f"  {iss['file']} para[{iss['para']}]: {iss['found']} → suggest: {iss['suggestion']}")
        print(f"    context: ...{iss['context']}...")
    print()
    print("Fix these before pushing!")
    sys.exit(1)
else:
    print(f"✅ CURRENCY_CHECK: All amounts in {date_str} have CNY conversions.")
    sys.exit(0)
