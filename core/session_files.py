# ============================================================
# session_files.py - UI 进程与前台服务进程之间的文件协议
#
#   plan.json   UI 写、服务读：本次训练方案（Plan.to_dict() + session id）
#   state.json  服务写、UI 读：引擎快照（每秒一次 + 每次段切换）
#   cmd.json    UI 写、服务读：{"seq": 递增, "cmd": "skip" | "stop"}
#
# 全部原子写（先写临时文件再 os.replace），读到半截 json 当作"暂无"。
# 目录：环境变量 SUBWAY_SESSION_DIR（测试用）> Android 私有目录/workout_session > None（桌面不用服务）
# ============================================================

import json
import os
import time

PLAN, STATE, CMD = 'plan.json', 'state.json', 'cmd.json'
STALE_SECS = 6.0        # state.json 超过这么久没更新就认为服务已经不在了


def default_dir():
    d = os.environ.get('SUBWAY_SESSION_DIR')
    if d:
        return d
    private = os.environ.get('ANDROID_PRIVATE')
    if private:
        return os.path.join(private, 'workout_session')
    return None


def _write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    for _ in range(3):                      # Windows 上读端刚好打开着文件时 replace 会失败，重试即可
        try:
            os.replace(tmp, path)
            return
        except OSError:
            time.sleep(0.02)
    _remove(tmp)                            # 实在换不上就放弃这一次（下一秒还会再写），别让服务循环因此中断


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


class SessionFiles:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.plan_path = os.path.join(base_dir, PLAN)
        self.state_path = os.path.join(base_dir, STATE)
        self.cmd_path = os.path.join(base_dir, CMD)

    # ---------------------------------------------------------- UI 端

    def begin(self, plan_dict, session_id):
        """开始一次新训练：写方案，清掉上一次的状态和命令。"""
        _remove(self.state_path)
        _remove(self.cmd_path)
        data = dict(plan_dict)
        data['session'] = session_id
        data['created'] = time.time()
        _write_json(self.plan_path, data)

    def send_cmd(self, cmd):
        prev = _read_json(self.cmd_path) or {}
        seq = int(prev.get('seq', 0)) + 1
        _write_json(self.cmd_path, {'seq': seq, 'cmd': cmd, 'at': time.time()})
        return seq

    def read_state(self):
        return _read_json(self.state_path)

    def running_state(self, now=None):
        """服务仍在跑（最近更新过且未结束）时返回 state，否则 None。"""
        st = self.read_state()
        if not st or not st.get('running'):
            return None
        now = time.time() if now is None else now
        if now - st.get('updated', 0) > STALE_SECS:
            return None
        return st

    def abandon(self):
        """UI 主动结束/放弃一次会话：删掉方案和状态，留着 cmd.json（里面是刚发的 stop，迟到的服务还要读）。
        没有 plan.json 的服务会直接退出，所以之后不会再有"幽灵"状态被误判为在跑。"""
        _remove(self.plan_path)
        _remove(self.state_path)

    def clear(self):
        for p in (self.plan_path, self.state_path, self.cmd_path):
            _remove(p)

    # ---------------------------------------------------------- 服务端

    def read_plan(self):
        return _read_json(self.plan_path)

    def write_state(self, snapshot, session_id, running):
        data = dict(snapshot)
        data['session'] = session_id
        data['running'] = running
        data['updated'] = time.time()
        _write_json(self.state_path, data)

    def poll_cmd(self, last_seq):
        """返回 (seq, cmd)；没有新命令时 cmd 为 None。"""
        data = _read_json(self.cmd_path)
        if not data:
            return last_seq, None
        seq = int(data.get('seq', 0))
        if seq <= last_seq:
            return last_seq, None
        return seq, data.get('cmd')
