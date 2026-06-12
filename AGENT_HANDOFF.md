# AGENT_HANDOFF.md - IGN Daily 项目交接文档

> 给接手这个项目的 AI agent 或开发者的完整操作手册。读完这个文件你就能运维整个系统。

---

## 2026-06-02 权威流程摘要（新 agent 先读这里）

下面这几条是当前唯一可信的自动化分工；如果本文档旧段落出现“主 session 心跳”“Opus 必须处理标题/正文”等旧说法，以本节为准。

1. RSS 抓取只由 GitHub Actions `.github/workflows/hourly-rss.yml` 负责，每小时第 5 分钟运行，产出 `index.json`、`need_titles.json`，并用 `scripts/article_cache.py` 缓存 `sources/NN.json`。
2. 标题/摘要翻译由 `data/automation-config.json.title_translator` 决定：`api` 时由 GitHub Actions/API 脚本处理；`openclaw` 时由 OpenClaw 独立 cron 处理。
3. 正文翻译由 `data/automation-config.json.fulltext_translator` 决定：`api` 时由 GitHub Actions/API 脚本复用 `sources/NN.json`；`openclaw` 时由 OpenClaw/主 session 处理。
4. 夜间学习由 `data/automation-config.json.nightly_learner` 决定：`api` 时由 `.github/workflows/nightly-style.yml` 更新 `STYLE_PROFILE.md`；`openclaw` 时由 OpenClaw 22:30 cron 处理。
5. OpenClaw 每次执行标题、正文或夜间学习前，必须先跑 `python3 scripts/automation_guard.py title|fulltext|nightly`。输出 `AUTOMATION_GUARD SKIP` 就立刻返回 `HEARTBEAT_OK`，不要读写队列或 `STYLE_PROFILE.md`；输出 `AUTOMATION_GUARD RUN` 才继续。
6. `scripts/rss_queue_check.py {date}` 只用于本次 RSS 目标日期，不要拿它全量扫描旧历史日期；旧数据可能没有 `publish_time_cn`。
7. 首页 Excel 导出是纯前端功能：用户勾选文章后可加入本地 `localStorage` 导出篮并跨日期导出 `.xlsx`，不应触发或修改 `requests.json`、`need_titles.json`、`translations/` 或任何 OpenClaw/API 自动化队列。
8. 润色正文按用户写作习惯处理：编辑框里“换一行就是新段落”。润色文件会保存 `body` 原文和 `paragraphs` 数组；夜间学习、diff 脚本应优先读取 `paragraphs`，没有该字段时才兼容旧版 `body`。

## 先跑脚本，不靠记忆

新 agent 接手先跑：

```bash
python3 scripts/agent_doctor.py
```

每次翻译完成、push 前只跑一个总入口：

```bash
python3 scripts/pre_push_check.py {date}
```

它会依次调用 `post_translate_check.py`、`check_currency.py`、`enforce_dict_titles.py`。任何失败都不能 push。

---

## 🏗 架构总览

```
用户视角:
  网页 (GitHub Pages) ← 用户浏览新闻、勾选翻译、润色译文

后端(AI agent + cron + heartbeat):
  [cron 每小时] RSS增量抓取 → 写 index.json + need_titles.json + sources/NN.json → push
  [Actions/OpenClaw] 检查 need_titles.json → 翻译标题+摘要 → push
  [cron 8:20 AM] 兜底校验补漏 → 生成 Excel → 发通知
  [Actions/OpenClaw] 用户勾选后 → 复用 sources/NN.json 翻译全文 → push
  [Actions/OpenClaw 22:30] nightly 学习 → 更新 STYLE_PROFILE
```

### 核心工作流

| 阶段 | 触发 | 做什么 | 模型 |
|------|------|--------|------|
| RSS 抓取 | GitHub Actions 每小时 | 增量抓 RSS → 追加 index.json + need_titles.json + sources/NN.json → push | 脚本 |
| 标题翻译 | Actions 或 OpenClaw | 检查 need_titles.json → 复用 sources/NN.json → 翻译 cn_title+summary → push | Flash/API 或 OpenClaw |
| 兜底校验 | cron 8:20 | 重跑完整 RSS 对比补漏 → 生成 Excel → 通知 | cron子代理 |
| 全文翻译 | 用户勾选 | 复用 sources/NN.json → 词库匹配 → 翻译全文 → push | Pro/API 或 OpenClaw |
| 夜间学习 | 22:30 | 从译文/润色样本学习 → 更新 STYLE_PROFILE | API 或 OpenClaw |

