# ============================================================
# main.py - 应用入口
# ============================================================

import os

# 桌面上用 SDL2 播放语音。ffpyplayer 在 Windows 上连续 stop/unload 后立刻再 load 会原生崩溃（access violation），
# 而训练中每段开头都要切语音；Android 用系统 MediaPlayer，不受影响。
# kivy 包导入时就会读取 KIVY_* 环境变量，所以必须放在任何 kivy 导入之前；用 p4a 的 ANDROID_ARGUMENT 判断平台。
if 'ANDROID_ARGUMENT' not in os.environ:
    os.environ.setdefault('KIVY_AUDIO', 'sdl2')

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.utils import platform
from components.theme import BG
from screens.home_screen import HomeScreen
from screens.workout_screen import WorkoutScreen

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'NotoSansSC-Regular.otf')
LabelBase.register(name='Roboto', fn_regular=FONT_PATH)

# 桌面预览用手机比例窗口；所有尺寸都按 dp 和窗口宽度相对计算，任何 DPI 缩放下布局一致
if platform not in ('android', 'ios'):
    Window.size = (390, 844)
Window.clearcolor = BG


class SubwaySportApp(App):
    def build(self):
        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(HomeScreen(name='home'))
        sm.add_widget(WorkoutScreen(name='workout'))
        return sm


if __name__ == '__main__':
    SubwaySportApp().run()
