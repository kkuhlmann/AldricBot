"""Tests for EventDispatcher — timestamp tracking, routing, and return values."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aldricbot.chat_handler import ChatHandler
from aldricbot.events import (
    AchievementHandler,
    EventContext,
    EventDispatcher,
    EventHandler,
    LevelUpHandler,
    LoginHandler,
)


@pytest.fixture
def mock_send_chat(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", mock)
    monkeypatch.setattr("aldricbot.input_control._activate_wow_window", lambda: None)
    return mock


class StubHandler(EventHandler):
    """Minimal handler that tracks calls and returns a configurable auth status."""

    def __init__(self, types: list[str], return_ok: bool = True):
        self.event_types = types
        self.return_ok = return_ok
        self.handled: list[dict] = []

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        self.handled.append(msg)
        return self.return_ok


# ── Timestamp tracking ───────────────────────────────────────────


def test_new_messages_dispatched():
    d = EventDispatcher()
    chat = StubHandler(["guild"])
    d.register(chat)

    state = {"chatMessages": [
        {"type": "guild", "text": "A: Hello", "time": 100.0},
        {"type": "guild", "text": "B: Hi", "time": 200.0},
    ]}
    ctx = EventContext(auth_ok=True)
    auth_ok, had = d.dispatch(state, ctx)
    assert had is True
    assert len(chat.handled) == 2
    assert d.chat_last_time == 200.0


def test_old_messages_skipped():
    d = EventDispatcher()
    chat = StubHandler(["guild"])
    d.register(chat)
    d._chat_last_time = 150.0

    state = {"chatMessages": [
        {"type": "guild", "text": "A: Old", "time": 100.0},
        {"type": "guild", "text": "B: New", "time": 200.0},
    ]}
    ctx = EventContext(auth_ok=True)
    d.dispatch(state, ctx)
    assert len(chat.handled) == 1
    assert chat.handled[0]["time"] == 200.0


def test_chat_and_event_timestamps_independent():
    """Login event uses event timestamp, not chat timestamp."""
    d = EventDispatcher()
    chat = StubHandler(["guild"])
    login = StubHandler(["login"])
    d.register(chat)
    d.register(login)
    d._chat_last_time = 500.0  # high chat timestamp

    state = {"chatMessages": [
        {"type": "login", "text": "Fenwick", "time": 100.0},
    ]}
    ctx = EventContext(auth_ok=True)
    d.dispatch(state, ctx)
    # Login at time 100 should still be dispatched (event timestamp is 0)
    assert len(login.handled) == 1


def test_event_timestamp_does_not_block_chat():
    d = EventDispatcher()
    chat = StubHandler(["guild"])
    login = StubHandler(["login"])
    d.register(chat)
    d.register(login)
    d._event_last_time = 500.0  # high event timestamp

    state = {"chatMessages": [
        {"type": "guild", "text": "A: Hello", "time": 100.0},
    ]}
    ctx = EventContext(auth_ok=True)
    d.dispatch(state, ctx)
    assert len(chat.handled) == 1


# ── Dispatch routing ─────────────────────────────────────────────


def test_guild_routes_to_chat_handler():
    d = EventDispatcher()
    chat = StubHandler(["guild", "party", "raid", "whisper"])
    login = StubHandler(["login"])
    d.register(chat)
    d.register(login)

    state = {"chatMessages": [{"type": "guild", "text": "A: Hi", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(chat.handled) == 1
    assert len(login.handled) == 0


def test_whisper_routes_to_chat_handler():
    d = EventDispatcher()
    chat = StubHandler(["guild", "party", "raid", "whisper"])
    login = StubHandler(["login"])
    d.register(chat)
    d.register(login)

    state = {"chatMessages": [{"type": "whisper", "text": "A: Hi", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(chat.handled) == 1


def test_login_routes_to_login_handler():
    d = EventDispatcher()
    chat = StubHandler(["guild", "party", "raid", "whisper"])
    login = StubHandler(["login"])
    d.register(chat)
    d.register(login)

    state = {"chatMessages": [{"type": "login", "text": "Fenwick", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(login.handled) == 1
    assert len(chat.handled) == 0


def test_achievement_routes_to_achievement_handler():
    d = EventDispatcher()
    achieve = StubHandler(["achievement"])
    d.register(achieve)

    state = {"chatMessages": [{"type": "achievement", "text": "Fenwick: Glory", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(achieve.handled) == 1


def test_levelup_routes_to_levelup_handler():
    d = EventDispatcher()
    level = StubHandler(["levelup"])
    d.register(level)

    state = {"chatMessages": [{"type": "levelup", "text": "Fenwick:72", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(level.handled) == 1


# ── Return value semantics ───────────────────────────────────────


def test_returns_had_messages_true():
    d = EventDispatcher()
    d.register(StubHandler(["guild"]))
    state = {"chatMessages": [{"type": "guild", "text": "A: Hi", "time": 100.0}]}
    auth_ok, had = d.dispatch(state, EventContext())
    assert had is True
    assert auth_ok is True


def test_returns_had_messages_false_empty():
    d = EventDispatcher()
    d.register(StubHandler(["guild"]))
    auth_ok, had = d.dispatch({}, EventContext())
    assert had is False
    assert auth_ok is True


def test_returns_had_messages_false_no_chat():
    d = EventDispatcher()
    d.register(StubHandler(["guild"]))
    state = {"chatMessages": []}
    auth_ok, had = d.dispatch(state, EventContext())
    assert had is False


def test_auth_failure_propagates():
    d = EventDispatcher()
    failing = StubHandler(["guild"], return_ok=False)
    d.register(failing)

    ctx = EventContext(auth_ok=True)
    state = {"chatMessages": [{"type": "guild", "text": "A: Hi", "time": 100.0}]}
    auth_ok, had = d.dispatch(state, ctx)
    assert auth_ok is False
    assert ctx.auth_ok is False
    assert had is True


# ── Timestamp persistence ────────────────────────────────────────


def test_timestamps_persist_to_disk(tmp_state_dir):
    d = EventDispatcher()
    d.register(StubHandler(["guild"]))
    d.register(StubHandler(["login"]))

    state = {"chatMessages": [
        {"type": "guild", "text": "A: Hi", "time": 123.0},
        {"type": "login", "text": "Fenwick", "time": 456.0},
    ]}
    d.dispatch(state, EventContext())

    # Create a new dispatcher and load from disk
    d2 = EventDispatcher()
    d2.load_timestamps()
    assert d2._chat_last_time == 123.0
    assert d2._event_last_time == 456.0


def test_load_timestamps_missing_files():
    """Loading timestamps when files don't exist defaults to 0."""
    d = EventDispatcher()
    d.load_timestamps()
    assert d._chat_last_time == 0.0
    assert d._event_last_time == 0.0


