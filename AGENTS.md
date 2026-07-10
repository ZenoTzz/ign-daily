# IGN Daily Agent Guide

这是本仓库唯一的 agent 总入口。不要先通读整个文档库；先运行检查，再按任务路由只读需要的文件。

## 接手后的第一分钟

```bash
git status --short --branch
python scripts/agent_doctor.py
```

- 工作区中的既有改动可能来自用户或其他 agent，未经确认不要回滚、覆盖或顺手提交。
- `agent_doctor.py` 失败时，先处理它报告的不变量；不要把失败当作通过。
- 处理网站刚提交的翻译任务时，以服务器任务和运行时数据为准；GitHub 不是服务器数据的自动双向镜像。

## 任务路由

| 任务 | 必读 | 按需参考 |
|---|---|---|
| 网站选文后的全文翻译与发布 | `docs/TRANSLATION_REQUIREMENTS.md`、`TRANSLATION_GUIDE.md`、`STYLE_PROFILE.md` | `data/README.md`、`server_api/API.md` |
| 标题/摘要恢复任务 | `AGENT_TITLE_TRANSLATOR.md` | `TRANSLATION_GUIDE.md` |
| 夜间学习 | `AGENT_NIGHTLY_LEARNER.md` | `STYLE_PROFILE.md` |
| 后端、服务器、部署、备份 | `docs/ARCHITECTURE.md`、`server_api/DEPLOYMENT.md` | `server_api/API.md`、最近审计报告 |
| 脚本维护或排障 | `scripts/README.md` | 对应脚本源码、`docs/rss-network-fallback.md` |
| 数据结构调整 | `data/README.md` | 前端消费者与校验脚本 |
| 小程序 | `miniprogram/README.md` | `server_api/API.md` |

## 当前系统边界

- `igndaily.site` 服务器是运行时主站，实时内容位于 `/srv/ign-daily/data`。
- 私有 FastAPI 位于 `/srv/ign-daily-api`，负责登录、JSON 写回和 Codex 任务状态。
- GitHub 保存代码和已提交的内容快照，并触发静态代码部署；部署会保留服务器运行时 `data/`。
- Google Docs 是完成译文的编辑副本；夜间学习再把用户润色稿导回仓库。
- 具体自动化归属只看 `data/automation-config.json`，不要把某个 owner 永久写死在说明里。

完整数据流见 `docs/ARCHITECTURE.md`。

## 全仓硬不变量

1. `data/dict.json` 是唯一词库主来源。
2. 历史 `data/{YYYY-MM-DD}/` 永久保留，除非用户明确要求删除。
3. 文章稳定键优先使用 URL；网页展示序号和旧 `requested_ids` 都不能代替 URL 匹配。
4. 译文文件使用两位补零：`id=3` 对应 `translations/03.json`。
5. 新闻日以北京时间 08:00 为边界，不按自然日 00:00 划分。
6. 正文和图片优先读取 `sources/NN.json`；缓存缺失时才允许重新抓取，不要把整页 HTML 交给模型。
7. 密钥只存在于未跟踪的 `.env`、服务器 secret 或 OAuth 文件中，不得写入日志、Markdown、提交或聊天回复。
8. `translation_status=needs_review` 不得自动反复重试；等待用户重新提交或人工放行。
9. `STYLE_PROFILE.md` 只接受用户明确采纳的长期规则，不能由单日样本直接重写。
10. 修改数据前后都检查 `git status`；只提交当前任务相关文件，不回滚陌生改动，不强推。

## 翻译任务的最低完成条件

全文任务必须同时完成：

1. 服务器任务/请求与文章 URL 对应正确。
2. `translations/NN.json` 字段完整，`index.json` 和 `requests.json` 状态一致。
3. 媒体从 `sources/NN.json` 保留或修复。
4. 对涉及日期运行：

```bash
python scripts/pre_push_check.py YYYY-MM-DD
```

5. 网站运行时数据、GitHub 内容快照和 Google Docs 增量副本按任务要求完成同步。
6. Codex job 只有在译文文件确实落盘后才能标记完成。

详细步骤只维护在 `docs/TRANSLATION_REQUIREMENTS.md`，不要在其他总览文档复制一套。

## 协作规则

- 子 agent 与主 agent 共享工作区；分派任务时避免让多个 agent 同时编辑同一文件。
- Git 状态和提交历史是变更归属的主要记录，不再要求为每次工作额外修改运行时 `data/` 工作日志。
- 发现冲突时保留双方内容，先核对调用方、测试和实时配置，再决定合并方式。
- 审查任务默认只读；只有用户要求修改时才实施变更。

## 文档维护规则

每类事实只维护一处：

| 事实 | 唯一维护位置 |
|---|---|
| Agent 入口、路由、全局不变量 | `AGENTS.md` |
| 当前系统架构和数据边界 | `docs/ARCHITECTURE.md` |
| 全文翻译与发布步骤 | `docs/TRANSLATION_REQUIREMENTS.md` |
| 语言、格式、词库翻译规则 | `TRANSLATION_GUIDE.md` |
| 用户确认的个性化偏好 | `STYLE_PROFILE.md` |
| 数据 Schema | `data/README.md` |
| 脚本入口 | `scripts/README.md` |
| API 与部署 | `server_api/API.md`、`server_api/DEPLOYMENT.md` |

- 不要再创建新的 Bootstrap、Handoff、Start 或 New Agent Prompt。
- 不要在 README 里按日期追加变更流水；历史由 Git 和 `docs/*AUDIT*.md` 保存。
- 改动只更新真正拥有该事实的文档，不要求每次同步修改所有说明文件。

## 冲突时的优先级

1. 可执行代码、测试和实时配置。
2. 本文件及对应任务手册。
3. `TRANSLATION_GUIDE.md` 与 `STYLE_PROFILE.md`。
4. 审计报告、旧提交和历史数据仅作背景，不定义当前操作。
