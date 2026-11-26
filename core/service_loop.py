# ============================================================
# service_loop.py - 前台服务进程里的主循环（纯 Python，可在桌面用假播放器测试）
#
#   每 1 秒调一次 engine.tick()；每圈轮询播放器（推进串播）和 cmd.json（跳过 / 停止）；
#   每次状态变化把快照写进 state.json；训练完成后等"训练完成"播完再退出。
# 用 time.monotonic 定点推进，不累积误差；服务里持有 WAKE_LOCK 保证 CPU 不睡。
# ============================================================

import time

from core.engine import Engine

TICK = 1.0
POLL_SLEEP = 0.05
FINISH_GRACE = 8.0          # 完成后最多等这么久让"训练完成"播完


def run(plan, player, files, stop_requested=None, now=time.monotonic, sleep=time.sleep, log=None):
    """
    plan:   files.read_plan() 的结果（含 session）
    player: 带 poll() 的播放器（见 service/android_player.py）
    返回最终快照。
    """
    log = log or (lambda *a: None)
    session_id = plan.get('session', '')
    engine = Engine(plan, player)
    engine.start()
    files.write_state(engine.snapshot(), session_id, running=True)
    log('session %s started: %d segments, %ds' % (session_id, len(engine.timeline), engine.total_secs))

    last_seq = 0                        # begin() 已清掉旧命令；服务冷启动期间用户点的跳过要补上
    next_tick = now() + TICK
    finished_at = None
    try:
        while True:
            if stop_requested and stop_requested():
                log('stop requested by host')
                break

            last_seq, cmd = files.poll_cmd(last_seq)
            if cmd == 'stop':
                log('stop command')
                break
            if cmd == 'skip' and not engine.finished:
                engine.skip()
                next_tick = now() + TICK
                files.write_state(engine.snapshot(), session_id, running=True)

            player.poll()

            t = now()
            if not engine.finished and t >= next_tick:
                engine.tick()
                next_tick += TICK
                if next_tick <= t:              # 被长时间挂起后不要连珠炮补 tick
                    next_tick = t + TICK
                files.write_state(engine.snapshot(), session_id, running=True)

            if engine.finished:
                if finished_at is None:
                    finished_at = t
                    log('finished, waiting for final clip')
                if player.idle() or t - finished_at > FINISH_GRACE:
                    break

            sleep(POLL_SLEEP)
    finally:
        engine.stop()
        files.write_state(engine.snapshot(), session_id, running=False)
        log('session %s ended (finished=%s)' % (session_id, engine.finished))
    return engine.snapshot()
