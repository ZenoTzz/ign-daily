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
| `ensure_translation_media.py` | 从 `sources/NN.json` 补回遗漏或损坏的译文封面与配图 | Codex/人工翻译写回后、标记任务完成前 |
| `translate_titles_deepseek.py` | OpenAI-compatible API 标题摘要翻译，只处理 need_titles 队列 | `title_translator=api` |
| `translate_fulltext_api.py` | 可选 OpenAI-compatible API 正文翻译，强制跑后处理和校验 | `fulltext_translator=api` |
| `translate_compare_api.py` | 手动把同一篇文章交给一个或多个模型各翻一次，写入 comparisons/NN.json，不覆盖正式译文 | 网页“对比翻译”按钮 |
| `automation_guard.py` | 给 OpenClaw cron 判断当前任务归 API 还是 OpenClaw | 每次 OpenClaw cron 启动后 |
| `nightly_polish_diff.py` | 对比用户润色与原译，提取风格规律；无原译时用 source+腾讯文档润色稿生成词库候选 | 每晚 22:30 cron |
| `nightly_style_api.py` | 用 API 从已完成译文/润色样本提取候选规律 | `nightly_learner=api` |
| `import_tencent_polish.py` | 从每月腾讯文档导入润色稿并匹配已翻译文章 | 每晚夜间学习前 |
| `prompt_blocks.py` | 统一稳定 prompt 前缀，提高 DeepSeek cache 命中 | 所有 API prompt 构造 |
| `usage_logger.py` | 记录 DeepSeek usage tokens/cache 命中数据 | API 脚本调用后 |
| `deepseek_balance.py` | 调 DeepSeek `/user/balance` 写余额快照 | usage workflow / API workflow |
| `check_polish_today.py` | 检查今天是否有润色记录（无则跳过学习） | 夜间学习入口 |
| `fetch_exchange_rates.py` | 拉取当日汇率写入 exchange_rates.json | 每天 8:20 cron |
| `currency_utils.py` | 统一外币金额后处理与缺失换算检测 | API 标题/正文/对比翻译、`check_currency.py` |
| `normalize_currency_files.py` | 批量修正某天 index/translations/comparisons 里的外币金额换算 | API 翻译后、货币校验前 |
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
LEGO set 等购物意图词。被拦截的条目不要直接写入 `index.json` 或
`need_titles.json`，而是写入 `data/{date}/filtered_rss.json` 隔离区。首页会显示
“被过滤”入口，用户可恢复误杀文章；恢复后才写入 `index.json` 和
`need_titles.json`。旧隔离区按 `data/rss-filter-config.json.filtered_retention_days`
自动删除。

`data/rss-filter-config.json` 可追加：

- `allow_patterns`：白名单正则，命中后即使像促销词也允许入库。
- `block_patterns` / `block_url_keywords`：额外黑名单。
- `filtered_retention_days`：隔离区文件保留天数，默认 7 天。

标题摘要/正文翻译/夜间学习由网页设置写入 `data/automation-config.json`：

- `openclaw`：保留队列，由 OpenClaw 独立 cron 处理。
- `api`：GitHub Actions 读取 Secret `TRANSLATOR_API_KEY`，或按接口自动读取 `DEEPSEEK_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY`，再从 `data/automation-config.json` 读取模型和 `api_base_url` 并运行：

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

网页文章卡片的“对比翻译”是手动-only 流程：模型来自
`data/automation-config.json.api_models`，用户可勾选任意数量模型参与。前端通过
`api-translation.yml` 的 `manual_payload` 传入 `compare_date`、`compare_article_id`
和 `compare_models` JSON 数组，调用 `scripts/translate_compare_api.py`。结果写入
`data/{date}/comparisons/NN.json`，并在 `index.json` 里标记
`comparison_status=done`；它不得写 `translations/NN.json`，不得移除
`requests.json`，也不得参与定时任务。

