"""Tests for ChatHandler — commands, permissions, Claude dispatch."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from aldricbot import memory
from aldricbot.chat_handler import THINKING_EMOTES, ChatHandler
from aldricbot.events import EventContext


@pytest.fixture
def handler():
    return ChatHandler()


# ── Remember command (any channel) ───────────────────────────────


@pytest.mark.parametrize("msg_type,prefix", [
    ("guild", "/g "),
    ("party", "/p "),
    ("raid", "/ra "),
    ("whisper", "/w Fenwick "),
])
def test_remember_routes_response_by_channel(handler, make_msg, default_ctx, mock_send_chat, msg_type, prefix):
    msg = make_msg(msg_type, "Fenwick", "Hey Aldric, remember that ICC is Thursday")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    # Fact should be stored
    facts = memory.load_server_memory()["facts"]
    assert len(facts) == 1
    assert facts[0]["text"] == "ICC is Thursday"
    assert facts[0]["added_by"] == "Fenwick"
    # Response should be routed correctly
    sent = mock_send_chat.call_args_list
    assert any(prefix in str(call) for call in sent)


def test_remember_does_not_call_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, remember that ICC is Thursday")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


# ── Forget server (any channel) ─────────────────────────────────


def test_forget_server_removes_fact(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.add_server_fact("ICC Thursday", "Fenwick")
    memory.add_server_fact("Grukk respecced", "Liora")
    # Claude returns index 0 to remove the first fact
    mock_claude(stdout="0")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget that ICC Thursday")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    facts = memory.load_server_memory()["facts"]
    assert len(facts) == 1
    assert facts[0]["text"] == "Grukk respecced"


def test_forget_server_no_facts(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget that ICC Thursday")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("nothing to forget" in t for t in sent_texts)


def test_forget_server_no_match(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.add_server_fact("ICC Thursday", "Fenwick")
    mock_claude(stdout="-1")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget that something else")
    handler.handle(msg, default_ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("do not recall" in t for t in sent_texts)


def test_forget_server_auth_error(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.add_server_fact("ICC Thursday", "Fenwick")
    mock_claude(stdout="not logged in", stderr="not logged in", returncode=1)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget that ICC Thursday")
    result = handler.handle(msg, default_ctx)
    assert result == "auth_error"


# ── Help (whisper only) ──────────────────────────────────────────


# ── About self (any channel) ──────────────────────────────────


def test_about_self_with_memory(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior who loves Ulduar.", **{"class": "Warrior", "level": 72, "friendliness": 3.0, "last_seen": "2026-03-12"})
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about myself")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Name: Fenwick" in t for t in sent)
    assert any("Class: Warrior" in t for t in sent)
    assert any("Level: 72" in t for t in sent)
    assert any("A warrior who loves Ulduar" in t for t in sent)


def test_about_self_no_memory(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("whisper", "Fenwick", "tell me about myself")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no record" in t for t in sent)


def test_about_self_does_not_call_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior.")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about myself")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


@pytest.mark.parametrize("msg_type,prefix", [
    ("guild", "/g "),
    ("party", "/p "),
    ("raid", "/ra "),
    ("whisper", "/w Fenwick "),
])
def test_about_self_routes_by_channel(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate, msg_type, prefix):
    seed_guildmate("Fenwick", summary="A warrior.")
    msg = make_msg(msg_type, "Fenwick", "Hey Aldric, tell me about myself")
    handler.handle(msg, default_ctx)
    sent = mock_send_chat.call_args_list
    assert any(prefix in str(call) for call in sent)


# ── World facts (any channel) ────────────────────────────────


def test_world_facts_with_facts(handler, make_msg, default_ctx, mock_send_chat):
    memory.add_server_fact("ICC Thursday at 8pm", "Grukk")
    memory.add_server_fact("Grukk respecced to DPS", "Liora")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me the world facts")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("ICC Thursday at 8pm" in t for t in sent)
    assert any("Grukk respecced to DPS" in t for t in sent)


def test_world_facts_no_facts(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me the world facts")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("nothing recorded" in t for t in sent)


def test_world_facts_does_not_call_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.add_server_fact("ICC Thursday", "Grukk")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me the world facts")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


@pytest.mark.parametrize("msg_type,prefix", [
    ("guild", "/g "),
    ("whisper", "/w Fenwick "),
])
def test_world_facts_routes_by_channel(handler, make_msg, default_ctx, mock_send_chat, msg_type, prefix):
    memory.add_server_fact("ICC Thursday", "Grukk")
    msg = make_msg(msg_type, "Fenwick", "Hey Aldric, tell me the world facts")
    handler.handle(msg, default_ctx)
    sent = mock_send_chat.call_args_list
    assert any(prefix in str(call) for call in sent)


# ── Help (any channel) ──────────────────────────────────────


@pytest.mark.parametrize("msg_type,prefix", [
    ("whisper", "/w Fenwick"),
    ("guild", "/g"),
    ("party", "/p"),
    ("raid", "/ra"),
])
def test_help_any_channel(handler, make_msg, default_ctx, mock_send_chat, msg_type, prefix):
    msg = make_msg(msg_type, "Fenwick", "Hey Aldric, help")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    assert mock_send_chat.call_count >= 3  # multiple help lines
    sent = mock_send_chat.call_args_list
    assert any(prefix in str(call) for call in sent)


# ── Forget self (any channel) ────────────────────────────────────


@pytest.mark.parametrize("msg_type,prefix", [
    ("guild", "/g "),
    ("party", "/p "),
    ("raid", "/ra "),
    ("whisper", "/w Fenwick "),
])
def test_forget_self_with_memory(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate, msg_type, prefix):
    seed_guildmate("Fenwick", summary="A warrior friend.")
    msg = make_msg(msg_type, "Fenwick", "Hey Aldric, forget about me")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    assert memory.load_guildmate("Fenwick") is None
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("forgotten" in t for t in sent_texts)
    assert any(prefix in str(call) for call in mock_send_chat.call_args_list)


def test_forget_self_no_memory(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget about me")
    handler.handle(msg, default_ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no memory" in t for t in sent_texts)


def test_forget_about_sender_name_triggers_self_forget(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
    """'forget about Fenwick' where sender IS Fenwick → self-forget."""
    seed_guildmate("Fenwick", summary="A warrior.")
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget about Fenwick")
    handler.handle(msg, default_ctx)
    assert memory.load_guildmate("Fenwick") is None


def test_forget_self_does_not_call_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Forget self from guild chat should NOT invoke Claude."""
    seed_guildmate("Fenwick", summary="A warrior.")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget about me")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


