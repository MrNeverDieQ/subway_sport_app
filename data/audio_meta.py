# ============================================================
# audio_meta.py - 音频文件的路径规则与时长表
#
# 路径规则（相对 audio/ 目录）：
#   neck/右侧集群.mp3      动作完整讲解，training_blocks 里的 audio 字段
#   neck/右侧集群_短.mp3   动作简短提示（熟手模式用），由 audio 字段自动推导
#   sys/开始.mp3           公共短句：开始 / 休息 / 下一个 / 第2组…第N组 / 最后一组 / 训练完成
#
# 时长表 audio/durations.json 由 tools/audio_durations.py 生成，用于估算引导阶段长度。
# ============================================================

import json
import os

AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio')
_DURATIONS_FILE = os.path.join(AUDIO_DIR, 'durations.json')
_durations = None


def audio_path(rel):
    """相对路径 → 绝对路径。"""
    return os.path.join(AUDIO_DIR, *rel.split('/'))


def exists(rel):
    return bool(rel) and os.path.isfile(audio_path(rel))


def short_variant(rel):
    """neck/右侧集群.mp3 → neck/右侧集群_短.mp3"""
    stem, ext = os.path.splitext(rel)
    return f'{stem}_短{ext}'


def sys_clip(name):
    return f'sys/{name}.mp3'


def set_clip(set_no, total_sets):
    """第 set_no 组（1 开始）的播报短句名。"""
    return '最后一组' if set_no == total_sets else f'第{set_no}组'


def _load():
    global _durations
    if _durations is None:
        _durations = {}
        try:
            with open(_DURATIONS_FILE, encoding='utf-8') as f:
                raw = json.load(f)
            _durations = {k.replace('\\', '/'): float(v) for k, v in raw.items()}
        except (OSError, ValueError):
            pass
    return _durations


def duration(rel):
    """已知的音频时长（秒），没有记录返回 None。"""
    if not rel:
        return None
    return _load().get(rel.replace('\\', '/'))


def reload():
    global _durations
    _durations = None
