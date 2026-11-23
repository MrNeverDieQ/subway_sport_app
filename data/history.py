# ============================================================
# history.py - 训练记录
#   blocks: {训练块名: 上次训练时间戳}   用于轮换推荐
#   counts: {训练块名: 完成次数}         用于自动选择语音引导模式
# ============================================================

import os
import time

_store = None


def _get_store():
    """App 运行中才有可写的 user_data_dir；拿不到就返回 None，调用方按无记录处理。"""
    global _store
    if _store is not None:
        return _store
    from kivy.app import App
    from kivy.logger import Logger
    from kivy.storage.jsonstore import JsonStore
    app = App.get_running_app()
    if app is None:
        return None
    base = app.user_data_dir
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, 'history.json')
    try:
        _store = JsonStore(path)
    except Exception as e:  # 文件损坏：挪走重建，不让训练记录功能永久失效
        Logger.warning('history: history.json 无法读取（%s），已重建', e)
        try:
            os.replace(path, path + '.corrupt')
        except OSError:
            pass
        _store = JsonStore(path)
    return _store


def _read():
    """返回 (blocks, counts)；读取失败返回 None（和"没有记录"区分开，避免覆盖）。"""
    try:
        store = _get_store()
        if store is None:
            return None
        if store.exists('history'):
            data = store.get('history')
            return dict(data.get('blocks', {})), dict(data.get('counts', {}))
        return {}, {}
    except Exception:
        return None


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
        _get_store().put('history', blocks=blocks, counts=counts)
    except Exception:
        pass
