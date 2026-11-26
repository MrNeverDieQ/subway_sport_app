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

# 1) 计时器加速：LocalSession 的 1 秒 tick 改成每帧
import screens.workout_session as sess_mod
_real_clock = sess_mod.Clock
class FastClock:
    @staticmethod
    def schedule_interval(fn, dt): return _real_clock.schedule_interval(fn, 0)
    @staticmethod
    def schedule_once(fn, dt): return _real_clock.schedule_once(fn, dt)
sess_mod.Clock = FastClock

# 2) 音频换成假对象：只验证流程，不做真实解码（加速后高频 load/stop 会让 ffpyplayer 死锁）
from kivy.core.audio import SoundLoader
import components.kivy_player as kp_mod
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
kp_mod.SoundLoader = SoundLoader
kp_mod._load_beep = lambda path: FakeSound(path)
# 所有短句都当作存在（sys/ 与 _短 还没录），时长压到极短让串播立刻衔接
_real_exists = audio_meta.exists
audio_meta.exists = lambda rel: bool(rel)
kp_mod._clip_len = lambda rel, sound: 0.01
kp_mod._CLIP_SLACK = 0.05          # FakeSound 不派发 on_stop，靠兜底推进，别等太久

# 2b) 视频换成假 Widget：加速后真实 ffpyplayer 在 setup 线程未完成时就被 unload，会在
#     _finish_setup→set_volume 访问已释放的播放器（access violation）。真实 App 1 秒一 tick 不会触发。
#     文件是否存在仍由 _show_video 的 os.path.isfile 把关，这里只记录被展示过的视频路径。
from kivy.uix.widget import Widget
shown_videos = []    # 所有被 _show_video 创建过的视频路径（相对 video/，正斜杠）
class FakeVideo(Widget):
    def __init__(self, source=None, state='stop', options=None, fit_mode='contain', **kw):
        super().__init__(**kw)
        self.source = source; self.state = state; self.options = options or {}; self.fit_mode = fit_mode
        shown_videos.append(os.path.relpath(source, ws_mod._VIDEO_DIR).replace('\\', '/'))
    def unload(self): pass
ws_mod.GuideVideo = FakeVideo

from kivy.clock import Clock
import main as app_main
from data import history
from data.workouts import get_durations, get_goals, AUTO, DETAILED, SHORT
from core.engine import REST_CLIP
from core.session_files import SessionFiles
from core import service_loop
from screens.workout_session import ServiceSession, LocalSession
import threading

# 3) 训练记录写到临时目录
TMP = tempfile.mkdtemp(prefix='subway_e2e_')
HIST = os.path.join(TMP, 'history.json')
history.set_path(HIST)

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

def freeze(ws):
    """停掉本地会话的 tick（等价于旧版 ws.timer.stop()），便于同步检查。"""
    ws.session._cancel_ticker()

def jump(ws, i):
    """直接跳到第 i 段并冻结：旧版 jump(ws, i)"""
    e = ws.session.engine
    e.seg_index = i; e._start_segment(); ws.session._notify(); freeze(ws)

