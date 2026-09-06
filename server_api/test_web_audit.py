"""Regression coverage for browser concurrency and job completion contracts."""
import json
import tempfile
import time
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace as Payload
from unittest.mock import patch
from test_ign_daily_api_helpers import load_api, FakeHTTPException


class WebAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = load_api(self.root, self.root / 'api')
        self.api.init_db()
        self.user = {'username': 'audit'}
        self.date = '2026-09-06'
        self.url = 'https://example.com/story'
        self.write(f'data/{self.date}/index.json', {'articles': [{'id': 1, 'url': self.url, 'translation_status': 'done', 'translation_path': 'translations/01.json'}]})
        self.write(f'data/{self.date}/sources/01.json', {'url': self.url, 'paragraphs_en': ['The story.']})

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data))
        return target

    def translation(self):
        return {'url': self.url, 'translator': 'api', 'translator_provider': 'test', 'translator_model': 'test',
                'reasoning_effort': 'low', 'reviewer_model': 'test', 'reviewed_at': 'today', 'prompt_version': 'v1',
                'quality_gate_version': 1, 'paragraphs': [{'en': 'The story.', 'cn': '这则新闻。'}],
                'quality_review': {'status': 'passed', 'reviewer_model': 'test', 'reviewed_at': 'today',
                                   'checks': {'source_coverage': True, 'quote_attribution': True, 'numeric_facts': True}}}

    def job(self):
        return self.api.create_job('translation', self.date, [1], 'audit')

    def test_empty_wrong_url_and_unreviewed_files_never_complete(self):
        for document in ({}, {**self.translation(), 'url': 'https://example.com/other'},
                         {**self.translation(), 'quality_review': {}},
                         {**self.translation(), 'paragraphs': []}):
            with self.subTest(document=document):
                self.write(f'data/{self.date}/translations/01.json', document)
                jid = self.job()
                self.assertNotEqual(self.api.serialize_job(self.api.load_job_row(jid))['status'], 'done')
                with self.assertRaises(FakeHTTPException):
                    self.api.codex_update_job_progress(jid, Payload(status='done', progress=100, message='done'), self.user)
                self.assertNotEqual(self.api.load_job_row(jid)['status'], 'done')

    def test_source_mismatch_blocks_complete(self):
        self.write(f'data/{self.date}/translations/01.json', self.translation())
        self.write(f'data/{self.date}/sources/01.json', {'url': self.url, 'paragraphs_en': ['A different story.']})
        with self.assertRaises(FakeHTTPException):
            self.api.codex_complete_job(self.job(), Payload(message='done'), self.user)

    def test_valid_translation_completes(self):
        self.write(f'data/{self.date}/translations/01.json', self.translation())
        result = self.api.codex_update_job_progress(self.job(), Payload(status='done', progress=100, message='done'), self.user)
        self.assertEqual(result['job']['status'], 'done')

    def test_dictionary_edit_preserves_concurrent_addition_and_metadata(self):
        old = {'cn': '旧译', 'source': 'curated'}
        self.write('data/dict.json', {'terms': {'Old': old, 'New': {'cn': '新增'}}})
        result = self.api.update_dict_term(Payload(original_category='terms', original_en='Old', expected_entry=old,
                                                  category='games', en='Renamed', cn='新译', note=None), self.user)
        data = json.loads((self.root / 'data/dict.json').read_text())
        self.assertIn('New', data['terms'])
        self.assertNotIn('Old', data['terms'])
        self.assertEqual(data['games']['Renamed'], {'cn': '新译', 'source': 'curated'})
        self.assertTrue(result['revision'])

    def test_dictionary_stale_edit_and_full_replace_conflict(self):
        target = self.write('data/dict.json', {'terms': {'Old': {'cn': 'new'}}})
        before = target.read_text()
        with self.assertRaises(FakeHTTPException):
            self.api.update_dict_term(Payload(original_category='terms', original_en='Old', expected_entry={'cn': 'old'},
                                             category='terms', en='Old', cn='overwrite', note=None), self.user)
        with self.assertRaises(FakeHTTPException):
            self.api.replace_dict(Payload(dictionary={}, message='replace', expected_revision='stale'), self.user)
        self.assertEqual(target.read_text(), before)

    def test_create_file_cas_does_not_overwrite(self):
        target = self.write('data/new.json', {'keep': True})
        with self.assertRaises(FakeHTTPException):
            self.api.put_project_file('data/new.json', Payload(content='{}', message='new', sha=None, expected_absent=True), self.user)
        self.assertEqual(json.loads(target.read_text()), {'keep': True})

    def test_polish_delete_checks_revision_and_updates_index(self):
        result = self.api.put_article_polish(self.date, 1, Payload(url=self.url, expected_revision=None, title='a', subtitle='', summary='', body='body'), self.user)
        with self.assertRaises(FakeHTTPException):
            self.api.delete_article_polish(self.date, 1, Payload(url=self.url, expected_revision='stale'), self.user)
        self.api.delete_article_polish(self.date, 1, Payload(url=self.url, expected_revision=result['revision']), self.user)
        result = self.api.get_article_polish(self.date, 1, self.user)
        self.assertFalse(result['exists'])
        self.assertEqual(json.loads((self.root / f'data/{self.date}/polished/_index.json').read_text()), {})

    def test_approval_stale_revision_preserves_file(self):
        target = self.write(f'data/{self.date}/translations/01.json', self.translation())
        before = target.read_text()
        with self.assertRaises(FakeHTTPException):
            self.api.approve_translation(Payload(date=self.date, article_id=1, url=self.url, expected_revision='stale'), self.user)
        self.assertEqual(target.read_text(), before)

    def test_worker_failure_is_persisted_and_retry_creates_job(self):
        jid = self.job()
        self.api.run_local_job([sys.executable, '-c', 'raise SystemExit(2)'], jid)
        deadline = time.monotonic() + 5
        while self.api.load_job_row(jid)['status'] != 'failed' and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')
        _, created, reused = self.api.create_or_reuse_translation_jobs(self.date, [1], 'audit')
        self.assertEqual(len(created), 1)
        self.assertEqual(reused, [])
        with self.api.db() as conn:
            worker = conn.execute('SELECT * FROM local_workers').fetchone()
        self.assertEqual(worker['status'], 'finished')
        self.assertEqual(Path(worker['log_path']).stat().st_mode & 0o777, 0o600)

    def test_worker_timeout_is_failed(self):
        jid = self.job()
        with patch.dict('os.environ', {'IGN_DAILY_JOB_TIMEOUT_SECONDS': '0'}):
            self.api.run_local_job([sys.executable, '-c', 'import time; time.sleep(60)'], jid)
            deadline = time.monotonic() + 5
            while self.api.load_job_row(jid)['status'] != 'failed' and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')
        self.assertIn('超时', self.api.load_job_row(jid)['message'])

    def test_reassigned_article_does_not_complete_or_reuse_old_job(self):
        jid = self.job()
        other = 'https://example.com/other'
        self.write(f'data/{self.date}/index.json', {'articles': [{'id': 1, 'url': other, 'translation_status': 'done', 'translation_path': 'translations/01.json'}]})
        self.write(f'data/{self.date}/sources/01.json', {'url': other, 'paragraphs_en': ['The story.']})
        self.write(f'data/{self.date}/translations/01.json', {**self.translation(), 'url': other})
        with self.assertRaises(FakeHTTPException):
            self.api.codex_complete_job(jid, Payload(message='done'), self.user)
        _, created, reused = self.api.create_or_reuse_translation_jobs(self.date, [1], 'audit')
        self.assertEqual(len(created), 1)
        self.assertEqual(reused, [])

    def test_recovery_does_not_signal_reused_pid(self):
        jid = self.job()
        with self.api.db() as conn:
            conn.execute("INSERT INTO local_workers VALUES (?, ?, ?, ?, ?, ?, 'running')", ('recover', 99999, 'old-identity', json.dumps([jid]), 1, 'private.log'))
            conn.commit()
        with patch.object(self.api, 'worker_identity', return_value='other-process'), patch.object(self.api.os, 'killpg') as kill:
            self.api.supervise_local_worker('recover')
            kill.assert_not_called()
        self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')

    def test_recovery_waits_for_matching_live_worker(self):
        jid = self.job()
        with self.api.db() as conn:
            conn.execute("INSERT INTO local_workers VALUES (?, ?, ?, ?, ?, ?, 'running')", ('live', 99999, 'identity', json.dumps([jid]), int(time.time()), 'private.log'))
            conn.commit()
        with patch.object(self.api, 'worker_identity', side_effect=['identity', None]), patch.object(self.api.time, 'sleep') as sleep:
            self.api.supervise_local_worker('live')
            sleep.assert_called_once_with(1)
        self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')

    def test_manual_approval_reads_and_writes_under_one_lock(self):
        path = self.write(f'data/{self.date}/translations/01.json', self.translation())
        read = self.api.read_json
        observations = []
        def guarded_read(*args, **kwargs):
            observations.append(getattr(self.api._RUNTIME_LOCK_STATE, 'held', False))
            return read(*args, **kwargs)
        with patch.object(self.api, 'read_json', side_effect=guarded_read):
            result = self.api.approve_translation(Payload(date=self.date, article_id=1, url=self.url,
                expected_revision=self.api.content_sha(path.read_text())), self.user)
        self.assertTrue(result['ok'])
        self.assertTrue(observations and all(observations))

    def test_busy_worker_fails_with_retryable_explanation(self):
        jid = self.job()
        self.api.run_local_job([sys.executable, '-c', 'raise SystemExit(75)'], jid)
        deadline = time.monotonic() + 5
        while self.api.load_job_row(jid)['status'] != 'failed' and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn('稍后重新提交', self.api.load_job_row(jid)['message'])

    def test_inference_never_persists_transient_file_state(self):
        jid = self.job()
        self.api.update_job(jid, 'done', 'completed previously', 100)
        before = dict(self.api.load_job_row(jid))
        self.write(f'data/{self.date}/translations/01.json', {})
        self.assertEqual(self.api.serialize_job(self.api.load_job_row(jid))['status'], 'failed')
        self.assertEqual(dict(self.api.load_job_row(jid)), before)
        self.write(f'data/{self.date}/translations/01.json', self.translation())
        self.assertEqual(self.api.serialize_job(self.api.load_job_row(jid))['status'], 'done')
        self.assertEqual(dict(self.api.load_job_row(jid)), before)

    def test_finish_worker_invalid_json_terminates_job(self):
        jid = self.job()
        target = self.write(f'data/{self.date}/translations/01.json', {})
        target.write_text('{broken')
        self.api.finish_local_worker('missing-worker', [jid], 'invalid output')
        self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')
        self.write(f'data/{self.date}/index.json', {'articles': 3})
        self.api.finish_local_worker('missing-worker', [jid], 'invalid output')
        self.assertEqual(self.api.load_job_row(jid)['status'], 'failed')

    def test_alignment_uses_shared_credit_exclusion(self):
        from check_source_alignment import expected_paragraphs
        source = {'url': self.url, 'paragraphs_en': ['The story.', 'Image Credit: IGN', 'Photo by Example']}
        self.assertEqual(expected_paragraphs(source), ['The story.'])
        self.write(f'data/{self.date}/sources/01.json', source)
        self.write(f'data/{self.date}/translations/01.json', self.translation())
        self.assertEqual(self.api.translation_completion_errors(self.date, 1), [])
