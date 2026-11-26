"""
纯 Python 的方案/时间线单元测试（不依赖 Kivy，秒级跑完）。

    .venv\\Scripts\\python.exe tests\\test_plan.py
"""
import os, sys, io
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from data import workouts as W
from data.training_blocks import TRAINING_BLOCKS

errors = []
def check(desc, cond, detail=''):
    if not cond:
        errors.append(f'FAIL {desc}  {detail}')

def validate_timeline(tl, items, tag):
    check(f'{tag} 以 guide 开头', tl and tl[0]['kind'] == 'guide')
    check(f'{tag} 以 set 结尾', tl and tl[-1]['kind'] == 'set', tl[-1]['kind'] if tl else '')
    check(f'{tag} 没有 0 秒段', all(s['secs'] > 0 for s in tl))
    for i, s in enumerate(tl):
        if s['kind'] == 'rest':
            check(f'{tag} rest 前后都是同一动作的 set', tl[i - 1]['kind'] == 'set' and tl[i + 1]['kind'] == 'set'
                  and tl[i - 1]['ex'] == tl[i + 1]['ex'] == s['ex'])
    for i, (e, _) in enumerate(items):
        segs = [s for s in tl if s['ex'] == i]
        check(f'{tag} 条目{i} 恰好 1 段 guide', sum(1 for s in segs if s['kind'] == 'guide') == 1)
        g = [s for s in segs if s['kind'] == 'guide'][0]
        prev_rest = items[i - 1][0]['rest'] if i else 0
        if e.get('warmup'):
            # 热身"准备"：只有一段 guide（边听边摆姿势），没有 set，不再重复一遍
            check(f'{tag} 条目{i} 热身只有 1 段', len(segs) == 1, [s['kind'] for s in segs])
            check(f'{tag} 条目{i} 热身时长 = max(上一个 rest, 引导时长, duration)',
                  g['secs'] == max(prev_rest, W.guide_secs(e, g['mode']), e['duration']), g['secs'])
        else:
            check(f'{tag} 条目{i} set 数 = sets', sum(1 for s in segs if s['kind'] == 'set') == e['sets'])
            check(f'{tag} 条目{i} rest 数 = sets-1', sum(1 for s in segs if s['kind'] == 'rest') == (e['sets'] - 1 if e['rest'] else 0))
            check(f'{tag} 条目{i} guide 长度 = max(上一个 rest, 本模式引导时长)',
                  g['secs'] == max(prev_rest, W.guide_secs(e, g['mode'])), g['secs'])
        check(f'{tag} 条目{i} 各段 mode 一致', len({s['mode'] for s in segs}) == 1)

