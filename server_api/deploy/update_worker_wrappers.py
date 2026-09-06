#!/usr/bin/env python3
"""Update generated wrappers idempotently, without reinstalling or secrets."""
import os
from pathlib import Path

GATE_SOURCE = 'source "$APP_DIR/server_api/deploy/worker_locks.sh"'
CONFIG_SOURCE = 'source /srv/ign-daily-ops/config-env.sh'

def updated(text):
    lines = text.splitlines()
    if CONFIG_SOURCE not in lines:
        raise ValueError('Unknown worker wrapper layout; refusing to change it')
    # Normalize older and already-updated wrappers to exactly one worker gate.
    lines = [line for line in lines if line.strip() not in ('with_write_lock', 'with_worker_lock', GATE_SOURCE)]
    position = lines.index(CONFIG_SOURCE) + 1
    lines[position:position] = [GATE_SOURCE, 'with_worker_lock']
    return ('\n'.join(lines) + '\n').replace('is not set"\n  exit 0', 'is not set"\n  exit 78')

def main():
    ops = Path(os.environ.get('OPS_DIR', '/srv/ign-daily-ops'))
    for name in ('run-rss.sh', 'run-api-translation.sh', 'run-exchange.sh', 'run-balance.sh'):
        path = ops / name
        if path.exists():
            path.write_text(updated(path.read_text()))
            path.chmod(0o755)

if __name__ == '__main__': main()