class App(app_main.SubwaySportApp):
    inst = None
    @classmethod
    def stop_app(cls): cls.inst.stop()

    def on_start(self):
        App.inst = self
        sm = self.root
        home = sm.get_screen('home'); ws = sm.get_screen('workout')
        ws.player.set_beep_volume(0)
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
                    state['clips'].update(ws.player.last_clips)
                    ex = ws.exercises[seg['ex']]
                    if ex.get('audio') and ex['audio'] in ws.player.last_clips:
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
            shown = [w.text for w in home.plan_card.walk() if hasattr(w, 'text') and w.text.startswith('约 ')]
            check("切模式后卡片分钟数跟着方案变", shown == [f'约 {home.plan.minutes} 分钟'], (shown, home.plan.minutes, state['total1']))
            home._select_mode(AUTO)
            home._start_workout()
            check("进入训练页", sm.current == 'workout', sm.current)
            first = home.plan.entries[0]
            check("首段是 guide", ws.segment['kind'] == 'guide', ws.segment['kind'])
            check("第一个条目", ws.exercise_label.text == first['name'], ws.exercise_label.text)
            check("详细：首段直接播完整讲解（不播 下一个）", ws.player.last_clips == [first['audio']], ws.player.last_clips)
            check("详细：首段是热身 准备，时长 ≥ 讲解时长 且 ≥ duration", first.get('warmup') and ws.status_label.text == '准备'
                  and ws.segment['secs'] >= max(audio_meta.duration(first['audio']) or 0, first['duration']),
                  (ws.status_label.text, ws.segment['secs']))
            check("热身段提示 边听边摆好姿势 + 下一个动作", ws.next_lbl.text.startswith('边听边摆好姿势') and ws.exercises[1]['name'] in ws.next_lbl.text, ws.next_lbl.text)
            check("热身后直接是第一个动作的 guide（没有 开始 + 再站 10 秒）",
                  ws.timeline[1]['kind'] == 'guide' and ws.timeline[1]['ex'] == 1, ws.timeline[1])
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
            check("完成时播 训练完成", ws.player.last_clips == ['sys/训练完成.mp3'], ws.player.last_clips)
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
            freeze(ws)
            tl = ws.timeline
            i = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and i + 1 < len(tl) and tl[i + 1]['kind'] == 'rest')
            jump(ws, i)
            ws._on_next_press()
            check("跳过一组：连带跳过休息", ws.seg_index == i + 2 and ws.segment['kind'] != 'rest', f"{i}->{ws.seg_index} {ws.segment['kind']}")
            g = next(i for i, sg in enumerate(tl) if sg['kind'] == 'guide' and i > 0)
            jump(ws, g)
            check("后续 guide 播 下一个 + 短提示", ws.player.last_clips[0] == 'sys/下一个.mp3' and len(ws.player.last_clips) == 2, ws.player.last_clips)
            check("后续 guide 状态为 下一个", ws.status_label.text == '下一个', ws.status_label.text)
            ws._on_next_press()
            check("跳过 guide：直接进 set", ws.segment['kind'] == 'set' and ws.segment['set'] == 0, ws.segment)
            check("简短模式：第一组不播讲解", ws.player.last_clips == ['sys/开始.mp3'], ws.player.last_clips)
            r = next(i for i, sg in enumerate(tl) if sg['kind'] == 'rest')
            jump(ws, r)
            check("休息段播 放松提示", ws.player.last_clips == [REST_CLIP], ws.player.last_clips)
            ws._on_next_press()
            check("跳过休息：进入下一组", ws.seg_index == r + 1 and ws.segment['kind'] == 'set', ws.segment)
            # 串播：缺失文件被跳过；自然播完（on_stop）推进到下一段
            audio_meta.exists = _real_exists
            freeze(ws)
            have = next(rel for rel in (e.get('audio') for e in ws.exercises) if rel and _real_exists(rel))
            del played[:]
            kp_mod._clip_len = lambda rel, sound: 100     # 兜底不触发，只靠 on_stop
            ws.player.play_sequence(['sys/不存在.mp3', have, 'sys/也不存在.mp3', have])
            check("串播：缺失的直接跳过，先播存在的", played == [have] and ws.player._current_sound is not None, played)
            ws.player._current_sound.fire_stop()
            def after_stop(dt):
                check("串播：on_stop 后 0.3 秒播下一段", played == [have, have], played)
                check("串播：播完的 Sound 已 unload", len(unloaded) >= 1)
                audio_meta.exists = lambda rel: bool(rel)
                kp_mod._clip_len = lambda rel, sound: 0.01
                ws.session.engine.seg_index = 0; ws.session.start()
                observe()
                wait_until(lambda: ws._pct >= 0.2, step3, desc='跑到 20%')
            Clock.schedule_once(after_stop, kp_mod._CLIP_GAP + 0.3)

        def step3():
            state['ev'].cancel()
            check("简短模式：跑到 20% 没播过讲解", state['narrated_sets'] == 0 and state['narrated_guides'] == 0,
                  (state['narrated_sets'], state['narrated_guides']))
            ws._go_home()
            h = read_hist()
            check("<50% 退出：记录不变", h == state['hist_after_1'], f"{len(h)} 条")
            check("退出后没有待播事件", ws.player._seq_event is None and ws.player._loop_event is None and ws.player._current_sound is None)
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
            check("退出后音频/视频已清理", ws.player._current_sound is None and ws.player._loop_sound is None and ws._current_video is None)
            missing_v = [v for v in shown_videos if not os.path.isfile(os.path.join(ws_mod._VIDEO_DIR, v))]
            check("训练页实际加载过动作视频且文件都存在", len(set(shown_videos)) >= 5 and not missing_v, (len(set(shown_videos)), missing_v))
            Clock.schedule_once(step5b, 0.5)

        def step5b(dt):
            # 跳过最后一段：直接完成并记录
            home._select_duration(10); home._select_goal('力量训练')
            home._start_workout(); freeze(ws)
            jump(ws, len(ws.timeline) - 1)
            ws._on_next_press()
            check("跳过最后一段：训练完成", ws.workout_finished and ws.player.last_clips == ['sys/训练完成.mp3'], ws.player.last_clips)
            ws._on_next_press()
            check("完成后点按钮回首页", sm.current == 'home')
            Clock.schedule_once(step5c, 0.5)

        def step5c(dt):
            # 语音引导放在首页最前面，说明文字不依赖方案；每个部位一次只练一轮
            check("语音引导区在时长之前", home.root_box.children.index(home.mode_row) > home.root_box.children.index(home.duration_layout))
            home._select_mode(DETAILED)
            check("详细模式说明提到时长/内容会变", '讲解时间算进总时长' in home.mode_hint.text, home.mode_hint.text)
            home._select_mode(SHORT)
            check("简短模式说明提到能安排更多", '更多部位' in home.mode_hint.text, home.mode_hint.text)
            home._select_duration(25); home._select_goal('力量训练')
            check("25min 简短：每个部位只有一轮", all(c == 1 for _, c in home.plan.parts), home.plan.parts)
            home._select_mode(DETAILED)
            check("25min 详细：每个部位只有一轮", all(c == 1 for _, c in home.plan.parts), home.plan.parts)
            notes = [w.text for w in home.plan_card.walk() if hasattr(w, 'text') and '讲解时间' in w.text]
            check("方案卡片提醒内容受模式影响", len(notes) == 1, notes)
            home._select_mode(AUTO)
            Clock.schedule_once(step6, 0.5)

        def step6(dt):
            # 呼吸训练完整跑
            home._select_duration(10); home._select_goal('呼吸训练')
            ok("10min 呼吸 预览", home.plan.summary)
            home._start_workout()
            freeze(ws)
            tl = ws.timeline
            main = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and ws.exercises[sg['ex']].get('audio_loop'))
            ex = ws.exercises[tl[main]['ex']]
            # 第 2 组 / 最后一组 短句
            jump(ws, main + 2)
            check("呼吸：第 2 组播 第2组", ws.player.last_clips == ['sys/第2组.mp3'], ws.player.last_clips)
            last = next(i for i, sg in enumerate(tl) if sg['kind'] == 'set' and sg['ex'] == tl[main]['ex'] and sg['set'] == ex['sets'] - 1)
            jump(ws, last)
            check("呼吸：最后一组播 最后一组", ws.player.last_clips == ['sys/最后一组.mp3'], ws.player.last_clips)
            # 讲解在 guide；第 1 组只播"开始"，紧接着循环音
            jump(ws, main - 1)
            check("呼吸：主循环前的 guide 播 下一个 + 指导语", ws.player.last_clips == ['sys/下一个.mp3', ex['audio']], ws.player.last_clips)
            del played[:]
            jump(ws, main)
            check("呼吸：第 1 组只请求 开始", ws.player.last_clips == ['sys/开始.mp3'], ws.player.last_clips)
            def after_clips(dt):
                check("呼吸：开始 已播放", played[:1] == ['sys/开始.mp3'], played)
                check("呼吸：开始 之后循环音已开始且 loop=True", ws.player._loop_sound is not None and ws.player._loop_sound.loop)
            def after_gap(dt):
                ws.session.engine.seg_index = 0; ws.session.start()
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
            check("呼吸：结束后循环音已停止", ws.player._loop_sound is None)
            ws._on_next_press()
            check("呼吸：返回首页", sm.current == 'home')
            Clock.schedule_once(step8, 0.3)

        # ---------------- ServiceSession 镜像：用线程模拟 Android 前台服务进程，走真实的 plan/state/cmd 文件协议
        svc = {'files': SessionFiles(os.path.join(TMP, 'svc')), 'threads': []}

        class SvcPlayer:
            """服务进程里的播放器替身：poll() 时立刻"播完"并触发 then。"""
            def __init__(self): self.last_clips = []; self._then = None; self._busy = False
            def play_sequence(self, clips, then=None): self.last_clips = list(clips); self._then = then; self._busy = True
            def start_loop(self, rel, delay=0): pass
            def beep(self, final=False): pass
            def stop(self): self._then = None; self._busy = False
            def poll(self):
                if self._busy:
                    self._busy = False; then, self._then = self._then, None
                    if then: then()
            def idle(self): return not self._busy

        def start_service_thread():
            files = svc['files']
            t = threading.Thread(target=service_loop.run, args=(files.read_plan(), SvcPlayer(), files), daemon=True)
            t.start(); svc['threads'].append(t)

        def use_service_session(plan, start_service, stop_service=lambda: None):
            ws._detach(); ws._prepare(plan)
            ws.session = ServiceSession(plan, on_change=ws._on_session_change, files=svc['files'], on_fail=ws._on_session_fail,
                                        start_service=start_service, stop_service=stop_service)
            sm.current = 'workout'
            ws.session.start()

        def step8(dt):
            home._select_duration(10); home._select_goal('力量训练'); home._select_mode(SHORT)
            svc['plan'] = home.plan
            use_service_session(home.plan, start_service_thread)
            check("服务镜像：会话类型 service", ws.session.kind == 'service', ws.session.kind)
            check("服务镜像：plan.json 已写、带 session", svc['files'].read_plan()['session'] == ws.session.session_id)
            wait_until(lambda: ws.session._confirmed and ws.exercise_label.text == svc['plan'].entries[0]['name'],
                       step8b, timeout=5, desc='服务上报状态并渲染')

        def step8b():
            check("服务镜像：首段 热身 guide 已渲染", ws.segment['kind'] == 'guide' and ws.status_label.text == '准备',
                  (ws.segment['kind'], ws.status_label.text))
            check("服务镜像：倒计时 = 段时长", ws.circular_progress.text == str(ws.segment['secs']), ws.circular_progress.text)
            svc['seg0'] = ws.seg_index
            ws._on_next_press()                         # → cmd.json skip（跳过热身 → 第一个动作的 guide）
            wait_until(lambda: ws.seg_index == svc['seg0'] + 1, step8b2, timeout=3, desc='skip 命令经文件生效')

        def step8b2():
            check("服务镜像：跳过热身后是第一个动作的 guide", ws.segment['kind'] == 'guide' and ws.status_label.text == '下一个',
                  (ws.segment['kind'], ws.status_label.text))
            svc['seg1'] = ws.seg_index
            ws._on_next_press()                         # 再跳一次 → set
            wait_until(lambda: ws.seg_index == svc['seg1'] + 1, step8c, timeout=3, desc='第二次 skip 经文件生效')

        def step8c():
            check("服务镜像：跳过后进入 set 并渲染", ws.segment['kind'] == 'set' and ws.status_label.text == '训练中',
                  (ws.segment['kind'], ws.status_label.text))
            svc['rem'] = ws.session.remaining
            wait_until(lambda: ws.session.remaining < svc['rem'], step8d, timeout=3, desc='服务每秒 tick 推进')

        def step8d():
            check("服务镜像：倒计时文字跟随服务状态", ws.circular_progress.text == str(ws.session.remaining),
                  (ws.circular_progress.text, ws.session.remaining))
            check("服务镜像：进度条 > 0", ws._pct > 0, ws._pct)
            n_before = len(played)
            ws._go_home()
            check("服务镜像：退出回首页", sm.current == 'home', sm.current)
            check("服务镜像：UI 进程自己没放过声音", len(played) == n_before, len(played) - n_before)
            t = svc['threads'][-1]
            def joined():
                t.join(0.01); return not t.is_alive()
            wait_until(joined, step9, timeout=4, desc='服务线程收到 stop 退出')

        def step9():
            check("服务镜像：退出后方案已撤、不会被误判为在跑", svc['files'].read_plan() is None and svc['files'].running_state() is None,
                  (svc['files'].read_plan(), svc['files'].read_state()))
            # 服务起了但一直没上报 → 超时后自动退回进程内会话（从当前段继续）
            ServiceSession.START_TIMEOUT = 0.5
            home._select_duration(10); home._select_goal('力量训练')
            use_service_session(home.plan, lambda: None)
            check("兜底：超时前仍是 service 会话", ws.session.kind == 'service')
            wait_until(lambda: ws.session.kind == 'local', step9b, timeout=4, desc='服务超时后退回进程内')

        def step9b():
            check("兜底：进程内会话已启动并渲染首个动作", ws.session.engine.started and ws.exercise_label.text == ws.exercises[0]['name'],
                  ws.exercise_label.text)
            check("兜底：进程内会话播了首段短句", bool(ws.player.last_clips), ws.player.last_clips)
            # 服务启动直接抛异常 → 立刻退回
            use_service_session(home.plan, lambda: (_ for _ in ()).throw(RuntimeError('no service')))
            check("兜底：启动抛异常立刻退回进程内", ws.session.kind == 'local', ws.session.kind)
            ws._go_home()
            check("兜底：退出回首页", sm.current == 'home')
            Clock.schedule_once(lambda d: self.stop(), 0.2)

        Clock.schedule_once(step0, 0.5)

try:
    App().run()
except Exception:
    fail("测试过程抛出异常", traceback.format_exc())
finally:
    print("\n".join(results))
    benign = ('Estimating duration', '改用进程内播放')      # 后者是兜底测试故意触发的
    warns = [w for w in kivy_warnings if not any(b in w for b in benign)]
    print(f"\nKivy 告警（排除已知无害）：{len(warns)}")
    for w in warns[:20]: print("  ", w)
    if errors:
        print("\n" + "\n".join(errors)); print("\nE2E FAILED"); sys.exit(1)
    print("\nE2E PASSED")
