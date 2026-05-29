# -*- coding: utf-8 -*-
"""
统一的 GitHub push 工具——读取 .env 里的 PAT 并直接通过 URL 内嵌 token 推送，
完全绕开 Git Credential Manager,永远不弹窗。

用法:
  python3 scripts/git_push.py [repo_path] [branch]

repo_path 默认是 ign-daily 仓库
branch 默认是 main
"""
import os
import sys
import subprocess
from pathlib import Path

DEFAULT_REPO = r'C:\Users\Administrator\.openclaw\workspace\ign-daily'
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


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    branch = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BRANCH

    env_path = r'C:\Users\Administrator\.openclaw\workspace\.env'
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

    # 构造 push URL
    push_url = f'https://{user}:{pat}@github.com/{repo_path}'

    # 先 pull --rebase 避免 fast-forward 失败
    print(f'[*] pulling --rebase from origin/{branch}')
    subprocess.run(
        ['git', '-C', repo, 'pull', '--rebase', 'origin', branch],
        check=False
    )

    # push（关闭 credential.helper 防止 GCM 干扰）
    print(f'[*] pushing to {repo_path} (branch: {branch})')
    env2 = os.environ.copy()
    env2['GIT_TERMINAL_PROMPT'] = '0'
    r = subprocess.run(
        ['git', '-C', repo, '-c', 'credential.helper=', 'push', push_url, branch],
        env=env2
    )
    if r.returncode != 0:
        print(f'[ERR] push failed (code {r.returncode})')
        sys.exit(r.returncode)

    print('[OK] push successful')


if __name__ == '__main__':
    main()
