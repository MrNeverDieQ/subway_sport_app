import os

from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.clock import Clock
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
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.uix.video import Video

from data.workouts import DETAILED
from data import history, audio_meta
from components.timer import CountdownTimer
from components.theme import (
    TEXT, TEXT_SEC, PRIMARY, PRIMARY_2, ACCENT, ACCENT_SOFT, WARNING,
    REST_BLUE, REST_SOFT, SUCCESS, SURFACE, SURFACE2, DANGER, BORDER, with_alpha, fs, hs,
)
from components.styled_widgets import (
    RoundedButton, CardBox, Chip, CircularProgress, ProgressStrip,
)

_VIDEO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'video')
_AUDIO_DIR = audio_meta.AUDIO_DIR
_REST_CLIP = '放松提示.mp3'      # 休息开始时的短句
_CLIP_GAP = 0.3                 # 连续短句之间的间隔（秒）
_CLIP_SLACK = 1.0               # 播放端不派发 on_stop 时，按估算时长 + 这个余量强制推进
_CLIP_FALLBACK_LEN = 3.0        # 既没有时长表也拿不到 sound.length 时按这个估


class WorkoutScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timer = CountdownTimer(on_tick=self._on_tick, on_finish=self._on_finish)
        self._current_video = None
        self._current_sound = None
        self._loop_sound = None
        self._loop_event = None
        self._seq_event = None
        self._seq_gen = 0            # 每次 _stop_audio 加一，旧序列的回调据此失效
        self._last_clips = []        # 最近一次请求播放的短句（含缺失的），便于测试/排查
        self._beep = _load_beep(os.path.join(_AUDIO_DIR, 'beep.wav'))
        self._beep_final = _load_beep(os.path.join(_AUDIO_DIR, 'beep_final.wav'))
        self.plan = None
        self.exercises = []
        self.timeline = []
        self.seg_index = 0
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        self._apply_metrics()

    def _apply_metrics(self):
        """所有与尺寸相关的数值集中在这里，窗口尺寸变化时整体重算。"""
        self.root_box.padding = [hs(22), hs(44), hs(22), hs(24)]
        self.root_box.spacing = hs(14)
        self.top_bar.spacing = hs(10)
        self.status_label.font_size = fs(12)
        self.status_label.pad_x = hs(12)
        self.status_label.pad_y = hs(4)
        self.step_lbl.font_size = fs(12)
        self.progress_pct.font_size = fs(12)
        self.progress_strip.height = hs(4)
        self.progress_strip.radius = hs(2)
        self.exercise_label.font_size = fs(26)
        self.center_area.spacing = hs(12)
        self.circular_progress.line_width = hs(7)
        self.cue_card.padding = [hs(20), hs(16), hs(20), hs(14)]
        self.cue_card.spacing = hs(8)
        self.cue_card.radius = hs(22)
        self.cue_label.font_size = fs(15)
        self.next_lbl.font_size = fs(12)
        self.btn_row.height = hs(52)
        self.btn_row.spacing = hs(10)
        self.next_btn.font_size = fs(16)
        self.next_btn.radius = hs(16)
        self.back_btn.font_size = fs(15)
        self.back_btn.radius = hs(16)
        self.back_btn.width = hs(92)
        self._fit_ring(self.ring_holder, self.ring_holder.size)

    # ------------------------------------------------------------ 构建

    def _build_ui(self):
        self.root_box = BoxLayout(orientation='vertical')
        root = self.root_box

        def auto_label(text, size, color, halign='left'):
            # 单行自适应标签：宽度跟随父容器，高度跟随字体
            lbl = Label(text=text, font_size=size, color=color, halign=halign,
                        valign='middle', size_hint_y=None)
            lbl.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)),
                     texture_size=lambda w, ts: setattr(w, 'height', ts[1]))
            return lbl

        # 顶栏：状态 chip | 第 x/y 个 | 百分比
        self.top_bar = BoxLayout(orientation='horizontal', size_hint_y=None)
        self.top_bar.bind(minimum_height=self.top_bar.setter('height'))
        self.status_label = Chip(text='训练中', font_size=fs(12), color=PRIMARY,
                                 bg_color=list(ACCENT_SOFT))
        self.step_lbl = auto_label('', fs(12), TEXT_SEC, halign='right')
        self.progress_pct = Label(text='0%', font_size=fs(12), color=TEXT_SEC,
                                  halign='right', valign='middle', size_hint=(None, None))
        self.progress_pct.bind(texture_size=lambda w, ts: setattr(w, 'size', (ts[0] + hs(4), ts[1])))
        # 顶栏三个元素各自高度不同，用一个水平盒子让它们垂直居中
        for w in (self.status_label, self.step_lbl, self.progress_pct):
            w.pos_hint = {'center_y': 0.5}
        self.top_bar.add_widget(self.status_label)
        self.top_bar.add_widget(self.step_lbl)
        self.top_bar.add_widget(self.progress_pct)
        root.add_widget(self.top_bar)

        self.progress_strip = ProgressStrip(size_hint_y=None, bar_color=list(ACCENT))
        root.add_widget(self.progress_strip)

        # 动作名：单行，过长时省略
        self.exercise_label = auto_label('', fs(26), TEXT)
        self.exercise_label.bold = True
        self.exercise_label.shorten = True
        self.exercise_label.shorten_from = 'right'
        root.add_widget(self.exercise_label)

        # 中央：视频（可选）+ 大倒计时环
        self.center_area = BoxLayout(orientation='vertical')
        self.ring_holder = AnchorLayout(anchor_x='center', anchor_y='center')
        self.circular_progress = CircularProgress(size_hint=(None, None), size=(240, 240),
                                                  arc_color=list(WARNING))
        self.ring_holder.add_widget(self.circular_progress)
        self.ring_holder.bind(size=self._fit_ring)
        self.center_area.add_widget(self.ring_holder)
        root.add_widget(self.center_area)

        # 提示语卡片：高度随文字
        self.cue_card = CardBox(orientation='vertical', size_hint_y=None)
        self.cue_card.bind(minimum_height=self.cue_card.setter('height'))
        self.cue_label = Label(text='', font_size=fs(15), color=TEXT,
                               halign='left', valign='top', size_hint_y=None)
        self.cue_label.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)),
                            texture_size=lambda w, ts: setattr(w, 'height', ts[1]))
        self.next_lbl = auto_label('', fs(12), TEXT_SEC)
        self.cue_card.add_widget(self.cue_label)
        self.cue_card.add_widget(self.next_lbl)
        root.add_widget(self.cue_card)

        # 按钮
        self.btn_row = BoxLayout(orientation='horizontal', size_hint_y=None)
        self.next_btn = RoundedButton(text='跳过', font_size=fs(16), bg_color=list(SURFACE2))
        self.next_btn.bind(on_press=self._on_next_press)
        self.back_btn = RoundedButton(text='退出', font_size=fs(15),
                                      bg_color=list(SURFACE), color=DANGER,
                                      border_color=list(with_alpha(DANGER, 0.45)),
                                      size_hint_x=None)
        self.back_btn.bind(on_press=self._go_home)
        self.btn_row.add_widget(self.next_btn)
        self.btn_row.add_widget(self.back_btn)
        root.add_widget(self.btn_row)

        self.add_widget(root)
        self.workout_finished = False
        self._apply_metrics()

    def _fit_ring(self, holder, size):
        d = min(size[0] * 0.72, size[1] * 0.92, hs(320))
        d = max(hs(40), min(d, size[0], size[1]))
        self.circular_progress.size = (d, d)

    # ------------------------------------------------------------ 视频

    def _show_video(self, filename):
        path = os.path.join(_VIDEO_DIR, filename)
        if not os.path.isfile(path):
            self._hide_video()
            return
        if self._current_video and self._current_video.source == path:
            self._current_video.state = 'play'
            return
        self._hide_video()
        vid = Video(source=path, state='play', options={'eos': 'loop'},
                    fit_mode='contain', size_hint_y=0.58)
        self.ring_holder.size_hint_y = 0.42
        self.center_area.add_widget(vid, index=1)
        self._current_video = vid

    def _hide_video(self):
        if self._current_video:
            self._current_video.state = 'stop'
            self._current_video.unload()
            self.center_area.remove_widget(self._current_video)
            self._current_video = None
        self.ring_holder.size_hint_y = 1

    def _sync_video(self, ex):
        video_file = ex.get('video')
        if video_file:
            self._show_video(video_file)
        else:
            self._hide_video()

    # ------------------------------------------------------------ 时间线

    @property
    def segment(self):
        return self.timeline[self.seg_index] if self.seg_index < len(self.timeline) else None

    @property
    def is_resting(self):
        seg = self.segment
        return bool(seg) and seg['kind'] == 'rest'

    @property
    def exercise_index(self):
        seg = self.segment
        return seg['ex'] if seg else len(self.exercises) - 1

    @property
    def set_index(self):
        seg = self.segment
        return seg['set'] if seg else 0

    def _update_progress(self, remaining):
        elapsed = self._elapsed_base + (self._total_seconds - remaining)
        pct = min(elapsed / self._total_workout_secs, 1.0) if self._total_workout_secs > 0 else 0
        self._pct = pct
        self.progress_strip.progress = pct
        self.progress_pct.text = f'{int(pct * 100)}%'

    def _next_text(self):
        """当前 set/rest 之后是什么。"""
        seg = self.segment
        ex = self.exercises[seg['ex']]
        if seg['set'] + 1 < ex['sets']:
            return f"下一组  ·  {ex['name']}  第 {seg['set'] + 2}/{ex['sets']} 组"
        if seg['ex'] + 1 < len(self.exercises):
            return f"下一个  ·  {self.exercises[seg['ex'] + 1]['name']}"
        return '最后一个动作'

    def _update_step(self):
        seg = self.segment
        ex = self.exercises[seg['ex']]
        text = f"{seg['ex'] + 1} / {len(self.exercises)}"
        if ex['sets'] > 1 and seg['kind'] != 'guide':
            text += f"   第 {seg['set'] + 1}/{ex['sets']} 组"
        self.step_lbl.text = text

    def _set_status(self, text, fg, bg):
        self.status_label.text = text
        self.status_label.color = fg
        self.status_label.bg_color = list(bg)

    # ------------------------------------------------------------ 生命周期

    def load(self, plan):
        self._hide_video()
        self._stop_audio()
        self.plan = plan
        self.exercises = plan.entries
        self.timeline = plan.timeline
        self.seg_index = 0
        self.workout_finished = False
        self._pct = 0.0
        self._real_secs = 0          # 真实经过的秒数（跳过不计入），用于判断中途退出是否算练过
        self._elapsed_base = 0
        self._total_seconds = 0
        self._total_workout_secs = plan.total_secs
        self.next_btn.text = '跳过'
        self.next_btn.gradient = None
        self.next_btn.bg_color = list(SURFACE2)
        self.next_btn.border_color = list(BORDER)
        self.next_btn.color = TEXT
        self.progress_strip.bar_color = list(ACCENT)
        self.circular_progress.track_color = [0.14, 0.14, 0.18, 1]
        self._start_segment()

    def _on_next_press(self, *args):
        if self.workout_finished:
            self._go_home()
            return
        self.timer.stop()
        seg = self.segment
        self.seg_index += 1
        # 跳过一组动作时，连带跳过紧跟的组间休息
        if seg and seg['kind'] == 'set' and self.segment and self.segment['kind'] == 'rest':
            self.seg_index += 1
        self._start_segment()

    def _on_finish(self):
        self.timer.stop()
        self.seg_index += 1
        self._start_segment()

    def _start_segment(self):
        seg = self.segment
        if seg is None:
            self._finish_workout()
            return
        self._elapsed_base = sum(s['secs'] for s in self.timeline[:self.seg_index])
        self._total_seconds = seg['secs']
        {'guide': self._start_guide, 'set': self._start_set, 'rest': self._start_rest}[seg['kind']](seg)
        self.timer.start(self._total_seconds)

    def _start_guide(self, seg):
        """动作开始前：详细模式听完整讲解，简短模式只报"下一个 + 短提示"。"""
        ex = self.exercises[seg['ex']]
        first = seg['ex'] == 0
        detailed = seg['mode'] == DETAILED and ex.get('audio')
        clips = [] if first else [audio_meta.sys_clip('下一个')]
        if detailed:
            clips.append(ex['audio'])
        elif ex.get('audio'):
            clips.append(audio_meta.short_variant(ex['audio']))
        self._play_sequence(clips)

        self.exercise_label.text = ex['name']
        if detailed:
            self._set_status('讲解', REST_BLUE, REST_SOFT)
        else:
            self._set_status('准备' if first else '下一个', REST_BLUE, REST_SOFT)
        self._update_step()
        cues = ex.get('cues', [])
        self.cue_label.text = cues[0] if cues else ''
        detail = f"{ex['sets']} 组 × {ex['duration']} 秒" if ex['sets'] > 1 else f"{ex['duration']} 秒"
        if ex['sets'] > 1 and ex.get('rest'):
            detail += f"  ·  组间休息 {ex['rest']} 秒"
        self.next_lbl.text = ('听完讲解后开始  ·  ' if detailed else '') + detail
        self.circular_progress.arc_color = list(REST_BLUE)
        self.circular_progress.sub_text = '讲解' if detailed else '准备'
        self._sync_video(ex)

    def _start_set(self, seg):
        """一组动作：开始 / 第 N 组 短句，之后只有倒计时；呼吸循环音紧接着短句开始。"""
        ex = self.exercises[seg['ex']]
        k = seg['set']
        if k == 0:
            clips = [audio_meta.sys_clip('开始')]
        else:
            clips = [audio_meta.sys_clip(audio_meta.set_clip(k + 1, ex['sets']))]
        loop = ex.get('audio_loop')
        if loop:
            self._play_sequence(clips, then=lambda: self._start_loop(loop, 0))
        else:
            self._play_sequence(clips)

        self.exercise_label.text = ex['name']
        self._set_status('训练中', PRIMARY, ACCENT_SOFT)
        self._update_step()
        cues = ex.get('cues', [])
        self.cue_label.text = cues[k % len(cues)] if cues else ''
        self.next_lbl.text = self._next_text()
        self.circular_progress.arc_color = list(WARNING)
        self.circular_progress.sub_text = '秒'
        self._sync_video(ex)

    def _start_rest(self, seg):
        self._play_sequence([_REST_CLIP])
        self._set_status('休息中', REST_BLUE, REST_SOFT)
        self.cue_label.text = '放松，调整呼吸'
        self.next_lbl.text = self._next_text()
        self._update_step()
        self.circular_progress.arc_color = list(REST_BLUE)
        self.circular_progress.sub_text = '休息'
        self._hide_video()

    def _on_tick(self, remaining):
        first_tick = remaining >= self._total_seconds
        if not first_tick:
            self._real_secs += 1
        self.circular_progress.text = str(remaining)
        if self._total_seconds > 0:
            self.circular_progress.progress = remaining / self._total_seconds
        self._update_progress(remaining)
        if first_tick:
            return          # 段刚开始不响提示音（短段会和语音撞上）
        if remaining == 1:
            if self._beep_final:
                self._beep_final.stop()
                self._beep_final.play()
        elif 2 <= remaining <= 5:
            if self._beep:
                self._beep.stop()
                self._beep.play()

    def _finish_workout(self):
        self.timer.stop()
        self._hide_video()
        self.workout_finished = True
        history.record(self.plan.blocks)
        self._play_sequence([audio_meta.sys_clip('训练完成')])

        self.exercise_label.text = '训练完成！'
        self._set_status('已完成', SUCCESS, with_alpha(SUCCESS, 0.14))
        self.step_lbl.text = f'{len(self.exercises)} / {len(self.exercises)}'
        self.progress_strip.progress = 1.0
        self.progress_strip.bar_color = list(SUCCESS)
        self.progress_pct.text = '100%'
        self._pct = 1.0

        self.circular_progress.text = '完成'
        self.circular_progress.sub_text = f'{self.plan.minutes} 分钟'
        self.circular_progress.progress = 1.0
        self.circular_progress.arc_color = list(SUCCESS)

        parts = '  ·  '.join(n if c <= 1 else f'{n} ×{c}' for n, c in self.plan.parts)
        self.cue_label.text = parts
        self.next_lbl.text = f'共 {self.plan.total_sets} 组动作  ·  记得补充水分，做好拉伸'

        self.next_btn.text = '返回首页'
        self.next_btn.gradient = (PRIMARY_2, PRIMARY)
        self.next_btn.border_color = [0, 0, 0, 0]
        self.next_btn.color = (1, 1, 1, 1)

    # ------------------------------------------------------------ 音频

    def _play_sequence(self, clips, then=None):
        """
        依次播放若干音频（相对 audio/ 的路径），缺失的直接跳过；全部播完后调用 then。
        以 on_stop（自然播完）为主，估算时长 + 余量为兜底，两者都用 _seq_gen 防止旧序列串台。
        """
        self._stop_audio()
        gen = self._seq_gen
        self._last_clips = list(clips)
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

    def _start_loop(self, rel, delay):
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

    def _stop_audio(self):
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

    def _go_home(self, *args):
        if self.manager is None or self.manager.current != self.name:
            return      # 转场期间再点一次，不重复记录
        self.timer.stop()
        self._stop_audio()
        self._hide_video()
        if not self.workout_finished and self._real_secs >= 0.5 * self._total_workout_secs:
            history.record(self.plan.blocks)
        self.manager.current = 'home'

    def on_leave(self, *args):
        self.timer.stop()
        self._stop_audio()
        self._hide_video()


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
