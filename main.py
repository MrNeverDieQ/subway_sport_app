# ============================================================
# main.py - 应用入口
# ============================================================

import os
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.utils import platform
from components.theme import BG
import components.theme as theme

# 设置全局 app 根目录（Android 上 __file__ 不可靠，用 App.directory）
theme.APP_ROOT = os.path.dirname(os.path.abspath(__file__))

FONT_PATH = os.path.join(theme.APP_ROOT, 'fonts', 'NotoSansSC-Regular.otf')
LabelBase.register(name='Roboto', fn_regular=FONT_PATH)

if platform != 'android':
    Window.size = (390, 844)

Window.clearcolor = BG

from screens.home_screen import HomeScreen
from screens.workout_screen import WorkoutScreen


class SubwaySportApp(App):
    def build(self):
        # Android 上用 self.directory 获取解压后的资源目录
        theme.APP_ROOT = self.directory
        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(HomeScreen(name='home'))
        sm.add_widget(WorkoutScreen(name='workout'))
        return sm


if __name__ == '__main__':
    SubwaySportApp().run()
