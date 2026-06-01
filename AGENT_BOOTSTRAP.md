# 🤖 Agent 交接启动指令

> 把这段文字直接发给新 agent，它就能接手 IGN Daily 翻译工作流。

---

你现在接手一个 IGN 英文游戏新闻每日翻译项目。以下是你需要知道的一切。

## 项目概述

每天自动抓取 IGN 英文站新闻，生成中文标题+摘要索引，用户在网页上勾选感兴趣的文章后你负责全文翻译。翻译质量要求极高，有严格的风格规范。

## 开始工作

```bash
git clone https://github.com/ZenoTzz/ign-daily.git
cd ign-daily
```

**一切都在这个仓库里**——文档、脚本、词库、数据、前端页面。

> ⚠️ **翻译完成后必须跑三连校验：**
> ```bash
> python3 scripts/post_translate_check.py {date}
> python3 scripts/check_currency.py {date}
> python3 scripts/enforce_dict_titles.py {date}
> ```
> 三个脚本都在 `scripts/` 目录下，全部通过才能 push。

## 关键文件（按重要性排序，必读）

1. **`TRANSLATION_GUIDE.md`** — 翻译风格圣经。所有标点、人名、金额、词库规则。翻译前必读。
2. **`AGENT_HANDOFF.md`** — 项目架构、文件结构、数据格式、常见场景处理。
3. **`STYLE_PROFILE.md`** — 从用户润色中学到的风格偏好（每晚自动更新）。
4. **`scripts/README.md`** — 所有脚本的用途和配置说明。

## 仓库结构

```
ign-daily/
├── data/{YYYY-MM-DD}/     ← 每天的文章数据（index.json + translations/）
├── scripts/               ← 核心脚本（RSS抓取、push、学习等）
│   ├── .env.example       ← 复制为 .env 填入 GitHub PAT
│   ├── git_push.py        ← 推送代码（必须用这个，不要 git push）
│   └── ign_rss_incremental.py ← 心跳 RSS 增量抓取
├── assets/                ← 前端 CSS/JS
├── TRANSLATION_GUIDE.md   ← 翻译风格指南
├── AGENT_HANDOFF.md       ← 项目架构说明
├── AGENT_BOOTSTRAP.md     ← 本文件
└── STYLE_PROFILE.md       ← 学习档案
```

## 环境配置

1. 复制 `scripts/.env.example` 为 `scripts/.env`（或工作区根目录的 `.env`）
2. 填入 GitHub PAT（需要 repo 权限）
3. Python 3.10+，安装依赖：`pip install feedparser`
4. 词库文件 `game_names_dict.json` 放在工作区根目录

## 日常工作流

### 心跳（每小时自动触发）
1. 运行 `python3 scripts/ign_rss_incremental.py` → 自动抓新文章、写 index.json、写 need_titles.json 队列
2. 检查 `data/{today}/need_titles.json` 队列
3. 有未翻译标题 → web_fetch 抓原文 → Opus 翻译 cn_title+summary → 更新 index.json → 从队列移除 → push
4. 检查 `data/{date}/requests.json` 有无用户勾选的翻译请求
5. 有请求 → 在主 session 直接翻译，更新 index.json 的 cn_title+summary → push → 通知用户

> ⚠️ **首页显示原则**：所有文章必须有中文标题+摘要。如果 index.json 的 cn_title 等于 en_title（英文），说明 need_titles 还没被心跳处理，这是 bug。

### 用户说"翻译"
等同于心跳任务2：检查 requests.json，翻译未完成的文章。

### 每晚 22:30（cron）
运行 `scripts/nightly_polish_diff.py` 对比润色，更新 STYLE_PROFILE.md 和 TRANSLATION_GUIDE.md。

## 绝对铁律

- **词库里有的译名必须用，不能自行翻译**
- **不知名人名保留英文，不要音译**
- **英文和中文之间不留空格**
- **引用用「」，作品名用《》，标题用全角标点**
- **每篇必须有副标题（2-15字）**
- **翻译在主 session 完成（子代理会超时）**
- **AI 猜的新译名写 pending_dict，不要直接入词库**
- **永远不要删除历史 data/{date}/ 文件夹**
- **推送必须用 `python3 scripts/git_push.py`**
- **每个翻译任务完成后 push 前必须跑三连校验：**
  `scripts/post_translate_check.py` + `check_currency.py` + `enforce_dict_titles.py`，全部通过才能 push

## 通知渠道

- 所有通知走**元宝（yuanbao）**，不走微信
- 翻译完成后通知：「✅ 已翻译 N 篇，刷新网页查看」

## 快速验证你准备好了

读完上面文件后，你应该能回答：
1. "Crimson Desert" 怎么翻译？（→《红色沙漠》，词库里有）
2. "Noah Centineo" 怎么处理？（→ 保留英文，不音译）
3. 金额 "$500" 怎么写？（→ 500美元(约合人民币3580元)）
4. 标题里的逗号用什么？（→ 全角 `，`）
5. 翻完后怎么 push？（→ `python3 scripts/git_push.py`）

全答对就可以开工了。
