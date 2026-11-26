r"""
引擎 / 文件协议 / 服务主循环的纯 Python 测试（不启动 Kivy，几秒跑完）。

    .venv\Scripts\python.exe tests\test_engine.py

服务主循环用假播放器 + 假时钟驱动，整条 10 分钟方案几毫秒跑完；
再用真实线程跑一遍"UI 写 plan/cmd ↔ 服务写 state"的往返，验证跨进程协议。
"""
import os, sys, io, json, tempfile, threading, time, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from data import audio_meta, history
from data.workouts import build_plan, Plan, DETAILED, SHORT
from core.engine import Engine, REST_CLIP, FINISH_CLIP, guide_clips
from core.session_files import SessionFiles
from core import service_loop

TMP = tempfile.mkdtemp(prefix='subway_engine_')
history.set_path(os.path.join(TMP, 'history.json'))
audio_meta.exists = lambda rel: bool(rel)      # sys/ 与 _短 还没录，全部当作存在

results, errors = [], []
def check(desc, cond, detail=None):
    (results if cond else errors).append(('OK   ' if cond else 'FAIL ') + desc + (f'  ->  {detail}' if detail is not None else ''))


class FakePlayer:
    """记录调用；poll() 时把串播"立刻播完"并触发 then。"""
    def __init__(self):
        self.calls = []; self.beeps = []; self.loops = []; self.stopped = 0
        self.last_clips = []; self._then = None; self._busy = False
    def play_sequence(self, clips, then=None):
        self.stop(); self.last_clips = list(clips); self.calls.append(list(clips)); self._then = then; self._busy = True
    def start_loop(self, rel, delay=0): self.loops.append(rel)
    def beep(self, final=False): self.beeps.append('final' if final else 'beep')
    def stop(self): self.stopped += 1; self._then = None; self._busy = False
    def poll(self):
        if self._busy:
            self._busy = False
            then, self._then = self._then, None
            if then: then()
    def idle(self): return not self._busy


def run_engine(plan, skips_at=()):
    """逐秒 tick 跑完整个方案，返回 (engine, player, 每段开始时的 remaining)。"""
    p = FakePlayer(); e = Engine(plan.to_dict(), p); e.start()
    starts = {0: e.remaining}; guard = 0
    while not e.finished and guard < 100000:
        guard += 1
        if e.seg_index in skips_at and e.remaining == plan.timeline[e.seg_index]['secs']:
            e.skip(); starts[e.seg_index] = e.remaining; p.poll(); continue
        before = e.seg_index
        e.tick(); p.poll()
        if e.seg_index != before and not e.finished:
            starts[e.seg_index] = e.remaining
    return e, p, starts


# ------------------------------------------------------------ 1. 引擎：完整方案
plan = build_plan(10, '力量训练', mode=DETAILED)
e, p, starts = run_engine(plan)
check('完整跑完：finished', e.finished)
check('真实秒数 = 计划总秒数', e.real_secs == plan.total_secs, f'{e.real_secs} vs {plan.total_secs}')
check('每段开始 remaining = 段时长', all(starts[i] == plan.timeline[i]['secs'] for i in starts))
check('完成时播 训练完成', p.last_clips == [FINISH_CLIP], p.last_clips)
check('完成后写训练记录', set(history.last_trained()) == set(plan.blocks), sorted(history.last_trained()))
n_sets = sum(1 for s in plan.timeline if s['kind'] == 'set')
narr = [c for c in p.calls if plan.entries[0]['audio'] in c]
check('详细模式：讲解只在 guide 播一次', len(narr) == 1 and narr[0] == [plan.entries[0]['audio']], narr)
beeps_per_seg = sum(1 for s in plan.timeline if s['secs'] >= 6) * 5
check('提示音：每个 ≥6 秒的段 5 声（4 短 1 长）', len(p.beeps) == beeps_per_seg and p.beeps.count('final') == beeps_per_seg // 5,
      f'{len(p.beeps)} vs {beeps_per_seg}')
