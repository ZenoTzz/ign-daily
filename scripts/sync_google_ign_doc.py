"""Sync completed IGN Daily translations into the configured Google Doc tabs.

Incremental mode is the normal workflow: it reads completed local translation
JSON files and prepends only missing articles to the appropriate monthly tab.
The legacy month-replacement mode remains explicitly opt-in.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_tencent_polish as tencent  # noqa: E402
from common_paths import DATA_DIR, REPO_ROOT  # noqa: E402


DOC_ID = "14a6hFPk8Mbw-FICiFa7icEiyv1BmhkWltf_xOon7uIs"
DEFAULT_CREDENTIALS_PATH = Path(r"D:\Daily News\credentials.json")
DEFAULT_TOKEN_PATH = Path(r"D:\Daily News\token.json")
SCOPES = ["https://www.googleapis.com/auth/documents"]

MONTHS = {
    "2026-07": {
        "url": "https://docs.qq.com/doc/DUFFzSmVQdUFEbG1T",
        "tab_title": "2026年7月",
    },
    "2026-06": {
        "url": "https://docs.qq.com/doc/DUGthbk1CYW9NSmNF",
        "tab_title": "2026年6月",
    },
    "2026-05": {
        "url": "https://docs.qq.com/doc/DUFVmQ3ZPb2RDaVdo",
        "tab_title": "2026年5月",
    },
}

DATE_HEADING_RE = re.compile(r"^\d{2}/\d{2}/\d{2}\s+")


@dataclass(frozen=True)
class TextRange:
    start: int
    end: int


@dataclass(frozen=True)
class MonthPayload:
    text: str
    title_ranges: list[TextRange]
    subtitle_ranges: list[TextRange]
    article_count: int


def load_google_config() -> dict[str, Any]:
    """Read the optional shared Google Docs configuration once and safely."""
    path = DATA_DIR / "google-polish-config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid Google Docs config: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Google Docs config must be a JSON object: {path}")
    return data


def configured_path(value: Any, default: Path) -> Path:
    candidate = Path(str(value)).expanduser() if value else default
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def credential_paths(config: dict[str, Any]) -> tuple[Path, Path]:
    """Resolve credential locations from env/config before falling back locally."""
    credentials = configured_path(
        os.environ.get("IGN_DAILY_GOOGLE_CREDENTIALS_PATH") or config.get("credentials_path"),
        DEFAULT_CREDENTIALS_PATH,
    )
    token = configured_path(
        os.environ.get("IGN_DAILY_GOOGLE_TOKEN_PATH") or config.get("token_path"),
        DEFAULT_TOKEN_PATH,
    )
    return credentials, token


def write_private_token(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def chunk_text(value: str, max_units: int = 24_000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    units = 0
    for char in value:
        char_units = utf16_len(char)
        if current and units + char_units > max_units:
            chunks.append("".join(current))
            current = []
            units = 0
        current.append(char)
        units += char_units
    if current:
        chunks.append("".join(current))
    return chunks


def load_credentials(config: dict[str, Any]) -> Credentials:
    credentials_path, token_path = credential_paths(config)
    creds: Credentials | None = None
    token_scopes: set[str] = set()
    if token_path.exists():
        try:
            token_payload = json.loads(token_path.read_text(encoding="utf-8"))
            raw_scopes = token_payload.get("scopes") or token_payload.get("scope") or []
            if isinstance(raw_scopes, str):
                token_scopes = set(raw_scopes.split())
            else:
                token_scopes = {str(scope) for scope in raw_scopes}
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (OSError, ValueError, json.JSONDecodeError):
            creds = None

    has_required_scope = set(SCOPES).issubset(token_scopes)
    if creds and creds.valid and has_required_scope:
        return creds
    if creds and creds.expired and creds.refresh_token and has_required_scope:
        creds.refresh(Request())
        write_private_token(token_path, creds.to_json())
        return creds

    if not credentials_path.exists():
        raise FileNotFoundError(
            "Google OAuth credentials not found: "
            f"{credentials_path}. Set credentials_path in data/google-polish-config.json "
            "or IGN_DAILY_GOOGLE_CREDENTIALS_PATH."
        )

    if token_path.exists():
        backup = token_path.with_suffix(".readonly.backup.json")
        if not backup.exists():
            shutil.copy2(token_path, backup)
        token_path.unlink()

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    write_private_token(token_path, creds.to_json())
    return creds


def fetch_month_payload(month: str, url: str) -> MonthPayload:
    _title, raw_payload = tencent.fetch_document_payload(url)
    text = tencent.find_document_text(raw_payload)
    articles = [
        article
        for article in tencent.parse_document_articles(text)
        if article.date.startswith(month)
    ]
    articles.sort(key=lambda article: article.date, reverse=True)

    parts: list[str] = []
    title_ranges: list[TextRange] = []
    subtitle_ranges: list[TextRange] = []
    index = 1

    for article in articles:
        yy, mm, dd = article.date[2:4], article.date[5:7], article.date[8:10]
        title_line = f"{yy}/{mm}/{dd} {article.title}\n"
        subtitle_line = f"{article.subtitle}\n"

        title_start = index
        title_end = title_start + utf16_len(title_line)
        title_ranges.append(TextRange(title_start, title_end))
        parts.append(title_line)
        index = title_end

        subtitle_start = index
        subtitle_end = subtitle_start + utf16_len(subtitle_line)
        subtitle_ranges.append(TextRange(subtitle_start, subtitle_end))
        parts.append(subtitle_line)
        index = subtitle_end

        for paragraph in article.paragraphs:
            line = f"{paragraph}\n"
            parts.append(line)
            index += utf16_len(line)

    return MonthPayload(
        text="".join(parts).rstrip() + "\n",
        title_ranges=title_ranges,
        subtitle_ranges=subtitle_ranges,
        article_count=len(articles),
    )


def execute_batch(service: Any, requests: list[dict[str, Any]]) -> None:
    if not requests:
        return
    for attempt in range(6):
        try:
            service.documents().batchUpdate(
                documentId=DOC_ID,
                body={"requests": requests},
            ).execute()
            return
        except HttpError as exc:
            if exc.resp.status != 429 or attempt == 5:
                raise
            time.sleep(20 + attempt * 10)


def get_document(service: Any) -> dict[str, Any]:
    return (
        service.documents()
        .get(
            documentId=DOC_ID,
            includeTabsContent=True,
            fields=(
                "documentId,title,revisionId,"
                "tabs(tabProperties(tabId,title,index),"
                "documentTab(body(content(startIndex,endIndex,"
                "paragraph(elements(textRun(content)),paragraphStyle(namedStyleType))))))"
            ),
        )
        .execute()
    )


def tab_content(document: dict[str, Any], tab_id: str) -> list[dict[str, Any]]:
    for tab in document.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("tabId") == tab_id:
            return tab.get("documentTab", {}).get("body", {}).get("content", [])
    raise RuntimeError(f"Google Doc tab not found: {tab_id}")


def tab_last_end(service: Any, tab_id: str) -> int:
    content = tab_content(get_document(service), tab_id)
    return max((item.get("endIndex", 1) for item in content), default=1)


def resolve_tab(document: dict[str, Any], title: str) -> tuple[str, int]:
    for tab in document.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("title") != title:
            continue
        body = tab.get("documentTab", {}).get("body", {})
        content = body.get("content", [])
        last_end = max((item.get("endIndex", 1) for item in content), default=1)
        return props["tabId"], last_end
    raise RuntimeError(f"Google Doc tab not found: {title}")


def clear_tab(service: Any, tab_id: str, last_end: int) -> None:
    if last_end <= 2:
        return
    execute_batch(
        service,
        [
            {
                "deleteContentRange": {
                    "range": {
                        "tabId": tab_id,
                        "startIndex": 1,
                        "endIndex": last_end - 1,
                    }
                }
            }
        ],
    )


def insert_text(service: Any, tab_id: str, text: str) -> None:
    for chunk in chunk_text(text):
        index = max(1, tab_last_end(service, tab_id) - 1)
        execute_batch(
            service,
            [
                {
                    "insertText": {
                        "location": {"tabId": tab_id, "index": index},
                        "text": chunk,
                    }
                }
            ],
        )


def paragraph_text(item: dict[str, Any]) -> str:
    para = item.get("paragraph") or {}
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in para.get("elements", [])
    )


def style_requests(tab_id: str, content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paragraph_items = [
        item
        for item in content
        if item.get("startIndex") is not None and item.get("paragraph")
    ]
    if not paragraph_items:
        return []

    full_range = {
        "tabId": tab_id,
        "startIndex": paragraph_items[0]["startIndex"],
        "endIndex": paragraph_items[-1]["endIndex"] - 1,
    }
    title_ranges: list[TextRange] = []
    subtitle_ranges: list[TextRange] = []
    special_ranges: list[TextRange] = []
    expect_subtitle = False

    for item in paragraph_items:
        text = paragraph_text(item)
        stripped = text.strip()
        if not stripped:
            continue
        start = int(item["startIndex"])
        end = int(item["endIndex"])
        if DATE_HEADING_RE.match(stripped):
            text_range = TextRange(start, end)
            title_ranges.append(text_range)
            special_ranges.append(text_range)
            expect_subtitle = True
            continue
        if expect_subtitle:
            text_range = TextRange(start, end)
            subtitle_ranges.append(text_range)
            special_ranges.append(text_range)
            expect_subtitle = False

    if not title_ranges:
        raise RuntimeError("No dated title paragraphs found after insertion")

    requests: list[dict[str, Any]] = [
        {
            "updateParagraphStyle": {
                "range": full_range,
                "paragraphStyle": {
                    "namedStyleType": "NORMAL_TEXT",
                    "alignment": "JUSTIFIED",
                    "lineSpacing": 115,
                },
                "fields": (
                    "namedStyleType,alignment,lineSpacing"
                ),
            }
        },
    ]

    special_keys = {(item.start, item.end) for item in special_ranges}
    for item in paragraph_items:
        text = paragraph_text(item)
        stripped = text.strip()
        if not stripped:
            continue
        start = int(item["startIndex"])
        end = int(item["endIndex"])
        if (start, end) in special_keys:
            continue
        requests.extend(
            [
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "paragraphStyle": {
                            "namedStyleType": "NORMAL_TEXT",
                            "alignment": "JUSTIFIED",
                            "lineSpacing": 115,
                        },
                        "fields": "namedStyleType,alignment,lineSpacing",
                    }
                },
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": start,
                            "endIndex": end,
                        },
                        "paragraphStyle": {},
                        "fields": "spaceAbove,spaceBelow",
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": start,
                            "endIndex": end - 1,
                        },
                        "textStyle": {},
                        "fields": (
                            "weightedFontFamily,fontSize,bold,italic,"
                            "foregroundColor"
                        ),
                    }
                },
            ]
        )

    for index, item in enumerate(title_ranges):
        requests.extend(
            [
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item.start,
                            "endIndex": item.end,
                        },
                        "paragraphStyle": {
                            "namedStyleType": "HEADING_1",
                            "alignment": "JUSTIFIED",
                            "spaceAbove": {"magnitude": 3, "unit": "PT"},
                            "spaceBelow": {"magnitude": 3, "unit": "PT"},
                            "lineSpacing": 115,
                            "pageBreakBefore": index > 0,
                        },
                        "fields": (
                            "namedStyleType,alignment,spaceAbove,spaceBelow,"
                            "lineSpacing,pageBreakBefore"
                        ),
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item.start,
                            "endIndex": item.end - 1,
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Microsoft YaHei"},
                            "fontSize": {"magnitude": 18, "unit": "PT"},
                            "bold": True,
                            "italic": False,
                            "foregroundColor": {
                                "color": {
                                    "rgbColor": {
                                        "red": 0.2,
                                        "green": 0.2,
                                        "blue": 0.2,
                                    }
                                }
                            },
                        },
                        "fields": (
                            "weightedFontFamily,fontSize,bold,italic,"
                            "foregroundColor"
                        ),
                    }
                },
            ]
        )

    for item in subtitle_ranges:
        requests.extend(
            [
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item.start,
                            "endIndex": item.end,
                        },
                        "paragraphStyle": {
                            "namedStyleType": "HEADING_2",
                            "alignment": "JUSTIFIED",
                            "spaceAbove": {"magnitude": 3, "unit": "PT"},
                            "spaceBelow": {"magnitude": 3, "unit": "PT"},
                            "lineSpacing": 115,
                        },
                        "fields": (
                            "namedStyleType,alignment,spaceAbove,spaceBelow,"
                            "lineSpacing"
                        ),
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item.start,
                            "endIndex": item.end - 1,
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Microsoft Yahei"},
                            "fontSize": {"magnitude": 15, "unit": "PT"},
                            "bold": False,
                            "italic": True,
                            "foregroundColor": {
                                "color": {
                                    "rgbColor": {
                                        "red": 0.5,
                                        "green": 0.5,
                                        "blue": 0.5,
                                    }
                                }
                            },
                        },
                        "fields": (
                            "weightedFontFamily,fontSize,bold,italic,"
                            "foregroundColor"
                        ),
                    }
                },
            ]
        )
    return requests


def apply_styles(service: Any, tab_id: str) -> None:
    execute_batch(
        service,
        [
            {
                "updateNamedStyle": {
                    "tabId": tab_id,
                    "namedStyle": {
                        "namedStyleType": "NORMAL_TEXT",
                        "textStyle": {
                            "weightedFontFamily": {
                                "fontFamily": "Microsoft Yahei",
                            },
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "bold": False,
                            "italic": False,
                            "foregroundColor": {
                                "color": {"rgbColor": {}}
                            },
                        },
                        "paragraphStyle": {
                            "lineSpacing": 115,
                            "spaceAbove": {"magnitude": 12, "unit": "PT"},
                            "spaceBelow": {"magnitude": 12, "unit": "PT"},
                        },
                    },
                    "fields": (
                        "namedStyleType,textStyle.weightedFontFamily,"
                        "textStyle.fontSize,textStyle.bold,textStyle.italic,"
                        "textStyle.foregroundColor,paragraphStyle.lineSpacing,"
                        "paragraphStyle.spaceAbove,paragraphStyle.spaceBelow"
                    ),
                }
            },
            {
                "updateNamedStyle": {
                    "tabId": tab_id,
                    "namedStyle": {
                        "namedStyleType": "HEADING_1",
                        "textStyle": {
                            "weightedFontFamily": {
                                "fontFamily": "Microsoft YaHei",
                            },
                            "bold": True,
                        },
                    },
                    "fields": (
                        "namedStyleType,textStyle.weightedFontFamily,"
                        "textStyle.bold"
                    ),
                }
            },
            {
                "updateNamedStyle": {
                    "tabId": tab_id,
                    "namedStyle": {
                        "namedStyleType": "HEADING_2",
                        "textStyle": {
                            "weightedFontFamily": {
                                "fontFamily": "Microsoft Yahei",
                            },
                            "fontSize": {"magnitude": 15, "unit": "PT"},
                            "bold": False,
                            "italic": True,
                            "foregroundColor": {
                                "color": {
                                    "rgbColor": {
                                        "red": 0.5,
                                        "green": 0.5,
                                        "blue": 0.5,
                                    }
                                }
                            },
                        },
                    },
                    "fields": (
                        "namedStyleType,textStyle.weightedFontFamily,"
                        "textStyle.fontSize,textStyle.bold,textStyle.italic,"
                        "textStyle.foregroundColor"
                    ),
                }
            },
        ],
    )
    content = tab_content(get_document(service), tab_id)
    requests = style_requests(tab_id, content)
    batch_size = 180
    for start in range(0, len(requests), batch_size):
        execute_batch(service, requests[start : start + batch_size])


def verify_tab(service: Any, tab_id: str, expected_prefix: str) -> int:
    result = (
        service.documents()
        .get(
            documentId=DOC_ID,
            includeTabsContent=True,
            fields=(
                "tabs(tabProperties(tabId,title),"
                "documentTab(body(content(startIndex,endIndex,"
                "paragraph(elements(textRun(content)),paragraphStyle(namedStyleType))))))"
            ),
        )
        .execute()
    )
    for tab in result.get("tabs", []):
        props = tab.get("tabProperties", {})
        if props.get("tabId") != tab_id:
            continue
        count = 0
        first_text = ""
        for item in tab.get("documentTab", {}).get("body", {}).get("content", []):
            para = item.get("paragraph")
            if not para:
                continue
            text = "".join(
                element.get("textRun", {}).get("content", "")
                for element in para.get("elements", [])
            )
            if not first_text and text.strip():
                first_text = text.strip()
            if text.startswith(expected_prefix):
                count += 1
        if not first_text.startswith(expected_prefix):
            raise RuntimeError(
                f"Unexpected first line in {props.get('title')}: {first_text[:80]}"
            )
        return count
    raise RuntimeError(f"Tab not found during verification: {tab_id}")


def sync_incremental(
    service: Any,
    target_date: str,
    *,
    article_ids: set[int] | None = None,
    dry_run: bool = False,
) -> None:
    # 1. Load config
    config = load_google_config()

    global DOC_ID
    doc_id = config.get("document_id", DOC_ID)
    DOC_ID = doc_id

    # Target month
    # E.g. target_date = "2026-07-02" -> month is "2026-07"
    month = target_date[:7]

    # Resolve tab title
    tab_title = None
    for tab_cfg in config.get("tabs", []):
        if tab_cfg.get("month") == month:
            tab_title = tab_cfg.get("title")
            break

    # Fallback to MONTHS tab_title if not in config
    if not tab_title:
        tab_title = MONTHS.get(month, {}).get("tab_title")

    if not tab_title:
        raise ValueError(f"No Google Doc tab title configured for month {month}")

    print(f"[*] Incremental sync for {target_date} into tab '{tab_title}'")

    # 2. Find translations on target_date
    translations_dir = DATA_DIR / target_date / "translations"
    if not translations_dir.exists():
        print(f"[WARN] No translations directory found for {target_date}")
        return

    translation_files = list(translations_dir.glob("*.json"))
    index_path = DATA_DIR / target_date / "index.json"
    if index_path.exists():
        try:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            allowed_paths = {
                str(article.get("translation_path") or "").replace("\\", "/")
                for article in index_data.get("articles", [])
                if article.get("translation_status") == "done"
                and article.get("translation_path")
            }
            if allowed_paths:
                translation_files = [
                    path
                    for path in translation_files
                    if f"translations/{path.name}" in allowed_paths
                ]
            else:
                translation_files = []
        except Exception as e:
            print(f"[WARN] Failed to read {index_path}: {e}")
    if not translation_files:
        print(f"[WARN] No translation files found in {translations_dir}")
        return

    # Load translation details
    articles = []
    for filepath in translation_files:
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            articles.append(data)
        except Exception as e:
            print(f"[ERR] Failed to load {filepath}: {e}")

    if not articles:
        print("[*] No valid articles found to sync.")
        return

    if article_ids:
        articles = [
            article
            for article in articles
            if int(article.get("id") or article.get("json_id") or -1) in article_ids
        ]
        if not articles:
            print(
                f"[*] No matching translated articles found for ids: "
                f"{sorted(article_ids)}"
            )
            return

    # Sort articles by publish_time_cn ascending
    # (oldest first so prepending puts the newest at the top)
    def get_pub_time(a):
        return a.get("publish_time_cn") or ""
    articles.sort(key=get_pub_time)

    # Get current Google Doc content to check for duplicates
    document = get_document(service)
    tab_id, last_end = resolve_tab(document, tab_title)
    content = tab_content(document, tab_id)

    # Extract existing titles to avoid duplication
    existing_titles = set()
    existing_title_items = []
    for item in content:
        para = item.get("paragraph")
        if para:
            text = "".join(
                el.get("textRun", {}).get("content", "")
                for el in para.get("elements", [])
            ).strip()
            if text:
                existing_titles.add(text)
                if DATE_HEADING_RE.match(text):
                    existing_title_items.append(
                        {
                            "text": text,
                            "startIndex": int(item.get("startIndex", 0)),
                            "endIndex": int(item.get("endIndex", 0)),
                        }
                    )

    # Build text to prepend
    date_prefix = target_date[2:].replace("-", "/")
    for article in articles:
        title = article.get("cn_title", "").strip()
        subtitle = article.get("subtitle", "").strip()

        # Heading 1 string
        title_line = f"{date_prefix} {title}\n"
        subtitle_line = f"{subtitle}\n"

        # Check if already exists in Doc
        dup_found = False
        for existing in existing_title_items:
            ext = existing["text"]
            if title_line.strip() in ext:
                dup_found = True
                break
            if title in ext:
                dup_found = True
                if not ext.startswith(f"{date_prefix} "):
                    print(
                        f"[~] Updating date prefix '{ext[:8]}' -> '{date_prefix}' "
                        f"for '{title}'"
                    )
                    if not dry_run:
                        execute_batch(
                            service,
                            [
                                {
                                    "deleteContentRange": {
                                        "range": {
                                            "tabId": tab_id,
                                            "startIndex": existing["startIndex"],
                                            "endIndex": existing["endIndex"] - 1,
                                        }
                                    }
                                },
                                {
                                    "insertText": {
                                        "location": {
                                            "tabId": tab_id,
                                            "index": existing["startIndex"],
                                        },
                                        "text": title_line.strip(),
                                    }
                                },
                            ],
                        )
                    existing["text"] = title_line.strip()
                    existing_titles.discard(ext)
                    existing_titles.add(title_line.strip())
                break

        if dup_found:
            print(f"[ ] Skipping '{title_line.strip()}' (already exists in Google Doc)")
            continue

        print(f"[+] Syncing '{title_line.strip()}' into Google Doc")
        if dry_run:
            continue

        body_parts = []
        for p in article.get("paragraphs", []):
            cn_text = p.get("cn", "").strip()
            if cn_text:
                body_parts.append(f"{cn_text}\n")

        article_text = title_line + subtitle_line + "".join(body_parts)
        article_units = utf16_len(article_text)

        # Step A: Insert text at index 1 of the tab
        execute_batch(
            service,
            [
                {
                    "insertText": {
                        "location": {"tabId": tab_id, "index": 1},
                        "text": article_text,
                    }
                }
            ]
        )

        # Step B: Re-fetch document content to get updated index ranges for styling
        document = get_document(service)
        content = tab_content(document, tab_id)

        new_para_items = []
        old_first_title_start = None

        for item in content:
            start = int(item.get("startIndex", 0))
            end = int(item.get("endIndex", 0))
            if start >= 1 and end <= 1 + article_units + 1:
                if item.get("paragraph"):
                    new_para_items.append(item)
            elif start >= 1 + article_units:
                if item.get("paragraph") and old_first_title_start is None:
                    text = "".join(el.get("textRun", {}).get("content", "") for el in item.get("paragraph", {}).get("elements", [])).strip()
                    if text:
                        old_first_title_start = start

        requests = []

        # Style Heading 1
        if new_para_items:
            first_item = new_para_items[0]
            requests.extend([
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": first_item["startIndex"],
                            "endIndex": first_item["endIndex"],
                        },
                        "paragraphStyle": {
                            "namedStyleType": "HEADING_1",
                            "alignment": "JUSTIFIED",
                            "spaceAbove": {"magnitude": 3, "unit": "PT"},
                            "spaceBelow": {"magnitude": 3, "unit": "PT"},
                            "lineSpacing": 115,
                            "pageBreakBefore": False,
                        },
                        "fields": "namedStyleType,alignment,spaceAbove,spaceBelow,lineSpacing,pageBreakBefore"
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": first_item["startIndex"],
                            "endIndex": first_item["endIndex"] - 1,
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Microsoft YaHei"},
                            "fontSize": {"magnitude": 18, "unit": "PT"},
                            "bold": True,
                            "italic": False,
                            "foregroundColor": {
                                "color": {"rgbColor": {"red": 0.2, "green": 0.2, "blue": 0.2}}
                            },
                        },
                        "fields": "weightedFontFamily,fontSize,bold,italic,foregroundColor"
                    }
                }
            ])

        # Style Heading 2 (Subtitle)
        if len(new_para_items) > 1:
            second_item = new_para_items[1]
            requests.extend([
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": second_item["startIndex"],
                            "endIndex": second_item["endIndex"],
                        },
                        "paragraphStyle": {
                            "namedStyleType": "HEADING_2",
                            "alignment": "JUSTIFIED",
                            "spaceAbove": {"magnitude": 3, "unit": "PT"},
                            "spaceBelow": {"magnitude": 3, "unit": "PT"},
                            "lineSpacing": 115,
                        },
                        "fields": "namedStyleType,alignment,spaceAbove,spaceBelow,lineSpacing"
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": second_item["startIndex"],
                            "endIndex": second_item["endIndex"] - 1,
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Microsoft YaHei"},
                            "fontSize": {"magnitude": 15, "unit": "PT"},
                            "bold": False,
                            "italic": True,
                            "foregroundColor": {
                                "color": {"rgbColor": {"red": 0.5, "green": 0.5, "blue": 0.5}}
                            },
                        },
                        "fields": "weightedFontFamily,fontSize,bold,italic,foregroundColor"
                    }
                }
            ])

        # Style Body Paragraphs
        for item in new_para_items[2:]:
            requests.extend([
                {
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item["startIndex"],
                            "endIndex": item["endIndex"],
                        },
                        "paragraphStyle": {
                            "namedStyleType": "NORMAL_TEXT",
                            "alignment": "JUSTIFIED",
                            "lineSpacing": 115,
                            "spaceAbove": {"magnitude": 12, "unit": "PT"},
                            "spaceBelow": {"magnitude": 12, "unit": "PT"},
                        },
                        "fields": "namedStyleType,alignment,lineSpacing,spaceAbove,spaceBelow",
                    }
                },
                {
                    "updateTextStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": item["startIndex"],
                            "endIndex": item["endIndex"] - 1,
                        },
                        "textStyle": {
                            "weightedFontFamily": {"fontFamily": "Microsoft YaHei"},
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "bold": False,
                            "italic": False,
                            "foregroundColor": {"color": {"rgbColor": {}}},
                        },
                        "fields": "weightedFontFamily,fontSize,bold,italic,foregroundColor"
                    }
                }
            ])

        # Step C: Update the previous first article's Heading 1 style to have pageBreakBefore = True
        if old_first_title_start is not None:
            old_first_title_end = None
            for item in content:
                if int(item.get("startIndex", 0)) == old_first_title_start:
                    old_first_title_end = int(item.get("endIndex", 0))
                    break
            if old_first_title_end is not None:
                requests.append({
                    "updateParagraphStyle": {
                        "range": {
                            "tabId": tab_id,
                            "startIndex": old_first_title_start,
                            "endIndex": old_first_title_end,
                        },
                        "paragraphStyle": {
                            "pageBreakBefore": True,
                        },
                        "fields": "pageBreakBefore"
                    }
                })

        if requests:
            execute_batch(service, requests)

    print(f"[*] Incremental sync completed for {target_date}")


def sync_month(service: Any, month: str, *, dry_run: bool = False) -> None:
    config = MONTHS[month]
    payload = fetch_month_payload(month, config["url"])
    print(
        f"{month}: parsed {payload.article_count} articles, "
        f"{utf16_len(payload.text)} UTF-16 units"
    )
    if dry_run:
        return

    document = get_document(service)
    tab_id, last_end = resolve_tab(document, config["tab_title"])
    clear_tab(service, tab_id, last_end)
    insert_text(service, tab_id, payload.text)
    apply_styles(service, tab_id)
    yy, mm = month[2:4], month[5:7]
    count = verify_tab(service, tab_id, f"{yy}/{mm}/")
    print(f"{month}: synced {count} headings into {config['tab_title']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--incremental",
        metavar="YYYY-MM-DD",
        help="Incremental sync for a specific date (e.g. 2026-07-02)"
    )
    parser.add_argument(
        "--article-id",
        action="append",
        type=int,
        default=[],
        help=(
            "Only sync the specified translated article id. Can be repeated; "
            "requires --incremental."
        ),
    )
    parser.add_argument(
        "--replace-month",
        action="store_true",
        help="Dangerously replace and overwrite the entire Google Doc month tab contents from Tencent Docs"
    )
    parser.add_argument(
        "months",
        nargs="*",
        choices=sorted(MONTHS),
        default=[],
        help="Months to rebuild (requires --replace-month)"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_google_config()
    global DOC_ID
    DOC_ID = str(config.get("document_id") or DOC_ID)

    if not args.incremental and not args.replace_month:
        parser.print_help()
        print("\n[ERR] Please specify either --incremental <YYYY-MM-DD> or --replace-month [months].")
        return 1

    creds = load_credentials(config)
    service = build("docs", "v1", credentials=creds)

    if args.incremental:
        sync_incremental(
            service,
            args.incremental,
            article_ids=set(args.article_id) if args.article_id else None,
            dry_run=args.dry_run,
        )
    elif args.replace_month:
        if not args.months:
            args.months = sorted(MONTHS, reverse=True)
        print(f"[WARNING] You are about to replace and overwrite the entire tabs for {args.months}!")
        print("This will clear the tabs content in the Google Doc and mirror it from Tencent Docs.")
        for month in args.months:
            sync_month(service, month, dry_run=args.dry_run)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
