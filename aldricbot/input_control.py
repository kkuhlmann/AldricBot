"""Cross-platform keyboard simulation for WoW interaction.

Uses pynput to send keystrokes to the WoW window for actions that
cannot go through SavedVariables (movement, /reload).
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import time

from pynput.keyboard import Controller, Key

_keyboard = Controller()

# Timing constants
_KEY_TAP_DELAY = 0.05  # seconds between key taps
_CHAT_OPEN_DELAY = 0.15  # seconds after Enter to let chat box open


def _activate_wow_window() -> None:
    """Bring the WoW window to the foreground (best-effort)."""
    system = platform.system()
    if system == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "World of Warcraft" to activate'],
            capture_output=True,
            timeout=5,
        )
        time.sleep(0.3)
    elif system == "Linux":
        subprocess.run(
            ["wmctrl", "-a", "World of Warcraft"],
            capture_output=True,
            timeout=5,
        )
        time.sleep(0.3)
    # Windows: best-effort — pynput generally sends to foreground window


def _type_string(text: str) -> None:
    """Type a string character by character."""
    for char in text:
        _keyboard.press(char)
        _keyboard.release(char)
        time.sleep(_KEY_TAP_DELAY)


async def send_reload() -> None:
    """Send /reload to WoW by typing Enter → /reload → Enter."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_reload_sync)


def _send_reload_sync() -> None:
    _activate_wow_window()
    # Open chat
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(_CHAT_OPEN_DELAY)
    # Type /reload
    _type_string("/reload")
    time.sleep(_KEY_TAP_DELAY)
    # Send
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)


async def tap_key_async(key: str) -> None:
    """Tap a key once (press and release).

    Args:
        key: Single character key or 'space' for spacebar.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _tap_key_sync, key)


def _tap_key_sync(key: str) -> None:
    _activate_wow_window()
    if key == "space":
        _keyboard.press(Key.space)
        _keyboard.release(Key.space)
    else:
        _keyboard.press(key)
        _keyboard.release(key)


async def send_chat_command(text: str) -> None:
    """Type a slash command directly into WoW's chat box and send it.

    Opens chat with Enter, types the text, then presses Enter to send.
    This bypasses SavedVariables entirely, avoiding the /reload overwrite race.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_chat_command_sync, text)


def _send_chat_command_sync(text: str) -> None:
    _activate_wow_window()
    # Open chat
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(_CHAT_OPEN_DELAY)
    # Type the command
    _type_string(text)
    time.sleep(_KEY_TAP_DELAY)
    # Send
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(0.1)  # brief pause before next command
