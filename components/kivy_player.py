# ============================================================
# kivy_player.py - 进程内播放器（桌面，以及 Android 上服务起不来时的兜底）
#
# 实现 core.engine 需要的播放接口：play_sequence / start_loop / beep / stop。
# 串播以 on_stop（自然播完）为主，估算时长 + 余量为兜底，两者都用 _seq_gen 防止旧序列串台。
# ============================================================

import os

from kivy.clock import Clock
from kivy.core.audio import SoundLoader
try:
    from kivy.core.audio.audio_sdl2 import SoundSDL2

    def _load_beep(path):
        s = SoundSDL2(source=path)
        s.load()
        return s
except Exception:
    def _load_beep(path):
        return SoundLoader.load(path)

from data import audio_meta

_CLIP_GAP = 0.3                 # 连续短句之间的间隔（秒）
_CLIP_SLACK = 1.0               # 播放端不派发 on_stop 时，按估算时长 + 这个余量强制推进
_CLIP_FALLBACK_LEN = 3.0        # 既没有时长表也拿不到 sound.length 时按这个估


class KivyPlayer:
    def __init__(self):
        self._current_sound = None
        self._loop_sound = None
        self._loop_event = None
        self._seq_event = None
        self._seq_gen = 0            # 每次 stop 加一，旧序列的回调据此失效
        self.last_clips = []         # 最近一次请求播放的短句（含缺失的），便于测试/排查
        self._beep = _load_beep(os.path.join(audio_meta.AUDIO_DIR, 'beep.wav'))
        self._beep_final = _load_beep(os.path.join(audio_meta.AUDIO_DIR, 'beep_final.wav'))

    # ------------------------------------------------------------ 接口

    def play_sequence(self, clips, then=None):
        """依次播放若干音频（相对 audio/ 的路径），缺失的直接跳过；全部播完后调用 then。"""
        self.stop()
        gen = self._seq_gen
        self.last_clips = list(clips)
        queue = [c for c in clips if audio_meta.exists(c)]

        def alive():
            return gen == self._seq_gen

        def start_next(dt=None):
            self._seq_event = None
            if not alive():
                return
            if not queue:
                if then:
                    then()
                return
            rel = queue.pop(0)
            sound = SoundLoader.load(audio_meta.audio_path(rel))
            if not sound:
                start_next()
                return
            sound.loop = False
            sound.bind(on_stop=on_clip_end)
            self._current_sound = sound
            sound.play()
            self._seq_event = Clock.schedule_once(force_end, _clip_len(rel, sound) + _CLIP_SLACK)

        def on_clip_end(sound):
            if alive() and sound is self._current_sound:
                finish_clip()

        def force_end(dt):
            self._seq_event = None
            if alive():
                finish_clip()

        def finish_clip():
            if self._seq_event:
                self._seq_event.cancel()
                self._seq_event = None
            sound = self._current_sound
            self._current_sound = None
            if sound:
                sound.unbind(on_stop=on_clip_end)
                _release(sound)
            self._seq_event = Clock.schedule_once(start_next, _CLIP_GAP)

        start_next()

    def start_loop(self, rel, delay=0):
        """delay 秒后开始循环播放 rel（呼吸循环音）。"""
        if not audio_meta.exists(rel):
            return

        def go(dt):
            self._loop_event = None
            s = SoundLoader.load(audio_meta.audio_path(rel))
            if s:
                s.loop = True
                s.play()
                self._loop_sound = s

        self._loop_event = Clock.schedule_once(go, delay)

    def beep(self, final=False):
        b = self._beep_final if final else self._beep
        if b:
            b.stop()
            b.play()

    def stop(self):
        """停掉所有语音与待播事件；之后旧序列的任何回调都不再生效。"""
        self._seq_gen += 1
        for attr in ('_seq_event', '_loop_event'):
            ev = getattr(self, attr)
            if ev:
                ev.cancel()
                setattr(self, attr, None)
        for attr in ('_loop_sound', '_current_sound'):
            snd = getattr(self, attr)
            if snd:
                setattr(self, attr, None)
                _release(snd)
        for b in (self._beep, self._beep_final):
            if b:
                b.stop()

    def set_beep_volume(self, v):
        for b in (self._beep, self._beep_final):
            if b:
                b.volume = v


def _release(sound):
    """停止并释放一个 Sound（Android 上每个 Sound 都占一个 MediaPlayer）。"""
    try:
        sound.stop()
    finally:
        unload = getattr(sound, 'unload', None)
        if unload:
            unload()


def _clip_len(rel, sound):
    """一段音频的时长：优先时长表，其次 sound.length，最后兜底常量。"""
    d = audio_meta.duration(rel)
    if d and d > 0:
        return d
    length = getattr(sound, 'length', 0) or 0
    return length if length > 0 else _CLIP_FALLBACK_LEN
