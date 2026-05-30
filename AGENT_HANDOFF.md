# AGENT_HANDOFF.md - IGN Daily 项目交接文档

> 给接手这个项目的 AI agent 或开发者的完整操作手册。读完这个文件你就能运维整个系统。

---

## 🏗 架构总览

```
用户视角:
  网页 (GitHub Pages) ← 用户浏览新闻、勾选翻译、润色译文

后端(AI agent + cron + heartbeat):
  [心跳 每小时] RSS增量抓取 → 翻译标题/摘要 → push 到 GitHub
  [cron 8:20 AM] 兜底校验补漏 → 生成 Excel → 发通知
  [心跳 检测翻译请求] 用户勾选后 → Opus 翻译全文 → push
  [cron 22:30] nightly polish-diff 学习 → 更新 STYLE_PROFILE
```

### 核心工作流

| 阶段 | 触发 | 做什么 | 模型 |
|------|------|--------|------|
| RSS 抓取 | 心跳(每小时) | 增量抓 RSS → 翻译标题摘要 → push 网页 | Sonnet(轻量) |
| 兜底校验 | cron 8:20 | 重跑完整 RSS 对比补漏 → 生成 Excel → 通知 | Sonnet |
| 全文翻译 | 用户勾选 | web_fetch 原文 → 词库匹配 → Opus 翻译 → push | **Opus(最好模型)** |
| 夜间学习 | cron 22:30 | 对比润色前后 diff → 提取风格规则 → 更新 STYLE_PROFILE | Opus |

### 日期归属规则

**8:00 CST 为分界线:**
- `2026-05-29` 这个日期 = 5/28 08:00 → 5/29 08:00 期间发布的文章
- 8:00 之后发布的文章归入**下一天**

---

## 📁 项目结构

```
ign-daily/                          # GitHub Pages 仓库
├── index.html                      # 主页(新闻列表、日期切换、勾选翻译)
├── article.html                    # 译文详情页
├── dict.html                       # 词库管理页
├── history.html                    # 历史浏览
├── learning.html                   # 学习日志 & 批注
├── STYLE_PROFILE.md                # AI 学到的翻译风格规则
├── assets/
│   ├── app.js                      # 主页 Alpine.js 逻辑
│   └── style.css                   # 样式
├── scripts/
│   ├── build_today.py              # 构建脚本
│   └── ...
└── data/
    ├── index-list.json             # 所有日期列表(网页日期切换用)
    ├── 2026-05-29/
    │   ├── index.json              # 当天文章索引(核心文件)
    │   ├── requests.json           # 用户翻译请求
    │   ├── translations/           # 翻译 JSON
    │   │   ├── 02.json
    │   │   └── ...
    │   ├── polished/               # 用户润色后的版本
    │   │   ├── _index.json
    │   │   └── NN_标题.json
    │   └── diff_analysis.json      # nightly diff 分析结果
    └── learning_log/
        ├── _index.json
        ├── 2026-05-29.json         # 学习日志
        ├── 2026-05-29_feedback.json # 用户批注
        └── 2026-05-29_response.json # AI 对批注的回复
```

### workspace 关键文件

```
workspace/
├── game_names_dict.json            # 🔴 词库(翻译必查)
├── exchange_rates.json             # 汇率(金额翻译用)
├── ign_rss_fetch.py                # 完整 RSS 抓取脚本(cron 用)
├── ign_cron_message.txt            # cron 任务指令文本
├── ign_rss_raw.json                # 上次完整抓取的原始结果
├── ign_rss_new.json                # 增量脚本发现的新文章
├── IGN_TRANSLATE_INSTRUCTIONS.md   # 🔴 翻译详细规则
├── STYLE_PROFILE.md → ign-daily/   # 风格学习结果(仓库里也有)
├── scripts/
│   ├── ign_rss_incremental.py      # 心跳增量抓取脚本
│   ├── git_push.py                 # GitHub PAT push 工具
│   ├── nightly_polish_diff.py      # 夜间学习脚本
│   ├── check_polish_today.py       # 夜间学习前置检查
│   └── ...
└── .env                            # GitHub PAT(不入 git)
```

