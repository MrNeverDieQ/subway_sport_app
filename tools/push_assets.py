"""
把核心资产同步到【私有资产仓库】并推送，供 GitHub Actions 打正式 APK。

    .venv\\Scripts\\python.exe tools\\push_assets.py                 # 同步 + 提交 + 推送
    .venv\\Scripts\\python.exe tools\\push_assets.py --no-push       # 只同步 + 提交
    .venv\\Scripts\\python.exe tools\\push_assets.py --dir D:\\x\\assets --remote https://github.com/<me>/<repo>.git

同步内容（镜像：目标里多出来的文件会删掉）：
    audio/**            （跳过 _ 开头的目录：_archive 备份/样例）
    video/**            （跳过 _ 开头的目录：_drafts 废片）
    data/training_blocks.py
    .github/workflows/build_apk.yml   ← 模板 tools/assets_repo/build_apk.yml
    README.md
保留不动：.git/、debug.keystore（CI 首次构建生成并提交，用来保证新包能覆盖安装）。

默认目标目录是本项目旁边的 ../subway_sport_assets，默认远端 https://github.com/MrNeverDieQ/subway_sport_assets.git。
目录不存在会自动 git init 并加 remote；仓库本身要先在 GitHub 上建好（Private，空的）。
"""
import argparse
import datetime
import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.normpath(os.path.join(ROOT, '..', 'subway_sport_assets'))
DEFAULT_REMOTE = 'https://github.com/MrNeverDieQ/subway_sport_assets.git'
WORKFLOW_SRC = os.path.join(ROOT, 'tools', 'assets_repo', 'build_apk.yml')
KEEP = {'.git', '.github', 'debug.keystore', 'README.md'}
README = """# subway_sport_assets

「地铁健身」App 的核心资产（私有）：`audio/`、`video/`、`data/training_blocks.py`。
代码在公开仓库 https://github.com/MrNeverDieQ/subway_sport_app ，这里的内容由那边的
`tools/push_assets.py` 同步过来，**不要在这里手改**。

打 APK：Actions → Build APK → Run workflow（选代码分支和架构）→ 跑完在 run 页面底部 Artifacts 下载。
`debug.keystore` 是 CI 第一次构建时生成并提交的固定调试签名，删了的话手机上要先卸载旧版才能装新版。
"""


def git_exe():
    for cand in ('git', os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Git', 'cmd', 'git.exe')):
        try:
            subprocess.run([cand, '--version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return cand
        except (OSError, subprocess.CalledProcessError):
            continue
    sys.exit('找不到 git')


def run(git, cwd, *args, check=True, capture=False):
    r = subprocess.run([git] + list(args), cwd=cwd, check=check,
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    return r.stdout.decode('utf-8', 'replace') if capture else None


def walk_sources():
    """yield (相对路径, 绝对路径)；相对路径用 / 分隔。"""
    for top in ('audio', 'video'):
        base = os.path.join(ROOT, top)
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith('_') and d != '__pycache__')
            for fn in sorted(files):
                full = os.path.join(dirpath, fn)
                yield os.path.relpath(full, ROOT).replace(os.sep, '/'), full
    yield 'data/training_blocks.py', os.path.join(ROOT, 'data', 'training_blocks.py')


def mirror(dest):
    wanted = {}
    copied = 0
    for rel, src in walk_sources():
        wanted[rel] = src
        dst = os.path.join(dest, *rel.split('/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src) \
                or int(os.path.getmtime(dst)) != int(os.path.getmtime(src)):
            shutil.copy2(src, dst)
            copied += 1
    removed = 0
    for dirpath, dirs, files in os.walk(dest, topdown=True):
        rel_dir = os.path.relpath(dirpath, dest)
        if rel_dir == '.':
            dirs[:] = [d for d in dirs if d not in KEEP]
            files = [f for f in files if f not in KEEP]
        for fn in files:
            rel = os.path.normpath(os.path.join(rel_dir, fn)).replace(os.sep, '/')
            if rel.startswith('./'):
                rel = rel[2:]
            if rel not in wanted:
                os.remove(os.path.join(dirpath, fn))
                removed += 1
    for dirpath, dirs, files in os.walk(dest, topdown=False):   # 清掉空目录
        if dirpath != dest and not os.listdir(dirpath) and '.git' not in dirpath:
            os.rmdir(dirpath)
    wf_dir = os.path.join(dest, '.github', 'workflows')
    os.makedirs(wf_dir, exist_ok=True)
    shutil.copy2(WORKFLOW_SRC, os.path.join(wf_dir, 'build_apk.yml'))
    with io.open(os.path.join(dest, 'README.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(README)
    return len(wanted), copied, removed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dir', default=DEFAULT_DIR)
    ap.add_argument('--remote', default=DEFAULT_REMOTE)
    ap.add_argument('--no-push', action='store_true')
    ap.add_argument('-m', '--message', default=None)
    args = ap.parse_args()

    git = git_exe()
    dest = os.path.abspath(args.dir)
    os.makedirs(dest, exist_ok=True)
    if not os.path.isdir(os.path.join(dest, '.git')):
        run(git, dest, 'init', '-b', 'main')
        run(git, dest, 'remote', 'add', 'origin', args.remote)
        print('已初始化仓库', dest, '→', args.remote)

    total, copied, removed = mirror(dest)
    print('同步 %d 个文件（更新 %d，删除 %d）→ %s' % (total, copied, removed, dest))

    run(git, dest, 'add', '-A')
    status = run(git, dest, 'status', '--porcelain', capture=True).strip()
    if not status:
        print('没有变化，不用提交')
    else:
        msg = args.message or 'assets %s：%d 个文件' % (datetime.date.today().isoformat(), total)
        run(git, dest, 'commit', '-q', '-m', msg)
        print('已提交:', msg)
    if args.no_push:
        return
    run(git, dest, 'push', '-u', 'origin', 'main')
    print('已推送到', args.remote)


if __name__ == '__main__':
    main()
