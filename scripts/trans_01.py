"""翻译 #1 观点：$949 Steam Deck，Steam Machine 恐怕更贵"""
import json, os

REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
DATE = '2026-05-28'

paragraphs = [
    {
        "en": "The number goes up.",
        "cn": "数字只会越涨越高。"
    },
    {
        "en": "Updated: May 27, 2026 10:08pm UTC",
        "cn": "更新时间：2026年5月27日 22:08 UTC（北京时间5月28日 06:08）"
    },
    {
        "en": "In the six months since Valve announced the Steam Machine, PC gaming hardware has continued to get more expensive, and now that the Steam Deck has an official price increase, anyone hoping to get a Steam Machine for less than a thousand bucks is probably going to be disappointed.",
        "cn": "自Valve宣布Steam Machine以来的这六个月里，PC游戏硬件价格持续走高。如今Steam Deck已经官宣涨价，那些指望Steam Machine能卖到一千美元以下的玩家恐怕要失望了。"
    },
    {
        "en": "When I visited Valve to take an early look at the Steam Machine last year, I was told that the price would be competitive with a comparable gaming PC. My gut feeling at the time was that would mean a $1,200 sticker price, which I walked back on once I started doing the math, figuring it would settle at around $800. But I wasn't taking a months-long RAM crisis into consideration.",
        "cn": "去年我去Valve提前体验Steam Machine时，对方告诉我它的售价会和同等配置的游戏PC具有竞争力。当时我的直觉是大概会贴1,200美元（约人民币8,592元）的价签——但等我自己一算账，又把估价调低到800美元（约人民币5,728元）左右。问题是，我当时根本没把这场已经持续数月的内存（RAM）危机算进去。"
    },
    {
        "en": "Welcome to The Desert of the RAM",
        "cn": "欢迎来到「内存的荒漠」"
    },
    {
        "en": "In the months since this all started, there have been these momentary glimpses of lower prices. I've been using this basic kit of G.Skill Flare X5 RAM as a sort of barometer for the memory market, and right now it's 'on sale' for $404. That's a high price to be sure, but it is about 10% lower than it's been for months. But, like all the other dips that have happened recently, that price will probably bounce back up in a few days.",
        "cn": "自这一切开始以来的几个月里，价格偶尔会出现短暂回落。我一直拿一套入门级的G.Skill Flare X5内存作为内存市场的「晴雨表」，目前它「特价」售404美元（约人民币2,894元）。这价格当然依旧不便宜，但已经比前几个月便宜了大约10%。不过，和最近几次价格回调一样，这个价格大概几天后又会反弹回去。"
    },
    {
        "en": "Even back in January, I was told by analyst Anshel Sag that this RAM crisis would be a long-term affair, and that just continues to be the case. But at least for the first few months, DIY PC builders were facing most of the pain. For a while at least, prebuilt gaming PCs and laptops were eating the price while the manufacturers had inventory to spare. But it seems like those days are drawing to an end.",
        "cn": "早在今年1月，分析师Anshel Sag就告诉我，这场内存危机将是一场持久战——事实证明确实如此。不过至少在最初几个月，承受最大压力的是DIY自组PC玩家。在那段时间里，整机PC和笔记本厂商凭借手中尚有的库存，自己消化了部分涨价压力。但这样的日子似乎已经接近尾声。"
    },
    {
        "en": "Sony, Microsoft and Nintendo have all raised prices on their consoles, and now the Steam Deck has finally followed suit. In the short term, if you're in the market for a handheld gaming PC, you're probably best off trying to find something more affordable. For instance, the lower-tier Xbox Ally is still available at Best Buy for $599. You can even install SteamOS if you want a Steam-Deck like experience.",
        "cn": "索尼、微软和任天堂都已上调了主机售价，如今Steam Deck终于也跟进涨价。短期内如果你正在挑选一款掌上游戏PC，最好的策略是去找更便宜的型号。比如低配版Xbox Ally目前在Best Buy仍以599美元（约人民币4,289元）出售。如果你想要类似Steam Deck的体验，甚至可以自己装一套SteamOS上去。"
    },
    {
        "en": "Asus ROG Xbox Ally — The Asus ROG Xbox Ally comes with an AMD Ryzen Z2 A and the Xbox Full Screen Experience. You even get a trial of Xbox Games Pass.",
        "cn": "Asus ROG Xbox Ally——这款掌机搭载AMD Ryzen Z2 A处理器以及Xbox全屏体验（Full Screen Experience），还附赠Xbox Game Pass的试用资格。"
    },
    {
        "en": "But I have to imagine it's only a matter of time before the Xbox Ally goes up in price, too. After all, it also has RAM in there. It pains me to say it, but we're probably heading into an era where most gaming devices start at around $1,000. It wouldn't surprise me in the slightest if the PS5 and Xbox Series X get another price bump up to that point, either.",
        "cn": "但我得说，Xbox Ally涨价恐怕也只是时间问题——毕竟它里面也有内存。说出这话挺让人难受，但我们大概正在迈入一个大多数游戏设备起步价都在1,000美元（约人民币7,160元）左右的时代。如果PS5和Xbox Series X再次涨价、也涨到这个区间，我一点都不会意外。"
    },
    {
        "en": "Steam Machine In the Age of AI",
        "cn": "AI时代的Steam Machine"
    },
    {
        "en": "In the few posts Valve has made about the delayed Steam Deck, it has referenced the rising costs of hardware as the one thing holding its console back. At face value, it seems like the company is just holding the mini gaming PC back, hoping that prices will drop enough to launch the Steam Machine at a reasonable price. There will come a time, and probably soon, where everything is more expensive, and suddenly a $1,200 Steam Machine feels much more reasonable, especially if the consoles get another price bump.",
        "cn": "在为数不多几篇谈到Steam Machine延期的官方文章里，Valve一直把硬件成本上涨列为该主机迟迟不能发售的关键原因。表面上看，Valve似乎只是在「按住」这台迷你游戏PC，希望价格能下降到一个合理水平再让Steam Machine上市。但事实可能恰恰相反——很快会有那么一天，几乎所有东西都更贵了，到那时一台1,200美元的Steam Machine突然就显得「合理」起来——尤其是如果其他主机再涨一轮价的话。"
    },
    {
        "en": "Because, sure, a $1,200 gaming PC with the equivalent of an AMD Radeon RX 7600 or Nvidia RTX 4060 is a hard sell when the PS5 costs $599. But that math is going to look a lot different if Sony's console goes up to $699 or $799 for the digital version.",
        "cn": "毕竟，当PS5只卖599美元时，要把一台搭载相当于AMD Radeon RX 7600或Nvidia RTX 4060显卡的1,200美元游戏PC卖出去，确实很难。但如果索尼把PS5或PS5数字版涨到699美元（约人民币5,005元）甚至799美元（约人民币5,720元），这笔账算起来就完全是另一回事了。"
    },
    {
        "en": "We still don't know when the Steam Machine is actually going to come out, but with each passing day, it becomes less likely that it's going to squeeze in under $1,000. I'd love to be wrong, but when Valve finally turns that order button on, don't be surprised if it's accompanied by a four-digit number.",
        "cn": "我们至今还不知道Steam Machine到底何时发售，但每多过一天，它能够压在1,000美元以下的可能性就低一分。我当然希望自己是错的，但等Valve真正把「立即购买」按钮点亮的那一天，如果价格是个四位数，请不要太惊讶。"
    },
]

