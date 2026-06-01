# scripts/ — 核心脚本

这些脚本是 IGN Daily 工作流的核心组件。新 agent 接手时需要了解每个脚本的用途。

## 必需脚本

| 脚本 | 用途 | 调用时机 |
|------|------|----------|
| `git_push.py` | 安全推送到 GitHub（内嵌 PAT，绕开 GCM） | 每次需要 push 时 |
| `ign_rss_incremental.py` | 增量 RSS 抓取（去重、过滤促销、时间窗口） | 心跳每小时 |
| `agent_doctor.py` | 新 agent 接手时检查仓库关键不变量 | 接手/大改后 |
| `pre_push_check.py` | 包装三连校验，防止忘跑某一步 | 每次 push 前 |
| `rss_queue_check.py` | 校验 RSS-only 自动化写出的 index/need_titles 队列 | GitHub Actions RSS 提交前 |
| `nightly_polish_diff.py` | 对比用户润色与原译，提取风格规律 | 每晚 22:30 cron |
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

它会依次跑三连：

```bash
python3 scripts/post_translate_check.py {date}
python3 scripts/check_currency.py {date}
python3 scripts/enforce_dict_titles.py {date}
```

这三个脚本必须扫描 `data/{date}` 下的真实文件。如果输出 `No index.json` 或
`No translations dir`，不要当作通过，先确认日期和路径是否正确。
