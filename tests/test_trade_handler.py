"""Tests for TradeHandler and complete_hide_and_seek_trade()."""

from __future__ import annotations

import pytest

from aldricbot import memory
from aldricbot.events import EventContext
from aldricbot.trade_handler import TradeHandler, complete_hide_and_seek_trade


@pytest.fixture
def handler():
    return TradeHandler()


@pytest.fixture
def active_game():
    """Set up an active hide-and-seek game."""
    memory.save_hide_and_seek({
        "active": True,
        "finders": [],
        "reward_copper": 5000000,
        "current_reward_copper": 4500000,
        "hint_count": 2,
        "hints": ["hint one", "hint two"],
    })


# ── Core trade flow ──────────────────────────────────────────


def test_trade_records_finder_and_deactivates(handler, make_msg, default_ctx, mock_send_chat, active_game):
    msg = make_msg("trade_complete", "Fenwick", "")
    result = handler.handle(msg, default_ctx)
    assert result is True
    hs = memory.load_hide_and_seek()
    assert hs["active"] is False
    assert len(hs["finders"]) == 1
    assert hs["finders"][0]["name"] == "Fenwick"
    assert hs["finders"][0]["copper_given"] == 4500000


def test_trade_guild_announcement(handler, make_msg, default_ctx, mock_send_chat, active_game):
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Fenwick has found me" in t for t in sent)
    assert any("450g" in t for t in sent)


def test_trade_addon_sync(handler, make_msg, default_ctx, mock_send_chat, active_game):
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("hideAndSeekActive = false" in t for t in sent)
    assert any("tradeCompletedWith = nil" in t for t in sent)
    assert any("tradePartnerName = nil" in t for t in sent)


# ── Not active / empty name ─────────────────────────────────


def test_trade_when_not_active_ignored(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("trade_complete", "Fenwick", "")
    result = handler.handle(msg, default_ctx)
    assert result is True
    mock_send_chat.assert_not_called()


def test_trade_empty_name_ignored(handler, make_msg, default_ctx, mock_send_chat, active_game):
    msg = {"type": "trade_complete", "text": "", "time": 1000.0}
    result = handler.handle(msg, default_ctx)
    assert result is True
    mock_send_chat.assert_not_called()


# ── Guildmate memory updates ────────────────────────────────


def test_trade_updates_finder_memory(handler, make_msg, default_ctx, mock_send_chat, active_game, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior.")
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["found_aldric_count"] == 1
    assert gm["nickname"] == "the Seeker"


def test_trade_preserves_existing_nickname(handler, make_msg, default_ctx, mock_send_chat, active_game, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior.", nickname="the Scholar")
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["nickname"] == "the Scholar"
    assert gm["found_aldric_count"] == 1


def test_trade_increments_found_count(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior.", found_aldric_count=2)
    # First game
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000})
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["found_aldric_count"] == 3


def test_trade_unknown_guildmate_no_crash(handler, make_msg, default_ctx, mock_send_chat, active_game):
    """Trade with unknown guildmate doesn't crash (no guildmate memory to update)."""
    msg = make_msg("trade_complete", "NewPlayer", "")
    result = handler.handle(msg, default_ctx)
    assert result is True
    hs = memory.load_hide_and_seek()
    assert hs["active"] is False


# ── Self-memory update ──────────────────────────────────────


def test_trade_updates_self_memory(handler, make_msg, default_ctx, mock_send_chat, active_game):
    msg = make_msg("trade_complete", "Fenwick", "")
    handler.handle(msg, default_ctx)
    sm = memory.load_self_memory()
    assert "Fenwick" in sm["summary"]
    assert "hide and seek" in sm["summary"]


# ── complete_hide_and_seek_trade() direct calls ─────────────


def test_direct_complete_records_and_deactivates(mock_send_chat, active_game):
    """Calling complete_hide_and_seek_trade() directly works the same as via handler."""
    complete_hide_and_seek_trade("Grom")
    hs = memory.load_hide_and_seek()
    assert hs["active"] is False
    assert hs["finders"][0]["name"] == "Grom"


def test_direct_complete_noop_when_inactive(mock_send_chat):
    """No-op when hide-and-seek is not active (double-processing safety)."""
    complete_hide_and_seek_trade("Grom")
    mock_send_chat.assert_not_called()


def test_direct_complete_noop_on_second_call(mock_send_chat, active_game):
    """Second call is a no-op — prevents duplicate announcements."""
    complete_hide_and_seek_trade("Grom")
    mock_send_chat.reset_mock()
    complete_hide_and_seek_trade("Grom")
    mock_send_chat.assert_not_called()


def test_direct_complete_clears_addon_flags(mock_send_chat, active_game):
    """The /script command clears all three addon flags."""
    complete_hide_and_seek_trade("Grom")
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("hideAndSeekActive = false" in t for t in sent)
    assert any("tradeCompletedWith = nil" in t for t in sent)
    assert any("tradePartnerName = nil" in t for t in sent)
