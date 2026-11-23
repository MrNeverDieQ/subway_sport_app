r"""
端到端用户旅程测试（真实 Kivy，会弹出窗口，约 20 秒）。

    .venv\Scripts\python.exe tests\e2e_app.py

做法：计时器加速到每帧一秒、音频换成假对象（避免 ffpyplayer 高频 load/stop 死锁）、
训练记录写到临时目录，不会影响真实数据。退出码 0 = 通过。
"""
import os, sys, io, json, tempfile, traceback, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ['KIVY_NO_ARGS'] = '1'
os.environ['KIVY_LOG_MODE'] = 'PYTHON'
from kivy.config import Config
Config.set('graphics', 'maxfps', '0')
import logging
kivy_warnings = []
class _H(logging.Handler):
    def emit(self, r):
        if r.levelno >= logging.WARNING:
            kivy_warnings.append(f"{r.levelname}: {r.getMessage()}")
logging.getLogger('kivy').addHandler(_H())
logging.getLogger('kivy').setLevel(logging.WARNING)

# 1) 计时器加速：CountdownTimer 的 1 秒 tick 改成每帧
import components.timer as timer_mod
_real_clock = timer_mod.Clock
class FastClock:
    @staticmethod
    def schedule_interval(fn, dt): return _real_clock.schedule_interval(fn, 0)
    @staticmethod
    def schedule_once(fn, dt): return _real_clock.schedule_once(fn, dt)
timer_mod.Clock = FastClock

# 2) 音频换成假对象：只验证流程，不做真实解码（加速后高频 load/stop 会让 ffpyplayer 死锁）
from kivy.core.audio import SoundLoader
import screens.workout_screen as ws_mod
played = []          # 所有被 play() 过的音频路径（相对 audio/，正斜杠）
unloaded = []        # 被 unload() 过的 FakeSound 数
class FakeSound:
    length = 1.0
    def __init__(self, source=None):
        self.source = source; self.loop = False; self.volume = 1; self.state = 'stop'; self._on_stop = []
    def load(self): pass
    def play(self):
        self.state = 'play'
        played.append(os.path.relpath(self.source, audio_meta.AUDIO_DIR).replace('\\', '/'))
    def stop(self): self.state = 'stop'
    def unload(self): unloaded.append(self)
    def bind(self, on_stop=None): self._on_stop.append(on_stop)
    def unbind(self, on_stop=None):
        if on_stop in self._on_stop: self._on_stop.remove(on_stop)
    def fire_stop(self):
        """模拟自然播完：真实播放端会派发 on_stop"""
        self.state = 'stop'
        for cb in list(self._on_stop): cb(self)
from data import audio_meta
SoundLoader.load = staticmethod(lambda path: FakeSound(path))
ws_mod.SoundLoader = SoundLoader
ws_mod._load_beep = lambda path: FakeSound(path)
# 所有短句都当作存在（sys/ 与 _短 还没录），时长压到极短让串播立刻衔接
_real_exists = audio_meta.exists
audio_meta.exists = lambda rel: bool(rel)
ws_mod._clip_len = lambda rel, sound: 0.01
ws_mod._CLIP_SLACK = 0.05          # FakeSound 不派发 on_stop，靠兜底推进，别等太久

from kivy.clock import Clock
from kivy.storage.jsonstore import JsonStore
import main as app_main
from data import history
from data.workouts import get_durations, get_goals, AUTO, DETAILED, SHORT

# 3) 训练记录写到临时目录
TMP = tempfile.mkdtemp(prefix='subway_e2e_')
HIST = os.path.join(TMP, 'history.json')
history._store = JsonStore(HIST)

results, errors = [], []
def ok(desc, detail=None): results.append(f"OK   {desc}" + (f"  ->  {detail}" if detail is not None else ""))
def fail(desc, detail): errors.append(f"FAIL {desc}  ->  {detail}")
def check(desc, cond, detail=None):
    (ok if cond else fail)(desc, detail)

def wait_until(pred, then, timeout=60, desc='等待'):
    t0 = time.time()
    def poll(dt):
        if pred(): then()
        elif time.time() - t0 > timeout: fail(desc, f'超时 {timeout}s'); App.stop_app()
        else: Clock.schedule_once(poll, 0.02)
    Clock.schedule_once(poll, 0.02)