out = {
    'id': 1,
    'en_title': 'Opinion: With A $949 Steam Deck, The Steam Machine Will Probably Be Very Expensive',
    'cn_title': '观点：Steam Deck涨到$949，Steam主机恐怕更贵',
    'url': 'https://www.ign.com/articles/opinion-with-a-949-steam-deck-the-steam-machine-will-probably-be-very-expensive',
    'translated_at': '2026-05-28T11:00+08:00',
    'paragraphs': paragraphs,
}

out_path = os.path.join(REPO, 'data', DATE, 'translations', '01.json')
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(f'Saved: {out_path}')

# 更新 index.json
idx_path = os.path.join(REPO, 'data', DATE, 'index.json')
with open(idx_path, 'r', encoding='utf-8') as f:
    idx = json.load(f)
for a in idx['articles']:
    if a['id'] == 1:
        a['translation_status'] = 'done'
        a['translation_path'] = 'translations/01.json'
        break
with open(idx_path, 'w', encoding='utf-8') as f:
    json.dump(idx, f, ensure_ascii=False, indent=2)
print('Updated index.json: #1 → done')

# 更新 history
hist_path = os.path.join(REPO, 'data', 'index-list.json')
with open(hist_path, 'r', encoding='utf-8') as f:
    hist = json.load(f)
for d in hist:
    if d['date'] == DATE:
        translated = [a for a in idx['articles'] if a['translation_status'] == 'done']
        d['translated'] = len(translated)
        d['translatedTitles'] = [{'id': a['id'], 'cn_title': a['cn_title']} for a in translated]
        break
with open(hist_path, 'w', encoding='utf-8') as f:
    json.dump(hist, f, ensure_ascii=False, indent=2)
print('Updated index-list.json')
