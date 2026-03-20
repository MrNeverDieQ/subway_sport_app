from kivy.core.window import Window
from kivy.metrics import dp

BG        = (0.04, 0.04, 0.06, 1)       # 近 OLED 黑
SURFACE   = (0.10, 0.10, 0.14, 1)       # 卡片底色，比背景亮一档
SURFACE2  = (0.15, 0.15, 0.20, 1)       # 次级卡片 / 按钮默认
PRIMARY   = (0.38, 0.62, 1.00, 1)       # 冰蓝，选中态
ACCENT    = (0.38, 0.62, 1.00, 1)       # 与 PRIMARY 统一
WARNING   = (1.00, 0.78, 0.20, 1)       # 琥珀黄，计时环
REST_BLUE = (0.45, 0.72, 1.00, 1)       # 休息态浅蓝
TEXT      = (0.96, 0.96, 0.98, 1)       # 主文字，近纯白
TEXT_SEC  = (0.50, 0.52, 0.58, 1)       # 次要文字，冷灰
DANGER    = (0.90, 0.32, 0.32, 1)       # 退出/危险
DISABLED  = (0.18, 0.18, 0.22, 1)       # 禁用按钮
BORDER    = (0.22, 0.22, 0.28, 1)       # 卡片描边


def fs(base):
    """返回 sp 字号字符串，适配不同 DPI 和用户字体偏好。"""
    return f'{base}sp'


def adaptive_fs(text, base, container_width=None):
    """根据文字长度动态缩小字号，防止溢出。
    仅在文字确实很长时才温和缩小。
    """
    length = len(text) if text else 0
    if length > 30:
        base = int(base * 0.75)
    elif length > 20:
        base = int(base * 0.85)
    return fs(base)


# 全局 app 根目录，由 main.py 启动时设置
APP_ROOT = None
