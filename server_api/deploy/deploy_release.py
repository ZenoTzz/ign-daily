#!/usr/bin/env python3
"""Deploy code plus its dependency environment, rolling both back on failure."""
from __future__ import annotations
import os
import json
import contextlib
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from runtime_restore import Service, exclusive, remove

SITE_EXCLUDES = ['.git/', '.env*', 'server_api/.env*', 'data/', 'exchange_rates.json', 'ign_rss_new.json']
API_MANIFEST = '.ign-daily-managed-release.json'
OPS_NAMES = ('run-rss.sh', 'run-api-translation.sh', 'run-exchange.sh', 'run-balance.sh')

@contextlib.contextmanager
def code_permissions():
    previous = os.umask(0o022)
    try: yield
    finally: os.umask(previous)

def sync(source, target, excludes):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    original = target.stat()
    subprocess.run(['rsync', '-a', '--delete', *[arg for item in excludes for arg in ('--exclude', item)], str(source) + '/', str(target) + '/'], check=True)
    # rsync also copies the source root's mode (mktemp/backup roots may be 0700).
    os.chmod(target, original.st_mode & 0o7777)
    os.chown(target, original.st_uid, original.st_gid)

def deploy(package, app, api, ops, releases, service, maintenance_lock, write_lock, prepare_env=True):
    package, app, api, ops, releases = map(Path, (package, app, api, ops, releases))
    if not (package / 'server_api/ign_daily_api.py').is_file(): raise ValueError('Incomplete release package')
    release = releases / uuid.uuid4().hex
    with code_permissions():
        release.mkdir(parents=True, mode=0o755)
    release.chmod(0o755)
    releases.chmod(0o755)
    previous_site, previous_api = release / 'previous-site', release / 'previous-api'
    old_venv = api / 'venv'
    requirements = package / 'server_api/requirements.txt'
    new_environment = not old_venv.exists() or not (api / 'requirements.txt').exists() or requirements.read_bytes() != (api / 'requirements.txt').read_bytes()
    if new_environment:
        if prepare_env:
            with code_permissions():
                subprocess.run([sys.executable, '-m', 'venv', str(release / 'venv')], check=True)
                subprocess.run([str(release / 'venv/bin/pip'), 'install', '-r', str(requirements)], check=True)
        else: (release / 'venv').mkdir()  # Isolated transaction tests only.
    with exclusive(maintenance_lock):
        active = service.active()
        with exclusive(write_lock):
            sync(app, previous_site, SITE_EXCLUDES)
            # Manage only candidate modules and files recorded by our own earlier release.
            # Never mirror-delete unknown API services, environments or private backups.
            managed = {p.name for p in (package / 'server_api').glob('*.py') if not p.name.startswith('test_')}
            managed.add('requirements.txt')
            manifest = api / API_MANIFEST
            previous_managed = set(json.loads(manifest.read_text())) if manifest.exists() else set()
            if any(Path(name).name != name or not (name.endswith('.py') or name == 'requirements.txt') for name in previous_managed):
                raise ValueError('Invalid managed API manifest')
            touched = managed | previous_managed | {API_MANIFEST}
            previous_api.mkdir(mode=0o700)
            for name in touched:
                current = api / name
                if current.exists():
                    if not current.is_file() or current.is_symlink(): raise ValueError('Managed API file is not a regular file')
                    shutil.copy2(current, previous_api / name)
            (release / 'previous-ops').mkdir(mode=0o700)
            for name in OPS_NAMES:
                if (ops / name).is_file(): shutil.copy2(ops / name, release / 'previous-ops' / name)
            for backup in (previous_site, previous_api, release / 'previous-ops'):
                if backup.exists(): backup.chmod(0o700)
            memory = app / 'data/translation-memory.json'
            previous_memory = memory.read_bytes() if memory.exists() else None
            moved_venv = False
            try:
                service.stop()
                sync(package, app, SITE_EXCLUDES)
                for name in previous_managed - managed:
                    (api / name).unlink(missing_ok=True)
                for name in managed:
                    shutil.copy2(package / 'server_api' / name, api / name)
                    (api / name).chmod(0o644)
                manifest.write_text(json.dumps(sorted(managed)) + '\n')
                manifest.chmod(0o644)
                # Fixed data exception is included in the rollback boundary.
                if (package / 'data/translation-memory.json').exists():
                    memory.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(package / 'data/translation-memory.json', memory)
                if new_environment:
                    if old_venv.exists() or old_venv.is_symlink(): old_venv.rename(release / 'previous-venv')
                    moved_venv = True
                    old_venv.symlink_to(release / 'venv', target_is_directory=True)
                updater = app / 'server_api/deploy/update_worker_wrappers.py'
                if updater.exists():
                    subprocess.run([sys.executable, str(updater)], env={**os.environ, 'OPS_DIR': str(ops)}, check=True)
                service.start()
                service.health()
            except BaseException:
                service.stop()
                sync(previous_site, app, SITE_EXCLUDES)
                for name in touched:
                    prior = previous_api / name
                    if prior.exists(): shutil.copy2(prior, api / name)
                    else: (api / name).unlink(missing_ok=True)
                for name in OPS_NAMES:
                    prior = release / 'previous-ops' / name
                    if prior.exists(): shutil.copy2(prior, ops / name)
                if previous_memory is None: memory.unlink(missing_ok=True)
                else: memory.write_bytes(previous_memory)
                if moved_venv:
                    remove(old_venv)
                    if (release / 'previous-venv').exists() or (release / 'previous-venv').is_symlink():
                        (release / 'previous-venv').rename(old_venv)
                if active: service.start()
                raise
            else:
                (release / 'DEPLOYED').write_text('Code and dependencies passed API health validation.\n')
    return release

def main():
    if len(sys.argv) != 2: raise SystemExit('Usage: deploy_release.py EXTRACTED_PACKAGE')
    app = Path(os.environ.get('APP_DIR', '/srv/ign-daily')).resolve()
    api = Path(os.environ.get('API_DIR', '/srv/ign-daily-api')).resolve()
    for path in (app, api):
        if not str(path).startswith('/srv/'): raise SystemExit('Unsafe managed path')
    release = deploy(sys.argv[1], app, api, os.environ.get('OPS_DIR', '/srv/ign-daily-ops'), '/srv/ign-daily-releases', Service(), '/var/lock/ign-daily-maintenance.lock', os.environ.get('IGN_DAILY_WRITE_LOCK', '/var/lock/ign-daily-write.lock'))
    print('Deployment verified; rollback snapshot:', release)

if __name__ == '__main__': main()
