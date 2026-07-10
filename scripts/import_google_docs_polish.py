"""Import polished articles from the IGN Daily Google Doc.

The expected tab layout is:

    YY/MM/DD Article title
    Subtitle
    First body paragraph
    Second body paragraph
    ...

Only high-confidence matches against existing translated articles are written.
Existing manually-created polish files are preserved unless
``--replace-existing`` is explicitly supplied.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_tencent_polish as polish  # noqa: E402
from common_paths import DATA_DIR, REPO_ROOT, configure_utf8_stdio  # noqa: E402


DEFAULT_CONFIG = DATA_DIR / "google-polish-config.json"
DEFAULT_CREDENTIALS_PATH = Path(r"D:\Daily News\credentials.json")
DEFAULT_TOKEN_PATH = Path(r"D:\Daily News\token.json")
SCOPES = ["https://www.googleapis.com/auth/documents"]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def load_config(path: Path) -> dict[str, Any]:
    config = load_json(path, {})
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    if not str(config.get("document_id") or "").strip():
        raise ValueError(f"document_id is missing from {path}")
    return config


def configured_path(value: Any, default: Path) -> Path:
    candidate = Path(str(value)).expanduser() if value else default
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()


def write_private_token(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_credentials(config: dict[str, Any]) -> Credentials:
    credentials_path = configured_path(
        os.environ.get("IGN_DAILY_GOOGLE_CREDENTIALS_PATH") or config.get("credentials_path"),
        DEFAULT_CREDENTIALS_PATH,
    )
    token_path = configured_path(
        os.environ.get("IGN_DAILY_GOOGLE_TOKEN_PATH") or config.get("token_path"),
        DEFAULT_TOKEN_PATH,
    )
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
            f"{credentials_path}. Configure credentials_path or "
            "IGN_DAILY_GOOGLE_CREDENTIALS_PATH."
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


def get_document(service: Any, document_id: str) -> dict[str, Any]:
    return (
        service.documents()
        .get(
            documentId=document_id,
            includeTabsContent=True,
            fields=(
                "title,tabs(tabProperties(tabId,title),"
                "documentTab(body(content(paragraph(elements(textRun(content)))))))"
            ),
        )
        .execute()
    )


def paragraph_text(item: dict[str, Any]) -> str:
    para = item.get("paragraph") or {}
    return "".join(
        element.get("textRun", {}).get("content", "")
        for element in para.get("elements", [])
    )


def parse_tab_articles(tab: dict[str, Any]) -> list[polish.DocumentArticle]:
    content = tab.get("documentTab", {}).get("body", {}).get("content", [])
    lines = [
        paragraph_text(item).replace("\u00a0", " ").strip()
        for item in content
        if item.get("paragraph")
    ]
    text = "\n".join(line for line in lines if line)
    return polish.parse_document_articles(text)


def configured_tab_titles(config: dict[str, Any]) -> set[str]:
    tabs = config.get("tabs") or []
    if not isinstance(tabs, list):
        return set()
    return {
        str(tab.get("title") or "").strip()
        for tab in tabs
        if isinstance(tab, dict) and str(tab.get("title") or "").strip()
    }


def fetch_articles(service: Any, config: dict[str, Any]) -> tuple[str, list[polish.DocumentArticle]]:
    document_id = str(config["document_id"]).strip()
    doc = get_document(service, document_id)
    selected_titles = configured_tab_titles(config)
    articles: list[polish.DocumentArticle] = []
    for tab in doc.get("tabs", []):
        title = str(tab.get("tabProperties", {}).get("title") or "").strip()
        if selected_titles and title not in selected_titles:
            continue
        articles.extend(parse_tab_articles(tab))
    articles.sort(key=lambda article: (article.date, article.title), reverse=True)
    return str(doc.get("title") or config.get("document_title") or ""), articles


def dates_to_process(
    articles: list[polish.DocumentArticle],
    requested_date: str | None,
    all_dates: bool,
    timezone_name: str,
) -> list[str]:
    available = sorted({article.date for article in articles})
    if all_dates:
        return available
    if requested_date:
        return [requested_date]
    today = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    return [today]


def import_for_date(
    date: str,
    articles: list[polish.DocumentArticle],
    document_url: str,
    document_title: str,
    *,
    dry_run: bool,
    replace_existing: bool,
) -> tuple[int, int, int, int]:
    sources = [article for article in articles if article.date == date]
    if not sources:
        print(f"NO_SOURCE {date}: no entries in Google Doc")
        return 0, 0, 0, 0

    candidates = polish.load_candidates(date)
    matches, skipped = polish.match_articles(sources, candidates)
    cross_date_matches: list[polish.Match] = []
    cross_date_skipped: list[tuple[polish.DocumentArticle, str]] = []
    if skipped:
        unmatched_sources = [source for source, _reason in skipped]
        cross_date_candidates: list[polish.TranslationCandidate] = []
        for adjacent_date in polish.adjacent_dates(date):
            cross_date_candidates.extend(polish.load_candidates(adjacent_date))
        if cross_date_candidates:
            cross_date_matches, cross_date_skipped = polish.match_articles(
                unmatched_sources,
                cross_date_candidates,
            )
            matched_source_ids = {id(match.source) for match in cross_date_matches}
            skipped = [
                (source, reason)
                for source, reason in cross_date_skipped
                if id(source) not in matched_source_ids
            ]

    imported = 0
    unchanged = 0
    import_messages: list[str] = []
    matches_by_target_date: dict[str, list[polish.Match]] = {}
    for match in [*matches, *cross_date_matches]:
        matches_by_target_date.setdefault(match.candidate.date, []).append(match)

    for target_date, target_matches in sorted(matches_by_target_date.items()):
        target_imported, target_unchanged, messages = polish.import_matches(
            target_date,
            target_matches,
            document_url,
            document_title,
            dry_run=dry_run,
            replace_existing=replace_existing,
            source_type="google_docs",
        )
        imported += target_imported
        unchanged += target_unchanged
        import_messages.extend(messages)

    print(
        f"\n[{date}] source={len(sources)} translated={len(candidates)} "
        f"matched={len(matches) + len(cross_date_matches)} skipped={len(skipped)}"
    )
    for match in cross_date_matches:
        print(
            f"CROSS_DATE {match.source.date} -> {match.candidate.date} "
            f"#{match.candidate.article_id:02d}: {match.source.title}"
        )
    for message in import_messages:
        print(message)
    for source, reason in skipped:
        print(f"SKIP {date}: {source.title} ({reason})")

    return imported, unchanged, len(matches) + len(cross_date_matches), len(skipped)


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--date", help="Import one YYYY-MM-DD date")
    parser.add_argument("--all", action="store_true", help="Import every date found in the document")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without writing files")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace existing manual polish files as well as prior Google Docs imports",
    )
    args = parser.parse_args()
    if args.all and args.date:
        parser.error("--all and --date cannot be used together")

    config = load_config(args.config)
    timezone_name = str(config.get("timezone") or "Asia/Shanghai")
    document_id = str(config["document_id"]).strip()
    document_url = str(config.get("document_url") or f"https://docs.google.com/document/d/{document_id}/edit")

    service = build("docs", "v1", credentials=load_credentials(config))
    document_title, articles = fetch_articles(service, config)
    if not articles:
        raise RuntimeError("No dated articles found in Google Doc")

    selected_dates = dates_to_process(articles, args.date, args.all, timezone_name)
    total_imported = 0
    total_unchanged = 0
    total_matched = 0
    total_skipped = 0

    print(f"Google Doc: {document_title or document_url} ({len(articles)} articles)")
    for date in selected_dates:
        imported, unchanged, matched, skipped = import_for_date(
            date,
            articles,
            document_url,
            document_title,
            dry_run=args.dry_run,
            replace_existing=args.replace_existing,
        )
        total_imported += imported
        total_unchanged += unchanged
        total_matched += matched
        total_skipped += skipped

    action = "would_import" if args.dry_run else "imported"
    print(
        f"\nSUMMARY {action}={total_imported} unchanged={total_unchanged} "
        f"matched={total_matched} skipped={total_skipped}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
