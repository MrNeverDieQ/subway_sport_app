import os

from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.video import Video


from data.workouts import get_exercises
from components.timer import CountdownTimer
from components.theme import (
    TEXT, TEXT_SEC, ACCENT, WARNING, REST_BLUE, SURFACE2, DANGER, fs, adaptive_fs, APP_ROOT,
)
from components.styled_widgets import (
    RoundedButton, CardBox, CircularProgress, ProgressStrip,
)

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _audio_path(filename):
    import components.theme as theme
    root = theme.APP_ROOT or _APP_DIR
    return os.path.join(root, 'audio', filename)


def _video_path(filename):
    import components.theme as theme
    root = theme.APP_ROOT or _APP_DIR
    return os.path.join(root, 'video', filename)


class WorkoutScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timer = CountdownTimer(on_tick=self._on_tick, on_finish=self._on_finish)
        self._current_video = None
        self._current_sound = None
        self._loop_sound = None
        self._loop_event = None
        self._beep = None
        self._beep_final = None
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    def _ensure_beeps(self):
        if self._beep is None:
            bp = _audio_path('beep.wav')
            bfp = _audio_path('beep_final.wav')
            print(f'[AUDIO] beep path={bp}, exists={os.path.exists(bp)}')
            print(f'[AUDIO] beep_final path={bfp}, exists={os.path.exists(bfp)}')
            self._beep = SoundLoader.load(bp)
            self._beep_final = SoundLoader.load(bfp)
            print(f'[AUDIO] beep loaded={self._beep}, beep_final loaded={self._beep_final}')

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
            size_hint_y=None, height=dp(6),
            bar_color=list(ACCENT),
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
            text='跳过', font_size=fs(17),
            bg_color=list(SURFACE2), radius=18,
        )
        self.next_btn.bind(on_press=self._on_next_press)
        self.back_btn = RoundedButton(
            text='退出', font_size=fs(17),
            bg_color=list(DANGER), radius=18,
            size_hint_x=None, width=dp(90),
        )
        self.back_btn.bind(on_press=self._go_home)
        btn_row.add_widget(self.next_btn)
        btn_row.add_widget(self.back_btn)
        root.add_widget(btn_row)

        self.add_widget(root)
        self.workout_finished = False

    # ------ 视频管理 ------

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
        for i, e in enumerate(self.exercises):
            total += e['duration'] * e['sets'] + e['rest'] * e['sets']
        # 最后一个动作的最后一组后不休息
        if self.exercises:
            total -= self.exercises[-1]['rest']
        return total

    def _calc_elapsed_base(self):
        elapsed = 0
        for i, e in enumerate(self.exercises[:self.exercise_index]):
            elapsed += e['duration'] * e['sets'] + e['rest'] * e['sets']
            if i == len(self.exercises) - 1:
                elapsed -= e['rest']
        ex = self.exercises[self.exercise_index]
        elapsed += ex['duration'] * self.set_index + ex['rest'] * self.set_index
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
            self._on_finish()

    def _play_audio(self, filename, loop_filename=None):
        self._stop_audio()
        path = _audio_path(filename)
        print(f'[AUDIO] play: {path}, exists={os.path.exists(path)}')
        if not os.path.exists(path):
            return

        sound = SoundLoader.load(path)
        print(f'[AUDIO] loaded: {sound}')
        if not sound:
            return
        sound.loop = False
        sound.play()
        self._current_sound = sound

        if loop_filename:
            loop_path = _audio_path(loop_filename)

            def _start_loop(dt):
                self._loop_event = None
                if not os.path.exists(loop_path):
                    return
                s = SoundLoader.load(loop_path)
                if s:
                    s.loop = True
                    s.play()
                    self._loop_sound = s

            from kivy.clock import Clock
            self._loop_event = Clock.schedule_once(_start_loop, 5)

    def _start_set(self):
        ex = self.exercises[self.exercise_index]
        self.is_resting = False

        if ex.get('audio'):
            self._play_audio(ex['audio'], ex.get('audio_loop'))
        self.exercise_label.text = ex['name']
        self.exercise_label.font_size = adaptive_fs(ex['name'], 22)
        self.status_label.text = '训练中'
        self.status_label.color = ACCENT

        cues = ex.get('cues', [])
        cue_text = cues[self.set_index % len(cues)] if cues else ''
        self.cue_label.text = cue_text
        self.cue_label.font_size = adaptive_fs(cue_text, 15)

        self._total_seconds = ex['duration']
        self._elapsed_base = self._calc_elapsed_base()
        self.circular_progress.arc_color = list(WARNING)
        self._sync_video(ex)
        self.timer.start(self._total_seconds)

    def _start_rest(self, between_exercises=False):
        ex = self.exercises[self.exercise_index]
        rest_secs = ex['rest']
        if rest_secs <= 0:
            # 无休息时间，直接进入下一阶段
            self._advance_after_rest(between_exercises)
            return

        self.is_resting = True
        self._rest_between_exercises = between_exercises

        self._play_audio('rest_prompt.wav')
        self.exercise_label.text = '休息'
        self.exercise_label.font_size = fs(22)
        self.status_label.text = '休息中'
        self.status_label.color = REST_BLUE
        hint = '放松，准备下一个动作' if between_exercises else '放松，准备下一组'
        self.cue_label.text = hint
        self.cue_label.font_size = adaptive_fs(hint, 15)

        self._total_seconds = rest_secs
        self._elapsed_base = self._calc_elapsed_base()
        self.circular_progress.arc_color = list(REST_BLUE)
        self._hide_video()
        print(f'[REST] start rest={rest_secs}s between_exercises={between_exercises} ex_idx={self.exercise_index} set_idx={self.set_index}')
        self.timer.start(self._total_seconds)

    def _on_tick(self, remaining):
        self.circular_progress.text = str(remaining)
        if self._total_seconds > 0:
            self.circular_progress.progress = remaining / self._total_seconds
        self._update_progress(remaining)
        self._ensure_beeps()
        if remaining == 1:
            if self._beep_final:
                self._beep_final.stop()
                self._beep_final.play()
        elif 2 <= remaining <= 5:
            if self._beep:
                self._beep.stop()
                self._beep.play()

    def _advance_after_rest(self, between_exercises):
        """Rest 结束（或跳过）后，进入下一组或下一个动作。"""
        if between_exercises:
            self.exercise_index += 1
            self.set_index = 0
        else:
            self.set_index += 1

        if self.exercise_index < len(self.exercises):
            self._start_set()
        else:
            self._finish_workout()

    def _on_finish(self):
        self.timer.stop()
        ex = self.exercises[self.exercise_index]

        if self.is_resting:
            # rest 结束，根据标记决定下一步
            self._advance_after_rest(self._rest_between_exercises)
        else:
            # 动作完成
            if self.set_index + 1 < ex['sets']:
                # 还有更多组 → 组间休息
                self._start_rest(between_exercises=False)
            else:
                # 所有组完成 → 动作间休息（如果还有下一个动作）
                if self.exercise_index + 1 < len(self.exercises):
                    self._start_rest(between_exercises=True)
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
        for snd in (self._loop_sound, self._current_sound):
            if snd is not None:
                snd.stop()
        self._loop_sound = None
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
