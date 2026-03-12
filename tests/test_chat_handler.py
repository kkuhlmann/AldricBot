"""Tests for ChatHandler — commands, permissions, Claude dispatch."""

from __future__ import annotations

import json

import pytest

from aldricbot import memory
from aldricbot.events import AUTH_DOWN_RESPONSES, ChatHandler, EventContext


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
    assert result is True
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
    assert result is True
    facts = memory.load_server_memory()["facts"]
    assert len(facts) == 1
    assert facts[0]["text"] == "Grukk respecced"


def test_forget_server_no_facts(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("guild", "Fenwick", "Hey Aldric, forget that ICC Thursday")
    result = handler.handle(msg, default_ctx)
    assert result is True
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
    assert result is False


# ── Help (whisper only) ──────────────────────────────────────────


def test_help_whisper(handler, make_msg, default_ctx, mock_send_chat):
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, help")
    result = handler.handle(msg, default_ctx)
    assert result is True
    assert mock_send_chat.call_count >= 3  # multiple help lines


def test_help_guild_falls_through_to_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    """Guild 'help' is not a command — it falls through to Claude."""
    mock_claude(stdout=json.dumps({"commands": ["/g I am here to help."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, help")
    handler.handle(msg, default_ctx)
    # Claude should have been called
    mock_claude.mock.assert_called_once()


# ── Forget self (whisper only) ───────────────────────────────────


def test_forget_self_with_memory(handler, make_msg, default_ctx, mock_send_chat, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior friend.")
    msg = make_msg("whisper", "Fenwick", "Hey Aldric, forget about me")
    result = handler.handle(msg, default_ctx)
    assert result is True
    assert memory.load_guildmate("Fenwick") is None
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any("forgotten" in t for t in sent_texts)


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
    assert result is True
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
    assert result is True
    mock_claude.mock.assert_not_called()
    sent_texts = [str(c) for c in mock_send_chat.call_args_list]
    assert any(any(resp_fragment in t for resp_fragment in ("Auth Token Expired",)) for t in sent_texts)


def test_auth_error_from_claude(handler, make_msg, default_ctx, mock_send_chat, mock_claude):
    mock_claude(stdout="", stderr="not logged in", returncode=1)
    msg = make_msg("guild", "Fenwick", "Hey Aldric, tell me about Ulduar")
    result = handler.handle(msg, default_ctx)
    assert result is False


# ── Memory context injection ─────────────────────────────────────


def test_known_guildmate_memory_in_prompt(handler, make_msg, default_ctx, mock_send_chat, mock_claude, seed_guildmate):
    seed_guildmate("Fenwick", summary="A warrior who loves Ulduar.")
    mock_claude(stdout=json.dumps({"commands": ["/g Aye."], "memory": None}))
    msg = make_msg("guild", "Fenwick", "Hey Aldric, hello")
    handler.handle(msg, default_ctx)
    prompt = mock_claude.mock.call_args[0][0][-1]  # last arg is the prompt string
    assert "You remember this person" in prompt
    assert "A warrior who loves Ulduar" in prompt


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