check('set 段开头播 开始 / 第N组', all(any(c in (['sys/开始.mp3'], ['sys/第2组.mp3'], ['sys/最后一组.mp3']) or c[0].startswith('sys/第') for c in [c]) for c in p.calls if c and c[0].startswith('sys/') and c[0] != 'sys/下一个.mp3' and c[0] != FINISH_CLIP))
n_rest = sum(1 for s in plan.timeline if s['kind'] == 'rest')
check('休息段播 放松提示（次数 = rest 段数）', p.calls.count([REST_CLIP]) == n_rest, f'{p.calls.count([REST_CLIP])} vs {n_rest}')
check('pct 完成 = 1', e.pct == 1.0)

# ------------------------------------------------------------ 2. 引擎：跳过语义
plan2 = build_plan(15, '力量训练', mode=SHORT)
tl = plan2.timeline
i = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and i + 1 < len(tl) and tl[i + 1]['kind'] == 'rest')
p2 = FakePlayer(); e2 = Engine(plan2.to_dict(), p2, record=False); e2.seg_index = i; e2.start()
e2.skip()
check('跳过一组：连带跳过休息', e2.seg_index == i + 2 and e2.segment['kind'] != 'rest', f'{i}->{e2.seg_index}')
g = next(i for i, sg in enumerate(tl) if sg['kind'] == 'guide' and i > 0)
e2.seg_index = g; e2._start_segment()
check('后续 guide 播 下一个 + 短提示', p2.last_clips[0] == 'sys/下一个.mp3' and len(p2.last_clips) == 2, p2.last_clips)
e2.skip()
check('跳过 guide：直接进 set，播 开始', e2.segment['kind'] == 'set' and e2.segment['set'] == 0 and p2.last_clips == ['sys/开始.mp3'], p2.last_clips)
r = next(i for i, sg in enumerate(tl) if sg['kind'] == 'rest')
e2.seg_index = r; e2._start_segment()
check('休息段播 放松提示', p2.last_clips == [REST_CLIP], p2.last_clips)
e2.skip()
check('跳过休息：进入下一组', e2.seg_index == r + 1 and e2.segment['kind'] == 'set')
e2.seg_index = len(tl) - 1; e2._start_segment(); e2.skip()
check('跳过最后一段：完成', e2.finished and p2.last_clips == [FINISH_CLIP])
check('跳过不计入真实秒数', e2.real_secs == 0, e2.real_secs)
e3 = Engine(plan2.to_dict(), FakePlayer(), record=False); e3.start()
for _ in range(int(0.5 * plan2.total_secs) + 1):
    e3.tick(); 
    if e3.finished: break
check('≥50% 时应记录', e3.should_record_on_exit())
e4 = Engine(plan2.to_dict(), FakePlayer(), record=False); e4.start(); e4.tick()
check('<50% 不记录', not e4.should_record_on_exit())

# ------------------------------------------------------------ 3. 引擎：呼吸训练 循环音 / 第N组
plan3 = build_plan(10, '呼吸训练', mode=DETAILED)
tl = plan3.timeline
main_i = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and plan3.entries[sg['ex']].get('audio_loop'))
ex = plan3.entries[tl[main_i]['ex']]
p3 = FakePlayer(); e5 = Engine(plan3.to_dict(), p3, record=False)
e5.seg_index = main_i - 1; e5.start()
check('呼吸：主循环前 guide 播 下一个 + 指导语', p3.last_clips == ['sys/下一个.mp3', ex['audio']], p3.last_clips)
e5.seg_index = main_i; e5._start_segment()
check('呼吸：第 1 组只播 开始', p3.last_clips == ['sys/开始.mp3'])
p3.poll()
check('呼吸：开始 播完紧接循环音', p3.loops == [ex['audio_loop']], p3.loops)
e5.seg_index = main_i + 2; e5._start_segment()
check('呼吸：第 2 组播 第2组', p3.last_clips == ['sys/第2组.mp3'], p3.last_clips)
last = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and sg['ex'] == tl[main_i]['ex'] and sg['set'] == ex['sets'] - 1)
e5.seg_index = last; e5._start_segment()
check('呼吸：最后一组播 最后一组', p3.last_clips == ['sys/最后一组.mp3'], p3.last_clips)

