from .training_blocks import TRAINING_BLOCKS

# 力量训练按优先级拼接的顺序
_STRENGTH_PRIORITY = ["颈部强化训练", "臀腿隐形激活训练", "背部全域静态对抗训练", "胸部全域静态对抗训练"]

# 固定时长挡位（分钟）
_DURATIONS = [10, 15, 20, 25, 30]


def _exercise_secs(e):
    """单个 exercise 的实际播放时长：sets 组训练 + (sets-1) 组间休息。"""
    return e["duration"] * e["sets"] + e["rest"] * (e["sets"] - 1)


def _block_secs(block):
    """整个训练块展开后的实际总时长。"""
    parts = block.get("warmup", []) + block["exercises"] * block["circuit_sets"] + block.get("cooldown", [])
    if not parts:
        return 0
    total = 0
    for i, e in enumerate(parts):
        total += _exercise_secs(e)
        # 动作间休息（非最后一个动作）
        if i < len(parts) - 1:
            total += e["rest"]
    return total


def _expand(block):
    return block.get("warmup", []) + block["exercises"] * block["circuit_sets"] + block.get("cooldown", [])


def get_durations():
    return list(_DURATIONS)


def get_goals(duration):
    return ["力量训练", "呼吸训练"]


def get_exercises(duration, goal):
    if goal == "呼吸训练":
        return _expand(TRAINING_BLOCKS["呼吸核心联动训练"])

    # 力量训练：按优先级贪心拼接，时间不够时单独返回第一个能放下的块
    target = duration * 60
    result, elapsed = [], 0
    for name in _STRENGTH_PRIORITY:
        block = TRAINING_BLOCKS[name]
        secs = _block_secs(block)
        if elapsed + secs <= target:
            result.extend(_expand(block))
            elapsed += secs
    # 如果一个都放不下，直接返回优先级最高的块
    if not result:
        result = _expand(TRAINING_BLOCKS[_STRENGTH_PRIORITY[0]])
    return result
