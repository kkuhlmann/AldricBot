"""Tests for daemon helper functions (_resolve_bool_flag, _parse_cadence)."""

import os
import pytest

from daemon import (
    CYCLE_SECONDS,
    IDLE_EMOTE_MIN_CYCLES,
    IDLE_EMOTE_MAX_CYCLES,
    PROACTIVE_MIN_CYCLES,
    PROACTIVE_MAX_CYCLES,
    _resolve_bool_flag,
    _parse_cadence,
)


# --- _resolve_bool_flag ---


class TestResolveBoolFlag:
    def test_cli_true_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "false")
        assert _resolve_bool_flag(True, "ALDRICBOT_TEST_FLAG") is True

    def test_cli_false_overrides_env(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "true")
        assert _resolve_bool_flag(False, "ALDRICBOT_TEST_FLAG") is False

    def test_env_true(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "true")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is True

    def test_env_yes(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "yes")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is True

    def test_env_1(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "1")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is True

    def test_env_false(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "false")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is False

    def test_env_no(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "no")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is False

    def test_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ALDRICBOT_TEST_FLAG", "TRUE")
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is True

    def test_default_when_no_cli_or_env(self, monkeypatch):
        monkeypatch.delenv("ALDRICBOT_TEST_FLAG", raising=False)
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG") is True
        assert _resolve_bool_flag(None, "ALDRICBOT_TEST_FLAG", default=False) is False


# --- _parse_cadence ---


class TestParseCadence:
    def test_none_returns_defaults(self):
        assert _parse_cadence(None, 48, 72) == (48, 72)

    def test_valid_range(self):
        # 5-15 minutes -> cycles: 5*60/10=30, 15*60/10=90
        min_c, max_c = _parse_cadence("5-15", 48, 72)
        assert min_c == 5 * 60 // CYCLE_SECONDS
        assert max_c == 15 * 60 // CYCLE_SECONDS

    def test_single_minute_range(self):
        # 1-1 minutes -> cycles: 6, 6
        min_c, max_c = _parse_cadence("1-1", 48, 72)
        assert min_c == 1 * 60 // CYCLE_SECONDS
        assert max_c == 1 * 60 // CYCLE_SECONDS

    def test_large_range(self):
        # 120-240 minutes (proactive default)
        min_c, max_c = _parse_cadence("120-240", 720, 1440)
        assert min_c == 120 * 60 // CYCLE_SECONDS
        assert max_c == 240 * 60 // CYCLE_SECONDS

    def test_invalid_format_returns_defaults(self):
        assert _parse_cadence("bad", 48, 72) == (48, 72)

    def test_single_number_returns_defaults(self):
        assert _parse_cadence("10", 48, 72) == (48, 72)

    def test_three_parts_returns_defaults(self):
        assert _parse_cadence("5-10-15", 48, 72) == (48, 72)

    def test_zero_min_returns_defaults(self):
        assert _parse_cadence("0-10", 48, 72) == (48, 72)

    def test_negative_returns_defaults(self):
        assert _parse_cadence("-5-10", 48, 72) == (48, 72)

    def test_min_greater_than_max_returns_defaults(self):
        assert _parse_cadence("15-5", 48, 72) == (48, 72)

    def test_non_numeric_returns_defaults(self):
        assert _parse_cadence("foo-bar", 48, 72) == (48, 72)
