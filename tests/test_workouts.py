"""Tests for data layer: workouts query logic and training_blocks integrity."""
import pytest
from data.training_blocks import TRAINING_BLOCKS
from data.workouts import (
    get_durations, get_goals, get_exercises, _block_secs, _exercise_secs, _expand,
)


# ------ training_blocks structure validation ------

REQUIRED_FIELDS = {"name", "duration", "sets", "rest"}


class TestTrainingBlocksIntegrity:
    """Verify every exercise in TRAINING_BLOCKS has required fields and sane values."""

    @pytest.mark.parametrize("block_name", list(TRAINING_BLOCKS.keys()))
    def test_block_has_required_keys(self, block_name):
        block = TRAINING_BLOCKS[block_name]
        assert "circuit_sets" in block and block["circuit_sets"] >= 1
        assert "exercises" in block and len(block["exercises"]) > 0

    @pytest.mark.parametrize("block_name", list(TRAINING_BLOCKS.keys()))
    def test_exercises_have_required_fields(self, block_name):
        block = TRAINING_BLOCKS[block_name]
        all_exercises = block.get("warmup", []) + block["exercises"] + block.get("cooldown", [])
        for ex in all_exercises:
            missing = REQUIRED_FIELDS - set(ex.keys())
            assert not missing, f"{block_name}/{ex.get('name','?')}: missing {missing}"
            assert ex["duration"] > 0, f"{ex['name']}: duration must be positive"
            assert ex["sets"] >= 1, f"{ex['name']}: sets must be >= 1"
            assert ex["rest"] >= 0, f"{ex['name']}: rest must be non-negative"


# ------ _exercise_secs ------

class TestExerciseSecs:
    def test_single_set_no_rest(self):
        assert _exercise_secs({"duration": 10, "sets": 1, "rest": 0}) == 10

    def test_single_set_with_rest(self):
        # 1 set -> 0 inter-set rests
        assert _exercise_secs({"duration": 10, "sets": 1, "rest": 5}) == 10

    def test_multi_set(self):
        # 3 sets of 20s + 2 inter-set rests of 10s = 60 + 20 = 80
        assert _exercise_secs({"duration": 20, "sets": 3, "rest": 10}) == 80


# ------ _block_secs ------

class TestBlockSecs:
    def test_all_blocks_positive(self):
        for name, block in TRAINING_BLOCKS.items():
            assert _block_secs(block) > 0, f"{name} has zero duration"

    def test_simple_block(self):
        block = {
            "circuit_sets": 1,
            "exercises": [
                {"duration": 10, "sets": 1, "rest": 5},
                {"duration": 10, "sets": 1, "rest": 5},
            ],
        }
        # ex1: 10s + between-exercise rest 5s + ex2: 10s = 25s
        assert _block_secs(block) == 25


# ------ get_durations / get_goals ------

class TestQueryFunctions:
    def test_durations_are_sorted(self):
        durations = get_durations()
        assert durations == sorted(durations)
        assert all(d > 0 for d in durations)

    def test_durations_returns_copy(self):
        d1 = get_durations()
        d1.append(999)
        assert 999 not in get_durations()

    def test_goals_always_has_options(self):
        for d in get_durations():
            goals = get_goals(d)
            assert len(goals) >= 1


# ------ get_exercises ------

class TestGetExercises:
    def test_breath_returns_exercises(self):
        exs = get_exercises(10, "呼吸训练")
        assert len(exs) > 0

    def test_strength_returns_exercises(self):
        for d in get_durations():
            exs = get_exercises(d, "力量训练")
            assert len(exs) > 0, f"No exercises for {d}min strength"

    def test_strength_fits_in_duration(self):
        """Greedy packing should not exceed target (except fallback)."""
        for d in get_durations():
            exs = get_exercises(d, "力量训练")
            total = 0
            for i, e in enumerate(exs):
                total += _exercise_secs(e)
                if i < len(exs) - 1:
                    total += e["rest"]
            # Allow fallback (single block may exceed target)
            # But should not exceed 2x target
            assert total <= d * 60 * 2, f"{d}min: total {total}s exceeds 2x target"

    def test_expand_matches_block_secs(self):
        """_expand + manual calc should equal _block_secs."""
        for name, block in TRAINING_BLOCKS.items():
            parts = _expand(block)
            total = 0
            for i, e in enumerate(parts):
                total += _exercise_secs(e)
                if i < len(parts) - 1:
                    total += e["rest"]
            assert total == _block_secs(block), f"{name}: expand={total} vs block_secs={_block_secs(block)}"
