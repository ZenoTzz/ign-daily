# scripts/ — 核心脚本

这些脚本是 IGN Daily 工作流的核心组件。新 agent 接手时需要了解每个脚本的用途。

## 必需脚本

| 脚本 | 用途 | 调用时机 |
|------|------|----------|
| `git_push.py` | 安全推送到 GitHub（内嵌 PAT，绕开 GCM） | 每次需要 push 时 |
| `ign_rss_incremental.py` | 增量 RSS 抓取（去重、过滤促销、时间窗口） | 心跳每小时 |
| `nightly_polish_diff.py` | 对比用户润色与原译，提取风格规律 | 每晚 22:30 cron |
| `check_polish_today.py` | 检查今天是否有润色记录（无则跳过学习） | 夜间学习入口 |
| `fetch_exchange_rates.py` | 拉取当日汇率写入 exchange_rates.json | 每天 8:20 cron |
| `rebuild_index_list.py` | 重建 data/index-list.json（所有日期列表） | 数据修复时 |

## 辅助脚本

| 脚本 | 用途 |
|------|------|
| `ign_image_fetch.py` | 从 IGN 文章页抓取图片 URL |
| `backfill_images_today.py` | 为今天已翻译文章补抓图片 |
| `generate_annotation_response.py` | 为用户批注生成 AI 回复 |
| `sync_dict_excel.py` | 同步 JSON 词库到 Excel 版本 |

## 环境配置

1. 复制 `.env.example` 为 `.env`
2. 填入 GitHub PAT
3. 确保 Python 3.10+ 可用
4. 依赖：`pip install feedparser`（RSS 抓取需要）

## 路径说明

脚本中的路径默认指向 `C:\Users\Administrator\.openclaw\workspace\`。
如果新 agent 在不同机器运行，需要修改：
- `git_push.py` 中的 `DEFAULT_REPO` 和 `.env` 路径
- `ign_rss_incremental.py` 中的 workspace 路径

建议新 agent 用环境变量 `WORKSPACE` 统一管理，或修改脚本顶部的路径常量。
