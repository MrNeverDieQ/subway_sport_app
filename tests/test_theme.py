"""Tests for theme and timer (pure Python, no Kivy GUI required)."""
import pytest
from components.theme import fs, adaptive_fs, PRIMARY, ACCENT, BG


class TestTheme:
    def test_fs_returns_sp_string(self):
        assert fs(18) == "18sp"
        assert fs(0) == "0sp"

    def test_adaptive_fs_short_text(self):
        # Short text: no shrink
        assert adaptive_fs("hello", 22) == fs(22)

    def test_adaptive_fs_medium_text(self):
        # 21-30 chars: 0.85x
        text = "a" * 25
        assert adaptive_fs(text, 22) == fs(int(22 * 0.85))

    def test_adaptive_fs_long_text(self):
        # >30 chars: 0.75x
        text = "a" * 35
        assert adaptive_fs(text, 22) == fs(int(22 * 0.75))

    def test_adaptive_fs_empty(self):
        assert adaptive_fs("", 22) == fs(22)
        assert adaptive_fs(None, 22) == fs(22)

    def test_accent_equals_primary(self):
        assert ACCENT == PRIMARY

    def test_colors_are_rgba_tuples(self):
        for color in (PRIMARY, BG, ACCENT):
            assert len(color) == 4
            assert all(0 <= c <= 1 for c in color)