# ── Permission model: non-admin ─────────────────────────────────


def test_non_admin_cannot_delete_others(handler, make_msg, mock_send_chat, seed_guildmate):
    seed_guildmate("Grukk", summary="An orc warrior.")
    ctx = EventContext(auth_ok=True, admin_name=None)
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget about Grukk")
    handler.handle(msg, ctx)
    # Grukk's memory should still exist
    assert memory.load_guildmate("Grukk") is not None
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("not my place" in t for t in sent_texts)


def test_non_admin_with_admin_configured_still_denied(handler, make_msg, mock_send_chat, seed_guildmate):
    seed_guildmate("Grukk", summary="An orc warrior.")
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget about Grukk")
    handler.handle(msg, ctx)
    assert memory.load_guildmate("Grukk") is not None


# ── Permission model: admin ──────────────────────────────────────


def test_admin_forget_guildmate(handler, make_msg, mock_send_chat, seed_guildmate):
    seed_guildmate("Grukk", summary="An orc warrior.")
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, forget about Grukk")
    handler.handle(msg, ctx)
    assert memory.load_guildmate("Grukk") is None
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("forgotten Grukk" in t.lower() or "forgotten grukk" in t.lower() for t in sent_texts)


def test_admin_forget_nonexistent(handler, make_msg, mock_send_chat):
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, forget about Grukk")
    handler.handle(msg, ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no memory" in t for t in sent_texts)


def test_admin_forget_all(handler, make_msg, mock_send_chat, seed_guildmate):
    seed_guildmate("Fenwick")
    seed_guildmate("Grukk")
    seed_guildmate("Liora")
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, forget everything")
    handler.handle(msg, ctx)
    assert memory.load_guildmate("Fenwick") is None
    assert memory.load_guildmate("Grukk") is None
    assert memory.load_guildmate("Liora") is None


def test_admin_forget_all_facts(handler, make_msg, mock_send_chat):
    memory.add_server_fact("ICC Thursday", "Fenwick")
    memory.add_server_fact("Grukk respecced", "Liora")
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, forget all facts")
    handler.handle(msg, ctx)
    assert memory.load_server_memory() == {"facts": []}
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("2 facts" in t for t in sent_texts)


def test_admin_forget_all_facts_empty(handler, make_msg, mock_send_chat):
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, forget all facts")
    handler.handle(msg, ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("0 facts" in t for t in sent_texts)


def test_non_admin_forget_all_facts_falls_through(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Non-admin 'forget all facts' falls through to Claude."""
    mock_claude(stdout='{"commands": ["/w Fenwick I cannot do that."], "memory": null}')
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget all facts")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_called_once()


def test_forget_everything_no_admin_falls_through(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """With no admin configured, 'forget everything' is not an admin command."""
    mock_claude(stdout=json.dumps({"commands": ["/w Fenwick I cannot do that."], "memory": None}))
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget everything")
    handler.handle(msg, default_ctx)
    # Should have reached Claude (not treated as admin command)
    mock_claude.mock.assert_called_once()


# ── Claude dispatch ──────────────────────────────────────────────


def test_claude_normal_guild_flow(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout=json.dumps({
        "commands": ["/g By the Light, friend."],
        "memory": "A curious warrior who asks about the Light.",
    }))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about the Light", senderClass="Warrior", senderLevel=72)
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    # Command sent
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("By the Light" in t for t in sent_texts)
    # Memory updated
    gm = memory.load_guildmate("Fenwick")
    assert gm is not None
    assert gm["summary"] == "A curious warrior who asks about the Light."


def test_claude_legacy_list_format(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout=json.dumps(["/g Legacy response."]))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Legacy response" in t for t in sent_texts)


def test_claude_code_fenced_response(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    fenced = '```json\n{"commands": ["/g Fenced reply."], "memory": null}\n```'
    mock_claude(stdout=fenced)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Fenced reply" in t for t in sent_texts)


def test_claude_memory_field_updates_summary(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout=json.dumps({
        "commands": ["/g Aye."],
        "memory": "Fenwick is a paladin who asks about Arthas.",
    }))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about Arthas")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["summary"] == "Fenwick is a paladin who asks about Arthas."


def test_claude_null_memory_preserves_existing(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    seed_guildmate("Fenwick", summary="Original summary.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["summary"] == "Original summary."


def test_claude_unparseable_still_saves_metadata(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout="This is not JSON at all")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello", senderClass="Warrior")
    handler.handle(msg, default_ctx)
    # Metadata should still be saved even though response was unparseable
    gm = memory.load_guildmate("Fenwick")
    assert gm is not None
    assert gm["class"] == "Warrior"


# ── Auth degradation ─────────────────────────────────────────────


def test_auth_down_sends_fallback(handler, make_msg, mock_send_chat, mock_claude):
    ctx = EventContext(auth_ok=False)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about Ulduar")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    mock_claude.mock.assert_not_called()
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any(any(resp_fragment in t for resp_fragment in ("Auth Token Expired",)) for t in sent_texts)


def test_auth_error_from_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout="", stderr="not logged in", returncode=1)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about Ulduar")
    result = handler.handle(msg, default_ctx)
    assert result == "auth_error"


# ── Memory context injection ─────────────────────────────────────


def test_known_guildmate_memory_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior who loves Ulduar.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]  # last arg is the prompt string
    assert "A warrior who loves Ulduar" in prompt
    # Relationship tier phrasing (seed_guildmate defaults to times_spoken=3 → acquaintance)
    assert "a few times" in prompt


def test_unknown_guildmate_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "You have not met this person before" in prompt


def test_server_memory_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.add_server_fact("ICC Thursday at 8pm", "Grukk")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, when is the raid?")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Things you have been told to remember" in prompt
    assert "ICC Thursday at 8pm" in prompt


# ── Relationship tier in prompt ─────────────────────────────────


def test_sentence_limit_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Sentence limit guideline appears in the prompt for known guildmates."""
    seed_guildmate("Fenwick", summary="A warrior.", times_spoken=20)
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Keep this person's summary to 8 sentences" in prompt


def test_stranger_no_sentence_limit_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Strangers should not get a sentence limit directive."""
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Keep this person's summary" not in prompt


# ── Disposition / friendliness ─────────────────────────────────


def test_disposition_injected_when_not_neutral(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Non-neutral disposition is injected into the prompt."""
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=-4.0, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Hmph."], "memory": None, "friendliness": 0}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Cold" in prompt


def test_disposition_not_injected_when_neutral(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Neutral disposition is not injected into the prompt."""
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=0.0, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 0}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "disposition" not in prompt.lower()


@patch("aldricbot.memory.datetime")
def test_friendliness_delta_applied(mock_dt, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Claude's friendliness delta is scaled (×0.25) and saved."""
    mock_dt.now.return_value = datetime(2026, 3, 12)
    mock_dt.strptime = datetime.strptime
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=0.0, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 2}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["friendliness"] == 0.5  # raw 2 × 0.25 = 0.5


@patch("aldricbot.memory.datetime")
def test_friendliness_clamped_at_boundaries(mock_dt, handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Score is clamped to [-10, +10]."""
    mock_dt.now.return_value = datetime(2026, 3, 12)
    mock_dt.strptime = datetime.strptime
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=9.8, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 2}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["friendliness"] == 10.0  # 9.8 + 0.5 = 10.3, clamped to 10.0


def test_friendliness_delta_clamped(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Delta from Claude is clamped to [-2, +2] then scaled (×0.25)."""
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=0.0, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 5}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["friendliness"] == 0.5  # raw 5 → clamped 2 → scaled 0.5


def test_friendliness_backward_compatible(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Guildmates without a friendliness field default to 0."""
    seed_guildmate("Fenwick", summary="A warrior.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": -1}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["friendliness"] == -0.25  # raw -1 × 0.25 = -0.25


def test_friendliness_daily_cap(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Repeated interactions in the same day are capped at ±1.0 total."""
    seed_guildmate("Fenwick", summary="A warrior.", friendliness=0.0, last_seen="2026-03-12")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 2}))
    # Three interactions, each returning +2 (scaled to +0.5 each)
    for _ in range(3):
        msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
        handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["friendliness"] == 1.0  # 0.5 + 0.5 = 1.0 (cap), third has no effect


# ── Self-memory ─────────────────────────────────────────────────


def test_self_memory_injected_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """When self-memory exists, it appears in the Claude prompt."""
    memory.save_self_memory("I told Fenwick about my knee wound from Hillsbrad.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "self_memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Things you have said about yourself" in prompt
    assert "knee wound from Hillsbrad" in prompt


def test_no_self_memory_no_injection(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """When no self-memory exists, that section is absent from the prompt."""
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "self_memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Things you have said about yourself" not in prompt


def test_self_memory_saved_from_response(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Claude's self_memory field is persisted."""
    mock_claude(stdout=json.dumps({
        "commands": ["/g The Light guides us."],
        "memory": None,
        "self_memory": "I mentioned my scar from the fall of Lordaeron.",
    }))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, how did you get that scar?")
    handler.handle(msg, default_ctx)
    sm = memory.load_self_memory()
    assert sm["summary"] == "I mentioned my scar from the fall of Lordaeron."


def test_self_memory_null_preserves_existing(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """self_memory: null does not overwrite existing self-memory."""
    memory.save_self_memory("Existing self-memory about the knee.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "self_memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    sm = memory.load_self_memory()
    assert sm["summary"] == "Existing self-memory about the knee."


def test_self_memory_absent_field_preserves_existing(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Response without self_memory field at all preserves existing."""
    memory.save_self_memory("Existing self-memory.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    sm = memory.load_self_memory()
    assert sm["summary"] == "Existing self-memory."


def test_legacy_list_format_no_self_memory_crash(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Legacy list response format does not crash self-memory logic."""
    memory.save_self_memory("Pre-existing.")
    mock_claude(stdout=json.dumps(["/g Legacy response."]))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    sm = memory.load_self_memory()
    assert sm["summary"] == "Pre-existing."


# ── Thinking emote ─────────────────────────────────────────────


# ── Retry queue ────────────────────────────────────────────────


def test_transient_failure_queues_message(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Claude timeout queues the message for retry."""
    mock_claude.mock.return_value = None  # simulate timeout
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    result = handler.handle(msg, default_ctx)
    assert result == "transient_failure"
    assert len(handler._retry_queue) == 1


def test_retry_succeeds_removes_from_queue(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Successful retry removes message from the queue."""
    # First call fails
    mock_claude.mock.return_value = None
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    assert len(handler._retry_queue) == 1

    # Retry succeeds
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "friendliness": 0}))
    result = handler.process_retries(default_ctx)
    assert result == "ok"
    assert len(handler._retry_queue) == 0


def test_retry_max_attempts_drops_message(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """After MAX_RETRY_ATTEMPTS, the message is dropped."""
    mock_claude.mock.return_value = None
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    # Manually add with attempts at max - 1
    handler._retry_queue.append((msg, handler.MAX_RETRY_ATTEMPTS - 1))
    handler.process_retries(default_ctx)
    # Should be dropped, not re-queued
    assert len(handler._retry_queue) == 0
    # Should have sent a drop message
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("try again later" in t for t in sent)


def test_auth_error_not_queued(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Auth errors are not queued for retry."""
    mock_claude(stdout="", stderr="not logged in", returncode=1)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    result = handler.handle(msg, default_ctx)
    assert result == "auth_error"
    assert len(handler._retry_queue) == 0


def test_retry_queue_maxlen(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Queue overflow drops the oldest message."""
    mock_claude.mock.return_value = None
    for i in range(7):
        msg = make_msg("guild", "Fenwick", f"Hey Aldric, msg {i}", time=1000.0 + i)
        handler.handle(msg, default_ctx)
    assert len(handler._retry_queue) == 5


# ── Thinking emote ─────────────────────────────────────────────


def test_thinking_emote_sent_before_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """A thinking emote is sent before Claude is invoked."""
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    # First send_chat_command call should be a thinking emote
    first_call = mock_send_chat.call_args_list[0]
    assert first_call[0][0] in THINKING_EMOTES


def test_thinking_emote_not_sent_on_commands(handler, make_msg, default_ctx, mock_send_chat):
    """Commands like 'remember' should not trigger a thinking emote."""
    msg = make_msg("guild", "Fenwick", "Hey Aldric, remember that ICC is Thursday")
    handler.handle(msg, default_ctx)
    sent = [call[0][0] for call in mock_send_chat.call_args_list]
    assert not any(e in THINKING_EMOTES for e in sent)


# ── Nicknames ─────────────────────────────────────────────────


def test_nickname_in_prompt_when_familiar_has_one(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Nickname appears in the prompt for Familiar+ guildmates."""
    seed_guildmate("Fenwick", summary="A warrior.", nickname="the Scholar", times_spoken=20)
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert 'Your nickname for this person: "the Scholar"' in prompt


def test_nickname_absent_from_prompt_for_acquaintance(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Acquaintances should not get a nickname line."""
    seed_guildmate("Fenwick", summary="A warrior.", nickname="the Scholar")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Your nickname for this person" not in prompt


def test_nickname_absent_from_prompt_for_strangers(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Strangers should not get a nickname line."""
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Your nickname for this person" not in prompt


def test_nickname_response_saved_for_familiar(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Claude's nickname response is saved for Familiar+ guildmates."""
    seed_guildmate("Fenwick", summary="A warrior.", times_spoken=20)
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": "young one"}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["nickname"] == "young one"


def test_nickname_response_not_saved_for_acquaintance(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Claude's nickname response is ignored for Acquaintance tier."""
    seed_guildmate("Fenwick", summary="A warrior.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": "young one"}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm.get("nickname") is None


def test_null_nickname_does_not_overwrite(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    """Null nickname does not overwrite existing one."""
    seed_guildmate("Fenwick", summary="A warrior.", nickname="the Scholar", times_spoken=20)
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None, "nickname": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    gm = memory.load_guildmate("Fenwick")
    assert gm["nickname"] == "the Scholar"


def test_nickname_shown_in_about_self(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
    """Nickname appears in 'tell me about myself' output."""
    seed_guildmate("Fenwick", summary="A warrior.", nickname="the Scholar")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about myself")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("I call you: the Scholar" in t for t in sent)


def test_custom_character_name_in_prompt(handler, make_msg, mock_send_chat, mock_claude):
    """Custom character name appears in the Claude prompt instead of 'Aldric'."""
    ctx = EventContext(auth_ok=True, admin_name=None, character_name="Theron")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Theron, hello")
    handler.handle(msg, ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]
    assert "Respond in character as Theron." in prompt
    assert "Respond in character as Aldric." not in prompt


# ── Hide and seek ───────────────────────────────────────────


def test_hide_and_seek_status_active(handler, make_msg, default_ctx, mock_send_chat):
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 4500000})
    msg = make_msg("guild", "Fenwick", "Hey Aldric, are you hiding")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("450g" in t for t in sent)


def test_hide_and_seek_status_inactive(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, are you hiding")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("not hiding" in t for t in sent)


def test_hide_and_seek_status_no_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, are you hiding")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


def test_hide_and_seek_hints_with_hints(handler, make_msg, default_ctx, mock_send_chat):
    memory.save_hide_and_seek({
        "active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 4500000,
        "hints": ["The earth mourns here...", "Spires of a fallen prince..."],
    })
    msg = make_msg("guild", "Fenwick", "Hey Aldric, what are the hints")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Hint 1" in t for t in sent)
    assert any("Hint 2" in t for t in sent)


def test_hide_and_seek_hints_no_hints(handler, make_msg, default_ctx, mock_send_chat):
    memory.save_hide_and_seek({"active": True, "finders": [], "hints": []})
    msg = make_msg("guild", "Fenwick", "Hey Aldric, what are the hints")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("No hints" in t for t in sent)


def test_hide_and_seek_hints_no_active_game(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, what are the hints")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no hunt" in t.lower() for t in sent)


def test_hide_and_seek_hints_no_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    memory.save_hide_and_seek({"active": True, "finders": [], "hints": ["a hint"]})
    msg = make_msg("guild", "Fenwick", "Hey Aldric, what are the hints")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


def test_hide_and_seek_hint_request_generates_hint(handler, make_msg, mock_send_chat, mock_claude):
    """Hint request triggers Claude and sends a guild message."""
    memory.save_hide_and_seek({
        "active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000,
        "hint_count": 0, "hints": [],
    })
    mock_claude(stdout=json.dumps(["/g The earth here still mourns... 500g remains."]))
    ctx = EventContext(auth_ok=True, admin_name=None, zone="Western Plaguelands", sub_zone="Andorhal")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, give me a hint")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    mock_claude.mock.assert_called_once()
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("earth" in t.lower() for t in sent)
    # Hint should be stored
    hs = memory.load_hide_and_seek()
    assert hs["hint_count"] == 1
    assert len(hs["hints"]) == 1


def test_hide_and_seek_hint_request_no_active_game(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Hint request with no active game responds appropriately."""
    msg = make_msg("guild", "Fenwick", "Hey Aldric, give me a hint")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    mock_claude.mock.assert_not_called()
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no hunt" in t.lower() for t in sent)


def test_hide_and_seek_hint_request_max_hints(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Hint request after 5 hints responds that all hints are given."""
    memory.save_hide_and_seek({
        "active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 3000000,
        "hint_count": 5, "hints": ["h1", "h2", "h3", "h4", "h5"],
    })
    msg = make_msg("guild", "Fenwick", "Hey Aldric, give me a hint")
    result = handler.handle(msg, default_ctx)
    assert result == "ok"
    mock_claude.mock.assert_not_called()
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("all hints" in t.lower() for t in sent)


def test_hide_and_seek_hint_request_no_zone(handler, make_msg, mock_send_chat, mock_claude):
    """Hint request without zone data responds gracefully."""
    memory.save_hide_and_seek({
        "active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000,
        "hint_count": 0, "hints": [],
    })
    ctx = EventContext(auth_ok=True, admin_name=None, zone="")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, give me a hint")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    mock_claude.mock.assert_not_called()


def test_hide_and_seek_hint_request_auth_down(handler, make_msg, mock_send_chat, mock_claude):
    """Hint request with auth down sends fallback message."""
    memory.save_hide_and_seek({
        "active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000,
        "hint_count": 0, "hints": [],
    })
    ctx = EventContext(auth_ok=False, zone="Elwynn Forest")
    msg = make_msg("guild", "Fenwick", "Hey Aldric, give me a hint")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    mock_claude.mock.assert_not_called()
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Auth Token Expired" in t for t in sent)


def test_hide_and_seek_winners(handler, make_msg, default_ctx, mock_send_chat):
    memory.save_hide_and_seek({
        "active": False,
        "finders": [
            {"name": "Fenwick", "found_at": "...", "copper_given": 5000000},
            {"name": "Grukk", "found_at": "...", "copper_given": 4500000},
            {"name": "Fenwick", "found_at": "...", "copper_given": 4000000},
        ],
    })
    msg = make_msg("guild", "Fenwick", "Hey Aldric, who's won hide and seek")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("Fenwick" in t and "2 win" in t for t in sent)
    assert any("Grukk" in t and "1 win" in t for t in sent)


def test_hide_and_seek_winners_no_finders(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, who won")
    handler.handle(msg, default_ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("No one" in t for t in sent)


def test_hide_and_seek_winners_no_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, who won")
    handler.handle(msg, default_ctx)
    mock_claude.mock.assert_not_called()


def test_admin_start_hide_and_seek(handler, make_msg, mock_send_chat):
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, start hide and seek 500 gold")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    hs = memory.load_hide_and_seek()
    assert hs["active"] is True
    assert hs["reward_copper"] == 5000000
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("500g" in t for t in sent)


def test_admin_start_hide_and_seek_already_active(handler, make_msg, mock_send_chat):
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000})
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, start hide and seek 300 gold")
    handler.handle(msg, ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("already" in t.lower() for t in sent)
    # Reward unchanged
    hs = memory.load_hide_and_seek()
    assert hs["reward_copper"] == 5000000


def test_admin_stop_hide_and_seek(handler, make_msg, mock_send_chat):
    memory.save_hide_and_seek({"active": True, "finders": [], "reward_copper": 5000000, "current_reward_copper": 5000000})
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, stop hide and seek")
    result = handler.handle(msg, ctx)
    assert result == "ok"
    hs = memory.load_hide_and_seek()
    assert hs["active"] is False
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("stopped" in t.lower() or "called off" in t.lower() for t in sent)


def test_admin_stop_hide_and_seek_not_active(handler, make_msg, mock_send_chat):
    ctx = EventContext(auth_ok=True, admin_name="AdminGuy")
    msg = make_msg("whisper", "AdminGuy", "Hey Aldric, stop hide and seek")
    handler.handle(msg, ctx)
    sent = [str(c) for c in mock_send_chat.call_args_list]
    assert any("no hunt" in t.lower() for t in sent)


def test_thinking_emote_no_consecutive_repeats(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """The same emote should not appear twice in a row."""
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    emotes_sent = []
    for i in range(10):
        msg = make_msg("guild", "Fenwick", "Hey Aldric, hello", time=1000.0 + i)
        handler.handle(msg, default_ctx)
        # First call each cycle is the thinking emote
        emote = mock_send_chat.call_args_list[0][0][0]
        assert emote in THINKING_EMOTES
        emotes_sent.append(emote)
        mock_send_chat.reset_mock()
    # No two consecutive emotes should be the same
    for i in range(1, len(emotes_sent)):
        assert emotes_sent[i] != emotes_sent[i - 1]
