#!/usr/bin/env python3
"""Package tracked deployable code, excluding growing runtime history and iOS."""
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def included(name):
    if name == 'data/translation-memory.json': return True
    return not (name.startswith(('data/', 'ios/', '.git/')) or name in ('exchange_rates.json', 'ign_rss_new.json', '.env', 'server_api/.env'))

def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    with tarfile.open(sys.argv[1], 'w:gz') as archive:
        for name in names:
            if name and included(name): archive.add(ROOT / name, arcname=name, recursive=False)

if __name__ == '__main__': main()
