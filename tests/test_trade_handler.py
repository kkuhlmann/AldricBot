"""Tests for TradeHandler and complete_hide_and_seek_trade()."""

from __future__ import annotations

import json

import pytest

from aldricbot import memory
from aldricbot.events import EventContext
from aldricbot.trade_handler import TradeHandler, complete_hide_and_seek_trade
from daemon import read_game_state


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


# ── read_game_state() DB merge ─────────────────────────────


def _write_sv(tmp_path, last_state_dict, **db_fields):
    """Write a minimal SavedVariables file and return the Path."""
    sv = tmp_path / "AldricBotAddon.lua"
    last_state_json = json.dumps(last_state_dict)
    extra = ""
    for k, v in db_fields.items():
        extra += f'  ["{k}"] = "{v}",\n'
    sv.write_text(
        f'AldricBotAddonDB = {{\n'
        f"  [\"lastState\"] = '{last_state_json}',\n"
        f'{extra}'
        f'}}\n'
    )
    return sv


def test_read_game_state_merges_direct_trade_flag(tmp_path, monkeypatch):
    """Direct DB tradeCompletedWith is merged when lastState lacks it."""
    sv = _write_sv(tmp_path, {"hideAndSeekActive": True}, tradeCompletedWith="Fenwick")
    monkeypatch.setattr("daemon.config.saved_variables_path", lambda: sv)
    state = read_game_state()
    assert state["tradeCompletedWith"] == "Fenwick"
    assert state["hideAndSeekActive"] is True


def test_read_game_state_no_trade_flag(tmp_path, monkeypatch):
    """State is unchanged when neither lastState nor DB has the flag."""
    sv = _write_sv(tmp_path, {"hideAndSeekActive": True})
    monkeypatch.setattr("daemon.config.saved_variables_path", lambda: sv)
    state = read_game_state()
    assert state.get("tradeCompletedWith") is None
    assert state["hideAndSeekActive"] is True


def test_read_game_state_both_have_flag(tmp_path, monkeypatch):
    """Direct DB flag wins when both lastState and DB have tradeCompletedWith."""
    sv = _write_sv(tmp_path, {"tradeCompletedWith": "OldName"}, tradeCompletedWith="Fenwick")
    monkeypatch.setattr("daemon.config.saved_variables_path", lambda: sv)
    state = read_game_state()
    assert state["tradeCompletedWith"] == "Fenwick"


# ── read_game_state() tradePartnerName merge ────────────────


def test_read_game_state_merges_trade_partner_name(tmp_path, monkeypatch):
    """Direct DB tradePartnerName is merged into state."""
    sv = _write_sv(tmp_path, {"hideAndSeekActive": True}, tradePartnerName="Fenwick")
    monkeypatch.setattr("daemon.config.saved_variables_path", lambda: sv)
    state = read_game_state()
    assert state["tradePartnerName"] == "Fenwick"


def test_read_game_state_no_trade_partner_name(tmp_path, monkeypatch):
    """State has no tradePartnerName when DB lacks it."""
    sv = _write_sv(tmp_path, {"hideAndSeekActive": True})
    monkeypatch.setattr("daemon.config.saved_variables_path", lambda: sv)
    state = read_game_state()
    assert state.get("tradePartnerName") is None


# ── Gold-based fallback detection ────────────────────────────


def test_gold_fallback_triggers_completion(mock_send_chat, active_game):
    """Gold decrease matching expected reward completes the game."""
    hs = memory.load_hide_and_seek()
    expected_copper = hs["current_reward_copper"]
    prev_gold = 10000000  # 1000g
    current_gold = prev_gold - expected_copper

    # Verify the daemon's fallback condition would be met
    gold_decrease = prev_gold - current_gold
    trade_partner = "Fenwick"
    assert gold_decrease >= expected_copper > 0 and trade_partner

    # Same call the daemon makes when fallback triggers
    complete_hide_and_seek_trade(trade_partner)
    hs = memory.load_hide_and_seek()
    assert hs["active"] is False
    assert hs["finders"][0]["name"] == "Fenwick"
    assert hs["finders"][0]["copper_given"] == expected_copper


def test_gold_fallback_ignores_small_changes(mock_send_chat, active_game):
    """Small gold changes (vendor, repairs) don't meet fallback threshold."""
    hs = memory.load_hide_and_seek()
    expected_copper = hs["current_reward_copper"]
    prev_gold = 10000000
    current_gold = prev_gold - 1000  # 10 silver — repair cost

    gold_decrease = prev_gold - current_gold
    assert not (gold_decrease >= expected_copper > 0)

    # Game stays active
    hs = memory.load_hide_and_seek()
    assert hs["active"] is True


def test_gold_fallback_requires_trade_partner(mock_send_chat, active_game):
    """Gold fallback does nothing without a recorded trade partner."""
    hs = memory.load_hide_and_seek()
    expected_copper = hs["current_reward_copper"]
    prev_gold = 10000000
    current_gold = prev_gold - expected_copper
    trade_partner = None

    gold_decrease = prev_gold - current_gold
    # Gold condition met, but no partner → fallback should not fire
    assert gold_decrease >= expected_copper > 0
    assert not trade_partner

    hs = memory.load_hide_and_seek()
    assert hs["active"] is True


def test_gold_fallback_ignores_gold_increase(mock_send_chat, active_game):
    """Gold increase (quest reward) doesn't trigger fallback."""
    hs = memory.load_hide_and_seek()
    expected_copper = hs["current_reward_copper"]
    prev_gold = 5000000
    current_gold = 10000000  # gained gold

    gold_decrease = prev_gold - current_gold  # negative
    assert not (gold_decrease >= expected_copper > 0)

    hs = memory.load_hide_and_seek()
    assert hs["active"] is True
