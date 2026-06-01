# 数据格式规范

## ⚠️ 数据保留原则

**所有日期文件夹永久保留**，不得删除。包括：
- 周末、节假日报者生成的 `data/{date}/index.json`
- 历史译文、润色、词库变更
- 学习日志 `data/learning_log/{date}.json`

用户可能在数天/数周后补润色、补翻译或补批注。
Cron 仅负责创建新日期文件夹，不得覆盖/清理/合并旧日期。

## index.json（每日新闻索引）

```json
{
  "date": "2026-05-28",
  "window": "2026-05-27 08:00 → 2026-05-28 08:00 (CST)",
  "total": 38,
  "articles": [
    {
      "id": 1,
      "json_id": 2,
      "category": "科技新闻",
      "emoji": "🔬",
      "en_title": "Opinion: ...",
      "cn_title": "观点：Steam Deck 涨到 $949",
      "summary": "...",
      "url": "https://www.ign.com/articles/...",
      "publish_time_cn": "2026-05-27 14:30",
      "translation_status": "none|requested|done",
      "translation_path": "translations/01.json"
    }
  ]
}
```

字段说明：
- `id` 推送顺序编号（1开始，与网页和聊天里的编号完全一致）
- `json_id` 原始 ign_daily_index.json 中的 id（备查）
- `publish_time_cn` 是发布时间主字段；旧 `pub_date` 只做兼容读取。
- 所有新写入文章都必须包含 `publish_time_cn`，否则首页时间会空白，排序也可能失效。
- `translation_status`:
  - `none`：未翻译
  - `requested`：用户已请求翻译，主session待处理
  - `done`：翻译已完成

## sources/NN.json（英文原文缓存）

每小时 RSS 发现新文章后，`scripts/article_cache.py` 会抓取一次 IGN 页面并写入：

```json
{
  "id": 1,
  "url": "https://www.ign.com/articles/...",
  "title_en": "...",
  "summary_en": "...",
  "body_en": "clean English article body",
  "paragraphs_en": ["paragraph 1", "paragraph 2"],
  "cover_image": "https://assets-prd.ignimgs.com/...",
  "images": ["https://assets-prd.ignimgs.com/..."],
  "publish_time_cn": "2026-06-01 10:20",
  "fetched_at": "2026-06-01T22:30:00+08:00",
  "extractor_version": "article_cache_v1"
}
```

标题摘要 API 和正文 API 必须优先读取这个缓存；只有缓存缺失时才允许临时抓网页。不要把整页 HTML 或导航/页脚文本喂给模型。

## translations/NN.json（单篇译文）

```json
{
  "id": 1,
  "en_title": "...",
  "cn_title": "...",
  "url": "https://www.ign.com/...",
  "translated_at": "2026-05-28T11:30+08:00",
  "subtitle": "急急急急急",
  "opus_summary": "50-70字总结",
  "translated_terms": {},
  "translator": "api",
  "translator_provider": "openai-compatible",
  "translator_model": "deepseek-v4-pro",
  "pending_dict": [],
  "cover": "https://assets-prd.ignimgs.com/...",
  "images": [{"url": "https://assets-prd.ignimgs.com/...", "caption": ""}],
  "paragraphs": [
    {"en": "...", "cn": "..."},
    {"en": "...", "cn": "..."}
  ]
}
```

副标题字段统一使用 `subtitle`。旧字段 `cn_subtitle` 仅作为历史兼容读取，不再作为新译文写入字段。

## dict.json（词库）

```json
{
  "_meta": {"last_updated": "2026-05-28"},
  "games": {"Final Fantasy Tactics": {"cn": "最终幻想战略版", "source": "user"}},
  "movies_tv": {...},
  "companies": {...},
  "people": {...},
  "media": {...},
  "terms": {...}
}
```

`source` 可选：
- `user` 用户确认（最高优先级）
- `ign_cn` IGN中国官网
- `bilibili` B站IGN中国主页
- `consensus` 玩家圈公认（待用户确认）
- `ai_guess` AI推测（必须用户确认）

## requests.json（待翻译请求）

```json
{
  "date": "2026-05-28",
  "requested_ids": [5, 14, 22],
  "requested_articles": [
    {"id": 5, "url": "https://www.ign.com/articles/...", "en_title": "..."}
  ],
  "requested_at": "2026-05-28T09:00+08:00"
}
```

新请求必须尽量写入 `requested_articles`，这样后端可按 URL 重新匹配当前 ID，避免增量抓取插入新文章后出现 ID 偏移。`requested_ids` 只作为旧格式兼容。
