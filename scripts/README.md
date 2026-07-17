# scripts/ — Production Script Index

本文件只回答“哪个脚本做什么、怎样调用”。业务步骤见 `AGENTS.md` 和对应任务手册，数据字段见 `data/README.md`。

## 首选入口

| 脚本 | 用途 | 常用命令 |
|---|---|---|
| `agent_doctor.py` | 仓库、文档链接、JSON、Python 和关键不变量检查 | `python scripts/agent_doctor.py` |
| `pre_push_check.py` | 翻译发布总校验（含 source alignment） | `python scripts/pre_push_check.py DATE` |
| `codex_job_client.py` | 查询、认领、更新服务器 Codex job | `python scripts/codex_job_client.py --help` |
| `git_push.py` | 使用环境中的 PAT 安全 pull/rebase/push | `python scripts/git_push.py` |
| `snapshot_runtime_to_github.py` | 服务器运行时白名单数据 → GitHub 数据快照 | `python scripts/snapshot_runtime_to_github.py --app-dir /srv/ign-daily` |

`git_push.py` 通过进程环境中的 HTTP header 传递 PAT，不把 token 放进远程 URL。PAT 来自未跟踪的 `.env` 或进程环境。

`snapshot_runtime_to_github.py` 使用一次性 clone，只复制日期目录、词库、日期索引和站点合规信息；不会复制翻译记忆、学习、用量、自动化、Google/Tencent 或部署配置，也不会删除 GitHub 中已有的历史文章。纯数据提交不会触发静态部署。

## RSS 与 source cache

| 脚本 | 输入 → 输出 |
|---|---|
| `ign_rss_incremental.py` | RSS → `index.json`、`need_titles.json`、`filtered_rss.json` |
| `article_cache.py` | 文章 URL → `sources/NN.json` 正文与图片缓存 |
| `rss_queue_check.py` | 检查 RSS/index/title queue 形状和新闻日窗口 |
| `fetch_exchange_rates.py` | 多源汇率 → `exchange_rates.json` |

生产定时 owner 是服务器 cron。GitHub workflow 是否定时必须直接查看 `.github/workflows/`；当前相关 workflow 主要作为手动入口。

## 翻译与校验

| 脚本 | 用途 |
|---|---|
| `translate_pipeline.py` | `--prep` 准备，`--post` 完整性检查和索引同步 |
| `translate_titles_deepseek.py` | API 标题/摘要 owner 处理 `need_titles.json` |
| `translate_fulltext_api.py` | 可选 API 正文模式，不是 Codex 正常全文入口 |
| `translate_compare_api.py` | 手动多模型对比，只写 `comparisons/` |
| `api_translation_audit.py` | 正文词库、金额、段落、噪音审计 |
| `audit_doctor.py` | 对疑似审计误报作受控诊断 |
| `ensure_translation_media.py` | 从 source cache 补回译文封面和图片 |
| `normalize_currency_files.py` | 统一当天 index/translation/comparison 金额格式 |
| `post_translate_check.py` | 译文结构、媒体、标点和摘要检查 |
| `check_source_alignment.py` | 阻断正文段落遗漏、合并或英文锚点改写 |
| `check_currency.py` | 外币与人民币换算检查 |
| `enforce_dict_titles.py` | 首页标题词库检查 |
| `check_dict_fulltext.py` | 全文词库检查 |
| `translation_memory.py` | 管理用户明确确认的精确段落/引语译文；翻译时只检索当前文章命中 |
| `check_translation_memory.py` | 阻止已批准的相同英文出现不同中文 |
| `check_translation_quality.py` | 校验新译文的模型元数据、独立复核声明、数字与高置信度漏译风险 |

统一校验入口：

```bash
python scripts/pre_push_check.py YYYY-MM-DD
```

明确批准整段现有译文：

```bash
python scripts/translation_memory.py approve --date YYYY-MM-DD --article-id ID --paragraph N
```

批准一条直接引语时显式提供完整英文和标准中文，并使用 `--kind quote`。不要将模型候选或未经用户确认的普通润色直接批准。

不要单独跑其中一项后声称整批通过。

## Google Docs 与学习

| 脚本 | 用途 |
|---|---|
| `sync_google_ign_doc.py` | 完成译文 → Google Docs；正常使用 `--incremental` |
| `import_google_docs_polish.py` | Google Docs 用户润色 → `polished/`，并刷新精确句段记忆 |
| `import_tencent_polish.py` | 历史腾讯文档 fallback |
| `rebuild_translation_memory.py` | 从已导入润色稿高置信对齐英文锚点；唯一译法批准、冲突译法隔离 |
| `nightly_polish_diff.py` | 原译/润色差异 → `diff_analysis.json` |
| `learning_quality.py` | 夜间学习 v2 的段落对齐、词库质量门禁与晋级状态机 |
| `prepare_codex_learning_review.py` | 把机械证据整理为 Codex 必须语义复核的队列 |
| `apply_codex_learning_review.py` | 校验并应用 Codex 的语义结论，不允许脚本直接晋级 |
| `migrate_learning_v2.py` | 可逆隔离旧版未经审核的低质量候选 |
| `test_miniprogram.py` | 微信小程序页面注册、WXML 结构和 tabBar 导航回归检查 |
| `nightly_style_api.py` | API 学习模式的证据池与周报 |
| `publish_weekly_learning_report.py` | 生成/刷新学习周报 |
| `generate_annotation_response.py` | 为学习页批注生成回复 |

Google OAuth 路径来自 `data/google-polish-config.json`，也可用：

- `IGN_DAILY_GOOGLE_CREDENTIALS_PATH`
- `IGN_DAILY_GOOGLE_TOKEN_PATH`

credentials 和 token 不得提交到 Git。`sync_google_ign_doc.py --replace-month` 是破坏性整月重建，仅在用户明确要求时使用。

## 自动化、用量与维护

| 脚本 | 用途 |
|---|---|
| `automation_guard.py` | OpenClaw 在写队列前检查实时 owner |
| `job_progress.py` | 翻译脚本写文章级进度文件 |
| `usage_logger.py` | 记录模型 token 和估算成本 |
| `deepseek_balance.py` | 查询平台余额快照 |
| `record_deepseek_run_cost.py` | 汇总一次运行的估算/实际扣费 |
| `rebuild_index_list.py` | 数据修复时重建日期索引 |
| `sync_translation_to_index.py` | 从译文回填 index 状态的维护工具 |
| `sync_dict_excel.py` | JSON 词库导出到 Excel |
| `check_encoding_health.py` | 检查真实 mojibake/替换字符 |

`data/usage/` 是旁路观测数据，记录失败不应阻断 RSS 或翻译主流程。

## 路径与环境

生产脚本通过 `common_paths.py` 从仓库位置推导根目录、`data/`、词库和汇率文件。

环境文件查找顺序以 `common_paths.env_paths()` 为准。新脚本不得再新增个人机器绝对路径；历史路径只存在于兼容 fallback 或 `scripts/legacy/`。

## 状态分类

- 生产：本文件列出的日常入口和 `.github/workflows/` / 服务器 ops 调用脚本。
- 维护：`normalize_*`、`rebuild_*`、`sync_*` 等明确按需工具。
- 测试：`test_*.py`。
- 历史：`scripts/legacy/`，不得接入 cron、API 或日常翻译。

删除或合并脚本前先搜索调用方：

```bash
rg -n "script_name.py" .github server_api scripts *.md docs data/README.md
```