# ── Edge cases ───────────────────────────────────────────────────


def test_message_missing_type_ignored():
    d = EventDispatcher()
    chat = StubHandler(["guild"])
    d.register(chat)

    state = {"chatMessages": [{"text": "A: Hi", "time": 100.0}]}
    auth_ok, had = d.dispatch(state, EventContext())
    assert had is False
    assert len(chat.handled) == 0


def test_each_message_handled_by_one_handler():
    """A message should only be handled by the first matching handler."""
    d = EventDispatcher()
    h1 = StubHandler(["guild"])
    h2 = StubHandler(["guild"])
    d.register(h1)
    d.register(h2)

    state = {"chatMessages": [{"type": "guild", "text": "A: Hi", "time": 100.0}]}
    d.dispatch(state, EventContext())
    assert len(h1.handled) == 1
    assert len(h2.handled) == 0


# ── Event handler tier & disposition in prompts ──────────────────


_GUILDMATE = {
    "name": "Fenwick",
    "first_seen": "2026-01-01",
    "last_seen": "2026-03-12",
    "times_spoken": 20,
    "summary": "A curious warrior who asks about Ulduar.",
    "friendliness": 4.0,
    "class": "Warrior",
    "level": 72,
}

_WARM_TIER_PHRASING = (
    "Your disposition toward this person is Warm. "
    "You are friendlier than usual and volunteer extra detail."
)
_HOSTILE_TIER_PHRASING = (
    "Your disposition toward this person is Hostile. "
    "You refuse to help them and may call them out openly."
)


