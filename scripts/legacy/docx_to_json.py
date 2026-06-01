"""把已翻译的 docx 解析成 paragraphs 格式 JSON"""
import json
import os
from docx import Document

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
DATE = '2026-05-28'
DOCX_DIR = r'X:\IGN_Daily_News\2026年05月28日'

# 推送编号 → docx文件名
mapping = {
    5:  '05_勇者斗恶龙12超越梦境最新进展_05月28日.docx',
    6:  '06_Valve宣布Steam Deck大幅涨价_05月28日.docx',
    9:  '09_漫威传奇Stan Lee将被AI复活用于商业授权_05月28日.docx',
    12: '12_007 初露锋芒作曲师揭秘创作唯一规则_05月28日.docx',
    13: '13_命运2玩家策划涌入服务器抗议Bungie停服_05月28日.docx',
    14: '14_暴雪老板守望先锋2动画剧集不排除可能_05月28日.docx',
    22: '22_Planet Zoo 2几乎坐实YouTube频道悄然更新_05月28日.docx',
    23: '23_独家EA Sports FC 26世界杯主题更新首曝_05月28日.docx',
    31: '31_天国拯救开发商预告指环王开放世界RPG_05月28日.docx',
    32: '32_Take-Two强制GTA5 Rage MP关停并迁至FiveM_05月28日.docx',
}

# 当日索引
with open(os.path.join(REPO, 'data', DATE, 'index.json'), 'r', encoding='utf-8') as f:
    idx = json.load(f)
art_by_id = {a['id']: a for a in idx['articles']}

translated_at = '2026-05-28T11:00+08:00'

for push_id, fname in mapping.items():
    path = os.path.join(DOCX_DIR, fname)
    doc = Document(path)
    
    # 解析：分前后两半（中文翻译标题为分界）
    en_paras = []
    cn_paras = []
    
    en_title = ''
    cn_title = ''
    in_cn = False
    saw_cn_section = False
    
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        # Heading 1 = 英文/中文翻译标题
        if p.style.name == 'Heading 1':
            if not en_title:
                en_title = text
            elif '中文翻译' in text:
                in_cn = True
                saw_cn_section = True
            continue
        if p.style.name == 'Heading 2' and in_cn:
            cn_title = text
            continue
        if not in_cn:
            en_paras.append(text)
        else:
            cn_paras.append(text)
    
    # 段落对齐：去除标题后简单按顺序对齐
    # 期望英文段数 == 中文段数（我之前生成时段落是1:1）
    n = min(len(en_paras), len(cn_paras))
    paragraphs = []
    for i in range(n):
        paragraphs.append({'en': en_paras[i], 'cn': cn_paras[i]})
    # 多出来的尾部段也包进去
    for i in range(n, len(en_paras)):
        paragraphs.append({'en': en_paras[i], 'cn': ''})
    for i in range(n, len(cn_paras)):
        paragraphs.append({'en': '', 'cn': cn_paras[i]})
    
    # 输出
    art = art_by_id.get(push_id)
    out = {
        'id': push_id,
        'en_title': en_title or art.get('en_title',''),
        'cn_title': cn_title or art.get('cn_title',''),
        'url': art.get('url',''),
        'translated_at': translated_at,
        'paragraphs': paragraphs,
    }
    
    out_path = os.path.join(REPO, 'data', DATE, 'translations', f'{push_id:02d}.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'#{push_id}: {len(paragraphs)} paragraphs → {os.path.basename(out_path)}')

print('\nDone')
