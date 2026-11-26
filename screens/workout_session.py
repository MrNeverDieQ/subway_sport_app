# ============================================================
# workout_session.py - 训练页看到的"会话"：方案 + 只读状态 + start/skip/stop
#
#   LocalSession    引擎在本进程里跑，Kivy Clock 每秒 tick（桌面；Android 上服务起不来时的兜底）
#   ServiceSession  引擎在 Android 前台服务进程里跑，这里只写 plan/cmd、轮询 state.json 做镜像
#                   （锁屏后 Kivy 主循环会被挂起，只有服务进程里的引擎还在走）
# 两者对界面暴露同一组接口，状态变化时回调 on_change(session)。
# ============================================================

import time
import uuid

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

from core.engine import Engine, RECORD_RATIO
from core.session_files import SessionFiles, default_dir, STALE_SECS
from data.workouts import Plan

NOTIFY_TITLE = '地铁健身'
NOTIFY_TEXT = '训练进行中，锁屏也会继续播放'

_STATE_KEYS = ('seg_index', 'remaining', 'real_secs', 'finished', 'started')


class Session:
    kind = ''

    def __init__(self, plan, on_change=None):
        self.plan = plan
        self.entries = plan.entries
        self.timeline = plan.timeline
        self.on_change = on_change

    # ------------------------------------------------------------ 只读状态（子类提供 state）

    @property
    def state(self):
        raise NotImplementedError

    @property
    def seg_index(self):
        return self.state['seg_index']

    @property
    def remaining(self):
        return self.state['remaining']

    @property
    def real_secs(self):
        return self.state['real_secs']

    @property
    def finished(self):
        return self.state['finished']

    @property
    def segment(self):
        i = self.seg_index
        return self.timeline[i] if i < len(self.timeline) else None

    @property
    def exercise(self):
        seg = self.segment
        return self.entries[seg['ex']] if seg else None

    @property
    def is_resting(self):
        seg = self.segment
        return bool(seg) and seg['kind'] == 'rest'

    @property
    def elapsed(self):
        if self.finished:
            return self.plan.total_secs
        seg = self.segment
        base = sum(s['secs'] for s in self.timeline[:self.seg_index])
        return base + ((seg['secs'] - self.remaining) if seg else 0)

    @property
    def pct(self):
        if self.finished:
            return 1.0
        total = self.plan.total_secs
        return min(self.elapsed / total, 1.0) if total > 0 else 0.0

    def should_record_on_exit(self):
        return not self.finished and self.real_secs >= RECORD_RATIO * self.plan.total_secs

    def _notify(self):
        if self.on_change:
            self.on_change(self)

    # ------------------------------------------------------------ 控制

    def start(self, from_seg=0):
        raise NotImplementedError

    def skip(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def refresh(self):
        self._notify()


class LocalSession(Session):
    kind = 'local'

    def __init__(self, plan, on_change=None, player=None):
        super().__init__(plan, on_change)
        if player is None:
            from components.kivy_player import KivyPlayer
            player = KivyPlayer()
        self.player = player
        self.engine = Engine(plan.to_dict(), player)
        self._ev = None

    @property
    def state(self):
        return self.engine.snapshot()

    def start(self, from_seg=0, real_secs=0):
        self.engine.seg_index = from_seg
        self.engine.real_secs = real_secs
        self.engine.start()
        self._restart_ticker()
        self._notify()

    def _restart_ticker(self):
        self._cancel_ticker()
        if not self.engine.finished:
            self._ev = Clock.schedule_interval(self._tick, 1)

    def _cancel_ticker(self):
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def _tick(self, dt):
        self.engine.tick()
        if self.engine.finished:
            self._cancel_ticker()
        self._notify()

    def skip(self):
        self.engine.skip()
        self._restart_ticker()
        self._notify()

    def stop(self):
        self._cancel_ticker()
        self.engine.stop()


class ServiceSession(Session):
    kind = 'service'
    POLL = 0.25
    START_TIMEOUT = 6.0

    def __init__(self, plan, on_change=None, files=None, session_id=None,
                 on_fail=None, start_service=None, stop_service=None):
        super().__init__(plan, on_change)
        self.files = files or SessionFiles(default_dir())
        self.session_id = session_id or uuid.uuid4().hex
        self.on_fail = on_fail
        self._start_service = start_service or _android_start_service
        self._stop_service = stop_service or _android_stop_service
        first = plan.timeline[0]['secs'] if plan.timeline else 0
        self._state = {'seg_index': 0, 'remaining': first, 'real_secs': 0, 'finished': False, 'started': False}
        self._version = -1
        self._confirmed = False
        self._started_at = None
        self._ev = None
        self._launch_ev = None
        self._failed = False
        self._stopped = False

    @property
    def state(self):
        return self._state

    RESTART_DELAY = 1.0

    def start(self, from_seg=0):
        self._notify()                      # 先把首段画出来，服务上报后再对齐
        if self.files.running_state():
            # 上一次的服务还在（UI 进程被杀后重开又直接开新训练之类）：p4a 的 PythonService 对重复 start 不理会，
            # 必须先停掉旧的；stopService 会杀进程，紧接着 start 可能被一起带走，所以隔 1 秒再起
            Logger.info('Workout: 停掉仍在运行的旧服务会话')
            self._halt_service()
            self._started_at = time.time()
            self._launch_ev = Clock.schedule_once(lambda dt: self._launch(), self.RESTART_DELAY)
            return
        self._launch()

    def _launch(self):
        self._launch_ev = None
        if self._failed or self._stopped:
            return
        self.files.begin(self.plan.to_dict(), self.session_id)
        self._started_at = time.time()
        try:
            self._start_service()
        except Exception as e:
            self._fail('无法启动前台服务：%r' % (e,))
            return
        self._schedule_poll()

    def _halt_service(self):
        """让服务停下：命令 + stopService 双保险，最后把方案/状态文件撤掉，迟到的服务读不到方案会自行退出。"""
        try:
            self.files.send_cmd('stop')
        except Exception:
            pass
        try:
            self._stop_service()
        except Exception as e:
            Logger.warning('Workout: 停止前台服务失败 %r', e)
        self.files.abandon()

    def attach(self, state):
        """接管一个已经在跑的服务会话（UI 进程被杀后重新打开）。"""
        self._apply(state)
        self._confirmed = True
        self._schedule_poll()
        self._notify()

    def _schedule_poll(self):
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._poll, self.POLL)

    def _cancel_poll(self):
        if self._ev:
            self._ev.cancel()
            self._ev = None

    def _apply(self, st):
        if st.get('version', -1) < 0:
            return                      # 服务崩溃时写的占位快照，不覆盖已知进度（兜底要从当前段接着练）
        self._version = st.get('version', -1)
        self._state = {k: st.get(k, self._state.get(k)) for k in _STATE_KEYS}

    def _poll(self, dt=0):
        if self._failed or self._stopped:
            return
        st = self.files.read_state()
        if st and st.get('session') == self.session_id:
            self._confirmed = True
            if st.get('version') != self._version:
                self._apply(st)
                self._notify()
            if st.get('finished'):
                self._cancel_poll()         # 服务播完"训练完成"会自己退出，没什么可镜像的了
            elif not st.get('running'):
                self._fail('前台服务中途退出')
            elif st.get('running') and time.time() - st.get('updated', 0) > STALE_SECS:
                self._fail('前台服务失联（%.0f 秒没有更新）' % STALE_SECS)
        elif not self._confirmed and self._started_at and time.time() - self._started_at > self.START_TIMEOUT:
            self._fail('前台服务 %.0f 秒内没有响应' % self.START_TIMEOUT)

    def _fail(self, reason):
        if self._failed or self._stopped:
            return
        self._failed = True
        self._cancel_poll()
        Logger.warning('Workout: %s，改用进程内播放（锁屏后会暂停）', reason)
        self._halt_service()            # 慢启动的服务若此刻才活过来，也要被拦住，否则会和进程内播放叠音
        if self.on_fail:
            self.on_fail(self, reason)

    def _sync_state(self):
        """同步读一次 state.json 并应用（不触发回调/兜底）。"""
        st = self.files.read_state()
        if st and st.get('session') == self.session_id:
            self._apply(st)

    def should_record_on_exit(self):
        # 解锁后立刻点退出时镜像可能还没刷新：以最新状态为准，避免服务已记录后这里再记一次
        self._sync_state()
        return super().should_record_on_exit()

    def skip(self):
        if self.finished or self._stopped:
            return
        self.files.send_cmd('skip')

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        self._cancel_poll()
        if self._launch_ev:
            self._launch_ev.cancel()
            self._launch_ev = None
        self._sync_state()              # 撤掉文件之前把最后的进度拿到，退出时的记录判断要用
        self._halt_service()

    def refresh(self):
        self._poll()
        self._notify()


