# ============================================================
# main.py - 应用入口
# ============================================================

import os
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, FadeTransition
from kivy.core.window import Window
from kivy.core.text import LabelBase
from components.theme import BG
from screens.home_screen import HomeScreen
from screens.workout_screen import WorkoutScreen

FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'NotoSansSC-Regular.otf')
LabelBase.register(name='Roboto', fn_regular=FONT_PATH)

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
