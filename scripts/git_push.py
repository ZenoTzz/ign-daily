# -*- coding: utf-8 -*-
"""
统一的 GitHub push 工具——读取 .env 里的 PAT，通过进程环境传给 Git，
完全绕开 Git Credential Manager,永远不弹窗，也不把 token 放进命令行 URL。

用法:
  python3 scripts/git_push.py [repo_path] [branch]

repo_path 默认是 ign-daily 仓库
branch 默认是 main
"""
import base64
import os
import subprocess
import sys

from common_paths import REPO_ROOT, env_paths

DEFAULT_REPO = str(REPO_ROOT)
DEFAULT_BRANCH = 'main'


def load_env(path):
    """加载 .env 文件,返回 dict"""
    env = {}
    if not os.path.exists(path):
        return env
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def git_auth_env(pat: str, user: str) -> dict[str, str]:
    """Return a Git environment that keeps the PAT out of process arguments."""
    env = os.environ.copy()
    try:
        count = int(env.get('GIT_CONFIG_COUNT', '0'))
    except ValueError:
        count = 0
    credential = base64.b64encode(f'{user}:{pat}'.encode('utf-8')).decode('ascii')
    env['GIT_CONFIG_COUNT'] = str(count + 1)
    env[f'GIT_CONFIG_KEY_{count}'] = 'http.extraHeader'
    env[f'GIT_CONFIG_VALUE_{count}'] = f'AUTHORIZATION: Basic {credential}'
    env['GIT_TERMINAL_PROMPT'] = '0'
    return env


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    branch = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BRANCH

    env_path = next((p for p in env_paths() if p.exists()), env_paths()[0])
    env = load_env(env_path)
    pat = env.get('GITHUB_PAT_IGN_DAILY') or os.environ.get('GITHUB_PAT_IGN_DAILY')
    user = env.get('GITHUB_USER_IGN_DAILY', 'ZenoTzz')

    if not pat:
        print(f'[ERR] GITHUB_PAT_IGN_DAILY not found in {env_path} or environment')
        sys.exit(1)

    # 取 origin URL 解析 repo path（owner/name）
    r = subprocess.run(
        ['git', '-C', repo, 'remote', 'get-url', 'origin'],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print(f'[ERR] cannot get origin url: {r.stderr}')
        sys.exit(1)
    origin = r.stdout.strip()

    # https://github.com/ZenoTzz/ign-daily.git -> ZenoTzz/ign-daily.git
    if not origin.startswith('https://github.com/'):
        print(f'[ERR] only https github origin supported, got: {origin}')
        sys.exit(1)
    repo_path = origin.replace('https://github.com/', '')
    auth_env = git_auth_env(pat, user)

    # 先 pull --rebase 避免 fast-forward 失败
    print(f'[*] pulling --rebase from origin/{branch}')
    pull = subprocess.run(
        ['git', '-C', repo, '-c', 'credential.helper=', 'pull', '--rebase', 'origin', branch],
        env=auth_env,
        check=False,
    )
    if pull.returncode != 0:
        print(f'[ERR] pull --rebase failed (code {pull.returncode}); no push was attempted')
        sys.exit(pull.returncode)

    # Push through origin with an in-memory HTTP header. Do not put the PAT in
    # a remote URL: command lines can be exposed by process viewers and logs.
    print(f'[*] pushing to {repo_path} (branch: {branch})')
    r = subprocess.run(
        ['git', '-C', repo, '-c', 'credential.helper=', 'push', 'origin', branch],
        env=auth_env
    )
    if r.returncode != 0:
        print(f'[ERR] push failed (code {r.returncode})')
        sys.exit(r.returncode)

    print('[OK] push successful')


if __name__ == '__main__':
    main()
