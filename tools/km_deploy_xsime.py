#!/usr/bin/env python3
"""把空明码词库部署到 XSIME（rimes / scholay），替代旧的 fcitx5-rime 流程。

XSIME 的数据布局（XDG）：
  ~/.local/share/rimes/schemes/active.yaml          当前激活的 package + schema
  ~/.local/share/rimes/schemes/packages/<id>/       共享数据目录（含 default.yaml 与各词库源文件）
  ~/.local/share/rimes/schemes/learning/<id>/       用户数据目录（build/ 编译产物）
  ~/.local/state/rimes/log/                         部署日志

部署器 `rimes-deploy`（libexec/rimes/）的调用约定（见 deploy_main.cpp）：
  argv = [shared_data_dir, user_data_dir, log_dir, full_check]
  fd 3 必须是指向 <user_data_dir>/.rimes-engine.lock 的、已加锁的描述符
该锁由运行中的 fcitx5（rimes 插件）持有，因此部署前必须先停掉 fcitx5，
部署完再拉起来；否则 rimes-deploy 会以退出码 3 直接拒绝。

用法：
  python3 tools/km_deploy_xsime.py                 # 增量部署 + 重启输入法
  python3 tools/km_deploy_xsime.py --full          # 强制全量重建
  python3 tools/km_deploy_xsime.py --dry-run       # 只看哪些文件会同步
  python3 tools/km_deploy_xsime.py --no-restart    # 假定 fcitx5 已停，只跑部署
"""
import argparse
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser('~')
RIMES = os.path.join(HOME, '.local/share/rimes')
SCHEMES = os.path.join(RIMES, 'schemes')
DEPLOY = os.path.join(HOME, '.local/libexec/rimes/rimes-deploy')
LOG_DIR = os.path.join(HOME, '.local/state/rimes/log')
FCITX_UNIT = 'app-org.fcitx.Fcitx5@autostart.service'

# 需要同步到包目录的文件（akm* 是空明码各版本，缺一不可）
SYNC_FILES = [
    'kongmingmas.schema.yaml', 'kongmingmas_t.schema.yaml', 'kongmingmas_ext.schema.yaml',
    'kongmingmas_core.dict.yaml', 'kongmingmas.dict.yaml', 'kongmingmas_t.dict.yaml',
    'kongmingma.schema.yaml', 'kongmingma_t.schema.yaml',
    'kongmingma.dict.yaml', 'kongmingma_t.dict.yaml',
    'rime.lua',
]


def md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def active_package():
    path = os.path.join(SCHEMES, 'active.yaml')
    pkg = schema = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            k, _, v = line.strip().partition(':')
            v = v.strip()
            if k == 'package':
                pkg = v
            elif k == 'schema':
                schema = v
    if not pkg:
        raise SystemExit('active.yaml 里没有 package 字段')
    return pkg, schema


def plan_sync(shared):
    todo = []
    for name in SYNC_FILES:
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(shared, name)
        if not os.path.exists(dst) or md5(src) != md5(dst):
            todo.append(name)
    lua_src = os.path.join(ROOT, 'lua')
    if os.path.isdir(lua_src):
        for name in sorted(os.listdir(lua_src)):
            if not name.endswith('.lua'):
                continue
            src = os.path.join(lua_src, name)
            dst = os.path.join(shared, 'lua', name)
            if not os.path.exists(dst) or md5(src) != md5(dst):
                todo.append(os.path.join('lua', name))
    return todo


def copy_files(shared, todo, stamp):
    os.makedirs(os.path.join(shared, 'lua'), exist_ok=True)
    for rel in todo:
        src = os.path.join(ROOT, rel)
        dst = os.path.join(shared, rel)
        if os.path.exists(dst):
            bak = '%s.bak-%s' % (dst, stamp)
            if not os.path.exists(bak):
                shutil.copy2(dst, bak)
        shutil.copy2(src, dst)
        print('  同步 %-32s %s' % (rel, md5(dst)[:12]))


def fcitx_running():
    return subprocess.run(['pgrep', '-x', 'fcitx5'],
                          capture_output=True).returncode == 0


def try_lock(lock_path):
    """拿到锁返回 fd，拿不到返回 None。"""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def lock_holder(lock_path):
    out = subprocess.run(['fuser', lock_path], capture_output=True, text=True)
    return out.stdout.strip()


