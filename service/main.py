# ============================================================
# service/main.py - Android 前台服务入口（buildozer.spec: services = Workout:service/main.py:foreground）
#
# UI 进程把方案写到 plan.json 后启动本服务；这里在独立进程里跑 core.service_loop：
# 播语音、计时、响提示音、写 state.json 供界面镜像，训练完成（或收到 stop 命令）后自己退出。
# 锁屏后 UI 进程的 Kivy 主循环会被挂起，但这个进程不受影响；持有 PARTIAL_WAKE_LOCK 防 CPU 休眠导致计时漂移。
# 日志走 print → logcat 的 python 标签。
# ============================================================

import os
import sys
import traceback

try:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
except NameError:                       # 极少数入口方式没有 __file__；服务的 cwd 就是应用目录
    ROOT = os.getcwd()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import service_loop                      # noqa: E402
from core.session_files import SessionFiles, default_dir   # noqa: E402

WAKELOCK_TAG = 'subwaysport:workout'
WAKELOCK_EXTRA_SECS = 120


def log(msg):
    print('[workout-service] %s' % msg, flush=True)


def _service():
    from jnius import autoclass
    return autoclass('org.kivy.android.PythonService').mService


def acquire_wakelock(secs):
    try:
        from jnius import autoclass, cast
        Context = autoclass('android.content.Context')
        PowerManager = autoclass('android.os.PowerManager')
        pm = cast('android.os.PowerManager', _service().getSystemService(Context.POWER_SERVICE))
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKELOCK_TAG)
        wl.acquire(int(secs * 1000))
        log('wakelock acquired for %ds' % secs)
        return wl
    except Exception as e:
        log('wakelock failed: %r' % (e,))
        return None


def release_wakelock(wl):
    if wl is None:
        return
    try:
        if wl.isHeld():
            wl.release()
    except Exception as e:
        log('wakelock release failed: %r' % (e,))


def stop_self():
    try:
        _service().stopSelf()
    except Exception as e:
        log('stopSelf failed: %r' % (e,))


def main():
    base = default_dir()
    if not base:
        log('no session dir, exiting')
        return
    files = SessionFiles(base)
    plan = files.read_plan()
    if not plan:
        log('no plan.json, exiting')
        return

    wl = acquire_wakelock(int(plan.get('total_secs', 900)) + WAKELOCK_EXTRA_SECS)
    player = None
    try:
        from service.android_player import MediaPlayerPlayer
        player = MediaPlayerPlayer(log=log)
        service_loop.run(plan, player, files, log=log)
    except Exception:
        log('crashed:\n' + traceback.format_exc())
        try:
            files.write_state({'seg_index': 0, 'remaining': 0, 'real_secs': 0, 'finished': False,
                               'started': False, 'version': -1}, plan.get('session', ''), running=False)
        except Exception:
            pass
    finally:
        if player is not None:
            player.close()
        release_wakelock(wl)
        stop_self()


if __name__ == '__main__':
    main()
