# scripts/ — 核心脚本

这些脚本是 IGN Daily 工作流的核心组件。新 agent 接手时需要了解每个脚本的用途。

## 必需脚本

| 脚本 | 用途 | 调用时机 |
|------|------|----------|
| `git_push.py` | 安全推送到 GitHub（内嵌 PAT，绕开 GCM） | 每次需要 push 时 |
| `ign_rss_incremental.py` | 增量 RSS 抓取（去重、过滤促销、时间窗口） | GitHub Actions 每小时第 5 分钟 |
| `agent_doctor.py` | 新 agent 接手时检查仓库关键不变量 | 接手/大改后 |
| `pre_push_check.py` | 包装三连校验，防止忘跑某一步 | 每次 push 前 |
| `rss_queue_check.py` | 校验 RSS-only 自动化写出的 index/need_titles 队列 | GitHub Actions RSS 提交前 |
| `article_cache.py` | 抓取并缓存干净英文正文、封面图、正文图 | RSS 后、API 翻译前 |
| `translate_titles_deepseek.py` | OpenAI-compatible API 标题摘要翻译，只处理 need_titles 队列 | `title_translator=api` |
| `translate_fulltext_api.py` | 可选 OpenAI-compatible API 正文翻译，强制跑后处理和校验 | `fulltext_translator=api` |
| `translate_compare_api.py` | 手动把同一篇文章交给两个模型各翻一次，写入 comparisons/NN.json，不覆盖正式译文 | 网页“对比翻译”按钮 |
| `automation_guard.py` | 给 OpenClaw cron 判断当前任务归 API 还是 OpenClaw | 每次 OpenClaw cron 启动后 |
| `nightly_polish_diff.py` | 对比用户润色与原译，提取风格规律 | 每晚 22:30 cron |
| `nightly_style_api.py` | 用 API 从已完成译文/润色样本学习并更新 STYLE_PROFILE.md | `nightly_learner=api` |
| `prompt_blocks.py` | 统一稳定 prompt 前缀，提高 DeepSeek cache 命中 | 所有 API prompt 构造 |
| `usage_logger.py` | 记录 DeepSeek usage tokens/cache 命中数据 | API 脚本调用后 |
| `deepseek_balance.py` | 调 DeepSeek `/user/balance` 写余额快照 | usage workflow / API workflow |
| `check_polish_today.py` | 检查今天是否有润色记录（无则跳过学习） | 夜间学习入口 |
| `fetch_exchange_rates.py` | 拉取当日汇率写入 exchange_rates.json | 每天 8:20 cron |
| `rebuild_index_list.py` | 重建 data/index-list.json（所有日期列表） | 数据修复时 |

## 辅助脚本

| 脚本 | 用途 |
|------|------|
| `ign_image_fetch.py` | 从 IGN 文章页抓取图片 URL |
| `generate_annotation_response.py` | 为用户批注生成 AI 回复 |
| `sync_dict_excel.py` | 同步 JSON 词库到 Excel 版本 |

## 旧脚本

`scripts/legacy/` 里的脚本是历史一次性修复/导入脚本，可能包含固定日期、
固定文章 ID 或旧机器路径。不要把它们接入 cron、heartbeat 或日常翻译流程。

## 环境配置

1. 复制 `.env.example` 为 `.env`
2. 填入 GitHub PAT
3. 确保 Python 3.10+ 可用
4. 当前仓库核心 RSS 脚本使用 Python 标准库；外部完整抓取脚本如需 `feedparser`，在外部环境安装。

## 路径说明

