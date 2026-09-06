#!/usr/bin/env python3
"""Maintenance-gated restore, with complete rollback until health succeeds."""
from __future__ import annotations
import contextlib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid

@contextlib.contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Linux protected_regular rejects O_CREAT on an existing file owned by
    # another user in /run/lock, even for root. Open existing locks without it.
    while True:
        try:
            descriptor = os.open(path, os.O_RDWR)
            break
        except FileNotFoundError:
            try:
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o664)
                break
            except FileExistsError:
                continue
    with os.fdopen(descriptor, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield

def remove(path):
    if path.is_dir() and not path.is_symlink(): shutil.rmtree(path)
    else: path.unlink(missing_ok=True)

def restore_owner(path, uid, gid):
    # copytree/copy2 preserve modes and timestamps, but not ownership under sudo.
    os.chown(path, uid, gid)
    if path.is_dir():
        for child in path.rglob('*'):
            os.chown(child, uid, gid)

class Service:
    def run(self, *args, check=True):
        return subprocess.run(([] if os.geteuid() == 0 else ['sudo']) + list(args), check=check, stdout=subprocess.DEVNULL)
    def active(self): return self.run('systemctl', 'is-active', '--quiet', 'ign-daily-api', check=False).returncode == 0
    def stop(self): self.run('systemctl', 'stop', 'ign-daily-api')
    def start(self): self.run('systemctl', 'start', 'ign-daily-api')
    def health(self):
        subprocess.run(['curl', '--retry', '10', '--retry-delay', '1', '--retry-connrefused', '--max-time', '5', '-fsS', 'http://127.0.0.1:8010/health'], check=True, stdout=subprocess.DEVNULL)

def validate_backup(archive, stage):
    with tarfile.open(archive, 'r:gz') as package:
        for member in package.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe backup archive member')
            if path.parts and path.parts[0] not in ('app', 'api'):
                raise ValueError('Unexpected backup archive root')
        package.extractall(stage)
    if not (stage / 'app/data').is_dir(): raise ValueError('Backup has no runtime data')
    for path in (stage / 'app/data').rglob('*.json'):
        json.loads(path.read_text(encoding='utf-8-sig'))
    db = stage / 'api/auth.sqlite3'
    if db.exists():
        with contextlib.closing(sqlite3.connect(f'file:{db}?mode=ro', uri=True)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup SQLite integrity check failed')

def restore(archive, app, api, service, maintenance_lock, write_lock):
    app, api = Path(app), Path(api)
    with tempfile.TemporaryDirectory(prefix='ign-restore-') as temp:
        stage = Path(temp)
        validate_backup(archive, stage)
        if (api / 'auth.sqlite3').exists() and not (stage / 'api/auth.sqlite3').exists():
            raise ValueError('A complete data and database backup is required')
        pairs = [(stage / 'app/data', app / 'data')]
        pairs += [(stage / 'app' / n, app / n) for n in ('exchange_rates.json', 'ign_rss_new.json', '.env') if (stage / 'app' / n).exists()]
        pairs += [(stage / 'api' / n, api / n) for n in ('auth.sqlite3', '.env') if (stage / 'api' / n).exists()]
        saved = []
        with exclusive(maintenance_lock):
            active = service.active()
            service.stop()  # Before replacing any data or SQLite files.
            try:
                with exclusive(write_lock):
                    try:
                        # Keep originals beside targets until every replacement and health check passes.
                        for source, target in pairs + [(None, api / 'auth.sqlite3-wal'), (None, api / 'auth.sqlite3-shm')]:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            suffix = uuid.uuid4().hex
                            backup = target.with_name('.' + target.name + '.before-restore-' + suffix)
                            staging = target.with_name('.' + target.name + '.restore-' + suffix)
                            if source is not None:
                                if source.is_dir(): shutil.copytree(source, staging)
                                else: shutil.copy2(source, staging)
                            existed = target.exists()
                            ownership = target.stat() if existed else target.parent.stat()
                            if existed: target.rename(backup)
                            saved.append((target, backup, existed))
                            if source is not None:
                                staging.rename(target)
                                restore_owner(target, ownership.st_uid, ownership.st_gid)
                                if target.name in ('.env', 'auth.sqlite3'): target.chmod(0o600)
                        if active:
                            service.start()
                            service.health()
                    except BaseException:
                        service.stop()
                        for target, backup, existed in reversed(saved):
                            remove(target)
                            if existed: backup.rename(target)
                        if active: service.start()
                        raise
                    else:
                        for _, backup, existed in saved:
                            if existed: remove(backup)
            except BaseException:
                # A failure acquiring the data lock must not leave the original API stopped.
                if active and not service.active(): service.start()
                raise

def main():
    if len(sys.argv) != 2: raise SystemExit('Usage: restore_data.sh BACKUP.tar.gz')
    app = Path(os.environ.get('APP_DIR', '/srv/ign-daily')).resolve()
    api = Path(os.environ.get('API_DIR', '/srv/ign-daily-api')).resolve()
    for path in (app, api):
        if not str(path).startswith('/srv/') or path == Path('/srv'): raise SystemExit('Unsafe managed path')
    restore(sys.argv[1], app, api, Service(), os.environ.get('IGN_DAILY_MAINTENANCE_LOCK', '/var/lock/ign-daily-maintenance.lock'), os.environ.get('IGN_DAILY_WRITE_LOCK', '/var/lock/ign-daily-write.lock'))
    print('Restore complete; data and database verified together.')

if __name__ == '__main__': main()
