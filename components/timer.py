# ============================================================
# timer.py - 可复用计时器组件
# ============================================================

from kivy.clock import Clock


class CountdownTimer:
    """
    倒计时计时器
    on_tick(remaining): 每秒回调，传入剩余秒数
    on_finish(): 计时结束回调
    """

    def __init__(self, on_tick=None, on_finish=None):
        self.on_tick = on_tick
        self.on_finish = on_finish
        self._event = None
        self.remaining = 0

    def start(self, seconds):
        self.stop()
        self.remaining = seconds
        if self.on_tick:
            self.on_tick(self.remaining)
        self._event = Clock.schedule_interval(self._tick, 1)

    def _tick(self, dt):
        self.remaining -= 1
        if self.on_tick:
            self.on_tick(self.remaining)
        if self.remaining <= 0:
            self.stop()
            if self.on_finish:
                self.on_finish()

    def stop(self):
        if self._event:
            self._event.cancel()
            self._event = None
