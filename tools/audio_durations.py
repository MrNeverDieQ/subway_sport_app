r"""
扫描 audio/ 下所有 mp3/wav，把时长写到 audio/durations.json。录完或改完音频后跑一次。
顺带做一次对照检查：动作缺 _短 短提示、短提示太长、sys/ 公共短句缺失。
详细引导模式下讲解在动作开始前整段播完，所以讲解长度没有上限，只是会计入训练时长。

    .venv\Scripts\python.exe tools\audio_durations.py

依赖 mutagen（只在电脑上用，App 不需要）：
    uv pip install --python .venv\Scripts\python.exe mutagen
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, 'audio')
OUT = os.path.join(AUDIO, 'durations.json')

try:
    from mutagen import File as MutagenFile
except ImportError:
    sys.exit('缺少 mutagen：uv pip install --python .venv\\Scripts\\python.exe mutagen')

result = {}
for dirpath, _, files in os.walk(AUDIO):
    for fn in sorted(files):
        if not fn.lower().endswith(('.mp3', '.wav', '.ogg')):
            continue
        path = os.path.join(dirpath, fn)
        rel = os.path.relpath(path, AUDIO).replace(os.sep, '/')
        try:
            info = MutagenFile(path)
            if info is not None and info.info.length > 0:
                result[rel] = round(info.info.length, 2)
            else:
                print(f'跳过（读不到时长）: {rel}')
        except Exception as e:  # noqa: BLE001
            print(f'跳过（{e}）: {rel}')

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f'写入 {len(result)} 条 → {os.path.relpath(OUT, ROOT)}')
for k, v in result.items():
    print(f'  {v:6.2f}s  {k}')

# ---------- 对照 training_blocks 检查 ----------
sys.path.insert(0, ROOT)
try:
    from data.training_blocks import TRAINING_BLOCKS
    from data import audio_meta
except ImportError as e:  # noqa: BLE001
    sys.exit(f'跳过对照检查：{e}')

from data.workouts import GUIDE_MIN_SECS

SHORT_MAX = GUIDE_MIN_SECS - 1.5   # "下一个"约 1 秒 + 间隔，短提示最长这么久才放得进最短的过渡
no_short, short_long, max_sets = [], [], 1
for name, block in TRAINING_BLOCKS.items():
    for e in block.get('warmup', []) + block['exercises'] + block.get('cooldown', []):
        max_sets = max(max_sets, e['sets'])
        a = e.get('audio')
        if not a:
            continue
        sv = audio_meta.short_variant(a)
        if sv not in result:
            no_short.append(sv)
        elif result[sv] > SHORT_MAX:
            short_long.append(f'{sv}  {result[sv]:.1f}s > {SHORT_MAX}s')
sys_needed = ['开始', '下一个', '训练完成', '最后一组'] + [f'第{i}组' for i in range(2, max_sets + 1)]
no_sys = [audio_meta.sys_clip(n) for n in sys_needed if audio_meta.sys_clip(n) not in result]

def report(title, items):
    print(f'\n{title}：{len(items)}')
    for it in items:
        print(f'  {it}')

report('缺少短提示 _短（简短模式和过渡时只会播"下一个"）', no_short)
report(f'短提示太长（过渡最短 {GUIDE_MIN_SECS} 秒，会被下一段切断）', short_long)
report('缺少公共短句 sys/（缺的会静默跳过）', no_sys)