`api_models` 是所有 API 模型的唯一目录。每个条目至少包含 `label`、`model`、
`base_url`；可选价格字段为 `input_cache_hit_usd_per_million`、
`input_cache_miss_usd_per_million`、`output_usd_per_million`。用量日志和
`usage.html` 都优先读取这些价格；没有价格的模型可以正常翻译，但成本显示为未配置。
Gemini 可通过 Google 官方 OpenAI-compatible endpoint 接入，`base_url` 使用
`https://generativelanguage.googleapis.com/v1beta/openai`，Secret 使用 `GEMINI_API_KEY`
或 `GOOGLE_API_KEY`。Google AI Pro/Gemini Pro 网页订阅不等同于 API key 或 API 额度。

DeepSeek thinking mode 由 `data/automation-config.json` 的
`api_title_thinking`、`api_fulltext_thinking`、`api_nightly_thinking`、
`api_compare_thinking` 控制，可选值为 `disabled`、`high`、`max`。
workflow 会把它们传给 `TRANSLATOR_THINKING_MODE`；脚本统一在
`translate_titles_deepseek.call_deepseek_response()` 中注入 API payload。
默认关闭以节省 token；需要更强自查时优先给正文或夜间学习开 `high/max`。

`article_cache.py` 会写 `data/{date}/sources/NN.json`，里面保存 `body_en`、`paragraphs_en`、`cover_image` 和 `images`。标题摘要和正文 API 都优先读取这个缓存；只有缓存缺失才会临时抓网页。不要让模型负责抓正文或图片。

API 翻译前 workflow 必须先跑 `python3 scripts/fetch_exchange_rates.py` 刷新汇率。标题摘要、正文和多模型对比都必须通过 `currency_utils.py` 做外币金额后处理；不要只依赖模型按 prompt 自觉换算。翻译后、`pre_push_check.py` 前必须跑 `normalize_currency_files.py {date}`，用于修正同一天历史摘要/译文里的旧漏项。`check_currency.py` 会同时检查首页 `index.json` 摘要、`translations/` 正式译文和 `comparisons/` 对比译文。

标题摘要 API 脚本不会翻译全文，也不会写 `translations/NN.json`。标题开启 thinking 时必须预留推理 token，workflow 设置 `TRANSLATOR_TITLE_MAX_TOKENS=4000`；若 API 返回 `finish_reason=length`，脚本会自动提高上限重试一次，避免把英文标题和空摘要长期留在队列。正文 API 脚本会写译文，但必须通过 `translate_pipeline.py --post` 和 `pre_push_check.py`。正文 API 输出较长，workflow 会设置 `TRANSLATOR_FULLTEXT_MAX_TOKENS=12000`。API 抓正文必须使用脚本内的 `extract_article_text()` 或 `article_cache.py`，优先抽取 IGN 的正文段落并过滤导航、页脚、作者简介、推荐链接；不要再用整页 HTML 去标签的方式喂给模型。

正文 API 质检失败时不要无限重试。`translate_fulltext_api.py` 会把草稿保存在 `translations/NN.json`，把首页状态设为 `translation_status=needs_review`，并写 `data/{date}/translation_failures.json`。失败文章会从 `requests.json` 移除，避免每小时重复烧 token。用户可在文章页人工修改并点击“人工放行”；放行后状态改回 `done`，失败记录清除。agent 不要把 `needs_review` 当成待自动重试，除非用户重新勾选提交。

仅 `opus_summary` 超过长度上限时，脚本按完整分句在本地压缩到目标范围，不再发起容易被 thinking token 截断的短 API 返修。词库审计发现译文原样保留英文词条时，脚本会在对应字段中安全替换固定译名后复审。批量翻译成功后还必须更新当前进程内的 index 对象，防止后续失败保存旧状态。

DeepSeek 用量看板读取 `data/usage/deepseek/*.json` 和 `data/usage/deepseek-balance.json`。这些文件是旁路观测数据：记录失败不得中断翻译；余额查询失败不得影响 RSS、标题摘要、正文翻译或夜间学习。用量日志应尽量写入 `article_id`、`article_title`、`article_url`、`article_date` 和 `estimated_cost_usd`；成本按模型目录每 1M tokens 价格估算，真实扣费以平台账户余额为准。看板会单独列出 `fulltext_chunk` / `fulltext_repair` / `audit_doctor` 造成的高请求文章，用来解释为什么某篇正文翻译请求数突然变高。