---

## 🔴 词库 (game_names_dict.json)

### 结构

```json
{
  "_meta": { "description": "...", "source_legend": {...} },
  "games": {
    "Crimson Desert": { "cn": "红色沙漠", "source": "ign_cn" },
    "Elden Ring": { "cn": "艾尔登法环", "source": "consensus" },
    ...
  },
  "movies_tv": { ... },
  "companies": { ... },
  "people": { ... },
  "terms": { ... },
  "Songs of the Past": { "cn": "旧时曲", "source": "user", "cat": "game" }
}
```

### 查询规则

1. **翻译标题/摘要/全文前必须加载词库**
2. 对文本中出现的游戏名、影视名、公司名、人物名逐一匹配
3. **匹配到 → 强制使用词库译名**,不能自行翻译
4. 未匹配 → 按优先级查:IGN中国 → B站IGN中国 → web_search → AI 推测
5. AI 推测的新词 → 写入译文的 `pending_dict` 字段,**不静默入库**

### source 优先级

`user` > `ign_cn` > `bilibili` > `consensus` > `ai_guess`

---

## 📄 核心数据格式

### index.json (每天一份)

```json
{
  "date": "2026-05-29",
  "window": "2026-05-28 08:00 -> 2026-05-29 08:00 (CST)",
  "total": 28,
  "articles": [
    {
      "id": 1,
      "en_title": "...",
      "cn_title": "精炼中文标题(≤20字)",
      "category": "游戏新闻",
      "emoji": "🎮",
      "url": "https://www.ign.com/articles/...",
      "publish_time_cn": "2026-05-29 06:49",
      "summary": "2-3句中文摘要",
      "translation_status": "none|requested|done",
      "translation_path": null | "translations/01.json"
    }
  ]
}
```

**category 枚举:** 游戏新闻 / 影视资讯 / 评测评分 / 行业动态 / 科技新闻 / 人物新闻 / 盘点推荐

**emoji 对应:** 🎮 ⭐ 🎬 🌟 💼 🔬 📋

### translations/NN.json (翻译结果)

⚠️ **文件名必须两位数补零**:id=5 → `05.json`,id=15 → `15.json`。前端用 `padStart(2,'0')` 加载,不补零会 404。

```json
{
  "id": 2,
  "en_title": "...",
  "cn_title": "...",
  "subtitle": "创意副标题(2-15字,自拟短句)",
  "url": "...",
  "category": "...",
  "emoji": "...",
  "publish_time_cn": "...",
  "translated_at": "2026-05-29T09:30:00+08:00",
  "cover": "https://assets-prd.ignimgs.com/...(去掉压缩参数)",
  "images": ["url1", "url2"],
  "opus_summary": "50-80字的精炼总结",
  "paragraphs": [
    { "type": "text", "en": "English paragraph", "cn": "中文翻译" },
    { "type": "heading", "en": "Section Title", "cn": "小标题" },
    { "type": "text", "en": "...", "cn": "..." }
  ],
  "translated_terms": {
    "Crimson Desert": "红色沙漠",
    "Pearl Abyss": "Pearl Abyss"
  },
  "pending_dict": [
    { "en": "NewGame", "cn": "新游戏", "cat": "games", "source": "ai_guess", "note": "" }
  ]
}
```

### subtitle 副标题规则(2026-05-30 新增)

每篇译文必须包含一个 **2-15 字创意短句** 作为副标题:
- 不是 paragraphs[0],不是 IGN 的 subheadline,是自己拟的
- 风格:情绪词、网络流行语、谐音、口头禅、短引用
- 示例:「急急急急急」「再见了,老朋友」「摊牌了」「第N滴血」
- 和 cn_title 不重复,补充情绪/角度而非重复信息
- 参考 STYLE_PROFILE.md 的副标题规则

### requests.json (用户勾选)