脚本统一通过 `scripts/common_paths.py` 从当前仓库推导路径，默认不再依赖
`C:\Users\Administrator\.openclaw\workspace\`。

- 仓库根目录：`Path(__file__).parents[1]`
- 数据目录：`data/`
- 词库：优先 `data/dict.json`，旧 `game_names_dict.json` 只作为兼容回退
- `.env`：优先仓库根目录 `.env`，其次 `scripts/.env`

如果新增脚本，不要再硬编码个人机器路径；应复用 `common_paths.py`。

## 校验说明

翻译完成后优先跑总入口：

```bash
python3 scripts/pre_push_check.py {date}
```

RSS-only 自动化不要用 `pre_push_check.py` 拦截未翻译的标题队列；GitHub Actions 使用：

```bash
IGN_DAILY_SKIP_GIT=1 python3 scripts/ign_rss_incremental.py
python3 scripts/rss_queue_check.py {date}
python3 scripts/agent_doctor.py
```

RSS 抓取阶段必须先过滤促销/导购/购物文章，包括 deal/sale/discount/coupon、
preorder、where to buy、exclusively at、action figure、collectible、merch、
LEGO set 等购物意图词。被拦截的条目会在 Actions 日志里显示 `[skip promo]`，
不要再把这类文章写入 `index.json` 或 `need_titles.json`。

标题摘要/正文翻译/夜间学习由网页设置写入 `data/automation-config.json`：

- `openclaw`：保留队列，由 OpenClaw 独立 cron 处理。
- `api`：GitHub Actions 读取 Secret `TRANSLATOR_API_KEY`，再从 `data/automation-config.json` 读取模型和 `api_base_url` 并运行：

```bash
python3 scripts/article_cache.py {date} --queued --missing
python3 scripts/translate_titles_deepseek.py {date}
python3 scripts/translate_fulltext_api.py {date}
python3 scripts/nightly_style_api.py {date}
```

手动点击“立即运行 API 翻译”或在 API 正文模式下提交翻译请求时，网页还会把当前
`title_translator`、`fulltext_translator`、`api_title_model`、
`api_fulltext_model` 和 `api_base_url` 作为 `workflow_dispatch` inputs 传给
`.github/workflows/api-translation.yml`。该 workflow 手动运行时优先使用 inputs，
定时运行时才回退读取 `data/automation-config.json`，避免刚切换 Pro/Flash 后立刻
触发翻译却读到旧模型。

网页文章卡片的“对比翻译”是手动-only 流程：它通过 `api-translation.yml`
传入 `compare_date`、`compare_article_id`、`compare_model_a`、`compare_model_b`，
调用 `scripts/translate_compare_api.py`。结果写入
`data/{date}/comparisons/NN.json`，并在 `index.json` 里标记
`comparison_status=done`；它不得写 `translations/NN.json`，不得移除
`requests.json`，也不得参与定时任务。

`article_cache.py` 会写 `data/{date}/sources/NN.json`，里面保存 `body_en`、`paragraphs_en`、`cover_image` 和 `images`。标题摘要和正文 API 都优先读取这个缓存；只有缓存缺失才会临时抓网页。不要让模型负责抓正文或图片。

标题摘要 API 脚本不会翻译全文，也不会写 `translations/NN.json`。正文 API 脚本会写译文，但必须通过 `translate_pipeline.py --post` 和 `pre_push_check.py`。正文 API 输出较长，workflow 会设置 `TRANSLATOR_FULLTEXT_MAX_TOKENS=12000`，不要沿用标题摘要的短输出上限。API 抓正文必须使用脚本内的 `extract_article_text()` 或 `article_cache.py`，优先抽取 IGN 的正文段落并过滤导航、页脚、作者简介、推荐链接；不要再用整页 HTML 去标签的方式喂给模型。

DeepSeek 用量看板读取 `data/usage/deepseek/*.json` 和 `data/usage/deepseek-balance.json`。这些文件是旁路观测数据：记录失败不得中断翻译；余额查询失败不得影响 RSS、标题摘要、正文翻译或夜间学习。用量日志应尽量写入 `article_id`、`article_title`、`article_url`、`article_date` 和 `estimated_cost_usd`；成本按 DeepSeek 官方每 1M tokens 价格估算，真实扣费以 DeepSeek 账户余额为准。

API prompt 的长规则块必须通过 `scripts/prompt_blocks.py` 生成，尽量保持字段顺序、文本和位置稳定，方便 DeepSeek 自动上下文缓存命中。不要在各脚本里复制粘贴不同版本的 `TRANSLATION_GUIDE.md` / `STYLE_PROFILE.md` prompt。

所有会写仓库数据的 Actions（RSS、API 翻译、DeepSeek 用量快照、夜间学习）
必须使用同一个 `concurrency.group: ign-daily-write-main`，避免多个任务同时写
`data/*.json` 造成 rebase 冲突。

正文 API 支持批量模式：定时任务默认 `TRANSLATOR_FULLTEXT_LIMIT=5`；网页手动触发可传 `fulltext_limit=10` 或 `999`。脚本同时读取 `TRANSLATOR_FULLTEXT_TIME_BUDGET_SECONDS`，达到时间预算会暂停并保留剩余 `requests.json`，避免 GitHub Actions 超时导致已完成译文无法提交。

它会依次跑三连：

```bash
python3 scripts/post_translate_check.py {date}
python3 scripts/check_currency.py {date}
python3 scripts/enforce_dict_titles.py {date}
```

这三个脚本必须扫描 `data/{date}` 下的真实文件。如果输出 `No index.json` 或
`No translations dir`，不要当作通过，先确认日期和路径是否正确。
