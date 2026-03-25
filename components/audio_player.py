"""Cross-platform audio player.

On Android: uses native MediaPlayer via pyjnius (survives screen-off / pause).
On desktop: falls back to Kivy SoundLoader.
"""
import os
import logging

log = logging.getLogger(__name__)

try:
    from jnius import autoclass
    MediaPlayer = autoclass('android.media.MediaPlayer')
    _ANDROID = True
except Exception:
    _ANDROID = False


class AudioPlayer:
    """Thin wrapper: play / stop / loop, works in background on Android."""

    def __init__(self):
        self._player = None
        self._fallback = None  # Kivy SoundLoader instance

    def play(self, path, loop=False):
        self.stop()
        if not os.path.exists(path):
            log.warning('Audio not found: %s', path)
            return
        if _ANDROID:
            try:
                mp = MediaPlayer()
                mp.setDataSource(path)
                mp.setLooping(loop)
                mp.prepare()
                mp.start()
                self._player = mp
            except Exception as e:
                log.warning('MediaPlayer failed: %s', e)
        else:
            from kivy.core.audio import SoundLoader
            s = SoundLoader.load(path)
            if s:
                s.loop = loop
                s.play()
                self._fallback = s

    def stop(self):
        if self._player is not None:
            try:
                self._player.stop()
                self._player.release()
            except Exception:
                pass
            self._player = None
        if self._fallback is not None:
            try:
                self._fallback.stop()
            except Exception:
                pass
            self._fallback = None