def read_hist(key='blocks'):
    try:
        with io.open(HIST, encoding='utf-8') as f:
            return json.load(f).get('history', {}).get(key, {})
    except Exception:
        return {}

class App(app_main.SubwaySportApp):
    inst = None
    @classmethod
    def stop_app(cls): cls.inst.stop()

    def on_start(self):
        App.inst = self
        sm = self.root
        home = sm.get_screen('home'); ws = sm.get_screen('workout')
        for b in (ws._beep, ws._beep_final):
            if b: b.volume = 0
        state = {}

        def observe():
            """每帧采样训练页，记录进度是否单调、是否出现休息、组数。"""
            state['pct_prev'] = -1; state['pct_monotonic'] = True; state['rests'] = 0; state['last_resting'] = False
            state['exercise_names'] = set(); state['kinds'] = set(); state['clips'] = set()
            state['narrated_sets'] = 0; state['narrated_guides'] = 0; state['seg_prev'] = None
            def ev(dt):
                if sm.current != 'workout' or ws.workout_finished: return False
                if ws._pct < state['pct_prev'] - 1e-9: state['pct_monotonic'] = False
                state['pct_prev'] = ws._pct
                if ws.is_resting and not state['last_resting']: state['rests'] += 1
                state['last_resting'] = ws.is_resting
                state['exercise_names'].add(ws.exercise_label.text)
                seg = ws.segment
                if seg is not None and seg is not state['seg_prev']:
                    state['seg_prev'] = seg
                    state['kinds'].add(seg['kind'])
                    state['clips'].update(ws._last_clips)
                    ex = ws.exercises[seg['ex']]
                    if ex.get('audio') and ex['audio'] in ws._last_clips:
                        state['narrated_sets' if seg['kind'] == 'set' else 'narrated_guides'] += 1
            state['ev'] = Clock.schedule_interval(ev, 0)

        def step0(dt):
            check("初始：开始按钮禁用", home.start_btn.disabled)
            check("初始：无预览", home.plan is None)
            # 所有组合的预览
            bad = []
            for g in get_goals(None):
                for d in get_durations():
                    home._select_duration(d); home._select_goal(g)
                    p = home.plan
                    if p is None or home.start_btn.disabled or p.total_secs > d * 60 or not p.entries:
                        bad.append((g, d))
            check("全部 10 种组合：预览可用、不超时", not bad, bad or f"{len(get_goals(None)) * len(get_durations())} 种")
            # 选 10min 力量，记录预览
            home._select_duration(10); home._select_goal('力量训练')
            state['preview1'] = home.plan.summary
            state['blocks1'] = list(home.plan.blocks)
            state['total1'] = home.plan.total_secs
            ok("10min 力量 预览", state['preview1'])
            # 语音模式切换：默认自动=详细（没练过），切简短不改变时长
            check("默认语音模式 自动→详细引导", home.mode_choice == AUTO and home.plan.mode_label == '详细引导', home.plan.mode_label)
            home._select_mode(SHORT)
            check("切到简短提示：不超时、时长可以不同", home.plan.mode_label == '简短提示' and home.plan.total_secs <= 600,
                  f"{home.plan.mode_label} / {home.plan.total_secs} (详细 {state['total1']})")
            check("模式按钮高亮跟随", home._mode_btns[SHORT].bold and not home._mode_btns[AUTO].bold)
            home._select_mode(AUTO)
            home._start_workout()
            check("进入训练页", sm.current == 'workout', sm.current)
            first = home.plan.entries[0]
            check("首段是 guide", ws.segment['kind'] == 'guide', ws.segment['kind'])
            check("第一个条目", ws.exercise_label.text == first['name'], ws.exercise_label.text)
            check("详细：首段直接播完整讲解（不播 下一个）", ws._last_clips == [first['audio']], ws._last_clips)
            check("详细：首段状态为 讲解，时长 ≥ 讲解时长", ws.status_label.text == '讲解'
                  and ws.segment['secs'] >= (audio_meta.duration(first['audio']) or 0), (ws.status_label.text, ws.segment['secs']))
            check("段开始的第一拍不响提示音", not any(x.startswith('beep') for x in played), [x for x in played if x.startswith('beep')])
            observe()
            wait_until(lambda: ws.workout_finished, step1, desc='完整跑完 10min 力量')

        def step1():
            state['ev'].cancel()
            check("训练完成文案", ws.exercise_label.text == '训练完成！' and ws.next_btn.text == '返回首页',
                  f"{ws.exercise_label.text} / {ws.next_btn.text}")
            check("完成时进度 100%", ws.progress_pct.text == '100%', ws.progress_pct.text)
            check("进度全程单调不倒退", state['pct_monotonic'])
            exp_rests = sum(1 for sg in ws.timeline if sg['kind'] == 'rest')
            check("组间休息次数 = 时间线里的 rest 段", state['rests'] == exp_rests, f"{state['rests']} vs {exp_rests}")
            check("真实经过秒数 = 计划秒数", ws._real_secs == state['total1'], f"{ws._real_secs} vs {state['total1']}")
            names = state['exercise_names'] - {'训练完成！'}
            check("所有动作都播过", names == {e['name'] for e in ws.exercises}, f"{len(names)} 个动作名")
            check("出现的段类型 = 时间线里的", state['kinds'] == {sg['kind'] for sg in ws.timeline}, state['kinds'])
            uniq = len({e['name'] for e in ws.exercises})
            check("详细模式：每个动作在 guide 讲解一次", state['narrated_guides'] == uniq, f"{state['narrated_guides']}/{uniq}")
            check("set 段从不播讲解", state['narrated_sets'] == 0, state['narrated_sets'])
            check("播过 下一个/开始 短句", {'sys/下一个.mp3', 'sys/开始.mp3'} <= state['clips'], sorted(state['clips'])[:6])
            check("完成时播 训练完成", ws._last_clips == ['sys/训练完成.mp3'], ws._last_clips)
            h = read_hist()
            check("完成后写入训练记录", set(h) == set(state['blocks1']), sorted(h))
            state['hist_after_1'] = dict(h)
            ws._on_next_press()
            check("返回首页", sm.current == 'home', sm.current)
            # 回来后预览应因轮换而变化
            Clock.schedule_once(step2, 0.1)

        def step2(dt):
            home._select_duration(10); home._select_goal('力量训练')
            check("轮换：10min 预览变了", home.plan.summary != state['preview1'],
                  f"{state['preview1']}  =>  {home.plan.summary}")
            check("轮换：刚练过的部位不在最前", home.plan.blocks[0] not in state['blocks1'], home.plan.blocks[0])
            # 中途退出 <50%：不记录；这一轮用简短模式
            home._select_duration(15); home._select_goal('力量训练'); home._select_mode(SHORT)
            state['blocks_15'] = list(home.plan.blocks)
            home._start_workout()
            # 跳过逻辑（同步验证）：跳过一组时连带跳过紧跟的休息；跳过 guide 直接进 set
            ws.timer.stop()
            tl = ws.timeline
            i = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and i + 1 < len(tl) and tl[i + 1]['kind'] == 'rest')
            ws.seg_index = i; ws._start_segment(); ws.timer.stop()
            ws._on_next_press()
            check("跳过一组：连带跳过休息", ws.seg_index == i + 2 and ws.segment['kind'] != 'rest', f"{i}->{ws.seg_index} {ws.segment['kind']}")
            g = next(i for i, sg in enumerate(tl) if sg['kind'] == 'guide' and i > 0)
            ws.timer.stop(); ws.seg_index = g; ws._start_segment(); ws.timer.stop()
            check("后续 guide 播 下一个 + 短提示", ws._last_clips[0] == 'sys/下一个.mp3' and len(ws._last_clips) == 2, ws._last_clips)
            check("后续 guide 状态为 下一个", ws.status_label.text == '下一个', ws.status_label.text)
            ws._on_next_press()
            check("跳过 guide：直接进 set", ws.segment['kind'] == 'set' and ws.segment['set'] == 0, ws.segment)
            check("简短模式：第一组不播讲解", ws._last_clips == ['sys/开始.mp3'], ws._last_clips)
            r = next(i for i, sg in enumerate(tl) if sg['kind'] == 'rest')
            ws.timer.stop(); ws.seg_index = r; ws._start_segment(); ws.timer.stop()
            check("休息段播 放松提示", ws._last_clips == [ws_mod._REST_CLIP], ws._last_clips)
            ws._on_next_press()
            check("跳过休息：进入下一组", ws.seg_index == r + 1 and ws.segment['kind'] == 'set', ws.segment)
            # 串播：缺失文件被跳过；自然播完（on_stop）推进到下一段
            audio_meta.exists = _real_exists
            ws.timer.stop()
            have = next(rel for rel in (e.get('audio') for e in ws.exercises) if rel and _real_exists(rel))
            del played[:]
            ws_mod._clip_len = lambda rel, sound: 100     # 兜底不触发，只靠 on_stop
            ws._play_sequence(['sys/不存在.mp3', have, 'sys/也不存在.mp3', have])
            check("串播：缺失的直接跳过，先播存在的", played == [have] and ws._current_sound is not None, played)
            ws._current_sound.fire_stop()
            def after_stop(dt):
                check("串播：on_stop 后 0.3 秒播下一段", played == [have, have], played)
                check("串播：播完的 Sound 已 unload", len(unloaded) >= 1)
                audio_meta.exists = lambda rel: bool(rel)
                ws_mod._clip_len = lambda rel, sound: 0.01
                ws.seg_index = 0; ws._start_segment()
                observe()
                wait_until(lambda: ws._pct >= 0.2, step3, desc='跑到 20%')
            Clock.schedule_once(after_stop, ws_mod._CLIP_GAP + 0.3)

        def step3():
            state['ev'].cancel()
            check("简短模式：跑到 20% 没播过讲解", state['narrated_sets'] == 0 and state['narrated_guides'] == 0,
                  (state['narrated_sets'], state['narrated_guides']))
            ws._go_home()
            h = read_hist()
            check("<50% 退出：记录不变", h == state['hist_after_1'], f"{len(h)} 条")
            check("退出后没有待播事件", ws._seq_event is None and ws._loop_event is None and ws._current_sound is None)
            n = len(played)
            def quiet(dt):
                check("退出后不再有任何声音", len(played) == n, len(played) - n)
                home._select_mode(AUTO)
                step4(0)
            Clock.schedule_once(quiet, 0.6)

        def step4(dt):
            # 中途退出 ≥50%：记录
            home._select_duration(15); home._select_goal('力量训练')
            state['blocks_b'] = list(home.plan.blocks)
            home._start_workout()
            wait_until(lambda: ws._real_secs >= 0.5 * ws._total_workout_secs + 1, step5, desc='跑到 50%')

        def step5():
            counts_before = read_hist('counts')
            ws._go_home(); ws._go_home()
            h = read_hist()
            new = [b for b in state['blocks_b'] if h.get(b, 0) > state['hist_after_1'].get(b, 0)]
            check("≥50% 退出：本次部位被记录", set(new) == set(state['blocks_b']), new)
            counts = read_hist('counts')
            check("连点两次退出：完成次数只 +1", all(counts.get(b, 0) == counts_before.get(b, 0) + 1 for b in state['blocks_b']), counts)
            check("退出后音频/视频已清理", ws._current_sound is None and ws._loop_sound is None and ws._current_video is None)
            Clock.schedule_once(step5b, 0.5)

        def step5b(dt):
            # 跳过最后一段：直接完成并记录
            home._select_duration(10); home._select_goal('力量训练')
            home._start_workout(); ws.timer.stop()
            ws.seg_index = len(ws.timeline) - 1; ws._start_segment(); ws.timer.stop()
            ws._on_next_press()
            check("跳过最后一段：训练完成", ws.workout_finished and ws._last_clips == ['sys/训练完成.mp3'], ws._last_clips)
            ws._on_next_press()
            check("完成后点按钮回首页", sm.current == 'home')
            Clock.schedule_once(step5c, 0.5)

        def step5c(dt):
            # 详细模式下同一次训练里重复出现的动作：第二次只播 下一个 + 短提示
            home._select_duration(25); home._select_goal('力量训练'); home._select_mode(DETAILED)
            tl = home.plan.timeline
            rep = next((i for i, sg in enumerate(tl) if sg['kind'] == 'guide' and sg['mode'] == SHORT
                        and home.plan.entries[sg['ex']].get('audio')), None)
            check("25min 详细方案里有重复动作", rep is not None, home.plan.summary)
            if rep is not None:
                home._start_workout(); ws.timer.stop()
                ws.seg_index = rep; ws._start_segment(); ws.timer.stop()
                ex = ws.exercises[tl[rep]['ex']]
                check("重复动作：第二次只播 下一个 + 短提示", ws._last_clips == ['sys/下一个.mp3', audio_meta.short_variant(ex['audio'])], ws._last_clips)
                check("重复动作：guide 不含讲解时长", tl[rep]['secs'] == max(ws.exercises[tl[rep]['ex'] - 1]['rest'], 5), tl[rep]['secs'])
                ws._go_home()
            home._select_mode(AUTO)
            Clock.schedule_once(step6, 0.5)

        def step6(dt):
            # 呼吸训练完整跑
            home._select_duration(10); home._select_goal('呼吸训练')
            ok("10min 呼吸 预览", home.plan.summary)
            home._start_workout()
            ws.timer.stop()
            tl = ws.timeline
            main = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and ws.exercises[sg['ex']].get('audio_loop'))
            ex = ws.exercises[tl[main]['ex']]
            # 第 2 组 / 最后一组 短句
            ws.seg_index = main + 2; ws._start_segment(); ws.timer.stop()
            check("呼吸：第 2 组播 第2组", ws._last_clips == ['sys/第2组.mp3'], ws._last_clips)
            last = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and sg['ex'] == tl[main]['ex'] and sg['set'] == ex['sets'] - 1)
            ws.seg_index = last; ws._start_segment(); ws.timer.stop()
            check("呼吸：最后一组播 最后一组", ws._last_clips == ['sys/最后一组.mp3'], ws._last_clips)
            # 讲解在 guide；第 1 组只播"开始"，紧接着循环音
            ws.seg_index = main - 1; ws._start_segment(); ws.timer.stop()
            check("呼吸：主循环前的 guide 播 下一个 + 指导语", ws._last_clips == ['sys/下一个.mp3', ex['audio']], ws._last_clips)
            del played[:]
            ws.seg_index = main; ws._start_segment(); ws.timer.stop()
            check("呼吸：第 1 组只请求 开始", ws._last_clips == ['sys/开始.mp3'], ws._last_clips)
            def after_clips(dt):
                check("呼吸：开始 已播放", played[:1] == ['sys/开始.mp3'], played)
                check("呼吸：开始 之后循环音已开始且 loop=True", ws._loop_sound is not None and ws._loop_sound.loop)
            def after_gap(dt):
                ws.seg_index = 0; ws._start_segment()
                observe()
                wait_until(lambda: ws.workout_finished, step7, desc='完整跑完 10min 呼吸')
            Clock.schedule_once(after_clips, 1.0)
            Clock.schedule_once(after_gap, 1.3)

        def step7():
            state['ev'].cancel()
            check("呼吸：完成 100%", ws.progress_pct.text == '100%' and ws.workout_finished)
            check("呼吸：进度单调", state['pct_monotonic'])
            exp_rests = sum(1 for sg in ws.timeline if sg['kind'] == 'rest')
            check("呼吸：组间休息次数 = 时间线", state['rests'] == exp_rests and exp_rests >= 2, f"{state['rests']} vs {exp_rests}")
            check("呼吸：结束后循环音已停止", ws._loop_sound is None)
            ws._on_next_press()
            check("呼吸：返回首页", sm.current == 'home')
            Clock.schedule_once(lambda d: self.stop(), 0.2)

        Clock.schedule_once(step0, 0.5)

try:
    App().run()
except Exception:
    fail("测试过程抛出异常", traceback.format_exc())
finally:
    print("\n".join(results))
    benign = ('Estimating duration',)
    warns = [w for w in kivy_warnings if not any(b in w for b in benign)]
    print(f"\nKivy 告警（排除已知无害）：{len(warns)}")
    for w in warns[:20]: print("  ", w)
    if errors:
        print("\n" + "\n".join(errors)); print("\nE2E FAILED"); sys.exit(1)
    print("\nE2E PASSED")
