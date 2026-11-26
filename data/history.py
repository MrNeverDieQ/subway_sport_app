# ============================================================
# history.py - 训练记录
#   blocks: {训练块名: 上次训练时间戳}   用于轮换推荐
#   counts: {训练块名: 完成次数}         用于自动选择语音引导模式
#
# 纯 json 读写（不用 Kivy JsonStore）：Android 前台服务进程里没有 Kivy App，训练完成时由它来记录。
# 文件格式沿用 JsonStore 的 {"history": {"blocks": ..., "counts": ...}}，老记录可直接读。
# 位置：set_path() 指定 > 运行中的 Kivy App 的 user_data_dir > $ANDROID_PRIVATE（服务进程）
# ============================================================

import json
import os
import sys
import time

_path_override = None


def set_path(path):
    """测试或特殊场景下指定记录文件。"""
    global _path_override
    _path_override = path


def _path():
    if _path_override:
        return _path_override
    base = None
    app_mod = sys.modules.get('kivy.app')          # 不主动 import kivy：服务进程里没有也不需要
    if app_mod is not None:
        app = app_mod.App.get_running_app()
        if app is not None:
            base = app.user_data_dir
    if not base:
        base = os.environ.get('ANDROID_PRIVATE')
    if not base:
        return None
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'history.json')


def _read():
    """返回 (blocks, counts)；读取失败返回 None（和"没有记录"区分开，避免覆盖）。"""
    try:
        path = _path()
        if path is None:
            return None
        if not os.path.isfile(path):
            return {}, {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except ValueError:
            # 文件损坏：挪走重建，不让训练记录功能永久失效
            try:
                os.replace(path, path + '.corrupt')
            except OSError:
                pass
            return {}, {}
        h = data.get('history', {}) if isinstance(data, dict) else {}
        return dict(h.get('blocks', {})), dict(h.get('counts', {}))
    except Exception:
        return None


def _write(blocks, counts):
    path = _path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'history': {'blocks': blocks, 'counts': counts}}, f, ensure_ascii=False)
    os.replace(tmp, path)


def last_trained():
    """返回 {训练块名: 上次训练的时间戳}。"""
    data = _read()
    return data[0] if data else {}


def completed_counts():
    """返回 {训练块名: 完成次数}。"""
    data = _read()
    return data[1] if data else {}


def record(block_names):
    """把这些训练块标记为"刚练过"，完成次数 +1。失败静默，不影响训练流程。"""
    try:
        data = _read()
        if data is None:
            return          # 读不到就不写，免得把已有记录冲掉
        blocks, counts = data
        now = time.time()
        for name in block_names:
            blocks[name] = now
            counts[name] = counts.get(name, 0) + 1
        _write(blocks, counts)
    except Exception:
        pass
