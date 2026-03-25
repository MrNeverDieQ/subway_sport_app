# ============================================================
# timer.py - 倒计时组件（后台线程驱动，锁屏不暂停）
# ============================================================

import time
import threading
import logging

log = logging.getLogger(__name__)


class CountdownTimer:
    """Wall-clock countdown driven by a background thread.

    All callbacks run in the background thread.
    Caller is responsible for scheduling UI updates to the main thread.
    """

    def __init__(self, on_tick=None, on_finish=None):
        self.on_tick = on_tick
        self.on_finish = on_finish
        self._end_time = 0
        self._thread = None
        self._stop_event = threading.Event()

    def start(self, seconds):
        self.stop()
        seconds = max(0, seconds)
        if seconds <= 0:
            if self.on_finish:
                self.on_finish()
            return
        self._end_time = time.time() + seconds
        self._stop_event.clear()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._thread = t

    def _run(self):
        last_reported = -1
        while not self._stop_event.is_set():
            left = max(0, round(self._end_time - time.time()))

            if left != last_reported:
                last_reported = left
                if self.on_tick:
                    try:
                        self.on_tick(left)
                    except Exception as e:
                        log.warning('on_tick error: %s', e)

            if left <= 0:
                if self.on_finish:
                    try:
                        self.on_finish()
                    except Exception as e:
                        log.warning('on_finish error: %s', e)
                return

            next_sec = self._end_time - (left - 1)
            sleep_time = max(0.05, next_sec - time.time())
            self._stop_event.wait(timeout=sleep_time)

    def stop(self):
        self._stop_event.set()
        self._thread = None
