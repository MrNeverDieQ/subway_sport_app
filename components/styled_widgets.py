from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.properties import (
    ListProperty, NumericProperty, StringProperty, BooleanProperty,
)

from components.theme import SURFACE, SURFACE2, TEXT, BORDER


class RoundedButton(ButtonBehavior, Label):
    bg_color = ListProperty(list(SURFACE2))
    radius = NumericProperty(18)
    disabled = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.color = TEXT
        self.bold = True
        self._bg_color_instr = None
        self._bg_rect = None
        self._border_color_instr = None
        self._border_rect = None
        self.bind(pos=self._update_canvas, size=self._update_canvas,
                  bg_color=self._update_canvas, radius=self._update_canvas)
        self._draw()

    def _draw(self):
        self.canvas.before.clear()
        with self.canvas.before:
            # 描边
            self._border_color_instr = Color(*BORDER)
            self._border_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius])
            # 填充（内缩 1px 模拟描边）
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = RoundedRectangle(
                pos=(self.x + 1, self.y + 1),
                size=(self.width - 2, self.height - 2),
                radius=[max(self.radius - 1, 0)])

    def _update_canvas(self, *_):
        if self._bg_color_instr:
            self._bg_color_instr.rgba = self.bg_color
        if self._bg_rect:
            self._bg_rect.pos = (self.x + 1, self.y + 1)
            self._bg_rect.size = (self.width - 2, self.height - 2)
            self._bg_rect.radius = [max(self.radius - 1, 0)]
        if self._border_rect:
            self._border_rect.pos = self.pos
            self._border_rect.size = self.size
            self._border_rect.radius = [self.radius]

    def on_press(self):
        if self.disabled:
            return
        r, g, b, a = self.bg_color
        self._bg_color_instr.rgba = (r * 0.72, g * 0.72, b * 0.72, a)

    def on_release(self):
        if self._bg_color_instr:
            self._bg_color_instr.rgba = self.bg_color

    def on_touch_down(self, touch):
        if self.disabled and self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)


class CardBox(BoxLayout):
    bg_color = ListProperty(list(SURFACE))
    radius = NumericProperty(20)

    def __init__(self, **kwargs):
        kwargs.setdefault('padding', [20, 16, 20, 16])
        kwargs.setdefault('spacing', 10)
        super().__init__(**kwargs)
        self._border_color_instr = None
        self._border_rect = None
        self._bg_color_instr = None
        self._bg_rect = None
        self.bind(pos=self._update_canvas, size=self._update_canvas,
                  bg_color=self._update_canvas)
        self._draw()

    def _draw(self):
        self.canvas.before.clear()
        with self.canvas.before:
            self._border_color_instr = Color(*BORDER)
            self._border_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius])
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = RoundedRectangle(
                pos=(self.x + 1, self.y + 1),
                size=(self.width - 2, self.height - 2),
                radius=[max(self.radius - 1, 0)])

    def _update_canvas(self, *_):
        if self._border_rect:
            self._border_rect.pos = self.pos
            self._border_rect.size = self.size
            self._border_rect.radius = [self.radius]
        if self._bg_color_instr:
            self._bg_color_instr.rgba = self.bg_color
        if self._bg_rect:
            self._bg_rect.pos = (self.x + 1, self.y + 1)
            self._bg_rect.size = (self.width - 2, self.height - 2)
            self._bg_rect.radius = [max(self.radius - 1, 0)]


class ProgressStrip(Widget):
    progress = NumericProperty(0.0)
    bar_color = ListProperty([0.38, 0.62, 1.0, 1])
    track_color = ListProperty(list(SURFACE2))
    radius = NumericProperty(4)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            self._track_color_instr = Color(*self.track_color)
            self._track_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius])
            self._bar_color_instr = Color(*self.bar_color)
            self._bar_rect = RoundedRectangle(
                pos=self.pos, size=(0, self.height), radius=[self.radius])
        self.bind(pos=self._update, size=self._update,
                  progress=self._update, bar_color=self._update)

    def _update(self, *_):
        p = max(0.0, min(1.0, self.progress))
        bar_w = self.width * p
        self._track_rect.pos = self.pos
        self._track_rect.size = self.size
        self._track_rect.radius = [self.radius]
        self._bar_rect.pos = self.pos
        self._bar_rect.size = (bar_w, self.height)
        self._bar_rect.radius = [self.radius]
        self._bar_color_instr.rgba = self.bar_color


class CircularProgress(Widget):
    progress = NumericProperty(1.0)
    text = StringProperty('')
    arc_color = ListProperty([1.0, 0.78, 0.20, 1])
    track_color = ListProperty([0.14, 0.14, 0.18, 1])
    line_width = NumericProperty(5)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._label = Label(
 
             text=self.text, font_size='32sp', bold=True,
            color=TEXT, halign='center', valign='middle',
        )
        self.add_widget(self._label)
        self.bind(pos=self._redraw, size=self._redraw,
                  progress=self._redraw, arc_color=self._redraw,
                  text=self._on_text)
        self._redraw()

    def _on_text(self, *_):
        self._label.text = self.text
        self._label.font_size = '32sp' if len(self.text) <= 2 else '22sp'

    def _redraw(self, *_):
        self.canvas.before.clear()
        cx, cy = self.center_x, self.center_y
        diameter = min(self.width, self.height)
        r = diameter / 2 - self.line_width
        if r < 10:
            return

        self._label.center = (cx, cy)
        self._label.size = self.size
        self._label.text_size = self.size

        with self.canvas.before:
            Color(*self.track_color)
            Line(ellipse=(cx - r, cy - r, r * 2, r * 2, 0, 360),
                 width=self.line_width, cap='none')
            if self.progress > 0:
                Color(*self.arc_color)
                Line(ellipse=(cx - r, cy - r, r * 2, r * 2, 0, self.progress * 360),
                     width=self.line_width, cap='round')
