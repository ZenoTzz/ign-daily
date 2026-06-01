# Agent Bootstrap - IGN Daily

把这份文件先读完，再读 `AGENT_HANDOFF.md` 和 `TRANSLATION_GUIDE.md`。目标是少靠记忆，多靠脚本检查。

## 这个项目做什么

IGN Daily 是一个个人化 IGN 英文新闻翻译工作流：

1. RSS 抓取 IGN 英文新闻，写入 `data/{date}/index.json`。
2. agent 先补中文标题 `cn_title` 和中文摘要 `summary`，首页必须显示中文。
3. 用户在网页勾选文章后，agent 翻译全文到 `data/{date}/translations/NN.json`。
4. push 前必须跑验证脚本，通过才允许推送。

## 只需要记住 7 条

1. 词库唯一主来源：`data/dict.json`。
2. 翻译文件名必须补零：`id=3` -> `translations/03.json`。
3. 全文翻译必须有：`subtitle`、`opus_summary`、`paragraphs`、`translated_terms`、`cover`、`url`、`en_title`。
4. 副标题字段统一叫 `subtitle`，不要新写 `cn_subtitle`。
5. 新请求优先按 `requested_articles[].url` 匹配当前文章，不要只信旧 ID。
6. 不要删除任何历史 `data/{date}/`。
7. push 前跑：`python3 scripts/pre_push_check.py {date}`。
8. 日期归属按 8:00 分界：`data/2026-06-02` 只能放 `2026-06-01 08:00 <= publish_time_cn < 2026-06-02 08:00` 的文章。

## 项目层级

```text
ign-daily/
├── data/
│   ├── dict.json                 # 词库，前端和脚本共同使用
│   ├── index-list.json           # 日期列表
│   └── {YYYY-MM-DD}/
│       ├── index.json            # 当天新闻索引
│       ├── requests.json         # 用户勾选请求
│       ├── need_titles.json      # 待补中文标题/摘要队列
│       └── translations/NN.json  # 全文译文
├── scripts/
│   ├── common_paths.py           # 所有脚本共用路径
│   ├── agent_doctor.py           # 新 agent 接手自检
│   ├── pre_push_check.py         # push 前总校验
│   ├── translate_pipeline.py     # 翻译前/后处理
│   ├── ign_rss_incremental.py    # RSS 增量抓取
│   └── git_push.py               # PAT push 工具
├── AGENT_HANDOFF.md              # 运维流程
├── AGENT_TITLE_TRANSLATOR.md     # OpenClaw 标题摘要翻译 cron 指引
├── TRANSLATION_GUIDE.md          # 翻译风格
└── STYLE_PROFILE.md              # 用户润色偏好
```

## 新 agent 接手时

```bash
python3 scripts/agent_doctor.py
```

看到 `AGENT_DOCTOR_OK` 再继续。失败时先修失败项，不要猜。

## 日常流程

### 1. RSS 增量抓取

```bash
python3 scripts/ign_rss_incremental.py
```

脚本会写 `index.json`、`need_titles.json`，并推送。它只抓取，不负责翻译标题。

### 2. 补标题和摘要

检查：

```text
data/{date}/need_titles.json
```

逐篇 web_fetch 原文，查 `data/dict.json`，补：

- `cn_title`
- `summary`
- `category`
- `emoji`

处理完从 `need_titles.json` 移除对应条目。

### 3. 用户请求全文翻译

检查：

```text
data/{date}/requests.json
```

优先用 `requested_articles[].url` 匹配当前 `index.json` 里的文章 ID。不要只拿 `requested_ids` 直接翻译，RSS 增量可能让旧 ID 失效。翻译前跑：

```bash
python3 scripts/translate_pipeline.py {date} {id} --prep
```

写完 `translations/NN.json` 后跑：

```bash
python3 scripts/translate_pipeline.py {date} {id} --post
python3 scripts/pre_push_check.py {date}
python3 scripts/git_push.py
```

## 翻译硬规则

- 词库有译名必须用。
- 不知名人名保留英文，不要音译。
- 英文和中文之间不留空格。
- 引用用「」，作品名用《》。
- 金额写成 `500美元(约合人民币3580元)`。
- 新猜译名写 `pending_dict`，不要直接入词库。

## 如果脚本报警

- `No index.json` / `No translations dir`：不是通过，先确认日期。
- `DICT_MISMATCH`：标题没用词库译名，修 `cn_title`。
- `MISSING subtitle/cover/translated_terms/opus_summary`：修译文 JSON。
- `CURRENCY_CHECK` 失败：补人民币换算。

## 自动化分工

- GitHub Actions `.github/workflows/hourly-rss.yml` 每小时第 5 分钟跑 RSS 增量抓取。
- Actions 会设置 `IGN_DAILY_SKIP_GIT=1`，所以 `scripts/ign_rss_incremental.py` 只写数据，不自己 commit/push。
- RSS-only 提交前跑 `python3 scripts/rss_queue_check.py {date}` 和 `python3 scripts/agent_doctor.py`。
- 网页设置会写 `data/automation-config.json`：`title_translator` 和 `fulltext_translator` 可分别设为 `openclaw` 或 `api`。
- API 模式读取 GitHub Secret `TRANSLATOR_API_KEY`（兼容 `DEEPSEEK_API_KEY`）。模型和 base URL 从 `data/automation-config.json` 读取，可在网页设置里切 `deepseek-v4-flash`/`deepseek-v4-pro`。密钥不得写入网页或仓库。
- OpenClaw 独立自动化 session 只在对应配置不是 `api` 时处理队列；不要依赖正在聊天的主 session 心跳。
- 翻译完成后的 push 仍然跑 `python3 scripts/pre_push_check.py {date}`。

最后记住：**不确定就先跑脚本，脚本比记忆可靠。**
