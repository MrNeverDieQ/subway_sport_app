import math

from .training_blocks import TRAINING_BLOCKS
from . import audio_meta

# 力量训练块的默认顺序（没有训练记录时的优先级）
_STRENGTH_BLOCKS = [
    "颈部强化训练",
    "臀腿隐形激活训练",
    "背部全域静态对抗训练",
    "胸部全域静态对抗训练",
]
_BREATH_BLOCK = "呼吸核心联动训练"

_SHORT = {
    "颈部强化训练": "颈部",
    "臀腿隐形激活训练": "臀腿",
    "背部全域静态对抗训练": "背部",
    "胸部全域静态对抗训练": "胸部",
    "呼吸核心联动训练": "呼吸",
}

_DURATIONS = [10, 15, 20, 25, 30]
_GOALS = ["力量训练", "呼吸训练"]

# ---------- 语音引导模式 ----------
#   详细引导：动作开始前先把完整讲解听完，再倒计时做动作（讲解时长计入训练时间）
#   简短提示：动作前只播"下一个 + 一句短提示"
#   自动：一个训练块完成 FAMILIAR_AFTER 次后，自动从详细切到简短
# 同一次训练里第二次出现的动作（循环第 2、3 轮）不再重复讲解，按简短处理。
AUTO, DETAILED, SHORT = "auto", "detailed", "short"
MODE_LABEL = {AUTO: "自动", DETAILED: "详细引导", SHORT: "简短提示"}
GUIDE_MIN_SECS = 5        # 动作之间至少留这么久，用来播"下一个 + 短提示"
GUIDE_EXTRA_SECS = 2      # 详细引导：讲解时长之外再留的余量（"下一个"短句 + 衔接间隔）
DEFAULT_GUIDE_SECS = 20   # 讲解音频时长未知（没跑 tools/audio_durations.py）时的估计值
FAMILIAR_AFTER = 3        # 一个训练块完成几次后，自动模式切到简短


def get_durations():
    return _DURATIONS


def get_goals(duration):
    return _GOALS


# ------------------------------------------------------------
# 时间线：训练的唯一时长口径，播放端按它逐段执行
#   guide  动作开始前：详细模式播完整讲解，简短模式播"下一个 + 短提示"
#   set    一组动作（只有倒计时和提示音，不再有讲解）
#   rest   同一动作的组间休息
# 规则：每个条目前都有一段 guide，长度 = max(上一个条目的 rest, 本段引导需要的时长)，
#       所以条目之间的休息被 guide 吸收，整个训练以 guide 开头、以 set 结尾。
# ------------------------------------------------------------

def guide_secs(entry, mode):
    """一个条目在该模式下的引导时长（不含吸收上一个 rest 的部分）。"""
    if mode == DETAILED and entry.get("audio"):
        d = audio_meta.duration(entry["audio"])
        base = int(math.ceil(d)) if d else DEFAULT_GUIDE_SECS
        return max(GUIDE_MIN_SECS, base + GUIDE_EXTRA_SECS)
    return GUIDE_MIN_SECS


def build_timeline(items, modes):
    """
    items: [(entry, block_name)]
    modes: {block_name: DETAILED | SHORT}
    返回 [{kind, ex, set, secs, mode}]，ex 是 items 的下标；mode 是这一段实际生效的模式。
    """
    timeline = []
    prev_rest = 0
    seen = set()
    for i, (e, block) in enumerate(items):
        mode = modes.get(block, DETAILED)
        key = (block, e["name"])
        if key in seen:
            mode = SHORT          # 同一次训练里已经讲过，不再重复
        seen.add(key)
        pre = max(prev_rest, guide_secs(e, mode))
        timeline.append({"kind": "guide", "ex": i, "set": 0, "secs": pre, "mode": mode})
        for k in range(e["sets"]):
            timeline.append({"kind": "set", "ex": i, "set": k, "secs": e["duration"], "mode": mode})
            if k < e["sets"] - 1 and e["rest"] > 0:
                timeline.append({"kind": "rest", "ex": i, "set": k, "secs": e["rest"], "mode": mode})
        prev_rest = e["rest"]
    return timeline


def timeline_secs(items, modes):
    return sum(s["secs"] for s in build_timeline(items, modes))


def _expand(block, circuits):
    return block.get("warmup", []) + block["exercises"] * circuits + block.get("cooldown", [])


def _items_for(parts):
    """parts: [(block_name, circuits)] → [(entry, block_name)]"""
    items = []
    for name, c in parts:
        items.extend((e, name) for e in _expand(TRAINING_BLOCKS[name], c))
    return items


def resolve_modes(block_names, mode, counts):
    """把用户选择（auto/detailed/short）落到每个训练块。"""
    counts = counts or {}
    out = {}
    for b in block_names:
        if mode == AUTO:
            out[b] = SHORT if counts.get(b, 0) >= FAMILIAR_AFTER else DETAILED
        else:
            out[b] = mode
    return out


