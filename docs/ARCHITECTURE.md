# IGN Daily Current Architecture

本文件只描述当前系统边界和数据流。操作步骤分别放在任务手册、脚本说明和服务端文档中。

## 三个数据层

```text
IGN RSS / article pages
          │
          ▼
igndaily.site server
  /srv/ign-daily/data        运行时主数据
  /srv/ign-daily-api         登录、文件和 Codex job API
          │
          ├────────► GitHub main
          │          代码 + 已提交内容快照 + 部署触发
          │
          └────────► Google Docs
                     完成译文的编辑副本
                              │
                              └──► polished / learning
                                   用户润色导回证据池
```

### 服务器

- `https://igndaily.site` 是生产主站。
- `/srv/ign-daily/data` 是实时内容源，服务器部署不得用 GitHub 的 `data/` 整体覆盖它。
- `/srv/ign-daily-api` 是独立运行的 FastAPI 副本，Nginx 通过 `/api/` 反向代理。
- 服务器 cron 负责生产 RSS、标题 API 补跑、汇率、余额和每日备份。具体时间以服务器 crontab 和 `server_api/deploy/install_server.sh` 为准。

### GitHub

- `main` 保存代码框架和已经提交的内容备份。
- push 会触发 `.github/workflows/deploy-static-server.yml`，部署代码并更新独立 API 副本。
- 部署通过 `rsync` 排除项原地保留服务器的 `data/`、`exchange_rates.json`、`ign_rss_new.json`、`.env` 和鉴权数据库，不再临时搬移运行时数据；版本化的 `translation-memory.json` 是唯一受控同步例外。
- RSS、翻译、汇率等 Actions 当前是手动入口；是否有 schedule 必须直接查看 workflow，不能依据旧文档猜测。
- GitHub 与服务器不是自动双向复制。发生内容差异时，先确认哪一侧是本次任务的来源，禁止用 `reset --hard` 粗暴解决。

### Google Docs

- `sync_google_ign_doc.py` 把完成译文增量写入 `data/google-polish-config.json` 指定的文档。
- `import_google_docs_polish.py` 把用户润色稿导回 `data/{date}/polished/`。
- Google Docs 是编辑和学习链路的下游副本，不是站点唯一数据源或服务器灾备。
- OAuth credentials/token 不得进入 Git；路径由配置文件或 `IGN_DAILY_GOOGLE_*_PATH` 环境变量提供。

## 自动化归属

`data/automation-config.json` 是 owner 的唯一事实来源：

- `title_translator`: `api` 或 `openclaw`
- `fulltext_translator`: `codex`、`api` 或兼容模式
- `nightly_learner`: `codex`、`api` 或 `openclaw`

当前常用组合是标题 API、正文 Codex、夜间学习 Codex，但 agent 每次运行仍必须读取实时配置。OpenClaw 任务先运行 `scripts/automation_guard.py`；输出 `SKIP` 就停止。

## 主流程

### RSS 与标题

1. 服务器 RSS 脚本写入 `index.json`、`need_titles.json`、`filtered_rss.json`。
2. `article_cache.py` 缓存干净正文与图片到 `sources/NN.json`。
3. 标题 owner 处理 `cn_title`、`summary`、分类和 emoji。
4. 被过滤稿件留在隔离区，只有用户恢复后才进入正常队列。

### 全文翻译与发布

1. 用户在主站勾选文章，FastAPI 写请求并创建 Codex job。
2. Codex 从服务器任务读取文章和 source cache，按 URL 核对稳定身份。
3. 译文落到 `translations/NN.json`，同步更新 `index.json` 和 `requests.json`。
4. 校验通过后，将同一内容保存到 GitHub 快照，并增量同步 Google Docs。
5. 只有译文文件存在且发布状态一致时，job 才能完成。

### 夜间学习

1. 先从 Google Docs 导入用户润色稿；腾讯文档只作历史缺口 fallback。
2. 对比原译和润色，更新 `style-evidence.json` 与周报。
3. 单日样本只能成为候选证据。
4. 用户明确采纳周报规则后，才允许更新 `STYLE_PROFILE.md`。

### 部署与恢复

- 安装、静态部署、备份、恢复以 `server_api/DEPLOYMENT.md` 为准。
- API 合约以 `server_api/API.md` 为准。
- 后端审计是点时记录，不覆盖这份当前架构说明。

## 并发与一致性边界

- 服务器写任务共享 `/var/lock/ign-daily-write.lock`；GitHub 写 workflow 共享同一 concurrency group。
- 单个 API JSON 写入具备原子替换和内容 SHA 冲突检查。
- 多个 JSON 文件组成的一次业务操作仍不是数据库事务；中断时应依据 URL、job 状态和校验脚本复核，不要凭单个状态字段推断全部成功。
- 历史日期目录永久保留。恢复前先备份，任何批量覆盖必须有明确来源和回滚点。
