# OpenClaw Title/summary Recovery Card

这是标题/摘要 owner 切换到 OpenClaw 时的专项任务卡。正常情况下先看实时配置；当前为 API owner 时本任务应立即退出。

## Gate

```bash
python scripts/automation_guard.py title
```

输出 `SKIP`：返回 `HEARTBEAT_OK`，不要读取或修改队列。输出 `RUN` 才继续。

## 输入与输出

读取最近非空的：

- `data/{date}/need_titles.json`
- `data/{date}/index.json`
- `data/{date}/sources/NN.json`
- `data/dict.json`
- `TRANSLATION_GUIDE.md`
- `STYLE_PROFILE.md`

按 URL 匹配文章，只更新：

- `cn_title`
- `summary`
- `category`
- `emoji`

不要写 `translations/NN.json`，不要处理全文请求。

## 原文规则

优先使用 `sources/NN.json`。缓存缺失时先运行 `article_cache.py`；仍无法获得可靠原文就保留队列项，不得编造。不要再次运行 RSS 抓取。

## 完成

只移除成功更新的 URL，保留失败项。运行：

```bash
python scripts/pre_push_check.py YYYY-MM-DD
python scripts/agent_doctor.py
```

只提交对应 index、need_titles 和必要的 index-list 变更。不得删除历史日期、强推或覆盖远端陌生改动。