# 1) 全部 时长 × 目的 × 模式
for goal in W.get_goals(None):
    for d in W.get_durations():
        secs_by_mode = {}
        for mode in (W.AUTO, W.DETAILED, W.SHORT):
            p = W.build_plan(d, goal, history=None, counts=None, mode=mode)
            tag = f'[{goal} {d}min {mode}]'
            check(f'{tag} 不超时', p.total_secs <= d * 60, f'{p.total_secs} > {d*60}')
            # 时间用足：力量 = 没放进来的部位一个也塞不下（设计上不为填时间给同一部位加轮，所以不检查利用率）；
            #           呼吸 = 再加 1 组就超时
            if goal == '力量训练':
                unused = [b for b in W._STRENGTH_BLOCKS if b not in p.blocks]
                check(f'{tag} 剩余时间塞不进任何未练部位', all(
                    W.timeline_secs(p.items + W._items_for([(b, 1)]), dict(p.modes, **{b: W.resolve_modes([b], mode, None)[b]})) > d * 60
                    for b in unused), (p.total_secs, p.blocks))
            else:
                sets = p.parts[0][1]
                more = [(dict(e, sets=sets + 1) if e['name'].startswith('联动循环') else e, b) for e, b in p.items]
                check(f'{tag} 呼吸再加 1 组就超时', W.timeline_secs(more, p.modes) > d * 60, (p.total_secs, sets))
            check(f'{tag} total_secs = 时间线之和', p.total_secs == sum(s['secs'] for s in p.timeline))
            check(f'{tag} 每块都有模式', set(p.blocks) == set(p.modes))
            validate_timeline(p.timeline, p.items, tag)
            secs_by_mode[mode] = p.total_secs
            if mode != W.AUTO:
                check(f'{tag} 模式覆盖生效', all(m == mode for m in p.modes.values()), p.modes)
                check(f'{tag} mode_label', p.mode_label == W.MODE_LABEL[mode], p.mode_label)
            if mode == W.DETAILED:
                firsts = {}
                for sg in p.timeline:
                    if sg['kind'] != 'guide':
                        continue
                    e, b = p.items[sg['ex']]
                    key = (b, e['name'])
                    expect = W.SHORT if key in firsts else W.DETAILED
                    firsts.setdefault(key, True)
                    if sg['mode'] != expect:
                        check(f'{tag} 重复动作不再讲解', False, (key, sg['mode']))
                        break
                check(f'{tag} 详细 guide 含讲解时长', all(
                    sg['secs'] >= W.guide_secs(p.items[sg['ex']][0], W.DETAILED)
                    for sg in p.timeline if sg['kind'] == 'guide' and sg['mode'] == W.DETAILED))
        check(f'[{goal} {d}min] 没有记录时 自动 = 详细', secs_by_mode[W.AUTO] == secs_by_mode[W.DETAILED], secs_by_mode)
        pd = W.build_plan(d, goal, mode=W.DETAILED)
        short_modes = {b: W.SHORT for b in pd.modes}
        check(f'[{goal} {d}min] 同样的内容 详细 ≥ 简短 时长',
              pd.total_secs >= W.timeline_secs(pd.items, short_modes), (pd.total_secs, W.timeline_secs(pd.items, short_modes)))

# 1b) 热身：每个块的 warmup 条目带 warmup 标记，方案里只出现一段 准备，紧接着就是第一个动作的 guide
for goal in W.get_goals(None):
    p = W.build_plan(15, goal, mode=W.DETAILED)
    warm = [i for i, e in enumerate(p.entries) if e.get('warmup')]
    check(f'[{goal}] 每个块恰好 1 个热身', len(warm) == len(p.blocks), (warm, p.blocks))
    for i in warm:
        segs = [s for s in p.timeline if s['ex'] == i]
        check(f'[{goal}] 热身 {p.entries[i]["name"]} 只有 1 段 guide', [s['kind'] for s in segs] == ['guide'], segs)
        j = p.timeline.index(segs[0])
        check(f'[{goal}] 热身后直接是下一个动作的 guide', p.timeline[j + 1]['kind'] == 'guide' and p.timeline[j + 1]['ex'] == i + 1, p.timeline[j + 1])
    check(f'[{goal}] total_sets 不含热身', p.total_sets == sum(e['sets'] for e in p.entries if not e.get('warmup')))
    for b in TRAINING_BLOCKS.values():
        for e in b.get('warmup', []):
            check(f'原始数据不被改动: {e["name"]}', 'warmup' not in e)

# 2) 自动模式：练过 ≥ FAMILIAR_AFTER 次的块切简短，其余详细
counts = {'颈部强化训练': W.FAMILIAR_AFTER, '臀腿隐形激活训练': W.FAMILIAR_AFTER - 1}
p = W.build_plan(30, '力量训练', counts=counts, mode=W.AUTO)
check('自动：颈部→简短', p.modes.get('颈部强化训练') == W.SHORT, p.modes)
check('自动：臀腿→详细', p.modes.get('臀腿隐形激活训练') == W.DETAILED, p.modes)
check('自动：混合时 mode_label 逐块列出', '颈部简短' in p.mode_label and '臀腿详细' in p.mode_label, p.mode_label)
check('自动：mode_choice 记录用户选择', p.mode_choice == W.AUTO)

