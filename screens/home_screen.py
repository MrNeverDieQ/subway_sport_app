from kivy.core.window import Window
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView

from components.theme import (
    TEXT, TEXT_SEC, PRIMARY, ACCENT, SURFACE, SURFACE2, DISABLED, fs,
)
from components.styled_widgets import RoundedButton, CardBox
from data.workouts import get_durations, get_goals


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_duration = None
        self.selected_goal = None
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    def _on_resize(self, *_):
        self.title_lbl.font_size = fs(34)
        self.subtitle_lbl.font_size = fs(13)
        for lbl in self._section_labels:
            lbl.font_size = fs(13)
        for btn in self._dur_btns.values():
            btn.font_size = fs(12)
        if hasattr(self, '_goal_btns'):
            for btn in self._goal_btns.values():
                btn.font_size = fs(17)
        self.start_btn.font_size = fs(18)

    def _build_ui(self):
        self._section_labels = []
        root = BoxLayout(orientation='vertical', padding=[24, 48, 24, 28], spacing=24)

        # Header
        header = CardBox(
            orientation='vertical', size_hint_y=None,
            padding=[28, 22, 28, 22], spacing=8,
        )
        header.bind(minimum_height=header.setter('height'))
        self.title_lbl = Label(
            text='地铁健身', font_size=fs(34), bold=True,
            size_hint_y=None, height=44, color=TEXT, halign='left', valign='middle',
        )
        self.title_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        self.subtitle_lbl = Label(
            text='碎片时间  · 高效训练  · 随时随地',
            font_size=fs(13), size_hint_y=None, height=28,
            color=TEXT_SEC, halign='left', valign='middle',
        )
        self.subtitle_lbl.bind(size=lambda w, s: setattr(w, 'text_size', (s[0], None)))
        header.add_widget(self.title_lbl)
        header.add_widget(self.subtitle_lbl)
        root.add_widget(header)

        # 时长选择
        root.add_widget(self._section_label('训练时长'))
        self.duration_layout = BoxLayout(
            orientation='horizontal', spacing=10,
            size_hint_y=None, height=54,
        )
        self._build_duration_buttons()
        root.add_widget(self.duration_layout)

        # 目的选择
        root.add_widget(self._section_label('训练目的'))
        self.goal_layout = BoxLayout(
            orientation='vertical', spacing=12,
            size_hint_y=None,
        )
        self.goal_layout.bind(minimum_height=self.goal_layout.setter('height'))
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.goal_layout)
        root.add_widget(scroll)

        # 开始按钮
        self.start_btn = RoundedButton(
            text='开始训练', font_size=fs(18),
            size_hint_y=None, height=58,
            bg_color=list(DISABLED), disabled=True,
            radius=18,
        )
        self.start_btn.bind(on_press=self._start_workout)
        root.add_widget(self.start_btn)

        self.add_widget(root)

    def _section_label(self, text):
        lbl = Label(
            text=text, font_size=fs(13), color=TEXT_SEC,
            size_hint_y=None, height=22, halign='left',
        )
        lbl.bind(size=lambda w, s: setattr(w, 'text_size', s))
        self._section_labels.append(lbl)
        return lbl

    def _build_duration_buttons(self):
        self.duration_layout.clear_widgets()
        self._dur_btns = {}
        for d in get_durations():
            btn = RoundedButton(
                text=f'{d}min', font_size=fs(12),
                bg_color=list(SURFACE2), radius=14,
            )
            btn.bind(on_press=lambda b, dur=d: self._select_duration(dur))
            self.duration_layout.add_widget(btn)
            self._dur_btns[d] = btn

    def _select_duration(self, duration):
        self.selected_duration = duration
        self.selected_goal = None
        for d, btn in self._dur_btns.items():
            btn.bg_color = list(PRIMARY) if d == duration else list(SURFACE2)
        self._build_goal_buttons(duration)
        self._update_start_btn()

    def _build_goal_buttons(self, duration):
        self.goal_layout.clear_widgets()
        self._goal_btns = {}
        for goal in get_goals(duration):
            btn = RoundedButton(
                text=goal, font_size=fs(17),
                size_hint_y=None, height=64,
                bg_color=list(SURFACE2), radius=18,
            )
            btn.bind(on_press=lambda b, g=goal: self._select_goal(g))
            self.goal_layout.add_widget(btn)
            self._goal_btns[goal] = btn

    def _select_goal(self, goal):
        self.selected_goal = goal
        for g, btn in self._goal_btns.items():
            btn.bg_color = list(PRIMARY) if g == goal else list(SURFACE2)
        self._update_start_btn()

    def _update_start_btn(self):
        ready = self.selected_duration is not None and self.selected_goal is not None
        self.start_btn.disabled = not ready
        self.start_btn.bg_color = list(ACCENT) if ready else list(DISABLED)

    def _start_workout(self, *args):
        if self.start_btn.disabled:
            return
        workout_screen = self.manager.get_screen('workout')
        workout_screen.load(self.selected_duration, self.selected_goal)
        self.manager.current = 'workout'