API 夜间学习不只看当天。默认会扫描最近 45 天里 `polished/` 或反馈有变化、
且尚未学习过当前变更指纹的日期；手动传入日期时才只处理指定日期。

当 `nightly_learner=codex` 时，不调用夜间学习 API。Codex 在腾讯文档同步后读取
`translations/` 与 `polished/` 的差异，更新相同的 `data/learning/style-evidence.json`
和周报文件。候选规则仍需用户在学习页确认后才可进入 `STYLE_PROFILE.md`。

如果用户改用 GPT 网页端翻译并把最终稿贴回腾讯文档，部分文章可能没有
`translations/NN.json`。这种情况下 `nightly_polish_diff.py` 会读取
`sources/NN.json` 与 `polished/*.json`，先检查英文专名是否已存在于
`data/dict.json`，不存在且中文稿中有高置信度对应译名时，只写入
`dictionary_candidate` 学习候选，不直接修改正式词库。

## 腾讯文档润色稿导入

每月腾讯文档链接保存在 `data/tencent-polish-config.json`。文档中的每篇文章按以下格式排列：

```text
YY/MM/DD 标题
副标题
正文第一段
正文第二段
```

每天导入当天内容：

```bash
python3 scripts/import_tencent_polish.py
```

首次接入或补录整月内容时先演练，再正式导入：

```bash
python3 scripts/import_tencent_polish.py --all --dry-run
python3 scripts/import_tencent_polish.py --all
```

Google Docs 同步与润色导入共用 `data/google-polish-config.json` 中的
`document_id`、`credentials_path` 和 `token_path`。换机器时也可设置
`IGN_DAILY_GOOGLE_CREDENTIALS_PATH` 与 `IGN_DAILY_GOOGLE_TOKEN_PATH`；相对路径按
仓库根目录解析。OAuth 客户端文件和 token 不得提交到 Git。

脚本会结合标题和正文匹配 `translations/NN.json`，只写入高置信度结果。已有网页手工润色默认不会被覆盖；先前由腾讯文档导入的记录只在文档内容发生变化时更新。

API prompt 的长规则块必须通过 `scripts/prompt_blocks.py` 生成。标题、全文、分段重试、全文修复和摘要修复统一使用 `translation_system_prompt()`；用户消息必须按“风格画像、固定任务规则、词库/文章动态数据”的顺序构造，并用 `stable_json()` 序列化。不要在各脚本里复制粘贴不同版本的 `TRANSLATION_GUIDE.md` / `STYLE_PROFILE.md` prompt，也不要随意调整稳定字段顺序，否则会让 DeepSeek 前缀缓存整体失效。

## API 翻译双重风格校验 (Style self-check & Local checks)

API 标题翻译、正文翻译和对比翻译已加入强风格自检与本地强质检：
1. **模型端自检 (`style_self_check`)**：每次翻译均会完整读入 `STYLE_PROFILE.md`（无字数限制）。模型输出的 JSON 必须包含 `style_self_check` 字段，确认自身落实了风格指导项（包括 XBOX 规范、标点符号规范、标题重写等）。缺失或任一项不为 `true` 则脚本直接拒收。
2. **本地硬校验**：脚本在写入译文前执行以下强校验：
   - 中文内容中严禁出现 `"Xbox"`（必须写成 `"XBOX"`）；`"Xbox Series X|S"` 或 `"Xbox Series X/S"` 必须写为 `"XBOX Series"`（禁止出现 `"XBOX Series X|S"`）。
   - 中文标点：标题、摘要、段落等中文内容中严禁残留英文双引号 `"`。
   - 首页标题/摘要：全文翻译拟定的标题和摘要，严禁直接沿用 index.json 中的旧 API 自动化标题和摘要。
   - 副标题：副标题（subtitle）不能为空，且不能明显复述标题内容。
3. **拒收机制**：任何校验不通过均执行“拒收”（`[REJECT]`）：不写入 `translations/` 译文文件，且不从 `requests.json` 队列中移除文章，保留在任务列表中以便分析或重新发起翻译。

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
