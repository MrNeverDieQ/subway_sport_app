from kivy.core.window import Window
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.stacklayout import StackLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line

from components.theme import (
    TEXT, TEXT_SEC, TEXT_TER, PRIMARY, PRIMARY_2, ACCENT_SOFT, SURFACE,
    DISABLED, BORDER, BG, with_alpha, fs, hs,
)
from components.styled_widgets import RoundedButton, CardBox, Chip
from data.workouts import get_durations, get_goals, build_plan, AUTO, DETAILED, SHORT, MODE_LABEL, FAMILIAR_AFTER
from data import history

# 目的卡片的副标题（纯 UI 文案）
_GOAL_DESC = {
    '力量训练': '静态对抗  ·  颈 / 臀腿 / 背 / 胸 智能轮换',
    '呼吸训练': '伞吸 - 真空呼  ·  核心联动',
}


def auto_label(text, size, color, halign='left'):
    """单行自适应标签：宽度跟随父容器，高度跟随字体，不会裁字。"""
    lbl = Label(text=text, font_size=size, color=color, halign=halign, valign='middle',
                size_hint_y=None)
    lbl.bind(width=lambda w, v: setattr(w, 'text_size', (v, None)),
             texture_size=lambda w, ts: setattr(w, 'height', ts[1]))
    return lbl


class _Dot(Widget):
    """选中指示点：选中为实心强调色，未选为细圈。"""

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        super().__init__(**kwargs)
        self.selected = False
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def set_selected(self, v):
        self.selected = v
        self._draw()

    def _draw(self, *_):
        self.canvas.clear()
        d = min(self.width, self.height)
        if d <= 0:
            return
        x, y = self.center_x - d / 2, self.center_y - d / 2
        with self.canvas:
            if self.selected:
                Color(*PRIMARY)
                Ellipse(pos=(x, y), size=(d, d))
                Color(*BG)
                Ellipse(pos=(x + d * 0.3, y + d * 0.3), size=(d * 0.4, d * 0.4))
            else:
                Color(1, 1, 1, 0.18)
                Line(circle=(self.center_x, self.center_y, d / 2 - 1), width=1.2)


