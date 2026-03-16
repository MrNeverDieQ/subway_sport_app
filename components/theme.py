from kivy.core.window import Window

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

_REF_WIDTH = 360  # 设计基准宽度（px）


def fs(base):
    """根据当前窗口宽度缩放字号，返回 Kivy sp 字符串。"""
    scale = max(0.7, min(1.6, Window.width / _REF_WIDTH))
    return f'{int(base * scale)}sp'