> ⚠️ **标题+摘要翻译原则**: 所有文章在首页必须显示中文标题和摘要，不能显示英文占位。RSS 只负责发现和缓存，标题摘要由当前开关指定的 API 或 OpenClaw 完成。

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
├── manifest.json                   # PWA manifest(2026-05-31 新增)
├── sw.js                           # Service Worker(离线缓存)
├── dict.html                       # 词库管理页
├── history.html                    # 历史浏览
├── learning.html                   # 学习日志 & 批注
├── STYLE_PROFILE.md                # AI 学到的翻译风格规则
├── assets/
│   ├── app.js                      # 主页 Alpine.js 逻辑 + SW 注册
│   ├── style.css                   # 样式
│   ├── exceljs.min.js              # 本地 Excel 导出库(首页导出篮使用)
│   ├── icon-192.png                # PWA 图标 192x192
│   └── icon-512.png                # PWA 图标 512x512
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
├── ign-daily/data/dict.json        # 🔴 词库(翻译必查，前端和脚本共同使用)
├── exchange_rates.json             # 汇率(金额翻译用，脚本会自动查找)
├── ign_rss_new.json                # 增量脚本发现的新文章（仓库根目录兼容输出）
├── ign-daily/TRANSLATION_GUIDE.md  # 🔴 翻译详细规则
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

## 🔴 词库 (`data/dict.json`)

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
  "images": [{"url": "url1", "caption": ""}],
  "opus_summary": "70-80字左右的精炼总结",
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
  "requested_articles": [
    { "id": 2, "url": "https://www.ign.com/articles/...", "en_title": "..." },
    { "id": 6, "url": "https://www.ign.com/articles/...", "en_title": "..." }
  ],
  "requested_at": "2026-05-29T01:16:00.936Z"
}
```

由前端提交到 GitHub(用户浏览器里的 PAT 直接 commit)。

**⚠️ ID 偏移防护(2026-05-31):**
- 心跳增量抓取会在 index.json 前面插入新文章，导致已有文章 ID 偏移
- 新格式包含 `requested_articles` 数组（含 URL 和标题），心跳翻译时**必须按 URL 匹配**当前 ID
- 旧格式只有 `requested_ids`（兼容：直接按 ID 匹配）

### index-list.json (日期列表)

```json
[
  { "date": "2026-05-30", "total": 3, "translated": 0, "translatedTitles": [] },
  { "date": "2026-05-29", "total": 28, "translated": 8, "translatedTitles": [...] }
]
```

### need_titles.json (待翻译标题队列)

由 `ign_rss_incremental.py` 在抓到新文章后生成，心跳检查并处理。

```json
[
  {
    "id": 18,
    "url": "https://www.ign.com/articles/...",
    "en_title": "New IGN Article Title",
    "publish_time_cn": "2026-06-01 14:30"
  }
]
```

**处理流程:**
1. 心跳检测到 need_titles.json 有内容
2. 逐条处理：web_fetch 抓原文 → 翻译 cn_title+summary → 更新 index.json
3. 从 need_titles.json 移除已处理的条目
4. 队列清空后 → `python3 scripts/pre_push_check.py {date}` → `python3 scripts/git_push.py`
5. 如果 need_titles.json 为空或不存在，跳过此任务

> ⚠️ **不要跳过标题翻译**：所有文章在首页必须显示中文标题和摘要。英文标题只作为中间占位，心跳必须尽快翻译。

---

## ⚙️ 关键脚本说明

> 🔴 **这些脚本都在仓库的 `scripts/` 目录下**（同步自 workspace），直接在 ign-daily 项目下运行即可：`python3 scripts/xxx.py`
> 不在 ign-daily 仓库的旧版本在 `workspace/scripts/`（忽略，已过时）

### `scripts/ign_rss_incremental.py` - 心跳增量抓取

- **用法:** `python3 scripts/ign_rss_incremental.py`
- **做什么:** 抓 3 页 RSS(60 条),与当天 index.json 去重,过滤促销
- **产出:**
  1. 追加新文章到 `data/{target_date}/index.json`（英文标题+空摘要占位）
  2. 更新 `data/index-list.json`
  3. 写入 `data/{target_date}/need_titles.json` 队列（供心跳翻译标题用）
  4. 同时输出到仓库根目录 `ign_rss_new.json`（兼容旧流程）
  5. git add + commit + push
- **日期逻辑:** 8:00 前 → target_date=今天; 8:00 后 → target_date=明天
- **注意:** 此脚本**只抓取不翻译**，标题翻译由主 session 心跳处理

### 完整 RSS 兜底脚本

当前仓库没有 `ign_rss_fetch.py`。如果 cron 兜底仍在使用完整抓取脚本，它属于仓库外部运行环境；不要在仓库内假定该文件存在。仓库内的标准抓取入口是 `scripts/ign_rss_incremental.py`。

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

### `scripts/post_translate_check.py` - 翻译后综合校验(2026-05-31 新增)

- **用法:** `python3 scripts/post_translate_check.py [YYYY-MM-DD]`
- **做什么:** 一次性检查所有 translation_status=done 的译文:
  - ✅ cover 非空且无压缩参数
  - ✅ translated_terms 存在
  - ✅ paragraphs 非空
  - ✅ subtitle 存在
  - ✅ opus_summary 存在
  - ✅ 无 ASCII 双引号残留
  - ✅ 金额有 CNY 折算
  - ✅ AGENT_HANDOFF.md 同步提醒
- **输出:** 有 error 则 exit(1) 阻断 push; 只有 warning 则 exit(0) 但提示
- **何时跑:** **每次翻译完成后、git push 前必跑**

### `scripts/nightly_polish_diff.py` - 夜间学习

- **用法:** `python3 scripts/nightly_polish_diff.py`
- **做什么:** 对比当天 translations/ vs polished/,提取 diff,生成学习日志

---

## 🔧 翻译规则速查

详见 `TRANSLATION_GUIDE.md`，核心：

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
11. **push 前必跑三连校验（按顺序）**
    ```bash
    python3 scripts/pre_push_check.py {date}
    ```
    三个都必须通过才能 push。
12. **改了代码/流程必同步：** AGENT_HANDOFF.md + TRANSLATION_GUIDE.md + scripts/README.md

---

## 🚀 Git 推送

**永远使用:** `python3 scripts/git_push.py`

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

## 🧠 心跳任务(60分钟)

心跳任务两件事（严格按顺序）:
1. **翻译待处理标题**: 检查 `data/{今天}/need_titles.json` → 有未处理的用 Opus 逐篇翻译 cn_title+summary → 更新 index.json 并移除队列条目 → push
   - 翻译前必须 web_fetch 抓原文，查词库，判断 category/emoji
   - 严格遵循词库规则、公司名规则、金额格式
2. **翻译请求**: 检查 `requests.json` → 有未翻译的用 Opus 全文翻译 → push

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
2. 读 data/dict.json
3. 对 3 篇文章翻译标题+分类+摘要(查词库!)
4. 追加到 ign-daily/data/{target_date}/index.json
5. 更新 data/index-list.json
6. python3 scripts/pre_push_check.py {target_date}
7. python3 scripts/git_push.py
```