# 3) 轮换：最久没练的排最前
hist = {'颈部强化训练': 100, '臀腿隐形激活训练': 50, '背部全域静态对抗训练': 10}
p = W.build_plan(10, '力量训练', history=hist)
check('轮换：没练过的胸部排最前', p.blocks[0] == '胸部全域静态对抗训练', p.blocks)

# 4) 呼吸：组数随时长递增，热身/放松各 1
prev = 0
for d in W.get_durations():
    p = W.build_plan(d, '呼吸训练')
    sets = p.parts[0][1]
    check(f'呼吸 {d}min 组数不减', sets >= prev, sets)
    prev = sets
    names = [e['name'] for e in p.entries]
    check(f'呼吸 {d}min 结构 = 热身+主循环+放松', len(names) == 3 and names[1].startswith('联动循环'), names)

# 5) 力量：每个部位一次只练一轮（不为了填满时间给同一部位加轮）
for d in W.get_durations() + [60]:
    for mode in (W.DETAILED, W.SHORT):
        p = W.build_plan(d, '力量训练', mode=mode)
        check(f'力量 {d}min {W.MODE_LABEL[mode]}：每个部位最多 1 轮', all(c == 1 for _, c in p.parts), p.parts)
        check(f'力量 {d}min {W.MODE_LABEL[mode]}：部位不重复', len(p.blocks) == len(set(p.blocks)), p.blocks)

# 6) 时间线 secs 用的是训练块数据
e = TRAINING_BLOCKS['臀腿隐形激活训练']['exercises'][2]
tl = W.build_timeline([(e, '臀腿隐形激活训练')], {})
check('5 组动作：set 段时长', all(s['secs'] == e['duration'] for s in tl if s['kind'] == 'set'))
check('5 组动作：rest 段时长', all(s['secs'] == e['rest'] for s in tl if s['kind'] == 'rest'))

# 7) 引导时长：详细 = 讲解时长 + 余量（未知时取默认），简短 = 最小值；同一动作第二次出现按简短
from data import audio_meta
d = audio_meta.duration(e['audio'])
exp = max(W.GUIDE_MIN_SECS, (int(-(-d // 1)) if d else W.DEFAULT_GUIDE_SECS) + W.GUIDE_EXTRA_SECS)
check('详细引导时长 = ceil(讲解) + 余量', W.guide_secs(e, W.DETAILED) == exp, (W.guide_secs(e, W.DETAILED), d))
check('简短引导时长 = 最小值', W.guide_secs(e, W.SHORT) == W.GUIDE_MIN_SECS)
check('无音频条目：详细也只留最小值', W.guide_secs({'name': 'x', 'sets': 1, 'duration': 10, 'rest': 0}, W.DETAILED) == W.GUIDE_MIN_SECS)
tl2 = W.build_timeline([(e, 'B'), (e, 'B')], {'B': W.DETAILED})
guides = [s for s in tl2 if s['kind'] == 'guide']
check('同一动作第二次出现 → 简短', guides[0]['mode'] == W.DETAILED and guides[1]['mode'] == W.SHORT, [g['mode'] for g in guides])
check('第二次出现的 guide 吸收 rest', guides[1]['secs'] == max(e['rest'], W.GUIDE_MIN_SECS), guides[1]['secs'])

if errors:
    print('\n'.join(errors)); print(f'\nPLAN TESTS FAILED ({len(errors)})'); sys.exit(1)
for goal in W.get_goals(None):
    for d in W.get_durations():
        line = f'{goal} {d:>2}min'
        for mode in (W.DETAILED, W.SHORT):
            p = W.build_plan(d, goal, mode=mode)
            line += f'   {W.MODE_LABEL[mode]} {p.total_secs:>4}s {p.summary}'
        print(line)
print('\nPLAN TESTS PASSED')
