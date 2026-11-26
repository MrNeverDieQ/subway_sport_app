import os

from kivy.core.window import Window
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.video import Video

from core.engine import is_detailed
from data import history
from screens.workout_session import make_session, LocalSession, ServiceSession
from components.theme import (
    TEXT, TEXT_SEC, PRIMARY, PRIMARY_2, ACCENT, ACCENT_SOFT, WARNING,
    REST_BLUE, REST_SOFT, SUCCESS, SURFACE, SURFACE2, DANGER, BORDER, with_alpha, fs, hs,
)
from components.styled_widgets import (
    RoundedButton, CardBox, Chip, CircularProgress, ProgressStrip,
)

_VIDEO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'video')


def _disable_video_audio_decoding():
    """
    让 ffpyplayer 解码视频时根本不打开音频流（ff_opts['an']）。演示视频只看画面，声音只来自语音指导。
    成片已剔除音轨，这是兜底：即使混进带声音的 mp4 也不会出声。
    注意不能用 Video(volume=0) 来静音：Kivy 2.3.0 + ffpyplayer 在 Windows 上给视频设 volume=0，
    会把同一时刻正在播放的 SDL_mixer 声道（也就是讲解 mp3）一起弄哑（2026-11-25 用系统电平表实测确认）。
    """
    try:
        from kivy.core.video import video_ffpyplayer as vf
    except Exception:
        return
    real = getattr(vf, 'MediaPlayer', None)
    if real is None or getattr(real, '_subway_an', False):
        return

    def media_player(filename, callback=None, thread_lib='SDL', loglevel='info', ff_opts=None, **kw):
        ff_opts = dict(ff_opts or {})
        ff_opts['an'] = True
        return real(filename, callback=callback, thread_lib=thread_lib, loglevel=loglevel, ff_opts=ff_opts, **kw)

    media_player._subway_an = True
    vf.MediaPlayer = media_player


_disable_video_audio_decoding()


class GuideVideo(Video):
    """
    动作演示视频。Kivy 2.3.0 的 Video.texture_update 在没有 preview 时会把 source（mp4）
    当作图片去 CoreImage 加载，必然失败并打一条 "Image: Error loading <...mp4>"（视频本身不受影响）。
    这里跳过这一步：画面纹理由视频播放器的帧回调写入，不需要先当图片读。
    静音靠 _disable_video_audio_decoding()，不要在这里设 volume=0（见其说明）。
    """

    def texture_update(self, *largs):
        if self.preview:
            self.set_texture_from_resource(self.preview)