class Plan:
    """一次训练的完整方案：时间线 + 用于展示和记录的元信息。"""

    def __init__(self, goal, items, parts, modes, mode_choice):
        self.goal = goal
        self.items = items                                # [(entry, block_name)]
        self.entries = [e for e, _ in items]
        self.blocks = []                                  # 包含的训练块名（去重、保序）
        for _, b in items:
            if b not in self.blocks:
                self.blocks.append(b)
        self.parts = parts                                # [(展示名, 数量)]
        self.modes = modes                                # {block_name: DETAILED|SHORT}
        self.mode_choice = mode_choice                    # 用户选的 AUTO/DETAILED/SHORT
        self.timeline = build_timeline(items, modes)
        self.total_secs = sum(s["secs"] for s in self.timeline)
        self.minutes = max(1, round(self.total_secs / 60))
        self.total_sets = sum(e["sets"] for e in self.entries)
        label = " + ".join(n + (f"×{c}" if c > 1 else "") for n, c in parts)
        self.summary = f"{label}  ·  约 {self.minutes} 分钟"

    @property
    def mode_label(self):
        """本次实际生效的语音模式，各块不一致时逐块列出。"""
        kinds = {self.modes[b] for b in self.blocks}
        if len(kinds) == 1:
            return MODE_LABEL[kinds.pop()]
        return " · ".join(f"{_SHORT.get(b, b)}{'简短' if self.modes[b] == SHORT else '详细'}"
                          for b in self.blocks)


def build_plan(duration, goal, history=None, counts=None, mode=AUTO):
    """
    duration: 分钟
    goal:     力量训练 / 呼吸训练
    history:  {训练块名: 上次训练时间戳}，用于轮换
    counts:   {训练块名: 完成次数}，用于自动选择语音模式
    mode:     AUTO / DETAILED / SHORT
    """
    target = duration * 60
    if goal == "呼吸训练":
        return _build_breath(target, counts, mode)
    return _build_strength(target, history or {}, counts, mode)


# ------------------------------------------------------------
# 力量训练：覆盖优先、深度补足
#   1. 按"最久没练的排前面"给训练块排序（没练过的最优先，同级按默认顺序）
#   2. 第一轮：每个块先放 1 轮，按顺序能放就放，保证训练部位多样
#   3. 第二轮：反复给"能放下且增量最大"的块加 1 轮（不超过块定义的 circuit_sets）
#   时长按时间线算，详细模式下讲解时间也算在内（新手少练多听）；一个块都放不下时取最短的那个
# ------------------------------------------------------------

def _order_blocks(history):
    return sorted(
        _STRENGTH_BLOCKS,
        key=lambda n: (history.get(n, 0), _STRENGTH_BLOCKS.index(n)),
    )


def _build_strength(target, history, counts, mode):
    order = _order_blocks(history)
    modes = resolve_modes(_STRENGTH_BLOCKS, mode, counts)
    circuits = {}

    def total_for(circ):
        parts = [(n, circ[n]) for n in order if n in circ]
        return timeline_secs(_items_for(parts), modes)

    for name in order:
        trial = dict(circuits, **{name: 1})
        if total_for(trial) <= target:
            circuits = trial

    if not circuits:
        circuits = {min(order, key=lambda n: total_for({n: 1})): 1}

    while True:
        best = None
        for name, c in circuits.items():
            if c >= TRAINING_BLOCKS[name]["circuit_sets"]:
                continue
            trial = dict(circuits, **{name: c + 1})
            secs = total_for(trial)
            if secs <= target and (best is None or secs > best[1]):
                best = (name, secs)
        if best is None:
            break
        circuits[best[0]] += 1

    parts = [(n, circuits[n]) for n in order if n in circuits]
    items = _items_for(parts)
    return Plan("力量训练", items, [(_SHORT.get(n, n), c) for n, c in parts],
                {n: modes[n] for n, _ in parts}, mode)


# ------------------------------------------------------------
# 呼吸训练：按时长缩放主循环的组数，热身和放松固定
# ------------------------------------------------------------

def _build_breath(target, counts, mode):
    block = TRAINING_BLOCKS[_BREATH_BLOCK]
    modes = resolve_modes([_BREATH_BLOCK], mode, counts)
    warmup = block.get("warmup", [])
    cooldown = block.get("cooldown", [])
    main = block["exercises"][0]
    rest_ex = block["exercises"][1:]

    def items_for(sets):
        scaled = dict(main, sets=int(sets))
        return [(e, _BREATH_BLOCK) for e in warmup + [scaled] + rest_ex + cooldown]

    sets = 1
    while sets < 60 and timeline_secs(items_for(sets + 1), modes) <= target:
        sets += 1
    items = items_for(sets)
    return Plan("呼吸训练", items, [("呼吸循环", sets)], modes, mode)
