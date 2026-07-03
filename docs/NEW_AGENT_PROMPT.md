# New Agent Prompt

你现在接手 IGN Daily 项目。项目路径是：

`C:\Users\v_tzntong\Documents\翻译网站项目`

先阅读以下文件，按顺序读：

1. `docs/AGENT_START.md`
2. `docs/TRANSLATION_REQUIREMENTS.md`
3. `docs/AGENT_COLLABORATION.md`
4. `AGENT_BOOTSTRAP.md`
5. `AGENT_HANDOFF.md`
6. `TRANSLATION_GUIDE.md`
7. `STYLE_PROFILE.md`
8. `AGENT_NIGHTLY_LEARNER.md`
9. `data/automation-config.json`
10. `data/dict.json`

接手后先运行：

```bash
python scripts/agent_doctor.py
```

如果用户说「处理翻译队列」或「我刚刚提交了一批翻译」，你要这样做：

1. 先获取最新 `main`，再读取 `data/*/requests.json`。
2. 对每个请求，必须用 `requested_articles[].url` 匹配当前
   `data/{date}/index.json` 里的文章，不要只信旧 ID。
3. 读取对应 `data/{date}/sources/NN.json`。
4. 翻译前先运行 `python scripts/fetch_exchange_rates.py` 刷新汇率；如果网络不可用，
   只能使用仍在有效期内且多源校验过的 `exchange_rates.json`，不能凭记忆粗算。
5. 翻译前运行 `python scripts/translate_pipeline.py {date} {id} --prep`。
6. 按 `TRANSLATION_GUIDE.md`、`STYLE_PROFILE.md` 和 `data/dict.json` 翻译：
   忠于原文；不要意译、扩写、漏段；中文引号用 `「」`；作品名用 `《》`；
   Xbox 统一写作 `XBOX`；`Xbox Series X|S` 统一写作 `XBOX Series`；
   金额和日期必须准确；词库命中必须使用词库译名。
7. 标题、副标题、摘要必须由你重新写。不要沿用现有 `index.json.cn_title`
   或 `index.json.summary`，也不要把 DeepSeek V4 Flash 的标题摘要结果当终稿。
8. 写入 `data/{date}/translations/NN.json`，文件名必须两位补零。
9. 更新 `data/{date}/index.json` 的 `translation_status`、`translation_path`、
   `cn_title`、`summary`。
10. 从 `requests.json` 移除已完成文章，保留未完成文章。
11. 运行：

```bash
python scripts/normalize_currency_files.py {date}
python scripts/translate_pipeline.py {date} {id} --post
python scripts/pre_push_check.py {date}
```

12. 校验通过后，只提交你本次任务相关文件，并用：

```bash
python scripts/git_push.py
```

13. 推送后，把完成稿同步进 `data/google-polish-config.json` 指向的 Google Doc，
    按月份分页、时间倒序、一篇一页的格式写入。

限制：

- 不要显示或询问 PAT、API key。
- 不要调用 DeepSeek/Gemini/OpenAI API，除非用户明确要求。
- 不要回滚你没做的改动；项目可能有另一个 agent 同时协作。
- 动手前后都看 `git status`，并把你做的事追加到 `data/agent-worklog.jsonl`。
- Codex 负责审查和校验时，重点看请求是否丢失、URL 匹配是否正确、词库/金额/日期/引号是否合规、Google Docs 格式是否正确。