def _mock_claude_response(commands):
    """Create a mock subprocess result with valid JSON output."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps(commands)
    result.stderr = ""
    return result


@patch("aldricbot.events._run_claude")
@patch("aldricbot.events.memory")
def test_login_prompt_includes_warm_disposition(mock_memory, mock_run, mock_send_chat):
    """Login greeting prompt includes relationship tier and warm disposition."""
    mock_memory.load_guildmate.return_value = dict(_GUILDMATE)
    mock_memory.get_relationship_tier.return_value = (
        "familiar", 4, "You have spoken with this person many times: A curious warrior."
    )
    mock_memory.apply_friendliness_decay.return_value = 4.0
    mock_memory.get_disposition_tier.return_value = ("warm", _WARM_TIER_PHRASING)
    mock_run.return_value = _mock_claude_response(["/g Well met, Fenwick!"])

    handler = LoginHandler()
    ctx = EventContext(auth_ok=True)
    handler.handle({"type": "login", "text": "Fenwick", "time": 100.0}, ctx)

    prompt = mock_run.call_args[0][0]
    assert "You have spoken with this person many times" in prompt
    assert "Warm" in prompt
    assert "Adjust your tone based on your disposition" in prompt


@patch("aldricbot.events._run_claude")
@patch("aldricbot.events.memory")
def test_achievement_prompt_includes_hostile_disposition(mock_memory, mock_run, mock_send_chat):
    """Achievement reaction prompt includes hostile disposition."""
    guildmate = dict(_GUILDMATE, friendliness=-8.0)
    mock_memory.load_guildmate.return_value = guildmate
    mock_memory.get_relationship_tier.return_value = (
        "familiar", 4, "You have spoken with this person many times: A curious warrior."
    )
    mock_memory.apply_friendliness_decay.return_value = -8.0
    mock_memory.get_disposition_tier.return_value = ("hostile", _HOSTILE_TIER_PHRASING)
    mock_run.return_value = _mock_claude_response(["/g ...noted."])

    handler = AchievementHandler()
    ctx = EventContext(auth_ok=True)
    handler.handle({"type": "achievement", "text": "Fenwick: Glory of the Raider", "time": 100.0}, ctx)

    prompt = mock_run.call_args[0][0]
    assert "Hostile" in prompt
    assert "Stay in character" in prompt


@patch("aldricbot.events._run_claude")
@patch("aldricbot.events.memory")
def test_levelup_prompt_omits_neutral_disposition(mock_memory, mock_run, mock_send_chat):
    """Level-up reaction prompt omits disposition line when neutral."""
    guildmate = dict(_GUILDMATE, friendliness=0.0)
    mock_memory.load_guildmate.return_value = guildmate
    mock_memory.get_relationship_tier.return_value = (
        "familiar", 4, "You have spoken with this person many times: A curious warrior."
    )
    mock_memory.apply_friendliness_decay.return_value = 0.0
    mock_memory.get_disposition_tier.return_value = ("neutral", "Your disposition toward this person is Neutral.")
    mock_memory.save_guildmate.return_value = None
    mock_run.return_value = _mock_claude_response(["/g Well done, Fenwick."])

    handler = LevelUpHandler()
    ctx = EventContext(auth_ok=True)
    handler.handle({"type": "levelup", "text": "Fenwick:73", "time": 100.0}, ctx)

    prompt = mock_run.call_args[0][0]
    assert "You have spoken with this person many times" in prompt
    assert "Neutral" not in prompt
