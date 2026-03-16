import os

from kivy.core.audio import SoundLoader
from kivy.core.window import Window
try:
    from kivy.core.audio.audio_sdl2 import SoundSDL2
    def _load_beep(path):
        s = SoundSDL2(source=path)
        s.load()
        return s
except Exception:
    def _load_beep(path):
        return SoundLoader.load(path)
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.video import Video

from data.workouts import get_exercises
from components.timer import CountdownTimer
from components.theme import (
    TEXT, TEXT_SEC, ACCENT, WARNING, REST_BLUE, SURFACE2, DANGER, fs,
)
from components.styled_widgets import (
    RoundedButton, CardBox, CircularProgress, ProgressStrip,
)

_VIDEO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'video')
_AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio')


class WorkoutScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timer = CountdownTimer(on_tick=self._on_tick, on_finish=self._on_finish)
        self._current_video = None
        self._current_sound = None
        self._loop_sound = None
        self._loop_event = None
        self._beep = _load_beep(os.path.join(_AUDIO_DIR, 'beep.wav'))
        self._beep_final = _load_beep(os.path.join(_AUDIO_DIR, 'beep_final.wav'))
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        self.exercise_label.font_size = fs(24)
        self.status_label.font_size = fs(13)
        self.progress_pct.font_size = fs(12)
        self.cue_label.font_size = fs(15)
        self.next_btn.font_size = fs(16)
        self.back_btn.font_size = fs(16)

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', padding=[24, 48, 24, 28], spacing=24)

        header = CardBox(
            orientation='vertical', size_hint_y=None, height=100,
            padding=[28, 18, 28, 14], spacing=8,
        )
        top_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=38)
        self.exercise_label = Label(
            text='', font_size=fs(24), bold=True, color=TEXT,
            halign='left', valign='middle',
        )
        self.exercise_label.bind(size=lambda w, s: setattr(w, 'text_size', s))
        self.status_label = Label(
            text='', font_size=fs(13), color=ACCENT,
            halign='right', valign='middle',
            size_hint_x=None, width=70,
        )
        self.status_label.bind(size=lambda w, s: setattr(w, 'text_size', s))
        top_row.add_widget(self.exercise_label)
        top_row.add_widget(self.status_label)

        bar_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=20, spacing=10)
        self.progress_strip = ProgressStrip(
            size_hint_y=None, height=6,
            bar_color=list(ACCENT),
        )
        self.progress_pct = Label(
            text='0%', font_size=fs(12), color=TEXT_SEC,
            halign='right', valign='middle',
            size_hint_x=None, width=36,
        )
        self.progress_pct.bind(size=lambda w, s: setattr(w, 'text_size', s))
        bar_row.add_widget(self.progress_strip)
        bar_row.add_widget(self.progress_pct)

        header.add_widget(top_row)
        header.add_widget(bar_row)
        root.add_widget(header)

        self.video_area = BoxLayout(orientation='vertical', size_hint_y=1)
        root.add_widget(self.video_area)

        bottom_card = CardBox(
            orientation='horizontal', size_hint_y=None, height=100,
            padding=[20, 14, 20, 14], spacing=16,
        )
        self.circular_progress = CircularProgress(
            size_hint=(None, None), size=(72, 72),
            arc_color=list(WARNING), line_width=5,
        )
        self.cue_label = Label(
            text='', font_size=fs(15), color=TEXT,
            halign='left', valign='middle',
        )
        self.cue_label.bind(size=lambda w, s: setattr(w, 'text_size', s))
        bottom_card.add_widget(self.circular_progress)
        bottom_card.add_widget(self.cue_label)
        root.add_widget(bottom_card)

        btn_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=54, spacing=12)
        self.next_btn = RoundedButton(
            text='跳过', font_size=fs(16),
            bg_color=list(SURFACE2), radius=18,
        )
        self.next_btn.bind(on_press=self._on_next_press)
        self.back_btn = RoundedButton(
            text='退出', font_size=fs(16),
            bg_color=list(DANGER), radius=18,
            size_hint_x=None, width=90,
        )
        self.back_btn.bind(on_press=self._go_home)
        btn_row.add_widget(self.next_btn)
        btn_row.add_widget(self.back_btn)
        root.add_widget(btn_row)

        self.add_widget(root)
        self.workout_finished = False

    # ------ 视频管理 ------

    def _show_video(self, filename):
        path = os.path.join(_VIDEO_DIR, filename)
        if not os.path.isfile(path):
            self._hide_video()
            return
        if self._current_video and self._current_video.source == path:
            self._current_video.state = 'play'
            return
        self._hide_video()
        vid = Video(
            source=path,
            state='play',
            options={'eos': 'loop'},
            allow_stretch=True,
            keep_ratio=True,
        )
        self.video_area.add_widget(vid)
        self._current_video = vid

    def _hide_video(self):
        if self._current_video:
            self._current_video.state = 'stop'
            self._current_video.unload()
            self.video_area.remove_widget(self._current_video)
            self._current_video = None

    def _sync_video(self, ex):
        video_file = ex.get('video')
        if video_file:
            self._show_video(video_file)
        else:
            self._hide_video()

    # ------ 进度计算 ------

    def _calc_total_secs(self):
        total = 0
        for e in self.exercises:
            total += e['duration'] * e['sets'] + e['rest'] * (e['sets'] - 1)
        return total

    def _calc_elapsed_base(self):
        elapsed = 0
        for e in self.exercises[:self.exercise_index]:
            elapsed += e['duration'] * e['sets'] + e['rest'] * (e['sets'] - 1)
        ex = self.exercises[self.exercise_index]
        elapsed += ex['duration'] * self.set_index + ex['rest'] * max(self.set_index, 0)
        if self.is_resting:
            elapsed += ex['duration']
        return elapsed

    def _update_progress(self, remaining):
        current_segment = self._total_seconds - remaining
        elapsed = self._elapsed_base + current_segment
        pct = min(elapsed / self._total_workout_secs, 1.0) if self._total_workout_secs > 0 else 0
        self.progress_strip.progress = pct
        self.progress_pct.text = f'{int(pct * 100)}%'

    # ------ 生命周期 ------

    def load(self, duration, goal):
        self._hide_video()
        self.exercises = get_exercises(duration, goal)
        self.exercise_index = 0
        self.set_index = 0
        self.is_resting = False
        self.workout_finished = False
        self._total_workout_secs = self._calc_total_secs()
        self.next_btn.text = '跳过'
        self.next_btn.bg_color = list(SURFACE2)
        self._start_set()

    def _on_next_press(self, *args):
        if self.workout_finished:
            self._go_home()
        else:
            self._on_finish()

    def _play_audio(self, filename, loop_filename=None):
        self._stop_audio()
        path = os.path.join(_AUDIO_DIR, filename)
        if not os.path.exists(path):
            return
        sound = SoundLoader.load(path)
        if not sound:
            return
        sound.loop = False
        sound.play()
        self._current_sound = sound
        if loop_filename:
            loop_path = os.path.join(_AUDIO_DIR, loop_filename)
            def _start_loop(dt):
                self._loop_event = None
                if not os.path.exists(loop_path):
                    return
                s = SoundLoader.load(loop_path)
                if s:
                    s.loop = True
                    s.play()
                    self._loop_sound = s
            duration = sound.length if sound.length and sound.length > 0 else 0
            from kivy.clock import Clock
            self._loop_event = Clock.schedule_once(_start_loop, duration + 2)

    def _start_set(self):
        ex = self.exercises[self.exercise_index]
        self.is_resting = False

        if ex.get('audio'):
            self._play_audio(ex['audio'], ex.get('audio_loop'))
        self.exercise_label.text = ex['name']
        self.status_label.text = '训练中'
        self.status_label.color = ACCENT

        cues = ex.get('cues', [])
        self.cue_label.text = cues[self.set_index % len(cues)] if cues else ''

        self._total_seconds = ex['duration']
        self._elapsed_base = self._calc_elapsed_base()
        self.circular_progress.arc_color = list(WARNING)
        self._sync_video(ex)
        self.timer.start(self._total_seconds)

    def _start_rest(self):
        ex = self.exercises[self.exercise_index]
        self.is_resting = True

        self._play_audio('放松提示.mp3')
        self.status_label.text = '休息中'
        self.status_label.color = REST_BLUE
        self.cue_label.text = '放松，准备下一组'

        self._total_seconds = ex['rest']
        self._elapsed_base = self._calc_elapsed_base()
        self.circular_progress.arc_color = list(REST_BLUE)
        self._hide_video()
        self.timer.start(self._total_seconds)

    def _on_tick(self, remaining):
        self.circular_progress.text = str(remaining)
        if self._total_seconds > 0:
            self.circular_progress.progress = remaining / self._total_seconds
        self._update_progress(remaining)
        if remaining == 1:
            if self._beep_final:
                self._beep_final.stop()
                self._beep_final.play()
        elif 2 <= remaining <= 5:
            if self._beep:
                self._beep.stop()
                self._beep.play()

    def _on_finish(self):
        self.timer.stop()
        ex = self.exercises[self.exercise_index]

        if self.is_resting:
            # 休息结束：进入下一组或下一个动作
            if self.set_index + 1 < ex['sets']:
                self.set_index += 1
                self._start_set()
            else:
                self.exercise_index += 1
                self.set_index = 0
                if self.exercise_index < len(self.exercises):
                    self._start_set()
                else:
                    self._finish_workout()
        else:
            # 动作结束：还有剩余组则休息，否则推进动作
            if self.set_index + 1 < ex['sets'] and ex.get('rest', 0) > 0:
                self._start_rest()
            elif self.set_index + 1 < ex['sets']:
                self.set_index += 1
                self._start_set()
            else:
                self.exercise_index += 1
                self.set_index = 0
                if self.exercise_index < len(self.exercises):
                    self._start_set()
                else:
                    self._finish_workout()

    def _finish_workout(self):
        self._hide_video()
        self.workout_finished = True
        self.exercise_label.text = '训练完成！'
        self.status_label.text = '做得好'
        self.status_label.color = WARNING
        self.progress_strip.progress = 1.0
        self.progress_pct.text = '100%'
        self.circular_progress.text = ''
        self.circular_progress.progress = 1.0
        self.circular_progress.arc_color = list(ACCENT)
        self.cue_label.text = '记得补充水分，做好拉伸'
        self.next_btn.text = '返回首页'
        self.next_btn.bg_color = list(ACCENT)

    def _stop_audio(self):
        if self._loop_event:
            self._loop_event.cancel()
            self._loop_event = None
        if self._loop_sound:
            self._loop_sound.stop()
            self._loop_sound = None
        if self._current_sound:
            self._current_sound.stop()
            self._current_sound = None

    def _go_home(self, *args):
        self.timer.stop()
        self._stop_audio()
        self._hide_video()
        self.manager.current = 'home'

    def on_leave(self, *args):
        self.timer.stop()
        self._stop_audio()
        self._hide_video()
