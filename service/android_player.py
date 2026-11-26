# ============================================================
# android_player.py - 前台服务进程里的播放器（android.media.MediaPlayer，经 pyjnius）
#
# 实现 core.engine 需要的接口 play_sequence / start_loop / beep / stop，另加 poll()：
# 服务主循环每圈调一次 poll()，用它推进串播（不依赖 Java 回调，避免跨线程回调 Python 的麻烦）。
# 一段播完的判定：isPlaying() 变 False（且至少播了 MIN_PLAY 秒），或超过 估算时长 + 余量。
# ============================================================

import os
import time

from jnius import autoclass

from data import audio_meta

MediaPlayer = autoclass('android.media.MediaPlayer')
AudioManager = autoclass('android.media.AudioManager')
AudioAttributesBuilder = autoclass('android.media.AudioAttributes$Builder')

CLIP_GAP = 0.3              # 连续短句之间的间隔（秒）
CLIP_SLACK = 1.0            # 超过估算时长 + 余量就强制推进
CLIP_FALLBACK_LEN = 3.0     # 拿不到时长时按这个估
MIN_PLAY = 0.3              # 刚 start() 的头几百毫秒 isPlaying 可能还没稳定，不据此判完


class MediaPlayerPlayer:
    def __init__(self, log=None):
        self.log = log or (lambda *a: None)
        self._mp = None
        self._queue = []
        self._then = None
        self._next_at = None
        self._clip_started = 0.0
        self._deadline = 0.0
        self._loop = None
        self.last_clips = []
        self._beep = self._prepare(audio_meta.audio_path('beep.wav'))
        self._beep_final = self._prepare(audio_meta.audio_path('beep_final.wav'))

    # ------------------------------------------------------------ MediaPlayer 封装

    def _prepare(self, path, looping=False):
        if not os.path.isfile(path):
            return None
        try:
            mp = MediaPlayer()
            mp.setAudioAttributes(
                AudioAttributesBuilder().setLegacyStreamType(AudioManager.STREAM_MUSIC).build())
            mp.setDataSource(path)
            mp.setLooping(looping)
            mp.prepare()
            return mp
        except Exception as e:
            self.log('load failed %s: %r' % (path, e))
            return None

    @staticmethod
    def _release(mp):
        if mp is None:
            return
        try:
            mp.stop()
        except Exception:
            pass
        try:
            mp.release()
        except Exception:
            pass

    @staticmethod
    def _is_playing(mp):
        try:
            return bool(mp.isPlaying())
        except Exception:
            return False

    @staticmethod
    def _length(rel, mp):
        d = audio_meta.duration(rel)
        if d and d > 0:
            return d
        try:
            ms = mp.getDuration()
            if ms and ms > 0:
                return ms / 1000.0
        except Exception:
            pass
        return CLIP_FALLBACK_LEN

    # ------------------------------------------------------------ 引擎接口

    def play_sequence(self, clips, then=None):
        self.stop()
        self.last_clips = list(clips)
        self._queue = [c for c in clips if audio_meta.exists(c)]
        self._then = then
        self._start_next()

    def _start_next(self):
        self._next_at = None
        while self._queue:
            rel = self._queue.pop(0)
            mp = self._prepare(audio_meta.audio_path(rel))
            if mp is None:
                continue
            try:
                mp.start()
            except Exception as e:
                self.log('start failed %s: %r' % (rel, e))
                self._release(mp)
                continue
            now = time.monotonic()
            self._mp = mp
            self._clip_started = now
            self._deadline = now + self._length(rel, mp) + CLIP_SLACK
            return
        then, self._then = self._then, None
        if then:
            then()

    def poll(self):
        now = time.monotonic()
        if self._mp is not None:
            played = now - self._clip_started
            if now >= self._deadline or (played >= MIN_PLAY and not self._is_playing(self._mp)):
                self._release(self._mp)
                self._mp = None
                self._next_at = now + CLIP_GAP
        elif self._next_at is not None and now >= self._next_at:
            self._start_next()

    def start_loop(self, rel, delay=0):
        self._release(self._loop)
        self._loop = None
        if not audio_meta.exists(rel):
            return
        mp = self._prepare(audio_meta.audio_path(rel), looping=True)
        if mp is None:
            return
        try:
            mp.start()
            self._loop = mp
        except Exception as e:
            self.log('loop start failed %s: %r' % (rel, e))
            self._release(mp)

    def beep(self, final=False):
        mp = self._beep_final if final else self._beep
        if mp is None:
            return
        try:
            mp.seekTo(0)
            mp.start()
        except Exception as e:
            self.log('beep failed: %r' % (e,))

    def stop(self):
        self._queue = []
        self._then = None
        self._next_at = None
        self._release(self._mp)
        self._mp = None
        self._release(self._loop)
        self._loop = None
        for mp in (self._beep, self._beep_final):
            if mp is not None:
                try:
                    if mp.isPlaying():
                        mp.pause()
                        mp.seekTo(0)
                except Exception:
                    pass

    def idle(self):
        return self._mp is None and self._next_at is None and not self._queue

    def close(self):
        self.stop()
        for attr in ('_beep', '_beep_final'):
            self._release(getattr(self, attr))
            setattr(self, attr, None)
