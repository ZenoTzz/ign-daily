from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from google.auth.exceptions import RefreshError

import sync_google_ign_doc as sync
from sync_google_ign_doc import (
    missing_source_highlight_requests,
    missing_source_ranges,
    utf16_len,
)


class MissingSourceHighlightTests(unittest.TestCase):
    def test_ranges_use_google_docs_utf16_indexes(self) -> None:
        text = "😀前文[原文此处缺失内容]后文\n"
        ranges = missing_source_ranges(text, 10)

        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0].start, 10 + utf16_len("😀前文"))
        self.assertEqual(
            ranges[0].end,
            ranges[0].start + utf16_len("[原文此处缺失内容]"),
        )

    def test_highlight_request_targets_marker_only(self) -> None:
        text = "正文[原文开头缺失内容]继续\n"
        requests = missing_source_highlight_requests(
            "tab-1",
            [
                {
                    "startIndex": 20,
                    "endIndex": 20 + utf16_len(text),
                    "paragraph": {
                        "elements": [{"textRun": {"content": text}}]
                    },
                }
            ],
        )

        self.assertEqual(len(requests), 1)
        update = requests[0]["updateTextStyle"]
        self.assertEqual(update["fields"], "backgroundColor")
        self.assertEqual(update["range"]["tabId"], "tab-1")
        self.assertEqual(update["range"]["startIndex"], 20 + utf16_len("正文"))
        self.assertEqual(
            update["textStyle"]["backgroundColor"]["color"]["rgbColor"],
            {"red": 1.0, "green": 1.0, "blue": 0.0},
        )

    def test_unrelated_brackets_are_not_highlighted(self) -> None:
        self.assertEqual(missing_source_ranges("[普通说明]", 1), [])


class GoogleCredentialRecoveryTests(unittest.TestCase):
    def test_revoked_refresh_token_starts_new_consent_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            credentials_path = root / "credentials.json"
            token_path = root / "token.json"
            credentials_path.write_text("{}", encoding="utf-8")
            token_path.write_text(
                '{"scopes":["https://www.googleapis.com/auth/documents"]}',
                encoding="utf-8",
            )

            expired = Mock(valid=False, expired=True, refresh_token="revoked")
            expired.refresh.side_effect = RefreshError("invalid_grant")
            renewed = Mock()
            renewed.to_json.return_value = '{"token":"renewed"}'
            flow = Mock()
            flow.run_local_server.return_value = renewed

            config = {
                "credentials_path": str(credentials_path),
                "token_path": str(token_path),
            }
            with patch.object(sync.Credentials, "from_authorized_user_file", return_value=expired), patch.object(
                sync.InstalledAppFlow,
                "from_client_secrets_file",
                return_value=flow,
            ):
                result = sync.load_credentials(config)

            self.assertIs(result, renewed)
            flow.run_local_server.assert_called_once_with(port=0, prompt="consent")
            self.assertEqual(token_path.read_text(encoding="utf-8"), '{"token":"renewed"}')
            self.assertTrue(token_path.with_suffix(".readonly.backup.json").exists())


if __name__ == "__main__":
    unittest.main()
