# Fulltext Translation and Publish Workflow

这是网站选文后由 Codex 完成全文翻译、发布和 Google Docs 同步的唯一操作手册。语言风格细节不在这里重复，分别以 `TRANSLATION_GUIDE.md` 和 `STYLE_PROFILE.md` 为准。

## 开始前

1. 阅读根目录 `AGENTS.md`。
2. 运行：

```bash
git status --short --branch
python scripts/agent_doctor.py
```

3. 读取 `data/automation-config.json`。只有 `fulltext_translator=codex` 时才按本流程接管正常 Codex 队列；用户明确要求其他模式时按其要求执行。
4. 不打印、询问或提交 PAT、API key、服务器密码和 OAuth token。

## 1. 获取并认领任务

生产服务器是刚提交任务的来源。配置了 `IGN_DAILY_API_TOKEN` 时使用：

```bash
python scripts/codex_job_client.py pending --limit 5
python scripts/codex_job_client.py claim JOB_ID
```

也可以按 `server_api/API.md` 调用同一组接口。

- 任务中的 `requested_articles[].url` 或 job item URL 是稳定身份。
- 必须用 URL 对照当天 `index.json`；旧 ID 和网页展示序号只作提示。
- 同时检查任务是否已经有译文或被其他 agent 认领，避免重复处理。

## 2. 准备原文与参考

每篇文章读取：

- job payload / `data/{date}/index.json`
- `data/{date}/sources/NN.json`
- `data/dict.json`
- `TRANSLATION_GUIDE.md`
- `STYLE_PROFILE.md`

运行 `--prep` 时还会读取 `data/translation-memory.json`，但只返回当前文章命中的已批准记录，不会把历史文章或整份记忆库交给模型。批准来源包括用户显式批准，以及从 Google Docs 用户润色终稿高置信对齐后自动生成的记录。

原文和图片以 `sources/NN.json` 为首选。缓存缺失或明显损坏时才运行：

```bash
python scripts/article_cache.py YYYY-MM-DD --missing
```

不要把整页 HTML、导航、广告、作者简介或推荐卡交给模型。

涉及外币时先刷新汇率：

```bash
python scripts/fetch_exchange_rates.py
```

网络不可用时，只能使用仍在新鲜期且多源验证通过的 `exchange_rates.json`。

## 3. 翻译

可先运行预处理：

```bash
python scripts/translate_pipeline.py YYYY-MM-DD ID --prep
```

若输出 `Approved translation memory` 命中：

- 完整英文段落完全一致时，后处理脚本会直接复用人工确认译文。
- 英文直接引语完全一致时，译文必须逐字复用锁定中文；脚本不会对相似引语做猜测替换。
- 只有 `status=approved` 的记录生效；机器候选、存在多个润色版本的冲突项和模糊匹配不参与自动复用。
- 记忆项从 `active_from` 起约束新译文，不追溯改写此前已经完成的历史文章。
- 新记录必须由用户明确确认后通过 `translation_memory.py approve` 加入，普通润色不会静默升级为全局标准。

写入 `data/{date}/translations/NN.json`，文件名两位补零。最低字段集合见 `data/README.md`。

必须做到：

- 忠于正文事实、主体、指代、不确定语气和段落覆盖。
- **正文绝不是摘要。** 对 `sources/NN.json` 中每一个正文 `paragraphs_en` 段落，`translations/NN.json` 必须保留一个、且仅一个同序 `{en, cn}` 对；`en` 必须逐字复制该 source 段落，`cn` 必须完整翻译其全部事实、引语和限定条件。不得合并、拆借、删减或以概述替代段落。仅可排除明确的作者简介、图片署名和站内导航/广告噪音；无法确定时保留并翻译。
- 标题、`subtitle`、`opus_summary` 由 Codex 重新撰写，不能直接把标题 API 占位稿当终稿。
- 词库命中使用 `data/dict.json`；不确定新译名放入 `pending_dict`。
- 保留 source cache 中有效的 `cover` 和 `images`。
- 不翻译 IGN 导航、广告、作者信息、图片署名、社交账号和推荐卡。
- 首译后必须进行一次独立双语复核，重新对照英文和中文检查：逐句覆盖、引语说话者/归属、所有数字与单位。新译文写入 `quality_gate_version=1`、`quality_review` 及完整模型/提示词元数据，不能用首译时的自检代替。