```json
{
  "date": "2026-05-29",
  "requested_ids": [2, 6, 7, 10],
  "requested_at": "2026-05-29T01:16:00.936Z"
}
```

由前端提交到 GitHub(用户浏览器里的 PAT 直接 commit)。

### index-list.json (日期列表)

```json
[
  { "date": "2026-05-30", "total": 3, "translated": 0, "translatedTitles": [] },
  { "date": "2026-05-29", "total": 28, "translated": 8, "translatedTitles": [...] }
]
```

---

## ⚙️ 关键脚本说明

### `scripts/ign_rss_incremental.py` - 心跳增量抓取

- **用法:** `python3 scripts/ign_rss_incremental.py`
- **做什么:** 抓 3 页 RSS(60 条),与当天 index.json 去重,过滤促销,输出新文章到 `ign_rss_new.json`
- **日期逻辑:** 8:00 前 → target_date=今天; 8:00 后 → target_date=明天
- **输出:** `workspace/ign_rss_new.json`(含 target_date、next_id、articles)

### `ign_rss_fetch.py` - 完整抓取(cron 兜底用)

- **用法:** `python3 ign_rss_fetch.py [YYYY-MM-DD]`
- **做什么:** 抓 3 页 RSS,按 24h 窗口过滤,输出全部文章到 `ign_rss_raw.json`

### `scripts/git_push.py` - GitHub push

- **用法:** `python3 scripts/git_push.py [repo_path] [branch]`
- **依赖:** `.env` 文件中的 `GITHUB_PAT_IGN_DAILY` 和 `GITHUB_USER_IGN_DAILY`
- **原理:** 用 `https://USER:PAT@github.com/...` 内嵌 token push,绕开 GCM

### `scripts/enforce_dict_titles.py` - 词库强制校验

- **用法:** `python3 scripts/enforce_dict_titles.py [YYYY-MM-DD]`
- **做什么:** 扫描 index.json 的 cn_title,检查是否使用了词库译名(如《神鬼寓言》不能写成《寓言》)
- **输出:** `DICT_MATCH_OK` 或 `DICT_MISMATCH`(并列出需修正的条目)
- **何时跑:** 心跳 RSS 抽取翻译标题后、push 前

### `scripts/check_currency.py` - 金额折算校验

- **用法:** `python3 scripts/check_currency.py [YYYY-MM-DD]`
- **做什么:** 扫描译文 JSON,找出外币金额缺少人民币折算的条目
- **输出:** `✅ CURRENCY_CHECK: All amounts have CNY conversions.` 或报错并建议修正值
- **何时跑:** 翻译完成后、git push 前(必须通过才能 push)

### `scripts/nightly_polish_diff.py` - 夜间学习

- **用法:** `python3 scripts/nightly_polish_diff.py`
- **做什么:** 对比当天 translations/ vs polished/,提取 diff,生成学习日志

---

## 🔧 翻译规则速查

详见 `IGN_TRANSLATE_INSTRUCTIONS.md`，核心：

1. **翻译前必须 grep 词库**
2. 英文和中文之间不留空格
3. 引用人物说的话用「」
4. 作品名用《》
5. 金额格式：`500美元(约合人民币3580元)`——不用 `$`，不用千分位逗号
6. 公司名：有公认中文的翻译（索尼/育碧/卡普空），拿不准的保留英文
7. 翻译 JSON 必须包含 `translated_terms` 快照
8. AI 推测新词写 `pending_dict`，不静默入库
9. **副标题 `subtitle`：2-15字创意短句，自拟，不是 paragraphs[0]**
10. **文件名补零：** id=5 → `05.json`，不补零前端 404
11. **push 前必跑：** `check_currency.py` + `enforce_dict_titles.py`

---

## 🚀 Git 推送

**永远使用:** `python3 C:\Users\Administrator\.openclaw\workspace\scripts\git_push.py`

不要用裸 `git push`(GCM 凭证已过期会弹窗卡死)。

---

## 📡 推送渠道