def stop_fcitx():
    # 锁才是真相：pgrep 在 PID namespace 隔离时会看不到宿主上的 fcitx5，
    # 于是出现「已停止」却仍拿不到锁的死循环。这里以锁为准，pgrep 只做提示。
    if not fcitx_running():
        print('  pgrep 未看到 fcitx5（可能被 PID namespace 隔离），直接请它退出')
    else:
        print('  停止 fcitx5 …')
    subprocess.run(['fcitx5-remote', '-e'], capture_output=True)
    for _ in range(20):
        if not fcitx_running():
            break
        time.sleep(0.5)
    if fcitx_running():
        subprocess.run(['systemctl', '--user', 'stop', FCITX_UNIT], capture_output=True)
        time.sleep(1)
    if fcitx_running():
        subprocess.run(['pkill', '-TERM', '-x', 'fcitx5'], capture_output=True)
        for _ in range(10):
            if not fcitx_running():
                break
            time.sleep(0.5)
    print('  fcitx5 已停止' if not fcitx_running() else '  注意：pgrep 仍能看到 fcitx5（正在等锁释放）')


def start_fcitx():
    if fcitx_running():
        return True
    subprocess.run(['systemctl', '--user', 'start', FCITX_UNIT],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if fcitx_running():
            return True
        time.sleep(0.5)
    # 注意：cgapture_output 配 `fcitx5 -d` 会死锁 —— 守护化的孙进程继承管道，
    # subprocess.run 要等管道关闭，而它会一直运行。必须走 DEVNULL + 脱离会话。
    subprocess.Popen(['fcitx5', '-r'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    for _ in range(20):
        if fcitx_running():
            return True
        time.sleep(0.5)
    return fcitx_running()


def run_deploy(shared, user, full):
    lock_path = os.path.join(user, '.rimes-engine.lock')
    fd = try_lock(lock_path)
    if fd is None:
        # 停 fcitx5 的判断可能被 namespace 骗过，这里再兜一次：直接请引擎退出。
        print('  锁仍被占用，重试 `fcitx5-remote -e` …')
        subprocess.run(['fcitx5-remote', '-e'], capture_output=True)
        for _ in range(20):
            time.sleep(0.5)
            fd = try_lock(lock_path)
            if fd is not None:
                print('  锁已释放')
                break
    if fd is None:
        holder = lock_holder(lock_path)
        print('  锁被占用（%s），无法部署' % (holder or '未知进程'))
        return None
    pid = os.fork()
    if pid == 0:                      # 子进程：dup2 会清除 FD_CLOEXEC
        try:
            os.dup2(fd, 3)
            os.execv(DEPLOY, [DEPLOY, shared, user, LOG_DIR, '1' if full else '0'])
        finally:
            os._exit(127)
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true', help='全量重建（full_check=1）')
    ap.add_argument('--dry-run', action='store_true', help='只列出待同步文件')
    ap.add_argument('--no-restart', action='store_true', help='不动 fcitx5，只跑部署')
    args = ap.parse_args()

    pkg, schema = active_package()
    shared = os.path.join(SCHEMES, 'packages', pkg)
    user = os.path.join(SCHEMES, 'learning', pkg)
    print('激活方案：package=%s  schema=%s' % (pkg, schema))
    print('shared = %s\nuser   = %s' % (shared, user))
    for p in (shared, user, DEPLOY):
        if not os.path.exists(p):
            raise SystemExit('缺少路径: %s' % p)

    todo = plan_sync(shared)
    if not todo:
        print('包内文件已与仓库一致，无需同步')
    else:
        print('待同步 %d 个文件：' % len(todo))
        for rel in todo:
            print('  %s' % rel)
    if args.dry_run:
        return 0

    stamp = time.strftime('%Y%m%d-%H%M%S')
    if todo:
        copy_files(shared, todo, stamp)

    if not args.no_restart:
        print('释放部署锁：')
        stop_fcitx()

    t0 = time.time()
    print('执行部署（full_check=%d）…' % (1 if args.full else 0))
    rc = run_deploy(shared, user, args.full)
    if rc is None:
        if not args.no_restart:
            start_fcitx()
        return 3
    print('部署退出码 = %d' % rc)

    if not args.no_restart:
        print('恢复输入法：')
        ok = start_fcitx()
        print('  fcitx5 %s' % ('已启动' if ok else '启动失败，请手动运行 fcitx5 -d -r'))

    build = os.path.join(user, 'build')
    fresh = []
    for name in sorted(os.listdir(build)):
        path = os.path.join(build, name)
        if name.startswith('kongmingmas') and os.path.getmtime(path) >= t0 - 2:
            fresh.append(name)
    print('本次重建产物 %d 个：%s' % (len(fresh), '、'.join(fresh) if fresh else '（无，可能未变更）'))

    pending = os.path.join(user, '.rimes-deployment-pending')
    if os.path.exists(pending):
        print('警告：存在 .rimes-deployment-pending，上次部署可能中断')
    return 0 if rc == 0 else rc


if __name__ == '__main__':
    sys.exit(main())
