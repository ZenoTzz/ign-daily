#!/usr/bin/env python3
"""Stable prompt blocks shared by API translation scripts.

DeepSeek context caching works best when repeated prompt prefixes are byte-for-
byte stable. Keep the long project rules in a consistent order here so title,
fulltext, chunk retry, and nightly learning calls can reuse cacheable prefixes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_paths import REPO_ROOT


def read_repo_text(path: str, max_chars: int) -> str:
    p = REPO_ROOT / path
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")[:max_chars]


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def shared_rules_block(guide_chars: int = 14000, style_chars: int = 9000) -> dict[str, str]:
    return {
        "project": "IGN Daily",
        "fixed_instruction": (
            "你正在为 IGN Daily 翻译英文游戏/影视新闻。必须遵守词库、翻译指南和风格画像。"
            "中文标点使用全角；作品名用《》。所有外币金额必须写成“外币金额(约合人民币金额)”；"
            "例如 500美元(约合人民币3580元)、2.5亿美元(约合人民币18亿元)。"
            "不要添加原文没有的信息，不要输出 Markdown，除非当前任务明确要求 Markdown。"
        ),
        "translation_guide": read_repo_text("TRANSLATION_GUIDE.md", guide_chars),
        "style_profile": read_repo_text("STYLE_PROFILE.md", style_chars),
    }


def article_context_block(article: dict[str, Any], article_text: str = "") -> dict[str, Any]:
    return {
        "url": article.get("url", ""),
        "en_title": article.get("en_title", ""),
        "cn_title": article.get("cn_title", ""),
        "summary": article.get("summary", ""),
        "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
        "body_excerpt": article_text,
    }


def title_user_payload(
    *,
    article: dict[str, Any],
    article_text: str,
    terms: dict[str, str],
    allowed_categories: list[str],
) -> dict[str, Any]:
    return {
        "cache_prefix": shared_rules_block(guide_chars=9000, style_chars=7000),
        "matched_dictionary_terms": terms,
        "article_context": article_context_block(article, article_text),
        "task": {
            "name": "title_summary",
            "instructions": [
                "只生成首页元数据，不翻译全文。",
                "标题要自然、有新闻感。",
                "摘要 80-160 个中文字符。",
                "如果词库中有译名，必须使用词库译名。",
                "摘要里出现美元、欧元、英镑、日元等外币金额时必须补人民币换算。",
            ],
            "allowed_categories": allowed_categories,
            "required_json_schema": {
                "cn_title": "中文标题",
                "summary": "中文摘要，80-160字",
                "category": "必须从 allowed_categories 选一个",
                "emoji": "一个相关 emoji",
                "pending_dict": [{"en": "未确认英文名", "cn": "建议译名", "reason": "为什么需要人工确认"}],
            },
        },
    }


def fulltext_user_payload(
    *,
    article: dict[str, Any],
    paragraphs: list[str],
    terms: dict[str, str],
) -> dict[str, Any]:
    return {
        "cache_prefix": shared_rules_block(guide_chars=14000, style_chars=9000),
        "matched_dictionary_terms": terms,
        "article_context": article_context_block(article, "\n\n".join(paragraphs[:4])),
        "task": {
            "name": "fulltext_translation",
            "instructions": [
                "逐段翻译 paragraphs_en。",
                "必须保持段落数量和顺序一致。",
                "输出严格 JSON，不要 Markdown。",
                "每篇必须有 2-15 字中文创意副标题 subtitle。",
                "opus_summary 写 150-260 字中文总述。",
                "cn_title、opus_summary 和每个段落里的外币金额必须补人民币换算。",
            ],
            "paragraphs_en": paragraphs,
            "required_json_schema": {
                "id": article.get("id"),
                "url": article.get("url"),
                "en_title": article.get("en_title"),
                "cn_title": "中文标题",
                "subtitle": "2-15字中文创意短句",
                "opus_summary": "150-260字中文总述",
                "publish_time_cn": article.get("publish_time_cn") or article.get("pub_date") or "",
                "paragraphs": [{"en": "原文段落", "cn": "中文译文"}],
                "pending_dict": [{"en": "未确认英文名", "cn": "建议译名", "reason": "原因"}],
                "translated_terms": {},
                "cover": "",
                "images": [],
            },
        },
    }


def chunk_user_payload(
    *,
    article: dict[str, Any],
    chunk: list[tuple[int, str]],
    terms: dict[str, str],
) -> dict[str, Any]:
    return {
        "cache_prefix": shared_rules_block(guide_chars=7000, style_chars=5000),
        "matched_dictionary_terms": terms,
        "article_context": article_context_block(article, ""),
        "task": {
            "name": "fulltext_chunk_retry",
            "instructions": [
                "只翻译本批 paragraphs_en。",
                "必须返回与 paragraphs_en 数量完全一致的 paragraphs 数组。",
                "每个元素必须包含 index 和 cn。",
                "每个 cn 里的外币金额必须补人民币换算。",
            ],
            "paragraphs_en": [{"index": idx, "en": en} for idx, en in chunk],
            "required_json_schema": {"paragraphs": [{"index": 1, "cn": "中文译文"}]},
        },
    }


def nightly_user_payload(date: str, current_profile: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cache_prefix": shared_rules_block(guide_chars=14000, style_chars=0),
        "date": date,
        "current_STYLE_PROFILE_md": current_profile,
        "samples": samples,
        "task": {
            "name": "nightly_style_learning",
            "rules": [
                "保留已有有效规则，删除重复或互相冲突的规则。",
                "只新增可复用的风格规律，不记录单篇文章细节。",
                "如果样本不足，原样返回 STYLE_PROFILE.md，并在 learning_notes 说明 skipped。",
                "STYLE_PROFILE.md 必须是简洁 Markdown，方便后续模型读取。",
            ],
            "required_json_schema": {
                "style_profile_md": "完整的新 STYLE_PROFILE.md 内容",
                "learning_notes": ["本次学习到或跳过的原因"],
            },
        },
    }
