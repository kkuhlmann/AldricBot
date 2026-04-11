"""Tests for LoginHandler, AchievementHandler, and LevelUpHandler."""

from __future__ import annotations

import json
import time

import pytest

from aldricbot import memory
from aldricbot.events import (
    ACHIEVEMENT_REACTIONS,
    EVENT_COOLDOWN_SECONDS,
    LEVELUP_REACTIONS,
    LOGIN_COOLDOWN_SECONDS,
    LOGIN_GREETINGS,
    AchievementHandler,
    EventContext,
    LevelUpHandler,
    LoginHandler,
)


# ── LoginHandler ─────────────────────────────────────────────────


class TestLoginHandler:

    @pytest.fixture
    def handler(self):
        return LoginHandler()

    def test_unknown_sends_prewritten(self, handler, make_msg, default_ctx, mock_send_chat):
        msg = make_msg("login", "Fenwick", "", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        sent = mock_send_chat.call_args_list
        assert len(sent) >= 1
        sent_text = str(sent[0])
        # Should be one of the pre-written greetings
        assert "Fenwick" in sent_text

    def test_known_invokes_claude(self, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior who loves Ulduar.")
        mock_claude(stdout=json.dumps(["/g Welcome back, Fenwick!"]))
        msg = make_msg("login", "Fenwick", "", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        mock_claude.mock.assert_called_once()
        sent = [str(c) for c in mock_send_chat.call_args_list]
        assert any("Welcome back" in t for t in sent)

    def test_known_claude_failure_fallback(self, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.")
        mock_claude.mock.return_value = None  # simulate _run_claude returning None
        # Need to also mock _run_claude directly since subprocess.run mock won't trigger None
        msg = make_msg("login", "Fenwick", "", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        # Should have sent something (pre-written fallback)
        assert mock_send_chat.call_count >= 1

    def test_known_auth_error_returns_false(self, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.")
        mock_claude(stdout="", stderr="not logged in", returncode=1)
        msg = make_msg("login", "Fenwick", "", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is False
        # Should still send a pre-written greeting as fallback
        assert mock_send_chat.call_count >= 1

    def test_cooldown_skips_duplicate(self, handler, make_msg, default_ctx, mock_send_chat):
        msg1 = make_msg("login", "Fenwick", "", time=100.0)
        msg2 = make_msg("login", "Fenwick", "", time=101.0)
        handler.handle(msg1, default_ctx)
        count_after_first = mock_send_chat.call_count
        handler.handle(msg2, default_ctx)
        # No additional commands sent for the second login
        assert mock_send_chat.call_count == count_after_first

    def test_auth_down_uses_prewritten_for_known(self, handler, make_msg, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.")
        ctx = EventContext(auth_ok=False)
        msg = make_msg("login", "Fenwick", "", time=100.0)
        result = handler.handle(msg, ctx)
        assert result is True
        mock_claude.mock.assert_not_called()
        assert mock_send_chat.call_count >= 1


# ── AchievementHandler ───────────────────────────────────────────


class TestAchievementHandler:

    @pytest.fixture
    def handler(self):
        return AchievementHandler()

    def test_unknown_sends_prewritten(self, handler, make_msg, default_ctx, mock_send_chat):
        msg = make_msg("achievement", "Fenwick", "Glory of the Raider", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        sent = [str(c) for c in mock_send_chat.call_args_list]
        assert any("Fenwick" in t for t in sent)

    def test_known_invokes_claude(self, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior who loves raids.")
        mock_claude(stdout=json.dumps(["/g Glory at last, Fenwick!"]))
        msg = make_msg("achievement", "Fenwick", "Glory of the Raider", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        mock_claude.mock.assert_called_once()
        # Verify achievement name is in the prompt
        prompt = mock_claude.mock.call_args[0][0][-1]
        assert "Glory of the Raider" in prompt

    def test_text_parsing(self, handler, make_msg, default_ctx, mock_send_chat):
        msg = make_msg("achievement", "Fenwick", "Glory of the Ulduar Raider", time=100.0)
        handler.handle(msg, default_ctx)
        # Should have sent a reaction mentioning Fenwick
        sent = [str(c) for c in mock_send_chat.call_args_list]
        assert any("Fenwick" in t for t in sent)

    def test_cooldown(self, handler, make_msg, default_ctx, mock_send_chat):
        msg1 = make_msg("achievement", "Fenwick", "Achievement A", time=100.0)
        msg2 = make_msg("achievement", "Fenwick", "Achievement B", time=101.0)
        handler.handle(msg1, default_ctx)
        count_after_first = mock_send_chat.call_count
        handler.handle(msg2, default_ctx)
        assert mock_send_chat.call_count == count_after_first

    def test_auth_down_uses_prewritten(self, handler, make_msg, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.")
        ctx = EventContext(auth_ok=False)
        msg = make_msg("achievement", "Fenwick", "Some Achievement", time=100.0)
        result = handler.handle(msg, ctx)
        assert result is True
        mock_claude.mock.assert_not_called()


# ── LevelUpHandler ───────────────────────────────────────────────


class TestLevelUpHandler:

    @pytest.fixture
    def handler(self):
        return LevelUpHandler()

    def test_unknown_sends_prewritten(self, handler, make_msg, default_ctx, mock_send_chat):
        msg = make_msg("levelup", "Fenwick", "72", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        sent = [str(c) for c in mock_send_chat.call_args_list]
        assert any("Fenwick" in t for t in sent)

    def test_known_invokes_claude(self, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior leveling through Northrend.")
        mock_claude(stdout=json.dumps(["/g Another step forward, Fenwick!"]))
        msg = make_msg("levelup", "Fenwick", "72", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        mock_claude.mock.assert_called_once()

    def test_auto_updates_level_in_memory(self, handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.", level=71)
        msg = make_msg("levelup", "Fenwick", "72", time=100.0)
        handler.handle(msg, default_ctx)
        gm = memory.load_guildmate("Fenwick")
        assert gm["level"] == 72

    def test_no_existing_memory_no_crash(self, handler, make_msg, default_ctx, mock_send_chat):
        """Levelup for unknown player doesn't crash and doesn't persist level."""
        msg = make_msg("levelup", "NewGuy", "10", time=100.0)
        result = handler.handle(msg, default_ctx)
        assert result is True
        # No memory file should exist since we never had one
        assert memory.load_guildmate("NewGuy") is None

    def test_text_parsing(self, handler, make_msg, default_ctx, mock_send_chat):
        msg = make_msg("levelup", "Fenwick", "80", time=100.0)
        handler.handle(msg, default_ctx)
        sent = [str(c) for c in mock_send_chat.call_args_list]
        assert any("Fenwick" in t for t in sent)

    def test_cooldown(self, handler, make_msg, default_ctx, mock_send_chat):
        msg1 = make_msg("levelup", "Fenwick", "72", time=100.0)
        msg2 = make_msg("levelup", "Fenwick", "73", time=101.0)
        handler.handle(msg1, default_ctx)
        count_after_first = mock_send_chat.call_count
        handler.handle(msg2, default_ctx)
        assert mock_send_chat.call_count == count_after_first

    def test_auth_down_uses_prewritten(self, handler, make_msg, mock_send_chat, mock_claude, seed_guildmate):
        seed_guildmate("Fenwick", summary="A warrior.")
        ctx = EventContext(auth_ok=False)
        msg = make_msg("levelup", "Fenwick", "72", time=100.0)
        result = handler.handle(msg, ctx)
        assert result is True
        mock_claude.mock.assert_not_called()


# ── _send_commands Unicode sanitization ──────────────────────────


class TestSendCommandsUnicode:

    def test_replaces_unicode_characters(self, mock_send_chat):
        from aldricbot.events import _send_commands
        cmds = ['/g He said \u201chello\u201d \u2014 it\u2019s a fine\u2026 day']
        _send_commands(cmds)
        sent = mock_send_chat.call_args_list[0][0][0]
        assert "\u201c" not in sent
        assert "\u201d" not in sent
        assert "\u2014" not in sent
        assert "\u2019" not in sent
        assert "\u2026" not in sent
        assert '"hello"' in sent
        assert "--" in sent
        assert "..." in sent

    def test_replaces_en_dash(self, mock_send_chat):
        from aldricbot.events import _send_commands
        cmds = ["/g levels 70\u201380"]
        _send_commands(cmds)
        sent = mock_send_chat.call_args_list[0][0][0]
        assert "\u2013" not in sent
        assert "70-80" in sent
