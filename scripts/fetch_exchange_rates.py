"""每日拉取汇率，写入 workspace/exchange_rates.json
公开免费API: https://api.exchangerate-api.com/v4/latest/USD
备用: https://open.er-api.com/v6/latest/USD
"""
import json
import urllib.request
from datetime import datetime
import os, sys

OUT = r'C:\Users\Administrator\.openclaw\workspace\exchange_rates.json'

URLS = [
    'https://open.er-api.com/v6/latest/USD',
    'https://api.exchangerate-api.com/v4/latest/USD',
]

def fetch():
    last_err = None
    for url in URLS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8'))
                rates = data.get('rates') or {}
                if 'CNY' in rates:
                    return data, url
        except Exception as e:
            last_err = e
            print(f'[warn] {url}: {e}')
            continue
    raise RuntimeError(f'All sources failed: {last_err}')

def main():
    data, used_url = fetch()
    rates = data['rates']
    cny_per_usd = rates['CNY']

    # 计算其他常用货币
    # 1欧元 = (1/EUR_per_USD) USD * cny_per_usd
    eur = round(cny_per_usd / rates['EUR'], 2) if rates.get('EUR') else None
    jpy = round((cny_per_usd / rates['JPY']) * 100, 2) if rates.get('JPY') else None  # 100日元
    gbp = round(cny_per_usd / rates['GBP'], 2) if rates.get('GBP') else None
    krw = round((cny_per_usd / rates['KRW']) * 100, 2) if rates.get('KRW') else None  # 100韩元

    out = {
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S +08:00'),
        'source': used_url,
        'base': 'USD',
        'rates_to_cny': {
            'USD': round(cny_per_usd, 2),
            'EUR': eur,
            'JPY_100': jpy,
            'GBP': gbp,
            'KRW_100': krw,
        },
        'note': '人民币兑外币参考汇率，取2位小数。翻译时按金额×对应rate取整数。'
    }

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f'✅ Saved: {OUT}')
    print(f'  1 USD = {out["rates_to_cny"]["USD"]} CNY')
    print(f'  1 EUR = {out["rates_to_cny"]["EUR"]} CNY')
    print(f'  100 JPY = {out["rates_to_cny"]["JPY_100"]} CNY')
    print(f'  1 GBP = {out["rates_to_cny"]["GBP"]} CNY')
    print(f'  100 KRW = {out["rates_to_cny"]["KRW_100"]} CNY')

if __name__ == '__main__':
    main()
