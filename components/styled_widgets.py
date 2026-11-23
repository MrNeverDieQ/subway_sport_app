from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Line
from kivy.metrics import dp
from kivy.properties import (
    ListProperty, NumericProperty, StringProperty, BooleanProperty, ObjectProperty,
)

from components.theme import SURFACE, SURFACE2, TEXT, BORDER, TRACK, gradient_texture


class RoundedButton(ButtonBehavior, Label):
    """
    圆角按钮。
      bg_color      填充色
      border_color  描边色，alpha 为 0 时不画描边
      gradient      (c_bottom, c_top) 两色渐变，设置后覆盖 bg_color 的填充
    """
    bg_color = ListProperty(list(SURFACE2))
    border_color = ListProperty(list(BORDER))
    gradient = ObjectProperty(None, allownone=True)
    radius = NumericProperty(18)
    disabled = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if 'color' not in kwargs:
            self.color = TEXT
        self._bg_color_instr = None
        self._bg_rect = None
        self._border_color_instr = None
        self._border_line = None
        self.bind(pos=self._update_canvas, size=self._update_canvas,
                  bg_color=self._update_canvas, radius=self._update_canvas,
                  border_color=self._update_canvas, gradient=self._redraw,
                  state=self._on_state)
        self._redraw()

    def _redraw(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            self._bg_color_instr = Color(1, 1, 1, 1) if self.gradient else Color(*self.bg_color)
            tex = gradient_texture(*self.gradient) if self.gradient else None
            self._bg_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[self.radius], texture=tex)
            self._border_color_instr = Color(*self.border_color)
            self._border_line = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius),
                width=1)
        self._update_canvas()

    def _fill_rgba(self):
        """当前应显示的填充色：按下时压暗；渐变模式下用白色乘纹理。"""
        pressed = self.state == 'down' and not self.disabled
        if self.gradient:
            return (0.8, 0.8, 0.8, 1) if pressed else (1, 1, 1, 1)
        r, g, b, a = self.bg_color
        return (r * 0.72, g * 0.72, b * 0.72, a) if pressed else (r, g, b, a)

    def _on_state(self, *_):
        if self._bg_color_instr:
            self._bg_color_instr.rgba = self._fill_rgba()

    def _update_canvas(self, *_):
        if not self._bg_rect:
            return
        self._bg_color_instr.rgba = self._fill_rgba()
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [self.radius]
        self._border_color_instr.rgba = self.border_color
        self._border_line.rounded_rectangle = (
            self.x + 0.5, self.y + 0.5, max(self.width - 1, 1), max(self.height - 1, 1), self.radius)

    def on_touch_down(self, touch):
        if self.disabled and self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)


class CardBox(BoxLayout):
    """圆角卡片。border_color alpha 为 0 时无描边。"""
    bg_color = ListProperty(list(SURFACE))
    border_color = ListProperty(list(BORDER))
    radius = NumericProperty(22)

    def __init__(self, **kwargs):
        kwargs.setdefault('padding', [20, 16, 20, 16])
        kwargs.setdefault('spacing', 10)
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            self._border_color_instr = Color(*self.border_color)
            self._border_line = Line(
                rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius), width=1)
        self.bind(pos=self._update_canvas, size=self._update_canvas,
                  bg_color=self._update_canvas, border_color=self._update_canvas,
                  radius=self._update_canvas)

    def _update_canvas(self, *_):
        self._bg_color_instr.rgba = self.bg_color
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [self.radius]
        self._border_color_instr.rgba = self.border_color
        self._border_line.rounded_rectangle = (
            self.x + 0.5, self.y + 0.5, max(self.width - 1, 1), max(self.height - 1, 1), self.radius)


class Chip(Label):
    """小药丸标签：淡色底 + 同色系文字。宽高都随文字自适应。"""
    bg_color = ListProperty([1, 1, 1, 0.08])
    radius = NumericProperty(999)
    pad_x = NumericProperty(dp(12))
    pad_y = NumericProperty(dp(5))

    def __init__(self, **kwargs):
        kwargs.setdefault('size_hint', (None, None))
        kwargs.pop('height', None)
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
        self.bind(pos=self._update, size=self._update, bg_color=self._update,
                  texture_size=self._fit, pad_x=self._fit, pad_y=self._fit)
        self._fit()
        self._update()

    def _fit(self, *_):
        tw, th = self.texture_size
        self.size = (tw + self.pad_x * 2, max(th, 12) + self.pad_y * 2)

    def _update(self, *_):
        self._bg_color_instr.rgba = self.bg_color
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        self._bg_rect.radius = [min(self.radius, self.height / 2)]


class ProgressStrip(Widget):
    progress = NumericProperty(0.0)
    bar_color = ListProperty([0.38, 0.62, 1.0, 1])
    track_color = ListProperty(list(TRACK))
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
    """
    环形进度 + 居中大数字 + 数字下方的小字（sub_text）。
    字号随直径缩放，适合做屏幕中央的大倒计时。
    """
    progress = NumericProperty(1.0)
    text = StringProperty('')
    sub_text = StringProperty('')
    arc_color = ListProperty([1.0, 0.78, 0.20, 1])
    track_color = ListProperty(list(TRACK))
    line_width = NumericProperty(6)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._label = Label(text=self.text, bold=True, color=TEXT,
                            halign='center', valign='middle')
        self._sub = Label(text=self.sub_text, color=(0.56, 0.58, 0.64, 1),
                          halign='center', valign='middle')
        self.add_widget(self._label)
        self.add_widget(self._sub)
        self.bind(pos=self._redraw, size=self._redraw,
                  progress=self._redraw, arc_color=self._redraw,
                  track_color=self._redraw, line_width=self._redraw,
                  text=self._on_text, sub_text=self._on_sub)
        self._redraw()

    def _on_text(self, *_):
        self._label.text = self.text
        self._layout_labels()

    def _on_sub(self, *_):
        self._sub.text = self.sub_text
        self._layout_labels()

    def _layout_labels(self):
        d = min(self.width, self.height)
        if d <= 0:
            return
        n = len(self.text)
        big = d * (0.34 if n <= 2 else 0.22 if n <= 4 else 0.14)
        self._label.font_size = max(big, 12)
        self._sub.font_size = max(d * 0.075, 10)
        has_sub = bool(self.sub_text)
        self._label.size = (d, d * 0.5)
        self._label.text_size = self._label.size
        self._label.center_x = self.center_x
        self._label.center_y = self.center_y + (d * 0.05 if has_sub else 0)
        self._sub.size = (d, d * 0.2)
        self._sub.text_size = self._sub.size
        self._sub.center_x = self.center_x
        self._sub.center_y = self.center_y - d * 0.21

    def _redraw(self, *_):
        self.canvas.before.clear()
        cx, cy = self.center_x, self.center_y
        diameter = min(self.width, self.height)
        self._layout_labels()
        r = diameter / 2 - self.line_width
        if r < 10:
            return
        with self.canvas.before:
            Color(*self.track_color)
            Line(ellipse=(cx - r, cy - r, r * 2, r * 2, 0, 360),
                 width=self.line_width, cap='none')
            if self.progress > 0:
                Color(*self.arc_color)
                Line(ellipse=(cx - r, cy - r, r * 2, r * 2, 0, self.progress * 360),
                     width=self.line_width, cap='round')
