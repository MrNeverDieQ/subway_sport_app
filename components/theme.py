from kivy.core.window import Window
from kivy.metrics import dp

# ---------- 配色：深色、低饱和表面 + 单一强调色 ----------
BG        = (0.04, 0.04, 0.06, 1)       # 近 OLED 黑
SURFACE   = (0.09, 0.09, 0.12, 1)       # 卡片底色
SURFACE2  = (0.13, 0.13, 0.17, 1)       # 次级卡片 / 按钮默认
SURFACE3  = (0.18, 0.18, 0.23, 1)       # 按下态 / 轨道
PRIMARY   = (0.38, 0.62, 1.00, 1)       # 冰蓝，强调色
PRIMARY_2 = (0.26, 0.42, 0.98, 1)       # 强调色渐变深端
ACCENT    = PRIMARY
ACCENT_SOFT = (0.38, 0.62, 1.00, 0.14)  # 选中态底色（强调色低透明）
WARNING   = (1.00, 0.78, 0.20, 1)       # 琥珀黄，计时环
REST_BLUE = (0.45, 0.72, 1.00, 1)       # 休息态浅蓝
REST_SOFT = (0.45, 0.72, 1.00, 0.14)
SUCCESS   = (0.36, 0.84, 0.60, 1)       # 完成态绿
TEXT      = (0.96, 0.96, 0.98, 1)       # 主文字
TEXT_SEC  = (0.56, 0.58, 0.64, 1)       # 次要文字
TEXT_TER  = (0.38, 0.40, 0.46, 1)       # 三级文字 / 占位
DANGER    = (0.95, 0.40, 0.40, 1)       # 退出
DISABLED  = (0.14, 0.14, 0.18, 1)       # 禁用按钮
BORDER    = (1.00, 1.00, 1.00, 0.06)    # 极淡描边
TRACK     = (0.14, 0.14, 0.18, 1)       # 进度轨道

# ---------- 尺寸 ----------
# 规则：字号用 sp，长度用 dp，两者都再乘同一个随窗口变化的系数 k，
# 设计基准是 360x780dp 的手机竖屏（k=1）。k 同时受宽和高约束、取较小值，
# 所以窗口变宽但不够高（横屏、桌面最大化）时不会把内容挤出屏幕。
_REF_WIDTH_DP = 360
_REF_HEIGHT_DP = 780


def _k():
    kw = Window.width / dp(_REF_WIDTH_DP)
    kh = Window.height / dp(_REF_HEIGHT_DP)
    return max(0.8, min(1.6, kw, kh))


def fs(base):
    """字号：返回 Kivy 可识别的 sp 字符串。"""
    return f'{base * _k():.1f}sp'


def hs(base):
    """长度（高度 / 内边距 / 间距 / 圆角）：与 fs 同步缩放的像素值。"""
    return dp(base * _k())


def with_alpha(color, alpha):
    r, g, b = color[:3]
    return (r, g, b, alpha)


_gradient_cache = {}


def gradient_texture(c1, c2, steps=64):
    """竖向线性渐变纹理（底部 c1 → 顶部 c2），用于按钮等需要一点层次的地方。"""
    key = (tuple(c1), tuple(c2), steps)
    if key in _gradient_cache:
        return _gradient_cache[key]
    from kivy.graphics.texture import Texture
    tex = Texture.create(size=(1, steps), colorfmt='rgba')
    buf = bytearray()
    for i in range(steps):
        t = i / (steps - 1)
        for a, b in zip(c1, c2):
            buf.append(int(round((a + (b - a) * t) * 255)))
    tex.blit_buffer(bytes(buf), colorfmt='rgba', bufferfmt='ubyte')
    tex.wrap = 'clamp_to_edge'
    _gradient_cache[key] = tex
    return tex
