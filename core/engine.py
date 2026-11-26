# ============================================================
# engine.py - 训练时间线状态机
#
# 不依赖 Kivy，也不自己计时：由驱动方每隔 1 秒调用一次 tick()，跳过时调用 skip()。
#   桌面：screens/workout_session.LocalSession 用 Kivy Clock 驱动
#   Android：core/service_loop 在前台服务进程里用 time.monotonic 驱动
# 所有"什么时候播哪句话、什么时候响提示音、何时算完成"的规则都在这里，界面只负责显示。
# ============================================================

from data import audio_meta, history
from data.workouts import DETAILED

GUIDE, SET, REST = 'guide', 'set', 'rest'
REST_CLIP = '放松提示.mp3'          # 休息开始时的短句
FINISH_CLIP = audio_meta.sys_clip('训练完成')
RECORD_RATIO = 0.5                  # 中途退出时真实练够这个比例就算练过


def is_detailed(seg, ex):
    """这段 guide 是否播放完整讲解。"""
    return seg['kind'] == GUIDE and seg['mode'] == DETAILED and bool(ex.get('audio'))


def guide_clips(seg, ex):
    """guide 段要播的短句：详细模式播完整讲解；简短模式播 下一个 + 短提示（首个动作不播 下一个）。"""
    first = seg['ex'] == 0
    clips = [] if first else [audio_meta.sys_clip('下一个')]
    if is_detailed(seg, ex):
        clips.append(ex['audio'])
    elif ex.get('audio'):
        clips.append(audio_meta.short_variant(ex['audio']))
    return clips


def set_clips(seg, ex):
    """set 段开头的短句：第 1 组播 开始，之后播 第N组 / 最后一组。"""
    k = seg['set']
    if k == 0:
        return [audio_meta.sys_clip('开始')]
    return [audio_meta.sys_clip(audio_meta.set_clip(k + 1, ex['sets']))]


class Engine:
    """
    plan:   Plan.to_dict() 的结果（entries / timeline / total_secs / blocks）
    player: 实现 play_sequence(clips, then=None) / start_loop(rel) / beep(final=False) / stop()
    """

    def __init__(self, plan, player, record=True):
        self.entries = plan['entries']
        self.timeline = plan['timeline']
        self.total_secs = plan['total_secs']
        self.blocks = plan['blocks']
        self.player = player
        self.record = record
        self.seg_index = 0
        self.remaining = 0
        self.real_secs = 0          # 真实经过的秒数（跳过不计入）
        self.finished = False
        self.started = False
        self.version = 0            # 每次状态变化 +1，供镜像端判断是否需要刷新

    # ------------------------------------------------------------ 只读状态

    @property
    def segment(self):
        return self.timeline[self.seg_index] if self.seg_index < len(self.timeline) else None

    @property
    def exercise(self):
        seg = self.segment
        return self.entries[seg['ex']] if seg else None

    @property
    def elapsed(self):
        if self.finished:
            return self.total_secs
        seg = self.segment
        base = sum(s['secs'] for s in self.timeline[:self.seg_index])
        return base + ((seg['secs'] - self.remaining) if seg else 0)

    @property
    def pct(self):
        if self.finished:
            return 1.0
        return min(self.elapsed / self.total_secs, 1.0) if self.total_secs > 0 else 0.0

    def should_record_on_exit(self):
        return not self.finished and self.real_secs >= RECORD_RATIO * self.total_secs

    def snapshot(self):
        return {
            'seg_index': self.seg_index,
            'remaining': self.remaining,
            'real_secs': self.real_secs,
            'finished': self.finished,
            'started': self.started,
            'version': self.version,
        }

    # ------------------------------------------------------------ 驱动接口

    def start(self):
        self.started = True
        self._start_segment()

    def tick(self):
        """过了 1 秒。段开始那一刻不算 tick，所以这里永远可以响提示音。"""
        if self.finished or not self.started:
            return
        self.remaining -= 1
        self.real_secs += 1
        self.version += 1
        if self.remaining <= 0:
            self._advance(1)
            return
        if self.remaining == 1:
            self.player.beep(final=True)
        elif 2 <= self.remaining <= 5:
            self.player.beep()

    def skip(self):
        """跳过当前段；跳过一组动作时连带跳过紧跟的组间休息。"""
        if self.finished or not self.started:
            return
        seg = self.segment
        n = 1
        if seg and seg['kind'] == SET and self.seg_index + 1 < len(self.timeline) \
                and self.timeline[self.seg_index + 1]['kind'] == REST:
            n = 2
        self._advance(n)

    def stop(self):
        self.player.stop()

    # ------------------------------------------------------------ 内部

    def _advance(self, n):
        self.seg_index += n
        self._start_segment()

    def _start_segment(self):
        seg = self.segment
        self.version += 1
        if seg is None:
            self._finish()
            return
        self.remaining = seg['secs']
        ex = self.entries[seg['ex']]
        if seg['kind'] == GUIDE:
            self.player.play_sequence(guide_clips(seg, ex))
        elif seg['kind'] == SET:
            loop = ex.get('audio_loop')
            if loop:
                self.player.play_sequence(set_clips(seg, ex), then=lambda: self.player.start_loop(loop))
            else:
                self.player.play_sequence(set_clips(seg, ex))
        else:
            self.player.play_sequence([REST_CLIP])

    def _finish(self):
        self.finished = True
        self.remaining = 0
        if self.record:
            history.record(self.blocks)
        self.player.play_sequence([FINISH_CLIP])
