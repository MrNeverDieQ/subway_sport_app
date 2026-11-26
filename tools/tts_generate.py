r"""
用微软 Edge 神经语音（Azure 同款，免 key）从 training_blocks 的 cues 批量生成训练语音。

    uv run --python 3.12 --with edge-tts python tools\tts_generate.py --voice zh-CN-YunxiNeural
    uv run --python 3.12 --with edge-tts python tools\tts_generate.py --list-voices
    uv run --python 3.12 --with edge-tts python tools\tts_generate.py --voice ... --only sys short   # 只生成一部分
    uv run --python 3.12 --with edge-tts python tools\tts_generate.py --voice ... --dry-run          # 只打印文本
    uv run --python 3.12 --with edge-tts python tools\tts_generate.py --voice ... --match breath/   # 只生成路径含该子串的文件

生成内容（相对 audio/）：
  <audio>            动作完整讲解 = cues 逐句相连（ASCII 逗号换成中文逗号，句末补句号，语调才自然）
  <audio>_短         短提示 = 条目的 short 字段，没有就用动作名（"进阶：手腿互抗(右侧)" → "进阶，手腿互抗，右侧"）
  sys/*.mp3          开始 / 下一个 / 第2组…第N组 / 最后一组 / 训练完成
  放松提示.mp3        组间休息短句（--rest-text 可改）
不生成：breath/呼吸循环.mp3（按节拍制作的循环音轨，单独处理）。

旧文件先整体备份到 audio/_archive/_backup_<时间>/（该目录不打包进 APK），生成完自动跑 tools/audio_durations.py 刷新时长表。
推荐声音：zh-CN-YunxiNeural（男·阳光）/ zh-CN-XiaoxiaoNeural（女·温暖）/ zh-CN-YunyangNeural（男·稳重）。
"""
import argparse
import asyncio
import datetime
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, 'audio')
sys.path.insert(0, ROOT)

from data.training_blocks import TRAINING_BLOCKS  # noqa: E402
from data import audio_meta  # noqa: E402

try:
    import edge_tts
except ImportError:
    sys.exit('缺少 edge-tts：用 uv run --python 3.12 --with edge-tts python tools\\tts_generate.py ... 运行')

SYS_TEXT = {
    '开始': '开始。',
    '下一个': '下一个。',
    '最后一组': '最后一组。',
    '训练完成': '训练完成，记得补水和拉伸。',
}
DEFAULT_REST_TEXT = '休息一下，放松肩膀，自然呼吸。'
MIN_SET_CLIPS = 12          # 第2组…第N组 至少生成到这里（呼吸训练组数随时长变化）


def tidy(text):
    """让神经语音读出正常停顿：ASCII 标点→中文标点（小数点保留），去掉标点旁的空格，句末补句号。"""
    text = text.strip().replace(',', '，').replace(':', '：').replace(';', '；')
    text = re.sub(r'(?<!\d)\.|\.(?!\d)', '。', text)
    text = re.sub(r'\s*([，。！？：；])\s*', r'\1', text)
    text = re.sub('，+', '，', text)
    if text and text[-1] not in '。！？':
        text += '。'
    return text


def short_text(entry):
    if entry.get('short'):
        return tidy(entry['short'])
    name = entry['name'].replace('：', '，').replace(':', '，').replace('-', '，')
    name = name.replace('(', '，').replace('（', '，').replace(')', '').replace('）', '')
    return tidy(name)


def all_entries():
    for block in TRAINING_BLOCKS.values():
        for e in block.get('warmup', []) + block['exercises'] + block.get('cooldown', []):
            yield e


def build_jobs(only, rest_text):
    """返回 [(相对路径, 文本)]。"""
    jobs = []
    max_sets = MIN_SET_CLIPS
    for e in all_entries():
        max_sets = max(max_sets, int(e.get('sets', 1)))
        a = e.get('audio')
        if not a:
            continue
        if 'full' in only:
            jobs.append((a, ''.join(tidy(c) for c in e.get('cues', []))))
        if 'short' in only:
            jobs.append((audio_meta.short_variant(a), short_text(e)))
    if 'sys' in only:
        for name, text in SYS_TEXT.items():
            jobs.append((audio_meta.sys_clip(name), text))
        for n in range(2, max_sets + 1):
            jobs.append((audio_meta.sys_clip('第%d组' % n), '第%d组。' % n))
    if 'rest' in only:
        jobs.append(('放松提示.mp3', tidy(rest_text)))
    return [(rel, text) for rel, text in jobs if text.strip('。')]


async def synth_all(jobs, voice, rate, concurrency=4):
    sem = asyncio.Semaphore(concurrency)
    failed = []

    async def one(rel, text):
        path = audio_meta.audio_path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with sem:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate).save(path)
                    print('  ok  %-32s %s' % (rel, text))
                    return
                except Exception as exc:  # noqa: BLE001
                    err = exc
                    await asyncio.sleep(1.5 * (attempt + 1))
            failed.append((rel, str(err)))
            print('  FAIL %-32s %s' % (rel, err))

    await asyncio.gather(*(one(rel, text) for rel, text in jobs))
    return failed


def backup(jobs):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = os.path.join(AUDIO, '_archive', '_backup_' + stamp)
    n = 0
    for rel, _ in jobs:
        src = audio_meta.audio_path(rel)
        if os.path.isfile(src):
            dst = os.path.join(dest, *rel.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    if n:
        print('已备份 %d 个旧文件 → %s' % (n, os.path.relpath(dest, ROOT)))
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--voice', default='zh-CN-YunxiNeural')
    ap.add_argument('--rate', default='-10%', help='语速，如 -10%% / +0%%')
    ap.add_argument('--only', nargs='+', choices=['full', 'short', 'sys', 'rest'], default=['full', 'short', 'sys', 'rest'])
    ap.add_argument('--rest-text', default=DEFAULT_REST_TEXT)
    ap.add_argument('--dry-run', action='store_true', help='只打印将要生成的文件和文本')
    ap.add_argument('--match', help='只生成相对路径里含这个子串的文件，如 --match breath/准备')
    ap.add_argument('--no-backup', action='store_true')
    ap.add_argument('--list-voices', action='store_true', help='列出中文声音')
    args = ap.parse_args()

    if args.list_voices:
        voices = asyncio.run(edge_tts.list_voices())
        for v in voices:
            if v['Locale'].startswith('zh-'):
                tags = v.get('VoiceTag', {})
                print('%-32s %-7s %s' % (v['ShortName'], v['Gender'], ', '.join(tags.get('VoicePersonalities', []))))
        return

    jobs = build_jobs(set(args.only), args.rest_text)
    if args.match:
        jobs = [j for j in jobs if args.match in j[0]]
    print('%d 个文件，声音 %s，语速 %s' % (len(jobs), args.voice, args.rate))
    if args.dry_run:
        for rel, text in jobs:
            print('  %-32s %s' % (rel, text))
        return
    if not args.no_backup:
        backup(jobs)
    failed = asyncio.run(synth_all(jobs, args.voice, args.rate))
    if failed:
        print('\n失败 %d 个：' % len(failed))
        for rel, err in failed:
            print('  %s  %s' % (rel, err))

    venv_py = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    tool = os.path.join(ROOT, 'tools', 'audio_durations.py')
    if os.path.isfile(venv_py):
        print('\n刷新时长表：')
        subprocess.run([venv_py, tool], cwd=ROOT)
    else:
        print('\n请手动运行 tools/audio_durations.py 刷新时长表')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