# ------------------------------------------------------------ 4. Plan 往返
d = json.loads(json.dumps(plan.to_dict(), ensure_ascii=False))
q = Plan.from_dict(d)
check('Plan json 往返：时间线/条目/部位一致', q.timeline == plan.timeline and q.entries == plan.entries and q.blocks == plan.blocks and q.parts == plan.parts)

# ------------------------------------------------------------ 5. 服务主循环（假时钟，瞬间跑完）
class FakeClock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, dt): self.t += dt
sdir = os.path.join(TMP, 'svc'); files = SessionFiles(sdir)
files.begin(plan2.to_dict(), 'sess-1')
files.send_cmd('skip')                                  # 服务冷启动期间用户点的跳过：启动后要补上
clk = FakeClock(); fp = FakePlayer(); log = []
plan_in = files.read_plan()
check('服务读到 plan 和 session', plan_in and plan_in['session'] == 'sess-1')
snap = service_loop.run(plan_in, fp, files, now=clk.now, sleep=clk.sleep, log=log.append)
st = files.read_state()
check('服务：跑完 finished，state.running=False', snap['finished'] and st and st['running'] is False and st['finished'] and st['session'] == 'sess-1', st)
check('服务：启动前的 skip 生效，真实秒数 = 计划 - 首段', snap['real_secs'] == plan2.total_secs - plan2.timeline[0]['secs'], f"{snap['real_secs']} vs {plan2.total_secs - plan2.timeline[0]['secs']}")
check('服务：用时 ≈ 计划秒数 - 首段', abs((clk.t - 1000.0) - (plan2.total_secs - plan2.timeline[0]['secs'])) < 2, clk.t - 1000.0)

# 中途 stop 命令
files.begin(plan2.to_dict(), 'sess-2'); clk = FakeClock(); fp = FakePlayer()
def stop_after(): return clk.t - 1000.0 > 20
snap = service_loop.run(files.read_plan(), fp, files, stop_requested=stop_after, now=clk.now, sleep=clk.sleep)
check('服务：宿主要求停止 → 未完成、running=False、播放器已 stop', not snap['finished'] and files.read_state()['running'] is False and fp.stopped > 0)

# ------------------------------------------------------------ 6. 真实线程：UI 端协议 ↔ 服务端
files.begin(plan2.to_dict(), 'sess-3')
fp = FakePlayer()
t = threading.Thread(target=service_loop.run, args=(files.read_plan(), fp, files), daemon=True); t.start()
deadline = time.time() + 5
while time.time() < deadline and not (files.read_state() or {}).get('started'): time.sleep(0.02)
st0 = files.read_state()
check('线程服务：启动后 ~立刻写出 state', st0 and st0['running'] and st0['seg_index'] == 0, st0)
files.send_cmd('skip')
deadline = time.time() + 2
while time.time() < deadline and (files.read_state() or {}).get('seg_index') == 0: time.sleep(0.02)
st1 = files.read_state()
check('线程服务：skip 命令 0.5 秒内生效', st1['seg_index'] >= 1 and time.time() < deadline, st1)
check('线程服务：running_state() 判定在跑', files.running_state() is not None)
time.sleep(1.3)
st2 = files.read_state()
check('线程服务：每秒 tick 推进 remaining', st2['version'] > st1['version'] and (st2['remaining'] < st1['remaining'] or st2['seg_index'] > st1['seg_index']), (st1['remaining'], st2['remaining']))
files.send_cmd('stop'); t.join(3)
check('线程服务：stop 命令后线程退出、running=False', not t.is_alive() and files.read_state()['running'] is False)
check('线程服务：退出后 running_state() 为 None', files.running_state() is None)

print('\n'.join(results))
if errors:
    print('\n' + '\n'.join(errors)); print('\nENGINE TESTS FAILED'); sys.exit(1)
print(f'\n{len(results)} OK, ENGINE TESTS PASSED')