详细标点、XBOX、作品名、人名、金额和语气规则只看 `TRANSLATION_GUIDE.md`。

## 4. 更新发布状态

同一篇完成后同步：

- `translations/NN.json`
- `index.json` 中的 `translation_status`、`translation_path`、`cn_title`、`summary` 和翻译器元数据
- `requests.json`：只移除真正完成的 URL，保留未完成项
- job progress：按文章上报当前步骤

译文落盘后必须从 source cache 合并媒体；脚本会按原始资源 URL 去重，保留已有图片说明，并补齐正文图片：

```bash
python scripts/ensure_translation_media.py YYYY-MM-DD --id ID
```

不要先把 job 标记完成再写文件。每个 job 最多两篇；后端会拒绝超过两篇、缺少译文、索引状态不一致、元数据不完整或独立复核未通过的完成请求。

## 5. 校验

逐篇后处理并对整天做统一校验：

```bash
python scripts/translate_pipeline.py YYYY-MM-DD ID --post
python scripts/normalize_currency_files.py YYYY-MM-DD
python scripts/pre_push_check.py YYYY-MM-DD
```

`pre_push_check.py` 的 source alignment 为阻断性检查：它会逐段比对 source 与译文中的英文锚点、顺序和中文字段。任何不一致都必须先修复，不能将文章标记为 `done`，也不能同步到 Google Docs 或 GitHub。

`pre_push_check.py` 当前运行七项：source alignment、译文结构/媒体与标点、金额、标题词库、全文词库、句段翻译记忆和版本化独立复核门禁。相同的人工确认英文若没有复用锁定中文，也会阻止发布。只以最终 `ALL PRE-PUSH CHECKS PASSED` 为通过。

以下都不是通过：

- `No index.json`
- `No translations dir`
- 词库或金额检查失败
- 副标题、摘要、正文、媒体缺失
- URL/英文标题与 index 不一致

## 6. 同步服务器与 GitHub

发布必须保持同一批文件在服务器运行时和 GitHub 内容快照中一致，但不要用整仓覆盖服务器 `data/`。

1. 通过私有 API 写回服务器相关 JSON，保留内容 SHA 冲突检查。
2. 在本地只提交本任务相关文件。
3. push 前再次看 `git status`，避免带入其他 agent 或运行时生成文件。
4. 使用 `python scripts/git_push.py` 推送 GitHub 快照。

如果服务器和 GitHub 已经不同，先按 URL 和 job 状态判断本次任务的权威侧，再做文件级合并；禁止 `reset --hard`。

## 7. 增量同步 Google Docs

配置来自 `data/google-polish-config.json`，不要在文档中硬编码月份、tab 或 document id。

仅同步本次文章：

```bash
python scripts/sync_google_ign_doc.py --incremental YYYY-MM-DD --article-id ID
```

- sync 是把完成译文写入 Google Docs。
- import 是把用户润色稿读回 `polished/`，两者不能混淆。
- 默认只增量添加缺失文章，不覆盖用户已有编辑。
- `--replace-month` 会清空并重建整月 tab，只有用户明确要求时才允许使用。
- Google Docs 标题日期使用新闻日目录日期，不使用文章自然日。

## 8. 完成任务

所有文章文件和同步都成功后：

```bash
python scripts/codex_job_client.py complete JOB_ID --message "Codex batch completed"
```

失败时使用 `fail` 或保留可恢复的 progress，说明具体文章和阻塞原因。不要为了让进度显示为 100% 而吞掉失败。

最终报告至少包含：文章 ID/标题、校验结果、服务器/GitHub/Google Docs 同步结果和提交哈希。