# ---------------------------------------------------------------- 选择与恢复

def use_service():
    return platform == 'android' and default_dir() is not None


def make_session(plan, on_change=None, player=None, on_fail=None):
    if use_service():
        return ServiceSession(plan, on_change, on_fail=on_fail)
    return LocalSession(plan, on_change, player=player)


def find_running():
    """有服务会话仍在跑时返回 (plan, state)，否则 None。App 启动/回前台时用。"""
    if not use_service():
        return None
    try:
        files = SessionFiles(default_dir())
        st = files.running_state()
        if not st:
            return None
        plan_dict = files.read_plan()
        if not plan_dict or plan_dict.get('session') != st.get('session'):
            return None
        return Plan.from_dict(plan_dict), st
    except Exception as e:
        Logger.warning('Workout: 读取服务状态失败 %r', e)
        return None


# ---------------------------------------------------------------- Android 胶水

def _service_class():
    from jnius import autoclass
    from android import mActivity
    # buildozer.spec: services = Workout:service/main.py:foreground  →  <package>.ServiceWorkout
    return autoclass(mActivity.getPackageName() + '.ServiceWorkout'), mActivity


def _android_start_service():
    svc, activity = _service_class()
    try:
        svc.start(activity, '', NOTIFY_TITLE, NOTIFY_TEXT, '')
    except Exception:
        svc.start(activity, '')          # 老版 p4a 只有 (Context, String) 这一种签名


def _android_stop_service():
    svc, activity = _service_class()
    svc.stop(activity)