- **所有通知走元宝(yuanbao)**,微信已停用
- cron delivery: `channel: yuanbao, to: QcKdfHBQkD3ORF1FEn+T3bGXMMbuP0BAfqllxAOkH3YwVFC1HLHzx5qq7AG0zjPq`

---

## 🕐 Cron 任务

| ID | 名称 | 时间 | 做什么 |
|----|------|------|--------|
| ac1c0361... | IGN Daily News Report | 8:20 AM CST | 兜底 RSS + Excel + 通知 |
| polish-diff-nightly-2026 | Nightly Learning | 22:30 CST | 润色 diff → 学习风格 |

---

## 🧠 心跳任务(每小时)

参见 `HEARTBEAT.md`,两件事:
1. 跑 `ign_rss_incremental.py` → 有新文章就翻译标题摘要 → push
2. 检查 `requests.json` → 有未翻译的就执行全文翻译(用 Opus)→ push

---

## ⚠️ 常见坑

1. **词库不查就翻译** → 必然翻错(如 Crimson Desert 翻成「绯红沙漠」而不是「红色沙漠」)
2. **JSON 中的 ASCII 双引号 `"`** → 会破坏 JSON 格式,中文标题/摘要里用「」替代
3. **日期归属** → 8:00 AM 是分界线,不是 0:00
4. **git push 弹窗** → 必须用 git_push.py,不能裸 push
5. **图片 URL 压缩参数** → 去掉 `?width=&format=&auto=webp&quality=` 后缀
6. **RSS 延迟** → 文章发布后 30-60 分钟才出现在 feed 里,8:20 cron 兜底补漏
7. **翻译文件名不补零** → 前端用 `padStart(2,'0')` 加载,`5.json` 会 404,必须是 `05.json`
8. **金额漏折算** → 外币金额必须有人民币折算,push 前跑 `check_currency.py` 拦截
9. **cn_title 不用词库译名** → push 前跑 `enforce_dict_titles.py` 拦截

---

## 🔄 典型操作场景

### 场景1:心跳发现新文章
```
1. python3 scripts/ign_rss_incremental.py → "✅ Found 3 new articles"
2. 读 game_names_dict.json
3. 对 3 篇文章翻译标题+分类+摘要(查词库!)
4. 追加到 ign-daily/data/{target_date}/index.json
5. 更新 data/index-list.json
6. git add + commit + python3 scripts/git_push.py
```

### 场景2:用户勾选翻译
```
1. git pull → 读 requests.json → 找出 translation_status != 'done' 的
2. 对每篇:
   a. web_fetch 原文页
   b. 提取 og:image → cover(去压缩参数)
   c. 提取正文图片 → images[]
   d. 读词库匹配
   e. Opus 翻译(paragraphs 格式)
   f. 生成 opus_summary(50-80字)
   g. 写 translated_terms 快照
   h. 新词写 pending_dict
3. 写 translations/NN.json
4. 更新 index.json 的 translation_status: 'done'
5. 更新 index-list.json 的 translated 计数
6. git push
```

### 场景3:用户发临时文章链接
```
1. web_fetch 抓原文 + og:image
2. 新 id = 当天 max_id + 1
3. 追加到 index.json
4. 翻译全文(同场景2)
5. push
```

---

## 📝 STYLE_PROFILE.md

记录 AI 从用户润色中学到的翻译风格偏好。夜间学习自动更新。用户可以在 learning.html 上批注(同意/拒绝/修改规则)。

---

*最后更新:2026-05-30*


---

## 📌 维护原则

**对这个项目做任何改动后,都必须同步更新本文件(AGENT_HANDOFF.md)和相关指令文档(IGN_TRANSLATE_INSTRUCTIONS.md / HEARTBEAT.md)。**

改动包括但不限于:
- 新增/修改前端展示字段
- 新增/修改翻译 JSON 结构
- 新增/修改自动化检查脚本
- 修改工作流步骤或顺序
- 修复 bug 后的经验教训

原则:下一个接手的 agent 或人类只读这一份文件就能完整理解和运维整个系统。
