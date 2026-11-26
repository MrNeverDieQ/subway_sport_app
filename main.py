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

    # 训练中的计时和放音在 Android 上跑在前台服务进程里（见 screens/workout_session.py），
    # 这里只处理 UI 进程自身的前后台切换：锁屏期间 Kivy 主循环会被挂起，回来时让训练页立刻对齐状态。

    def on_start(self):
        if platform == 'android':
            _request_notification_permission()
            self._rejoin_running_workout()

    def on_pause(self):
        return True

    def on_resume(self):
        sm = self.root
        if sm.current == 'workout':
            sm.get_screen('workout').refresh()
        else:
            self._rejoin_running_workout()

    def _rejoin_running_workout(self):
        """UI 进程被杀或被用户划掉后再打开：前台服务还在跑就直接回到训练页。"""
        from screens.workout_session import find_running
        found = find_running()
        if not found:
            return
        plan, state = found
        sm = self.root
        sm.get_screen('workout').attach(plan, state)
        sm.current = 'workout'


def _request_notification_permission():
    """Android 13+ 前台服务的通知要用户授权才显示；拒绝也不影响服务本身运行。"""
    try:
        from android import api_version
        if api_version < 33:
            return
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.POST_NOTIFICATIONS])
    except Exception as e:
        from kivy.logger import Logger
        Logger.warning('App: 申请通知权限失败 %r', e)


if __name__ == '__main__':
    SubwaySportApp().run()
