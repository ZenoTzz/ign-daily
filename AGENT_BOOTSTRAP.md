# 🤖 Agent 交接启动指令

> 把这段文字直接发给新 agent，它就能接手 IGN Daily 翻译工作流。

---

你现在接手一个 IGN 英文游戏新闻每日翻译项目。以下是你需要知道的一切。

## 项目概述

每天自动抓取 IGN 英文站新闻，生成中文标题+摘要索引，用户在网页上勾选感兴趣的文章后你负责全文翻译。翻译质量要求极高，有严格的风格规范。

## 关键文件（按重要性排序，必读）

1. **`ign-daily/TRANSLATION_GUIDE.md`** — 翻译风格圣经。所有标点、人名、金额、词库规则都在这里。翻译前必读。
2. **`ign-daily/AGENT_HANDOFF.md`** — 项目架构、文件结构、数据格式、脚本说明、常见场景处理。
3. **`workspace/HEARTBEAT.md`** — 心跳任务定义（每小时执行：RSS增量抓取 + 翻译请求检查）。
4. **`workspace/IGN_TRANSLATE_INSTRUCTIONS.md`** — 翻译执行的详细技术流程（抓原文→查词库→翻译→写JSON→push）。
5. **`workspace/game_names_dict.json`** — 游戏/影视/公司名词库。翻译时强制使用，不能自行翻译。
6. **`ign-daily/STYLE_PROFILE.md`** — 从用户润色中学到的风格偏好（每晚自动更新）。

## 仓库位置

- 工作区：`C:\Users\Administrator\.openclaw\workspace\`
- IGN Daily 仓库：`workspace\ign-daily\`（GitHub: `zenotzz.github.io/ign-daily`）
- 脚本目录：`workspace\scripts\`
- Git 推送：**必须用** `python3 workspace/scripts/git_push.py`（内嵌 PAT，不要用 git push）

## 日常工作流

### 心跳（每小时自动触发）
1. 运行 `python3 scripts/ign_rss_incremental.py` 检查新文章
2. 有新文章 → 翻译标题+摘要 → 追加到 `ign-daily/data/{date}/index.json` → push
3. 检查 `data/{date}/requests.json` 有无用户勾选的翻译请求
4. 有请求 → 在主 session 直接翻译（不用子代理）→ push → 通知用户

### 用户说"翻译"
等同于心跳任务2：检查 requests.json，翻译未完成的文章。

### 每晚 22:30（cron）
对比用户润色与原译，提取风格规律，更新 STYLE_PROFILE.md 和 TRANSLATION_GUIDE.md。

## 绝对铁律

- **词库里有的译名必须用，不能自行翻译**
- **不知名人名保留英文，不要音译**
- **英文和中文之间不留空格**
- **引用用「」，作品名用《》，标题用全角标点**
- **每篇必须有副标题（2-15字）**
- **翻译在主 session 完成（子代理会超时）**
- **AI 猜的新译名写 pending_dict，不要直接入词库**
- **永远不要删除历史 data/{date}/ 文件夹**

## 通知渠道

- 所有通知走**元宝（yuanbao）**，不走微信
- 翻译完成后通知：「✅ 已翻译 N 篇，刷新网页查看」

## 快速验证你准备好了

读完上面 6 个文件后，你应该能回答：
1. "Crimson Desert" 怎么翻译？（→《红色沙漠》，词库里有）
2. "Noah Centineo" 怎么处理？（→ 保留英文，不音译）
3. 金额 "$500" 怎么写？（→ 500美元(约合人民币3580元)）
4. 标题里的逗号用什么？（→ 全角 `，`）
5. 翻完后怎么 push？（→ `python3 scripts/git_push.py`）

全答对就可以开工了。
