"""Tests for _parse_command in aldricbot.events."""

import pytest

from aldricbot.chat_handler import _parse_command


# ── Parametrized: command recognition ────────────────────────────

@pytest.mark.parametrize(
    "msg_text, msg_type, expected",
    [
        # Remember
        ("Fenwick: Hey Aldric, remember that ICC is Thursday", "guild", ("remember", "ICC is Thursday")),
        ("Fenwick: Hey Aldric, remember this: Grukk is tanking", "guild", ("remember", "Grukk is tanking")),
        ("Fenwick: Hey Aldric, don't forget that the bank alt is Sparky", "guild", ("remember", "the bank alt is Sparky")),
        ("Fenwick: Hey Aldric, do not forget that we need flasks", "guild", ("remember", "we need flasks")),
        # Forget server
        ("Fenwick: Hey Aldric, forget that ICC is Thursday", "guild", ("forget_server", "ICC is Thursday")),
        # Help (any channel)
        ("Fenwick: Hey Aldric, help", "whisper", ("help", "")),
        ("Fenwick: Hey Aldric, commands", "whisper", ("help", "")),
        ("Fenwick: Hey Aldric, what can I say to you?", "whisper", ("help", "")),
        ("Fenwick: Hey Aldric, help", "guild", ("help", "")),
        ("Fenwick: Hey Aldric, help", "party", ("help", "")),
        ("Fenwick: Hey Aldric, help", "raid", ("help", "")),
        # Forget self
        ("Fenwick: Hey Aldric, forget about me", "whisper", ("forget_self", "")),
        ("Fenwick: Hey Aldric, forget everything about me", "whisper", ("forget_self", "")),
        # Forget guildmate (admin parse only — permission checked elsewhere)
        ("Fenwick: Hey Aldric, forget about Grukk", "whisper", ("forget_guildmate", "Grukk")),
        # Forget all
        ("Fenwick: Hey Aldric, forget everything", "whisper", ("forget_all", "")),
        # Forget all facts
        ("Fenwick: Hey Aldric, forget all facts", "whisper", ("forget_all_facts", "")),
        # Whisper without "Hey Aldric" prefix — still works
        ("Fenwick: remember that the raid is at 8pm", "whisper", ("remember", "the raid is at 8pm")),
        ("Fenwick: help", "whisper", ("help", "")),
        ("Fenwick: forget about me", "whisper", ("forget_self", "")),
        ("Fenwick: forget that the raid is canceled", "whisper", ("forget_server", "the raid is canceled")),
        # Remember/forget from party and raid channels
        ("Fenwick: Hey Aldric, remember that we need more healers", "party", ("remember", "we need more healers")),
        ("Fenwick: Hey Aldric, forget that we need more healers", "raid", ("forget_server", "we need more healers")),
        # About self
        ("Fenwick: Hey Aldric, tell me about myself", "guild", ("about_self", "")),
        ("Fenwick: Hey Aldric, tell me about me", "guild", ("about_self", "")),
        ("Fenwick: tell me about myself", "whisper", ("about_self", "")),
        ("Fenwick: tell me about me", "whisper", ("about_self", "")),
        # World facts
        ("Fenwick: Hey Aldric, tell me the world facts", "guild", ("world_facts", "")),
        ("Fenwick: Hey Aldric, tell me the facts", "guild", ("world_facts", "")),
        ("Fenwick: Hey Aldric, what are the world facts", "guild", ("world_facts", "")),
        ("Fenwick: Hey Aldric, what are the facts", "guild", ("world_facts", "")),
        ("Fenwick: tell me the world facts", "whisper", ("world_facts", "")),
        ("Fenwick: tell me the facts", "whisper", ("world_facts", "")),
    ],
)
def test_command_recognition(msg_text, msg_type, expected):
    assert _parse_command(msg_text, msg_type) == expected


# ── Non-commands return None ─────────────────────────────────────

@pytest.mark.parametrize(
    "msg_text, msg_type",
    [
        # Guild without "Hey Aldric" prefix → not a command
        ("Fenwick: What's up everyone?", "guild"),
        ("Fenwick: remember that ICC is Thursday", "guild"),
        # Regular conversation with prefix
        ("Fenwick: Hey Aldric, what was the Second War like?", "guild"),
        # No colon separator
        ("Fenwick says hello", "whisper"),
        # Regular whisper conversation (not a command)
        ("Fenwick: Hey Aldric, how are you today?", "whisper"),
    ],
)
def test_non_commands_return_none(msg_text, msg_type):
    assert _parse_command(msg_text, msg_type) is None


# ── Priority ordering ────────────────────────────────────────────

def test_forget_everything_about_me_before_forget_everything():
    """'forget everything about me' must match forget_self, not forget_all."""
    result = _parse_command("Fenwick: Hey Aldric, forget everything about me", "whisper")
    assert result == ("forget_self", "")


def test_forget_about_me_before_forget_about_name():
    """'forget about me' must match forget_self, not forget_guildmate('me')."""
    result = _parse_command("Fenwick: Hey Aldric, forget about me", "whisper")
    assert result == ("forget_self", "")


def test_forget_all_facts_before_forget_everything():
    """'forget all facts' must match forget_all_facts, not forget_all."""
    result = _parse_command("Fenwick: Hey Aldric, forget all facts", "whisper")
    assert result == ("forget_all_facts", "")


def test_dont_forget_before_forget():
    """'don't forget that X' must match remember, not forget_server."""
    result = _parse_command("Fenwick: Hey Aldric, don't forget that we need flasks", "whisper")
    assert result == ("remember", "we need flasks")


def test_do_not_forget_before_forget():
    """'do not forget that X' must match remember, not forget_server."""
    result = _parse_command("Fenwick: Hey Aldric, do not forget that we need flasks", "whisper")
    assert result == ("remember", "we need flasks")


# ── Case insensitivity ───────────────────────────────────────────

def test_case_insensitive_hey_aldric():
    result = _parse_command("Fenwick: HEY ALDRIC, remember that X", "guild")
    assert result == ("remember", "X")


def test_case_insensitive_command():
    result = _parse_command("Fenwick: Hey Aldric, REMEMBER THAT the bank is full", "guild")
    assert result == ("remember", "the bank is full")


def test_hey_aldric_with_period():
    result = _parse_command("Fenwick: Hey Aldric. remember that X", "guild")
    assert result == ("remember", "X")


# ── About self vs about others ──────────────────────────────────

def test_tell_me_about_other_person_is_not_command():
    """'tell me about Grukk' is NOT a command — falls through to Claude."""
    assert _parse_command("Fenwick: Hey Aldric, tell me about Grukk", "guild") is None


def test_tell_me_about_myself_case_insensitive():
    result = _parse_command("Fenwick: Hey Aldric, TELL ME ABOUT MYSELF", "guild")
    assert result == ("about_self", "")


# ── Custom character name ────────────────────────────────────────


def test_custom_character_name_matches():
    """Commands using a custom character name are recognized."""
    result = _parse_command("Fenwick: Hey Theron, remember that ICC is Thursday", "guild", character_name="Theron")
    assert result == ("remember", "ICC is Thursday")


def test_custom_character_name_case_insensitive():
    """Custom character name matching is case-insensitive."""
    result = _parse_command("Fenwick: HEY THERON, remember that X", "guild", character_name="Theron")
    assert result == ("remember", "X")


def test_wrong_character_name_returns_none():
    """Using the wrong character name in guild chat returns None."""
    result = _parse_command("Fenwick: Hey Aldric, remember that X", "guild", character_name="Theron")
    assert result is None
