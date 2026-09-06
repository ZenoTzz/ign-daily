from __future__ import annotations
import copy
import contextlib
import json
import os
import subprocess
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from runtime_write_lock import RuntimeConflict, article_snapshot, article_transaction, atomic_json, read_json
from package_server_release import included
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server_api/deploy'))
from runtime_restore import exclusive, restore
from deploy_release import deploy
from update_worker_wrappers import updated

class FakeService:
    def __init__(self, fail=False): self.running = True; self.fail = fail; self.events = []
    def active(self): return self.running
    def stop(self): self.events.append('stop'); self.running = False
    def start(self): self.events.append('start'); self.running = True
    def health(self):
        self.events.append('health')
        if self.fail: raise RuntimeError('simulated health failure')

class RuntimeTransactionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'IGN_DAILY_WRITE_LOCK': str(self.root / 'write.lock')})
        self.env.start()
        self.data = self.root / 'data'
        self.date = '2026-09-06'
        self.article = {'id': 1, 'url': 'https://example.test/a', 'translation_status': 'requested'}
        self.index = {'date': self.date, 'articles': [self.article, {'id': 2, 'url': 'https://example.test/b'}]}
        atomic_json(self.data / self.date / 'index.json', self.index)
    def tearDown(self): self.env.stop(); self.temp.cleanup()
    def test_model_time_updates_to_other_articles_and_requests_survive_commit(self):
        snapshot = article_snapshot(self.data, self.date, self.article)
        latest = copy.deepcopy(self.index)
        latest['articles'][1]['cn_title'] = 'another editor'
        atomic_json(self.data / self.date / 'index.json', latest)
        atomic_json(self.data / self.date / 'requests.json', {'requested_ids': [1, 2]})
        req = {}
        with article_transaction(self.data, self.date, self.article, self.index, req, snapshot):
            self.article['translation_status'] = 'done'
            atomic_json(self.data / self.date / 'index.json', self.index)
            self.assertEqual(req['requested_ids'], [1, 2])
        self.assertEqual(read_json(self.data / self.date / 'index.json')['articles'][1]['cn_title'], 'another editor')
    def test_title_model_call_releases_lock_and_commit_merges_concurrent_changes(self):
        import translate_titles_deepseek as titles
        queue = [{'id': 1, 'url': self.article['url']}]
        atomic_json(self.data / self.date / 'need_titles.json', queue)
        result = {'cn_title': 'Translated', 'summary': 'Summary', 'category': '游戏新闻', 'emoji': '🎮', 'pending_dict': []}
        def model(*args, **kwargs):
            # A second process can take the data lock while the model is working.
            subprocess.run([sys.executable, '-c', "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)", str(self.root / 'write.lock')], check=True)
            latest = read_json(self.data / self.date / 'index.json')
            latest['articles'][1]['cn_title'] = 'Concurrent edit'
            atomic_json(self.data / self.date / 'index.json', latest)
            atomic_json(self.data / self.date / 'need_titles.json', queue + [{'id': 2, 'url': 'https://example.test/b'}])
            return '{}', {}
        with (patch.object(titles, 'DATA_DIR', self.data), patch.object(titles, 'load_env_file'),
              patch.object(titles, 'resolve_api_key', return_value='test'), patch.object(titles, 'cached_article_text', return_value='source'),
              patch.object(titles, 'matched_terms', return_value={}), patch.object(titles, 'build_messages', return_value=[]),
              patch.object(titles, 'call_deepseek_response', side_effect=model), patch.object(titles, 'record_deepseek_usage_safe'),
              patch.object(titles, 'normalize_result', return_value=result), patch.object(titles, 'validate_style_check', return_value=[]),
              patch.object(titles, 'apply_title_dictionary', return_value='Translated'), patch.object(titles.time, 'sleep')):
            self.assertEqual(titles.translate_date(self.date), 1)
        latest = read_json(self.data / self.date / 'index.json')
        self.assertEqual(latest['articles'][0]['cn_title'], 'Translated')
        self.assertEqual(latest['articles'][1]['cn_title'], 'Concurrent edit')
        self.assertEqual(read_json(self.data / self.date / 'need_titles.json'), [{'id': 2, 'url': 'https://example.test/b'}])
    def test_renumbered_url_is_rejected_without_writes(self):
        snapshot = article_snapshot(self.data, self.date, self.article)
        latest = copy.deepcopy(self.index); latest['articles'][0]['url'] = 'https://example.test/reassigned'
        atomic_json(self.data / self.date / 'index.json', latest)
        with self.assertRaises(RuntimeConflict):
            with article_transaction(self.data, self.date, self.article, self.index, {}, snapshot): self.fail('must not enter')
        self.assertEqual(read_json(self.data / self.date / 'index.json'), latest)
    def test_new_translation_file_is_not_overwritten(self):
        snapshot = article_snapshot(self.data, self.date, self.article)
        atomic_json(self.data / self.date / 'translations/01.json', {'url': self.article['url'], 'body': 'newer'})
        with self.assertRaises(RuntimeConflict):
            with article_transaction(self.data, self.date, self.article, self.index, {}, snapshot): self.fail('must not enter')
    def test_failed_commit_rolls_back_all_files(self):
        snapshot = article_snapshot(self.data, self.date, self.article)
        with self.assertRaisesRegex(RuntimeError, 'disk failure'):
            with article_transaction(self.data, self.date, self.article, self.index, {}, snapshot):
                atomic_json(self.data / self.date / 'translations/01.json', {'body': 'partial'})
                atomic_json(self.data / self.date / 'index.json', {})
                raise RuntimeError('disk failure')
        self.assertFalse((self.data / self.date / 'translations/01.json').exists())
        self.assertEqual(read_json(self.data / self.date / 'index.json')['articles'][0], snapshot['article'])
    def test_existing_maintenance_lock_never_uses_create_flag(self):
        lock = self.root / 'shared.lock'
        lock.touch()
        real_open = os.open
        def protected_open(path, flags, *args, **kwargs):
            if Path(path) == lock and flags & os.O_CREAT:
                raise PermissionError('Linux protected_regular')
            return real_open(path, flags, *args, **kwargs)
        with patch('runtime_restore.os.open', side_effect=protected_open):
            with exclusive(lock):
                self.assertTrue(lock.exists())

    def test_package_excludes_runtime_history_and_ios(self):
        for name in ['data/2026-09-06/translations/01.json', 'data/auth.json', 'ios/IGNDaily/App.swift', '.env']:
            self.assertFalse(included(name))
        self.assertTrue(included('data/translation-memory.json'))
        self.assertTrue(included('server_api/ign_daily_api.py'))
    def test_missing_source_never_submits_paid_model_request(self):
        import translate_fulltext_api as fulltext
        atomic_json(self.data / self.date / 'requests.json', {'requested_ids': [1], 'requested_articles': [self.article]})
        with (patch.object(fulltext, 'DATA_DIR', self.data), patch.object(fulltext, 'load_env_file'),
              patch.object(fulltext, 'resolve_api_key', return_value='test'), patch('article_cache.cache_date', return_value=0),
              patch.object(fulltext, 'call_deepseek_response') as model):
            with self.assertRaisesRegex(RuntimeError, 'Source cache unavailable'):
                fulltext.translate_date(self.date)
            model.assert_not_called()

    def test_worker_wrapper_upgrade_is_idempotent(self):
        original = '#!/bin/bash\nsource /srv/ign-daily-ops/config-env.sh\nwith_write_lock\ncd "$APP_DIR"\n'
        once = updated(original)
        self.assertEqual(updated(once), once)
        duplicated = once.replace('with_worker_lock\n', 'with_worker_lock\nwith_write_lock\n')
        self.assertEqual(updated(duplicated), once)
        self.assertEqual(once.count('with_worker_lock'), 1)
        self.assertNotIn('with_write_lock', once)

    def make_backup(self):
        backup = self.root / 'backup'
        (backup / 'app/data').mkdir(parents=True)
        atomic_json(backup / 'app/data/index-list.json', [{'date': 'new'}])
        (backup / 'api').mkdir()
        with contextlib.closing(sqlite3.connect(backup / 'api/auth.sqlite3')) as db, db:
            db.execute('create table sample (value text)'); db.execute("insert into sample values ('new')")
        archive = self.root / 'backup.tar.gz'
        with tarfile.open(archive, 'w:gz') as package: package.add(backup, arcname='.')
        return archive
    def test_restore_failure_restores_data_and_database(self):
        app, api = self.root / 'app', self.root / 'api'
        (app / 'data').mkdir(parents=True); api.mkdir()
        atomic_json(app / 'data/index-list.json', [{'date': 'old'}])
        with contextlib.closing(sqlite3.connect(api / 'auth.sqlite3')) as db, db:
            db.execute('create table sample (value text)'); db.execute("insert into sample values ('old')")
        service = FakeService(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'health failure'):
            restore(self.make_backup(), app, api, service, self.root / 'maintenance.lock', self.root / 'write.lock')
        self.assertEqual(read_json(app / 'data/index-list.json'), [{'date': 'old'}])
        with contextlib.closing(sqlite3.connect(api / 'auth.sqlite3')) as db, db: self.assertEqual(db.execute('select value from sample').fetchone()[0], 'old')
        self.assertTrue(service.running)
        self.assertEqual(service.events[0], 'stop')
    def test_restore_success_replaces_data_and_database_together(self):
        app, api = self.root / 'app', self.root / 'api'
        (app / 'data').mkdir(parents=True); api.mkdir()
        atomic_json(app / 'data/old.json', {})
        service = FakeService()
        with patch('runtime_restore.os.chown', wraps=os.chown) as chown:
            restore(self.make_backup(), app, api, service, self.root / 'maintenance.lock', self.root / 'write.lock')
        expected_owner = app.stat()
        chown.assert_any_call(app / 'data/index-list.json', expected_owner.st_uid, expected_owner.st_gid)
        chown.assert_any_call(api / 'auth.sqlite3', api.stat().st_uid, api.stat().st_gid)
        self.assertEqual((api / 'auth.sqlite3').stat().st_mode & 0o777, 0o600)
        self.assertFalse((app / 'data/old.json').exists())
        self.assertEqual(read_json(app / 'data/index-list.json'), [{'date': 'new'}])
        self.assertTrue(service.running)
    def test_deploy_failure_rolls_back_all_code_and_dependencies(self):
        app, api, package, ops = [self.root / p for p in ('app', 'api', 'package', 'ops')]
        for path in [app / 'data', api / 'venv/bin', package / 'server_api', ops]: path.mkdir(parents=True)
        (app / 'index.html').write_text('old site'); (app / 'data/private.json').write_text('runtime')
        (api / 'ign_daily_api.py').write_text('old api'); (api / 'translation_quality.py').write_text('old quality')
        (api / 'requirements.txt').write_text('old dependencies'); (api / 'venv/bin/python').write_text('old python')
        (api / 'auth.sqlite3').write_text('private database')
        (api / '.env.backup-old').write_text('private credential')
        (api / 'work_readonly.py').write_text('unrelated service')
        (api / 'venv.work-mcp').mkdir()
        (api / 'venv.work-mcp/keep').write_text('other environment')
        (package / 'index.html').write_text('new site'); (package / 'added.html').write_text('new')
        (package / 'server_api/ign_daily_api.py').write_text('new api')
        (package / 'server_api/translation_quality.py').write_text('new quality')
        (package / 'server_api/requirements.txt').write_text('new dependencies')
        original_mode = app.stat().st_mode & 0o777
        package.chmod(0o700)
        service = FakeService(fail=True)
        with self.assertRaisesRegex(RuntimeError, 'health failure'):
            deploy(package, app, api, ops, self.root / 'releases', service, self.root / 'maintenance.lock', self.root / 'write.lock', prepare_env=False)
        self.assertEqual(app.stat().st_mode & 0o777, original_mode)
        self.assertEqual((app / 'index.html').read_text(), 'old site')
        self.assertFalse((app / 'added.html').exists())
        self.assertEqual((api / 'translation_quality.py').read_text(), 'old quality')
        self.assertEqual((api / 'requirements.txt').read_text(), 'old dependencies')
        self.assertEqual((api / 'venv/bin/python').read_text(), 'old python')
        self.assertEqual((api / 'auth.sqlite3').read_text(), 'private database')
        self.assertEqual((api / '.env.backup-old').read_text(), 'private credential')
        self.assertEqual((api / 'work_readonly.py').read_text(), 'unrelated service')
        self.assertEqual((api / 'venv.work-mcp/keep').read_text(), 'other environment')
        self.assertEqual(list((self.root / 'releases').rglob('.env.backup-old')), [])
        self.assertEqual(list((self.root / 'releases').rglob('work_readonly.py')), [])
        self.assertEqual((app / 'data/private.json').read_text(), 'runtime')
        self.assertTrue(service.running)

if __name__ == '__main__': unittest.main()
