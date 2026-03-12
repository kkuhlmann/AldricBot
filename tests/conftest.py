"""Shared fixtures for AldricBot tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aldricbot import memory
from aldricbot.events import EventContext


# ── Filesystem isolation ────────────────────────────────────────


@pytest.fixture(autouse=True)
def tmp_state_dir(tmp_path, monkeypatch):
    """Redirect all memory/state paths to a per-test temp directory."""
    guildmates_dir = tmp_path / "guildmates"
    guildmates_dir.mkdir()

    monkeypatch.setattr("aldricbot.memory.STATE_DIR", tmp_path)
    monkeypatch.setattr("aldricbot.memory.GUILDMATES_DIR", guildmates_dir)
    monkeypatch.setattr("aldricbot.memory.SERVER_MEMORY_FILE", tmp_path / "server_memory.json")

    monkeypatch.setattr("aldricbot.events.STATE_DIR", tmp_path)
    monkeypatch.setattr("aldricbot.events.LAST_EVENT_TIME_FILE", tmp_path / "last_event_time.txt")

    return tmp_path


# ── Input control mocks ─────────────────────────────────────────


@pytest.fixture
def mock_send_chat(monkeypatch):
    """Mock keyboard input — capture sent chat commands without typing."""
    mock = MagicMock()
    monkeypatch.setattr("aldricbot.input_control.send_chat_command", mock)
    monkeypatch.setattr("aldricbot.input_control._activate_wow_window", lambda: None)
    return mock


# ── Claude subprocess mock ───────────────────────────────────────


@pytest.fixture
def mock_claude(monkeypatch):
    """Mock subprocess.run in the events module.

    Returns a callable: mock_claude(stdout, stderr="", returncode=0)
    that configures what the next Claude call will return.
    The underlying MagicMock is available as mock_claude.mock.
    """
    mock = MagicMock()
    monkeypatch.setattr("aldricbot.events.subprocess.run", mock)

    def configure(stdout: str, stderr: str = "", returncode: int = 0):
        mock.return_value = subprocess.CompletedProcess(
            args=["claude"], returncode=returncode, stdout=stdout, stderr=stderr,
        )
        return mock

    configure.mock = mock
    return configure


# ── Message factories ────────────────────────────────────────────


@pytest.fixture
def make_msg():
    """Factory for building addon message dicts."""

    def _make(
        msg_type: str,
        sender: str,
        body: str,
        time: float = 1000.0,
        **kwargs,
    ) -> dict:
        if msg_type == "login":
            text = sender
        elif msg_type == "levelup":
            text = f"{sender}:{body}"
        elif msg_type == "achievement":
            text = f"{sender}: {body}"
        else:
            # guild, party, raid, whisper
            text = f"{sender}: {body}"

        msg = {"type": msg_type, "text": text, "time": time}
        for key in ("senderClass", "senderLevel", "senderZone", "senderRank", "senderNote", "senderOfficerNote"):
            if key in kwargs:
                msg[key] = kwargs[key]
        return msg

    return _make


# ── Context factory ──────────────────────────────────────────────


@pytest.fixture
def default_ctx():
    """Default EventContext with auth enabled and no admin."""
    return EventContext(auth_ok=True, admin_name=None)


# ── Guildmate seeding ────────────────────────────────────────────


@pytest.fixture
def seed_guildmate():
    """Factory to pre-populate a guildmate memory file."""

    def _seed(name: str, summary: str = "", **extra) -> dict:
        data = {
            "name": name,
            "first_seen": "2026-03-01",
            "last_seen": "2026-03-11",
            "times_spoken": 3,
            "summary": summary,
            **extra,
        }
        memory.save_guildmate(name, data)
        return data

    return _seed
