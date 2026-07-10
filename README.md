# IGN Daily News

IGN Daily 是一个个人化的 IGN 新闻采集、翻译、校验和编辑协作系统。

- 生产主站：[igndaily.site](https://igndaily.site)
- GitHub：代码与已提交内容快照
- Google Docs：完成译文的编辑与润色副本

Agent 或开发者从 [AGENTS.md](AGENTS.md) 开始，不要从历史 Handoff 或审计报告推断当前流程。

## 核心功能

- 定时抓取 IGN RSS，并缓存干净英文正文、封面和正文图片。
- 在网页选择文章后创建 Codex 翻译任务并显示进度。
- 中文译文与英文原文左右对照阅读。
- 在线管理游戏、影视、公司、人物和媒体词库。
- 翻译前后执行词库、金额、标点、段落和媒体完整性校验。
- 将完成稿增量同步到 Google Docs，再导回用户润色稿用于长期学习。
- 保留每日索引、译文、润色、学习证据和 API 用量记录。

## 当前架构

生产服务器保存实时运行数据；GitHub 保存代码和内容快照；Google Docs 是下游编辑副本。三者不是可以互相任意覆盖的同一份存储。

完整边界与数据流见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 快速开始

### 本地查看静态页面

```bash
python -m http.server 8000
```

然后访问 `http://localhost:8000`。

### 仓库健康检查

```bash
python scripts/agent_doctor.py
```

### 翻译校验

```bash
python scripts/pre_push_check.py YYYY-MM-DD
```

## 主要目录

```text
assets/          前端资源
data/            每日索引、source cache、译文、润色和学习数据
docs/            当前架构、任务手册和专项排障
miniprogram/     微信小程序客户端
scripts/         抓取、翻译、校验、同步和运维脚本
server_api/      私有 FastAPI 与服务器部署/备份工具
```

## 文档地图

| 读者/任务 | 文档 |
|---|---|
| Agent 唯一入口 | [AGENTS.md](AGENTS.md) |
| 当前系统边界 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 全文翻译与发布 | [docs/TRANSLATION_REQUIREMENTS.md](docs/TRANSLATION_REQUIREMENTS.md) |
| 翻译语言规范 | [TRANSLATION_GUIDE.md](TRANSLATION_GUIDE.md) |
| 用户确认风格 | [STYLE_PROFILE.md](STYLE_PROFILE.md) |
| 数据 Schema | [data/README.md](data/README.md) |
| 脚本目录 | [scripts/README.md](scripts/README.md) |
| API 合约 | [server_api/API.md](server_api/API.md) |
| 部署、备份与恢复 | [server_api/DEPLOYMENT.md](server_api/DEPLOYMENT.md) |
| RSS 网络故障 | [docs/rss-network-fallback.md](docs/rss-network-fallback.md) |
| 小程序 | [miniprogram/README.md](miniprogram/README.md) |

点时审计报告只记录当时发现，不是当前操作手册。

## 数据与安全原则

- 所有历史 `data/{date}/` 永久保留。
- `data/dict.json` 是词库唯一主来源。
- `.env`、PAT、API key、OAuth credentials 和 token 不得提交到 Git。
- 服务器部署保留运行时数据，不用 GitHub `data/` 整体覆盖生产内容。
- 前端生产写入通过私有 API；GitHub PAT 直写只保留为非生产兼容路径。

## 部署

- 主站服务器部署：`server_api/DEPLOYMENT.md`
- `main` push 会触发静态服务器镜像部署并更新独立 API 副本。
- GitHub Pages 可以作为静态兼容镜像，但不是当前生产数据源。

## License

MIT