class WorkoutScreen(Screen):
    """
    训练页只负责显示：所有计时、放音、推进都在 Session 里（桌面进程内；Android 前台服务进程）。
    Session 每次状态变化回调 _on_session_change，这里按 seg_index / remaining 重绘。
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session = None
        self._player = None              # 进程内播放器，用到时才建（Android 正常走服务，不需要）
        self._current_video = None
        self.plan = None
        self.exercises = []
        self.timeline = []
        self._rendered_seg = None
        self._pct = 0.0
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    @property
    def player(self):
        if self._player is None:
            from components.kivy_player import KivyPlayer
            self._player = KivyPlayer()
        return self._player

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
        vid = GuideVideo(source=path, state='play', options={'eos': 'loop'},
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

    # ------------------------------------------------------------ 只读状态（来自 Session）

    @property
    def seg_index(self):
        return self.session.seg_index if self.session else 0

    @property
    def segment(self):
        return self.session.segment if self.session else None

    @property
    def is_resting(self):
        return bool(self.session) and self.session.is_resting

    @property
    def exercise_index(self):
        seg = self.segment
        return seg['ex'] if seg else len(self.exercises) - 1

    @property
    def set_index(self):
        seg = self.segment
        return seg['set'] if seg else 0

    @property
    def _real_secs(self):
        return self.session.real_secs if self.session else 0

    @property
    def _total_workout_secs(self):
        return self.plan.total_secs if self.plan else 0

    # ------------------------------------------------------------ 生命周期

    def load(self, plan):
        """开始一次新训练。"""
        self._detach()
        self._prepare(plan)
        self.session = make_session(plan, on_change=self._on_session_change,
                                    player=self._player_for_local(), on_fail=self._on_session_fail)
        self.session.start()

    def attach(self, plan, state):
        """接管一个仍在跑的前台服务会话（App 被杀后重新打开）。"""
        self._detach()
        self._prepare(plan)
        self.session = ServiceSession(plan, on_change=self._on_session_change,
                                      session_id=state.get('session'), on_fail=self._on_session_fail)
        self.session.attach(state)

    def refresh(self):
        """回到前台时立刻和会话对齐（后台期间 Clock 不走，镜像可能落后）。"""
        if self.session:
            self.session.refresh()

    def _player_for_local(self):
        from screens.workout_session import use_service
        return None if use_service() else self.player

    def _prepare(self, plan):
        self.plan = plan
        self.exercises = plan.entries
        self.timeline = plan.timeline
        self.workout_finished = False
        self._rendered_seg = None
        self._pct = 0.0
        self.next_btn.text = '跳过'
        self.next_btn.gradient = None
        self.next_btn.bg_color = list(SURFACE2)
        self.next_btn.border_color = list(BORDER)
        self.next_btn.color = TEXT
        self.progress_strip.bar_color = list(ACCENT)
        self.progress_strip.progress = 0
        self.progress_pct.text = '0%'
        self.circular_progress.track_color = [0.14, 0.14, 0.18, 1]

    def _detach(self):
        if self.session:
            self.session.stop()
            self.session = None
        self._hide_video()

    def _on_session_fail(self, session, reason):
        """前台服务不可用：进程内从当前段继续（锁屏后会暂停，但至少能练）。"""
        if session is not self.session:
            return
        from_seg, real_secs = session.seg_index, session.real_secs
        self.session = LocalSession(self.plan, on_change=self._on_session_change, player=self.player)
        self._rendered_seg = None
        self.session.start(from_seg=from_seg, real_secs=real_secs)

    def _on_session_change(self, session):
        if session is not self.session:
            return
        if session.finished:
            if not self.workout_finished:
                self._render_finish()
            return
        seg = session.segment
        if seg is None:
            return
        if session.seg_index != self._rendered_seg:
            self._rendered_seg = session.seg_index
            {'guide': self._render_guide, 'set': self._render_set, 'rest': self._render_rest}[seg['kind']](seg)
        self._render_tick(session, seg)

    def _on_next_press(self, *args):
        if self.workout_finished or self.session is None:
            self._go_home()
            return
        self.session.skip()

    def _go_home(self, *args):
        if self.manager is None or self.manager.current != self.name:
            return      # 转场期间再点一次，不重复记录
        session, self.session = self.session, None
        if session:
            session.stop()
            if session.should_record_on_exit():
                history.record(self.plan.blocks)
        self._hide_video()
        self.manager.current = 'home'

    def on_leave(self, *args):
        self._detach()

    # ------------------------------------------------------------ 渲染

    def _next_text(self, seg):
        """当前 set/rest 之后是什么。"""
        ex = self.exercises[seg['ex']]
        if seg['set'] + 1 < ex['sets']:
            return f"下一组  ·  {ex['name']}  第 {seg['set'] + 2}/{ex['sets']} 组"
        if seg['ex'] + 1 < len(self.exercises):
            return f"下一个  ·  {self.exercises[seg['ex'] + 1]['name']}"
        return '最后一个动作'

    def _update_step(self, seg):
        ex = self.exercises[seg['ex']]
        text = f"{seg['ex'] + 1} / {len(self.exercises)}"
        if ex['sets'] > 1 and seg['kind'] != 'guide':
            text += f"   第 {seg['set'] + 1}/{ex['sets']} 组"
        self.step_lbl.text = text

    def _set_status(self, text, fg, bg):
        self.status_label.text = text
        self.status_label.color = fg
        self.status_label.bg_color = list(bg)

    def _render_guide(self, seg):
        """动作开始前：详细模式听完整讲解，简短模式只报"下一个 + 短提示"。
        热身"准备"条目只有这一段：边听讲解边摆好姿势，倒计时结束直接进下一个动作。"""
        ex = self.exercises[seg['ex']]
        first = seg['ex'] == 0
        warmup = bool(ex.get('warmup'))
        detailed = is_detailed(seg, ex)
        self.exercise_label.text = ex['name']
        if warmup:
            self._set_status('准备', REST_BLUE, REST_SOFT)
        elif detailed:
            self._set_status('讲解', REST_BLUE, REST_SOFT)
        else:
            self._set_status('准备' if first else '下一个', REST_BLUE, REST_SOFT)
        self._update_step(seg)
        cues = ex.get('cues', [])
        self.cue_label.text = cues[0] if cues else ''
        if warmup:
            self.next_lbl.text = '边听边摆好姿势  ·  ' + self._next_text(seg)
        else:
            detail = f"{ex['sets']} 组 × {ex['duration']} 秒" if ex['sets'] > 1 else f"{ex['duration']} 秒"
            if ex['sets'] > 1 and ex.get('rest'):
                detail += f"  ·  组间休息 {ex['rest']} 秒"
            self.next_lbl.text = ('听完讲解后开始  ·  ' if detailed else '') + detail
        self.circular_progress.arc_color = list(REST_BLUE)
        self.circular_progress.sub_text = '讲解' if detailed and not warmup else '准备'
        self._sync_video(ex)

    def _render_set(self, seg):
        ex = self.exercises[seg['ex']]
        k = seg['set']
        self.exercise_label.text = ex['name']
        self._set_status('训练中', PRIMARY, ACCENT_SOFT)
        self._update_step(seg)
        cues = ex.get('cues', [])
        self.cue_label.text = cues[k % len(cues)] if cues else ''
        self.next_lbl.text = self._next_text(seg)
        self.circular_progress.arc_color = list(WARNING)
        self.circular_progress.sub_text = '秒'
        self._sync_video(ex)

    def _render_rest(self, seg):
        self._set_status('休息中', REST_BLUE, REST_SOFT)
        self.cue_label.text = '放松，调整呼吸'
        self.next_lbl.text = self._next_text(seg)
        self._update_step(seg)
        self.circular_progress.arc_color = list(REST_BLUE)
        self.circular_progress.sub_text = '休息'
        self._hide_video()

    def _render_tick(self, session, seg):
        remaining = max(session.remaining, 0)
        self.circular_progress.text = str(remaining)
        self.circular_progress.progress = remaining / seg['secs'] if seg['secs'] > 0 else 0
        pct = session.pct
        self._pct = pct
        self.progress_strip.progress = pct
        self.progress_pct.text = f'{int(pct * 100)}%'

    def _render_finish(self):
        self._hide_video()
        self.workout_finished = True

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