class GoalCard(ButtonBehavior, CardBox):
    """训练目的卡片：标题 + 副标题 + 右侧指示点。高度跟随内容。"""

    def __init__(self, title, desc, **kwargs):
        super().__init__(orientation='horizontal', size_hint_y=None, **kwargs)
        self.bind(minimum_height=self.setter('height'))
        col = BoxLayout(orientation='vertical', size_hint_y=None)
        col.bind(minimum_height=col.setter('height'))
        self.title_lbl = auto_label(title, fs(17), TEXT)
        self.desc_lbl = auto_label(desc, fs(12), TEXT_SEC)
        col.add_widget(self.title_lbl)
        col.add_widget(self.desc_lbl)
        self.dot = _Dot()
        dot_holder = BoxLayout(orientation='vertical', size_hint_x=None)
        dot_holder.add_widget(Widget())
        dot_holder.add_widget(self.dot)
        dot_holder.add_widget(Widget())
        self._col = col
        self._dot_holder = dot_holder
        self.add_widget(col)
        self.add_widget(dot_holder)
        self.selected = False
        self.set_selected(False)
        self.apply_metrics()

    def apply_metrics(self):
        self.padding = [hs(20), hs(16), hs(18), hs(16)]
        self.spacing = hs(12)
        self.radius = hs(22)
        self._col.spacing = hs(4)
        self.title_lbl.font_size = fs(17)
        self.desc_lbl.font_size = fs(12)
        self.dot.size = (hs(18), hs(18))
        self._dot_holder.width = hs(18)

    def set_selected(self, v):
        self.selected = v
        self.border_color = list(with_alpha(PRIMARY, 0.7)) if v else list(BORDER)
        self.dot.set_selected(v)
        self._apply_bg()

    def _apply_bg(self):
        if self.state == 'down':
            self.bg_color = list(with_alpha(PRIMARY, 0.22))
        else:
            self.bg_color = list(ACCENT_SOFT) if self.selected else list(SURFACE)

    def on_state(self, *_):
        self._apply_bg()


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_duration = None
        self.selected_goal = None
        self.mode_choice = AUTO       # 语音引导：自动 / 详细引导 / 简短提示
        self.plan = None
        self._mode_btns = {}
        self._build_ui()
        Window.bind(on_resize=self._on_resize)

    def on_pre_enter(self, *args):
        # 从训练页回来后训练记录可能已更新，重新生成方案
        self._update_start_btn()

    def _on_resize(self, *_):
        self._apply_metrics()
        self._render_plan()

    # ------------------------------------------------------------ 构建

    def _build_ui(self):
        self._section_labels = []
        self._gaps = []
        self.root_box = BoxLayout(orientation='vertical')
        root = self.root_box

        # Hero：不放卡片，直接大标题
        self.title_lbl = auto_label('地铁健身', fs(32), TEXT)
        self.subtitle_lbl = auto_label('碎片时间  ·  高效训练  ·  随时随地', fs(13), TEXT_SEC)
        root.add_widget(self.title_lbl)
        root.add_widget(self.subtitle_lbl)
        root.add_widget(self._gap(8))

        # 时长
        root.add_widget(self._section_label('训练时长'))
        self.duration_layout = BoxLayout(orientation='horizontal', size_hint_y=None)
        self._build_duration_buttons()
        root.add_widget(self.duration_layout)
        root.add_widget(self._gap(6))

        # 目的
        root.add_widget(self._section_label('训练目的'))
        self.goal_layout = BoxLayout(orientation='vertical', size_hint_y=None)
        self.goal_layout.bind(minimum_height=self.goal_layout.setter('height'))
        self._build_goal_cards()
        root.add_widget(self.goal_layout)
        root.add_widget(self._gap(6))

        # 本次方案
        self.plan_card = CardBox(orientation='vertical', size_hint_y=None)
        self.plan_card.bind(minimum_height=self.plan_card.setter('height'))
        self._build_mode_row()
        root.add_widget(self.plan_card)

        # 填充，把开始按钮推到底
        root.add_widget(Widget())

        self.start_btn = RoundedButton(text='开始训练', font_size=fs(17), bold=True,
                                       size_hint_y=None)
        self.start_btn.bind(on_press=self._start_workout)
        root.add_widget(self.start_btn)

        self.add_widget(root)
        self._apply_metrics()
        self._render_plan()
        self._style_start_btn(False)

    def _build_mode_row(self):
        """语音引导三段切换，只建一次，_render_plan 时挂到方案卡片里。"""
        self.mode_row = BoxLayout(orientation='horizontal', size_hint_y=None)
        # 固定宽度标签：尺寸只跟随文字纹理，不反过来影响排版（避免 texture/layout 互相触发）
        self.mode_lbl = Label(text='语音引导', font_size=fs(12), color=TEXT_SEC, size_hint=(None, None),
                              pos_hint={'center_y': 0.5})
        self.mode_lbl.bind(texture_size=lambda w, ts: setattr(w, 'size', (ts[0] + hs(10), ts[1])))
        self.mode_row.add_widget(self.mode_lbl)
        self._mode_btns = {}
        for mode in (AUTO, DETAILED, SHORT):
            btn = RoundedButton(text=MODE_LABEL[mode], font_size=fs(12))
            btn.bind(on_press=lambda b, m=mode: self._select_mode(m))
            self.mode_row.add_widget(btn)
            self._mode_btns[mode] = btn
        self.mode_hint = auto_label('', fs(11), TEXT_TER)
        self._style_mode_buttons()

    def _gap(self, h):
        w = Widget(size_hint_y=None, height=hs(h))
        self._gaps.append((w, h))
        return w

    def _apply_metrics(self):
        """所有与尺寸相关的数值集中在这里，窗口尺寸变化时整体重算。"""
        self.root_box.padding = [hs(22), hs(44), hs(22), hs(24)]
        self.root_box.spacing = hs(14)
        self.title_lbl.font_size = fs(32)
        self.subtitle_lbl.font_size = fs(13)
        for lbl in self._section_labels:
            lbl.font_size = fs(12)
        for w, h in self._gaps:
            w.height = hs(h)
        self.duration_layout.height = hs(44)
        self.duration_layout.spacing = hs(8)
        for btn in self._dur_btns.values():
            btn.font_size = fs(13)
            btn.radius = hs(14)
        self.goal_layout.spacing = hs(10)
        for card in self._goal_cards.values():
            card.apply_metrics()
        self.plan_card.padding = [hs(20), hs(16), hs(20), hs(16)]
        self.plan_card.spacing = hs(10)
        self.plan_card.radius = hs(22)
        self.mode_row.height = hs(34)
        self.mode_row.spacing = hs(6)
        self.mode_lbl.font_size = fs(12)
        for btn in self._mode_btns.values():
            btn.font_size = fs(12)
            btn.radius = hs(11)
        self.mode_hint.font_size = fs(11)
        self.start_btn.font_size = fs(17)
        self.start_btn.height = hs(56)
        self.start_btn.radius = hs(18)

    def _section_label(self, text):
        lbl = auto_label(text, fs(12), TEXT_SEC)
        self._section_labels.append(lbl)
        return lbl

    def _build_duration_buttons(self):
        self.duration_layout.clear_widgets()
        self._dur_btns = {}
        for d in get_durations():
            btn = RoundedButton(text=f'{d} min', font_size=fs(13))
            btn.bind(on_press=lambda b, dur=d: self._select_duration(dur))
            self.duration_layout.add_widget(btn)
            self._dur_btns[d] = btn
        self._style_duration_buttons()

    def _style_duration_buttons(self):
        for d, btn in self._dur_btns.items():
            if d == self.selected_duration:
                btn.bg_color = list(PRIMARY)
                btn.border_color = [0, 0, 0, 0]
                btn.color = (0.03, 0.04, 0.08, 1)
                btn.bold = True
            else:
                btn.bg_color = list(SURFACE)
                btn.border_color = list(BORDER)
                btn.color = TEXT_SEC
                btn.bold = False

    def _build_goal_cards(self):
        self.goal_layout.clear_widgets()
        self._goal_cards = {}
        for goal in get_goals(self.selected_duration):
            card = GoalCard(goal, _GOAL_DESC.get(goal, ''))
            card.bind(on_release=lambda c, g=goal: self._select_goal(g))
            self.goal_layout.add_widget(card)
            self._goal_cards[goal] = card

    # ------------------------------------------------------------ 交互

    def _select_duration(self, duration):
        self.selected_duration = duration
        self._style_duration_buttons()
        self._update_start_btn()

    def _select_goal(self, goal):
        self.selected_goal = goal
        for g, card in self._goal_cards.items():
            card.set_selected(g == goal)
        self._update_start_btn()

    def _select_mode(self, mode):
        if mode == self.mode_choice:
            return
        self.mode_choice = mode
        self._style_mode_buttons()
        if self.plan is None:
            return
        self.plan = build_plan(self.selected_duration, self.selected_goal,
                               history.last_trained(), history.completed_counts(), mode)
        self.mode_hint.text = self._mode_hint_text()

    def _update_start_btn(self):
        ready = self.selected_duration is not None and self.selected_goal is not None
        if ready:
            self.plan = build_plan(self.selected_duration, self.selected_goal,
                                   history.last_trained(), history.completed_counts(),
                                   self.mode_choice)
        else:
            self.plan = None
        self._render_plan()
        self._style_start_btn(ready)

    def _style_start_btn(self, ready):
        self.start_btn.disabled = not ready
        if ready:
            self.start_btn.gradient = (PRIMARY_2, PRIMARY)
            self.start_btn.border_color = [0, 0, 0, 0]
            self.start_btn.color = (1, 1, 1, 1)
        else:
            self.start_btn.gradient = None
            self.start_btn.bg_color = list(DISABLED)
            self.start_btn.border_color = list(BORDER)
            self.start_btn.color = TEXT_TER

    def _render_plan(self):
        """把当前方案画到"本次方案"卡片里；未选齐时显示引导。"""
        card = self.plan_card
        card.clear_widgets()
        plan = self.plan
        if plan is None:
            hint = '选好时长和目的，这里会显示本次训练方案' if self.selected_duration is None \
                else '再选一个训练目的'
            card.add_widget(auto_label(hint, fs(13), TEXT_TER))
            return

        head = BoxLayout(orientation='horizontal', size_hint_y=None)
        head.bind(minimum_height=head.setter('height'))
        head.add_widget(auto_label('本次方案', fs(12), TEXT_SEC))
        head.add_widget(auto_label(f'约 {plan.minutes} 分钟', fs(12), PRIMARY, halign='right'))
        card.add_widget(head)

        chips = StackLayout(orientation='lr-tb', size_hint_y=None, spacing=(hs(8), hs(6)))
        chips.bind(minimum_height=chips.setter('height'))
        for name, count in plan.parts:
            text = name if count <= 1 else f'{name} ×{count}'
            chips.add_widget(Chip(text=text, font_size=fs(13), color=PRIMARY,
                                  bg_color=list(ACCENT_SOFT), pad_x=hs(12), pad_y=hs(5)))
        card.add_widget(chips)

        if plan.goal == '呼吸训练':
            detail = f'{plan.parts[0][1]} 组呼吸循环  ·  含热身与放松'
        else:
            detail = f'{plan.total_sets} 组动作  ·  优先安排最久未练的部位'
        card.add_widget(auto_label(detail, fs(12), TEXT_SEC))

        # 语音引导模式：三段切换，训练中不再需要任何操作
        for w in (self.mode_row, self.mode_hint):
            if w.parent is not None:
                w.parent.remove_widget(w)
        self.mode_hint.text = self._mode_hint_text()
        card.add_widget(self.mode_row)
        card.add_widget(self.mode_hint)

    def _mode_hint_text(self):
        plan = self.plan
        if plan.mode_choice == AUTO:
            return f'本次：{plan.mode_label}  ·  同一部位练满 {FAMILIAR_AFTER} 次后自动改为简短提示'
        if plan.mode_choice == DETAILED:
            return '每个动作开始前先听完整讲解，再开始计时；讲解时间已计入'
        return '动作前只报名称和一句要点，不播讲解'

    def _style_mode_buttons(self):
        for mode, btn in self._mode_btns.items():
            if mode == self.mode_choice:
                btn.bg_color = list(ACCENT_SOFT)
                btn.border_color = list(with_alpha(PRIMARY, 0.7))
                btn.color = PRIMARY
                btn.bold = True
            else:
                btn.bg_color = list(SURFACE)
                btn.border_color = list(BORDER)
                btn.color = TEXT_SEC
                btn.bold = False

    def _start_workout(self, *args):
        if self.start_btn.disabled or self.plan is None:
            return
        workout_screen = self.manager.get_screen('workout')
        workout_screen.load(self.plan)
        self.manager.current = 'workout'
