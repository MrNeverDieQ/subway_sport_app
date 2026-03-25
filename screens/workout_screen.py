import os
import logging

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.video import Video

from data.workouts import get_exercises
from components.timer import CountdownTimer
from components.audio_player import AudioPlayer
from components.theme import (
    TEXT, TEXT_SEC, ACCENT, WARNING, REST_BLUE, SURFACE2, DANGER, fs, adaptive_fs,
)
from components.styled_widgets import (
    RoundedButton, CardBox, CircularProgress, ProgressStrip,
)

log = logging.getLogger(__name__)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _start_foreground_service():
    try:
        from jnius import autoclass
        service = autoclass('com.subwaysport.subwaysport.ServiceWorkout')
        mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
        service.start(mActivity, '')
    except Exception:
        log.debug('Foreground service not available (not on Android)')


def _stop_foreground_service():
    try:
        from jnius import autoclass
        service = autoclass('com.subwaysport.subwaysport.ServiceWorkout')
        mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
        service.stop(mActivity)
    except Exception:
        pass


def _audio_path(filename):
    import components.theme as theme
    root = theme.APP_ROOT or _APP_DIR
    return os.path.join(root, 'audio', filename)


def _video_path(filename):
    import components.theme as theme
    root = theme.APP_ROOT or _APP_DIR
    return os.path.join(root, 'video', filename)


def _schedule_ui(func):
    """Schedule a no-arg function to run on the Kivy main thread."""
    Clock.schedule_once(lambda dt: func(), 0)


class WorkoutScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.exercises = []
        self.exercise_index = 0
        self.set_index = 0
        self.is_resting = False
        self._rest_between_exercises = False
        self.workout_finished = False
        self._total_seconds = 0
        self._elapsed_base = 0
        self._total_workout_secs = 0

        # Timer: callbacks run in background thread
        self.timer = CountdownTimer(on_tick=self._on_tick, on_finish=self._on_finish)

        # Audio players (AudioPlayer uses native MediaPlayer on Android)
        self._current_sound = AudioPlayer()
        self._loop_sound = AudioPlayer()
        self._beep = AudioPlayer()
        self._beep_final = AudioPlayer()

        self._current_video = None
        self._service_running = False
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    # ------ UI 构建 ------

    def _on_resize(self, *_):
        self.exercise_label.font_size = fs(22)
        self.status_label.font_size = fs(14)
        self.progress_pct.font_size = fs(13)
        self.cue_label.font_size = fs(15)
        self.next_btn.font_size = fs(17)
        self.back_btn.font_size = fs(17)

    def _build_ui(self):
        root = BoxLayout(orientation='vertical', padding=[dp(24), dp(48), dp(24), dp(28)], spacing=dp(24))

        header = CardBox(
            orientation='vertical', size_hint_y=None, height=dp(100),
            padding=[dp(28), dp(18), dp(28), dp(14)], spacing=dp(8),
        )
        top_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(38))
        self.exercise_label = Label(
            text='', font_size=fs(22), bold=True, color=TEXT,
            halign='left', valign='middle',
        )
        self.exercise_label.bind(size=lambda w, s: setattr(w, 'text_size', s))
        self.status_label = Label(
            text='', font_size=fs(14), color=ACCENT,
            halign='right', valign='middle',
            size_hint_x=None, width=dp(70),
        )
        self.status_label.bind(size=lambda w, s: setattr(w, 'text_size', s))
        top_row.add_widget(self.exercise_label)
        top_row.add_widget(self.status_label)

        bar_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(20), spacing=dp(10))
        self.progress_strip = ProgressStrip(
            size_hint_y=None, height=dp(6), bar_color=list(ACCENT),
        )
        self.progress_pct = Label(
            text='0%', font_size=fs(13), color=TEXT_SEC,
            halign='right', valign='middle',
            size_hint_x=None, width=dp(36),
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
            orientation='horizontal', size_hint_y=None, height=dp(100),
            padding=[dp(20), dp(14), dp(20), dp(14)], spacing=dp(16),
        )
        self.circular_progress = CircularProgress(
            size_hint=(None, None), size=(dp(72), dp(72)),
            arc_color=list(WARNING), line_width=5,
        )
        self.cue_label = Label(
            text='', font_size=fs(15), color=TEXT,
            halign='left', valign='top', markup=True,
        )
        self.cue_label.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        bottom_card.add_widget(self.circular_progress)
        bottom_card.add_widget(self.cue_label)
        root.add_widget(bottom_card)

        btn_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(54), spacing=dp(12))
        self.next_btn = RoundedButton(
            text='跳过', font_size=fs(17), bg_color=list(SURFACE2), radius=18,
        )
        self.next_btn.bind(on_press=self._on_next_press)
        self.back_btn = RoundedButton(
            text='退出', font_size=fs(17), bg_color=list(DANGER), radius=18,
            size_hint_x=None, width=dp(90),
        )
        self.back_btn.bind(on_press=self._go_home)
        btn_row.add_widget(self.next_btn)
        btn_row.add_widget(self.back_btn)
        root.add_widget(btn_row)

        self.add_widget(root)

    # ------ 视频管理 (主线程) ------

    def _show_video(self, filename):
        path = _video_path(filename)
        if not os.path.isfile(path):
            self._hide_video()
            return
        if self._current_video and self._current_video.source == path:
            self._current_video.state = 'play'
            return
        self._hide_video()
        vid = Video(
            source=path, state='play',
            options={'eos': 'loop'},
            allow_stretch=True, keep_ratio=True,
        )
        self.video_area.add_widget(vid)
        self._current_video = vid

    def _hide_video(self):
        if self._current_video:
            self._current_video.state = 'stop'
            self._current_video.unload()
            self.video_area.remove_widget(self._current_video)
            self._current_video = None

    # ------ 进度计算 (线程安全，纯数学) ------

    def _exercise_total_secs(self, ex):
        return ex['duration'] * ex['sets'] + ex['rest'] * (ex['sets'] - 1)

    def _calc_total_secs(self):
        if not self.exercises:
            return 0
        total = 0
        for i, e in enumerate(self.exercises):
            total += self._exercise_total_secs(e)
            if i < len(self.exercises) - 1:
                total += e['rest']
        return total

    def _calc_elapsed_base(self):
        elapsed = 0
        for i, e in enumerate(self.exercises[:self.exercise_index]):
            elapsed += self._exercise_total_secs(e)
            if i < self.exercise_index:
                elapsed += e['rest']
        ex = self.exercises[self.exercise_index]
        elapsed += ex['duration'] * self.set_index + ex['rest'] * self.set_index
        if self.is_resting:
            elapsed += ex['duration']
        return elapsed

    # ------ 音频管理 (线程安全，AudioPlayer 用原生 MediaPlayer) ------

    def _play_audio(self, filename, loop_filename=None):
        self._stop_audio()
        self._current_sound.play(_audio_path(filename))
        if loop_filename:
            import threading, time
            loop_path = _audio_path(loop_filename)

            def _delayed_loop():
                time.sleep(5)
                self._loop_sound.play(loop_path, loop=True)

            threading.Thread(target=_delayed_loop, daemon=True).start()

    def _stop_audio(self):
        self._loop_sound.stop()
        self._current_sound.stop()

    # ------ UI 更新 (schedule 到主线程) ------

    def _update_ui_set(self, ex_name, cue_text, duration):
        """Schedule UI update for a new exercise set."""
        def _do():
            self.exercise_label.text = ex_name
            self.exercise_label.font_size = adaptive_fs(ex_name, 22)
            self.status_label.text = '训练中'
            self.status_label.color = ACCENT
            self.cue_label.text = cue_text
            self.cue_label.font_size = adaptive_fs(cue_text, 15)
            self.circular_progress.arc_color = list(WARNING)
            self.circular_progress.text = str(duration)
            # Video
            video_file = self.exercises[self.exercise_index].get('video') if self.exercise_index < len(self.exercises) else None
            if video_file:
                self._show_video(video_file)
            else:
                self._hide_video()
        _schedule_ui(_do)

    def _update_ui_rest(self, hint):
        def _do():
            self.exercise_label.text = '休息'
            self.exercise_label.font_size = fs(22)
            self.status_label.text = '休息中'
            self.status_label.color = REST_BLUE
            self.cue_label.text = hint
            self.cue_label.font_size = adaptive_fs(hint, 15)
            self.circular_progress.arc_color = list(REST_BLUE)
            self._hide_video()
        _schedule_ui(_do)

    def _update_ui_tick(self, remaining):
        def _do():
            self.circular_progress.text = str(remaining)
            if self._total_seconds > 0:
                self.circular_progress.progress = remaining / self._total_seconds
            current_segment = self._total_seconds - remaining
            elapsed = self._elapsed_base + current_segment
            pct = min(elapsed / self._total_workout_secs, 1.0) if self._total_workout_secs > 0 else 0
            self.progress_strip.progress = pct
            self.progress_pct.text = f'{int(pct * 100)}%'
        _schedule_ui(_do)

    def _update_ui_finish(self):
        def _do():
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
        _schedule_ui(_do)

    # ====== 训练状态机 (全部在后台线程运行) ======

    def _on_tick(self, remaining):
        """Background thread: play beeps + schedule UI update."""
        if remaining == 1:
            self._beep_final.play(_audio_path('beep_final.wav'))
        elif 2 <= remaining <= 5:
            self._beep.play(_audio_path('beep.wav'))
        self._update_ui_tick(remaining)

    def _on_finish(self):
        """Background thread: advance state machine, play audio, schedule UI."""
        if not self.exercises or self.exercise_index >= len(self.exercises):
            self._finish_workout()
            return

        ex = self.exercises[self.exercise_index]

        if self.is_resting:
            self._advance_after_rest(self._rest_between_exercises)
        else:
            if self.set_index + 1 < ex['sets']:
                self._start_rest(between_exercises=False)
            elif self.exercise_index + 1 < len(self.exercises):
                self._start_rest(between_exercises=True)
            else:
                self._finish_workout()

    def _start_set(self):
        """Background thread: start next exercise set."""
        if self.exercise_index >= len(self.exercises):
            self._finish_workout()
            return

        ex = self.exercises[self.exercise_index]
        self.is_resting = False

        if ex.get('audio'):
            self._play_audio(ex['audio'], ex.get('audio_loop'))

        cues = ex.get('cues', [])
        cue_text = cues[self.set_index % len(cues)] if cues else ''

        self._total_seconds = ex['duration']
        self._elapsed_base = self._calc_elapsed_base()

        self._update_ui_set(ex['name'], cue_text, ex['duration'])
        self.timer.start(self._total_seconds)

    def _start_rest(self, between_exercises=False):
        """Background thread: start rest period."""
        ex = self.exercises[self.exercise_index]
        rest_secs = ex['rest']
        if rest_secs <= 0:
            self._advance_after_rest(between_exercises)
            return

        self.is_resting = True
        self._rest_between_exercises = between_exercises

        self._play_audio('rest_prompt.wav')
        hint = '放松，准备下一个动作' if between_exercises else '放松，准备下一组'

        self._total_seconds = rest_secs
        self._elapsed_base = self._calc_elapsed_base()

        self._update_ui_rest(hint)
        self.timer.start(self._total_seconds)

    def _advance_after_rest(self, between_exercises):
        if between_exercises:
            self.exercise_index += 1
            self.set_index = 0
        else:
            self.set_index += 1

        if self.exercise_index < len(self.exercises):
            self._start_set()
        else:
            self._finish_workout()

    def _finish_workout(self):
        self._stop_audio()
        if self._service_running:
            _stop_foreground_service()
            self._service_running = False
        self.workout_finished = True
        self._update_ui_finish()

    # ====== 主线程入口 ======

    def load(self, duration, goal):
        self._hide_video()
        _start_foreground_service()
        self._service_running = True
        self.exercises = get_exercises(duration, goal)
        if not self.exercises:
            log.error('No exercises found for duration=%s goal=%s', duration, goal)
            return
        self.exercise_index = 0
        self.set_index = 0
        self.is_resting = False
        self._rest_between_exercises = False
        self.workout_finished = False
        self._total_workout_secs = self._calc_total_secs()
        self.next_btn.text = '跳过'
        self.next_btn.bg_color = list(SURFACE2)
        self._start_set()

    def _on_next_press(self, *args):
        if self.workout_finished:
            self._go_home()
        else:
            self.timer.stop()
            self._on_finish()

    def _go_home(self, *args):
        self.timer.stop()
        self._stop_audio()
        self._hide_video()
        if self._service_running:
            _stop_foreground_service()
            self._service_running = False
        self.manager.current = 'home'

    def on_leave(self, *args):
        self.timer.stop()
        self._stop_audio()
        self._hide_video()
        if self._service_running:
            _stop_foreground_service()
            self._service_running = False