### 场景2:用户勾选翻译
```
1. git pull → 读 requests.json
2. 按 URL 匹配当前 ID（新格式）或直接按 ID（旧格式）
3. 对每篇:
   a. python3 scripts/translate_pipeline.py {date} {id} --prep
      (获取 cover + 词库命中列表)
   b. web_fetch 原文页
   c. Opus 翻译(paragraphs + cn_title + opus_summary + subtitle)
   d. 新词写 pending_dict
   e. 写 translations/NN.json
      🔴 必须包含 en_title 和 url 字段(从 index.json 取)
   f. python3 scripts/translate_pipeline.py {date} {id} --post
      (自动补 cover/images/translated_terms + url/en_title + 清理 + 同步)
4. python3 scripts/pre_push_check.py {date}
5. python3 scripts/git_push.py
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

*最后更新:2026-05-31*


---

## 📌 维护原则

**对这个项目做任何改动后,都必须同步更新本文件(AGENT_HANDOFF.md)和相关指令文档(TRANSLATION_GUIDE.md / scripts/README.md)。**

改动包括但不限于:
- 新增/修改前端展示字段
- 新增/修改翻译 JSON 结构
- 新增/修改自动化检查脚本
- 修改工作流步骤或顺序
- 修复 bug 后的经验教训

原则:下一个接手的 agent 或人类只读这一份文件就能完整理解和运维整个系统。

---

## 2026-06-01 维护补充：路径、词库与校验

- 脚本统一通过 `scripts/common_paths.py` 推导仓库根目录、`data/`、词库和 `.env` 路径。
- 新脚本不要再硬编码 `C:\Users\Administrator\.openclaw\workspace`；旧路径只保留为兼容回退。
- 词库统一优先使用 `data/dict.json`。前端词库管理页和后端校验/管道必须读写同一个文件。
- 副标题字段统一为 `subtitle`。`cn_subtitle` 只作为历史兼容读取，不作为新译文写入字段。
- `ign_rss_incremental.py` 新增文章必须同时写 `publish_time_cn`，避免前端排序拿不到发布时间。
- push 前优先跑 `scripts/pre_push_check.py {date}`，它会扫描真实的 `data/{date}`。如果输出 `No index.json` 或 `No translations dir`，不能视为通过，应先确认日期或路径。
- `scripts/legacy/` 仅存放历史一次性修复/导入脚本，不得接入 cron、heartbeat 或日常翻译流程。
- `article.html` 的「复制全文」必须同时写入 `text/plain` 和 `text/html`；正文段落要复制为独立 `<p>`，否则粘贴到腾讯文档等富文本编辑器时可能丢失分段。
- `index.json` 每篇文章必须写 `publish_time_cn`。前端显示和排序优先使用该字段；`pub_date`/`pubDate_cst` 只作为历史兼容。

## 2026-06-01 自动化更新

- RSS 增量抓取已迁移到 GitHub Actions：`.github/workflows/hourly-rss.yml`，每小时第 5 分钟运行。
- Actions 调用 `scripts/ign_rss_incremental.py` 时会设置 `IGN_DAILY_SKIP_GIT=1`，避免脚本在 CI 内自行 commit/push。
- RSS-only 自动提交前必须跑 `python3 scripts/rss_queue_check.py {date}` 和 `python3 scripts/agent_doctor.py`。
- `scripts/rss_queue_check.py` 只校验 RSS 队列数据形状、URL/ID 去重、`publish_time_cn` 和 `need_titles.json` 一致性；它不要求标题摘要已经翻译。
- `scripts/pre_push_check.py {date}` 仍然用于标题摘要或全文翻译完成后的 push。
- 主聊天 session 不再承担每小时 RSS 心跳；OpenClaw 如需自动化，只开独立 session 处理 `need_titles.json` 的标题/摘要翻译。
- OpenClaw 标题摘要 cron 启动时读取仓库根目录 `AGENT_TITLE_TRANSLATOR.md`，按 URL 匹配队列文章，不要按旧 ID 直接改。

## 标题摘要翻译开关

- 网页设置面板会写 `data/automation-config.json`：
  - `title_translator=openclaw|api`
  - `fulltext_translator=openclaw|api`
- `nightly_learner=openclaw|api`
- `openclaw`：保留队列给 OpenClaw；`api`：GitHub Actions 调用 OpenAI-compatible API。
- API 模式需要 GitHub Secret `TRANSLATOR_API_KEY`（兼容旧名 `DEEPSEEK_API_KEY`）。网页会把 `api_title_model`、`api_fulltext_model`、`api_nightly_model` 和 `api_base_url` 写入 `data/automation-config.json`；建议标题摘要用 Flash，正文用 Pro，夜间学习用 Flash。
- 网页设置面板的“立即运行 API 翻译”按钮会先保存 `data/automation-config.json`，再触发 GitHub Actions `api-translation.yml` 的 `workflow_dispatch`；按钮依赖浏览器本地 PAT 具备 Actions 写权限。
- 当 `fulltext_translator=api` 时，首页勾选文章并提交翻译会写 `requests.json`，随后立刻触发 `api-translation.yml`；无需等待下一次半小时定时。
- 首页提交全文翻译时必须合并而不是覆盖现有 `requests.json`；GitHub 文件写入成功即视为已进入翻译池并立即显示 `requested`。后续 Actions 触发失败只能提示等待定时任务，不得把已成功入池误报为“提交失败”。
- 首页加载/刷新会尝试触发 `hourly-rss.yml` 抓最新 RSS 和缓存 `sources/NN.json`，浏览器本地 10 分钟节流；没有 PAT 或 PAT 缺少 Actions 写权限时只会等待 GitHub Actions 自己的每小时定时。
- 每小时 RSS 后会运行 `scripts/article_cache.py {date} --missing`，把干净英文正文和图片写入 `data/{date}/sources/NN.json`；API 标题和正文都优先读这个缓存。
- 标题摘要 API 脚本只处理 `need_titles.json`，不会翻译全文，也不会写 `translations/NN.json`。
- 标题摘要开启 thinking 时，输出预算不得沿用旧的 1200 token；workflow 固定设置 `TRANSLATOR_TITLE_MAX_TOKENS=4000`，API 因长度截断时脚本自动加大预算重试一次。
- 正文 API 脚本处理 `requests.json`，写 `translations/NN.json` 后必须跑 `translate_pipeline.py --post` 和 `pre_push_check.py`，不通过就不 push。
- 正文摘要仅因长度超限时使用本地分句压缩，不再调用短输出的 API 返修；模型保留英文词库名时先做安全的字面替换再复审。批量处理中每篇成功后必须同步内存中的 index 状态，避免后续失败把前一篇 `done` 覆盖回 `none`。
- API 正文写入和网页人工放行前必须把中文字段中的 `"`、`“”`、`＂` 统一转换为 `「」`；`api_translation_audit.py` 和 `post_translate_check.py` 必须把残留的非直角双引号视为错误。
- API 正文 Prompt 必须要求先识别动作主体、对象、指代和并列/比较范围，再按中文语序重组；忠实指事实与逻辑，不是保留英文句法。`prompt_blocks.py` 中的 Gen Atlas 样例是机翻腔回归基准，不得移除。
- 自然中文重组不等于意译：只允许调整语序、拆句和补出中文必需主语；不得增加原文未明确表达的时间、动机、因果、评价、程度或背景。不确定语气必须保留，歧义采用最小推断。
- DeepSeek API 用量看板在 `usage.html`。API 脚本通过 `scripts/usage_logger.py` 写 `data/usage/deepseek/{date}.json`；`scripts/deepseek_balance.py` 调官方 `/user/balance` 写 `data/usage/deepseek-balance.json`。这些是旁路观测数据，失败不得阻断翻译、RSS 或夜间学习。
- API prompt 长规则块统一由 `scripts/prompt_blocks.py` 生成，以提高 DeepSeek 自动缓存命中；标题、全文、分段重试和修复请求必须共用 `translation_system_prompt()`，任务规则与文章动态内容放在其后。不要在各脚本里复制不同版本的规则 prompt，也不要把文章标题、正文、词库命中放到稳定前缀之前。
- 正文 API 手动触发支持批量：`fulltext_limit=5|10|999`。定时任务默认 5；`999` 表示尽量全部，但脚本会按 `TRANSLATOR_FULLTEXT_TIME_BUDGET_SECONDS` 到点暂停并保留剩余请求，避免 Actions 超时。
- API 标题/正文脚本都会读取 `TRANSLATION_GUIDE.md` 和 `STYLE_PROFILE.md`；夜间学习任务更新 `STYLE_PROFILE.md` 后，下一轮 API 翻译会自动吃到新风格。
- OpenClaw cron 每次启动必须先读 `data/automation-config.json`；对应任务为 `api` 时应静默退出，避免两边同时改同一队列。
- 更稳的入口是先运行 `python3 scripts/automation_guard.py title|fulltext|nightly`。输出 `AUTOMATION_GUARD SKIP` 就直接返回 `HEARTBEAT_OK`，输出 `RUN` 才继续处理对应任务。

## 2026-06-02 维护补充：展示序号、请求匹配、日期窗口

- 首页卡片左上角 `#N` 是排序/筛选后的展示序号，不再等同稳定 `id`；稳定 `id` 仍用于 `article.html?date=...&id=...` 和 `translations/NN.json`。
- 用户全文翻译请求必须按 `requests.json.requested_articles[].url` 匹配当前 `index.json` 文章；`requested_ids` 只作兼容显示，不得作为唯一依据。
- `scripts/translate_pipeline.py` post 阶段会校验译文 JSON 的 `url`/`en_title` 与 index 文章一致，不一致必须停止，避免 A 文请求错写到 B 文。
- 日期归属固定按 8:00 CST 分界：`data/YYYY-MM-DD` 覆盖前一天 08:00 到当天 08:00，左闭右开。例：`data/2026-06-02` 只能放 `2026-06-01 08:00 <= publish_time_cn < 2026-06-02 08:00`。
- `scripts/rss_queue_check.py` 和 `scripts/agent_doctor.py` 会检查最新/目标 index 的 `publish_time_cn` 是否落在对应日期窗口内。
