# Agent Bootstrap - IGN Daily

把这份文件先读完，再读 `AGENT_HANDOFF.md` 和 `TRANSLATION_GUIDE.md`。目标是少靠记忆，多靠脚本检查。

## 这个项目做什么

IGN Daily 是一个个人化 IGN 英文新闻翻译工作流：

1. RSS 抓取 IGN 英文新闻，写入 `data/{date}/index.json`。
2. RSS 后先缓存干净英文正文和图片到 `data/{date}/sources/NN.json`。
3. agent/API 先补中文标题 `cn_title` 和中文摘要 `summary`，首页必须显示中文。
4. 用户在网页勾选文章后，agent/API 复用缓存翻译全文到 `data/{date}/translations/NN.json`。
5. 用户手动点击“对比翻译”时，API 把同一篇文章交给用户勾选的一个或多个模型分别翻译，只写 `data/{date}/comparisons/NN.json`。
6. push 前必须跑验证脚本，通过才允许推送。

## 只需要记住 10 条

1. 词库唯一主来源：`data/dict.json`。
2. 翻译文件名必须补零：`id=3` -> `translations/03.json`。
3. 全文翻译必须有：`subtitle`、`opus_summary`、`paragraphs`、`translated_terms`、`cover`、`url`、`en_title`。
4. 副标题字段统一叫 `subtitle`，不要新写 `cn_subtitle`。
5. 新请求优先按 `requested_articles[].url` 匹配当前文章，不要只信旧 ID。
6. 不要删除任何历史 `data/{date}/`。
7. API/OpenClaw 分工只看 `scripts/automation_guard.py title|fulltext|nightly` 输出。
8. push 前跑：`python3 scripts/pre_push_check.py {date}`。
9. 日期归属按 8:00 分界：`data/2026-06-02` 只能放 `2026-06-01 08:00 <= publish_time_cn < 2026-06-02 08:00` 的文章。
10. RSS 过滤命中的文章先放 `filtered_rss.json` 隔离区，不要硬删；网页恢复后才进 `index.json`/`need_titles.json`。

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
│       ├── filtered_rss.json     # RSS 过滤隔离区，网页可恢复误杀
│       ├── sources/NN.json       # 干净英文正文、封面图、正文图缓存
│       ├── comparisons/NN.json   # 手动双模型对比译文，不覆盖正式译文
│       └── translations/NN.json  # 全文译文
├── scripts/
│   ├── common_paths.py           # 所有脚本共用路径
│   ├── agent_doctor.py           # 新 agent 接手自检
│   ├── pre_push_check.py         # push 前总校验
│   ├── translate_pipeline.py     # 翻译前/后处理
│   ├── ign_rss_incremental.py    # RSS 增量抓取
│   ├── article_cache.py          # 英文正文/图片缓存
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

脚本会写 `index.json`、`need_titles.json`，并推送。促销/导购疑似稿写入 `filtered_rss.json` 隔离区，首页可手动恢复。它只抓取，不负责翻译标题。

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
- API 翻译前必须刷新汇率并让 `currency_utils.py` 后处理金额；不要只靠模型遵守 prompt。
- 新猜译名写 `pending_dict`，不要直接入词库。

## 如果脚本报警

- `No index.json` / `No translations dir`：不是通过，先确认日期。
- `DICT_MISMATCH`：标题没用词库译名，修 `cn_title`。
- `MISSING subtitle/cover/translated_terms/opus_summary`：修译文 JSON。
- `CURRENCY_CHECK` 失败：补人民币换算。

## 自动化分工

- GitHub Actions `.github/workflows/hourly-rss.yml` 每小时第 5 分钟跑 RSS 增量抓取。
- RSS 抓取阶段必须过滤促销/导购/购物稿：deal/sale/discount/coupon、preorder、where to buy、exclusively at、action figure、collectible、merch、LEGO set 等不要直接写入 `index.json` 或 `need_titles.json`。
- 被过滤文章写入 `data/{date}/filtered_rss.json` 隔离区；用户可在首页“被过滤”里恢复误杀文章。`data/rss-filter-config.json.filtered_retention_days` 控制旧隔离文件保留天数，超期可自动删除。
- Actions 会设置 `IGN_DAILY_SKIP_GIT=1`，所以 `scripts/ign_rss_incremental.py` 只写数据，不自己 commit/push。
- RSS-only 提交前跑 `python3 scripts/rss_queue_check.py {date}`、`python3 scripts/article_cache.py {date} --missing` 和 `python3 scripts/agent_doctor.py`。
- 所有会写仓库数据的 Actions 必须使用 `concurrency.group: ign-daily-write-main`，避免 RSS、API 翻译、用量快照、夜间学习同时 push 造成 rebase 冲突。
- 网页设置会写 `data/automation-config.json`：`title_translator`、`fulltext_translator`、`nightly_learner` 可分别设为 `openclaw` 或 `api`。
- API 模式读取 GitHub Secret `TRANSLATOR_API_KEY`（兼容 `DEEPSEEK_API_KEY`）。标题/正文/夜间学习可分别用 `api_title_model`、`api_fulltext_model`、`api_nightly_model`，base URL 从 `api_base_url` 读取。密钥不得写入网页或仓库。
- API 正文翻译不能只靠 prompt 自觉执行规范。`translate_fulltext_api.py` 必须先生成词库/货币硬性清单，写入前调用 `api_translation_audit.py` 的检查逻辑；审计失败时只允许局部返修一次，仍失败就保留 `requests.json` 并让 workflow 失败，不能提交不合格译文。
- DeepSeek 用量看板有两层数据：`usage_logger.py` 记录脚本估算 tokens/成本；API workflow 运行前后用 `deepseek_balance.py --snapshot` 记录平台余额，并由 `record_deepseek_run_cost.py` 写入 `data/usage/deepseek-runs.json`。估算成本用于分析模型和文章，真实扣费以 DeepSeek 平台余额差为准。
- OpenClaw 独立自动化 session 只在对应配置不是 `api` 时处理队列；不要依赖正在聊天的主 session 心跳。
- OpenClaw cron 启动后先跑 `python3 scripts/automation_guard.py title|fulltext|nightly`。输出 `SKIP` 就静默退出，输出 `RUN` 才继续。
- 翻译完成后的 push 仍然跑 `python3 scripts/pre_push_check.py {date}`。

最后记住：**不确定就先跑脚本，脚本比记忆可靠。**
