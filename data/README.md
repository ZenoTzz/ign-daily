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
  "window": "2026-05-27 08:30 → 2026-05-28 08:30 (CST)",
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
- `translation_status`:
  - `none`：未翻译
  - `requested`：用户已请求翻译，主session待处理
  - `done`：翻译已完成

## translations/NN.json（单篇译文）

```json
{
  "id": 1,
  "en_title": "...",
  "cn_title": "...",
  "url": "https://www.ign.com/...",
  "translated_at": "2026-05-28T11:30+08:00",
  "paragraphs": [
    {"en": "...", "cn": "..."},
    {"en": "...", "cn": "..."}
  ]
}
```

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
  "requested_at": "2026-05-28T09:00+08:00"
}
```
