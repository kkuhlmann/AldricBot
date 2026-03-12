"""Cross-platform keyboard simulation for WoW interaction.

Uses pynput to send keystrokes to the WoW window for actions that
cannot go through SavedVariables (movement, /reload).
"""

from __future__ import annotations

import logging
import platform
import re
import subprocess
import time

from pynput.keyboard import Controller, Key

_log = logging.getLogger(__name__)

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


# Characters that require SHIFT on US keyboard layout
_SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '~': '`', '{': '[', '}': ']',
    '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.',
    '?': '/',
}

_SHIFT_SETTLE = 0.03  # seconds for SHIFT to register before/after base key


def _type_string(text: str) -> None:
    """Type a string character by character.

    Shifted characters (?, !, etc.) are typed with explicit SHIFT press/release
    and small delays so that games like WoW reliably register the modifier.
    """
    for char in text:
        if char in _SHIFT_MAP:
            _keyboard.press(Key.shift)
            time.sleep(_SHIFT_SETTLE)
            _keyboard.press(_SHIFT_MAP[char])
            _keyboard.release(_SHIFT_MAP[char])
            time.sleep(_SHIFT_SETTLE)
            _keyboard.release(Key.shift)
        elif char.isupper():
            _keyboard.press(Key.shift)
            time.sleep(_SHIFT_SETTLE)
            _keyboard.press(char.lower())
            _keyboard.release(char.lower())
            time.sleep(_SHIFT_SETTLE)
            _keyboard.release(Key.shift)
        else:
            _keyboard.press(char)
            _keyboard.release(char)
        time.sleep(_KEY_TAP_DELAY)


def send_reload() -> None:
    """Send /reload to WoW by typing Enter → /reload → Enter."""
    _activate_wow_window()
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(_CHAT_OPEN_DELAY)
    _type_string("/reload")
    time.sleep(_KEY_TAP_DELAY)
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)


def tap_key(key: str) -> None:
    """Tap a key once (press and release).

    Args:
        key: Single character key or 'space' for spacebar.
    """
    _activate_wow_window()
    if key == "space":
        _keyboard.press(Key.space)
        _keyboard.release(Key.space)
    else:
        _keyboard.press(key)
        _keyboard.release(key)


def send_chat_command(text: str) -> None:
    """Type a slash command directly into WoW's chat box and send it.

    Opens chat with Enter, types the text, then presses Enter to send.
    This bypasses SavedVariables entirely, avoiding the /reload overwrite race.
    """
    _activate_wow_window()
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(_CHAT_OPEN_DELAY)
    _type_string(text)
    time.sleep(_KEY_TAP_DELAY)
    _keyboard.press(Key.enter)
    _keyboard.release(Key.enter)
    time.sleep(0.1)  # brief pause before next command


# --- Chunk length validation ---

MAX_MACRO_LEN = 255

# Matches /g , /p , /ra , /w SenderName  at start of a command
_PREFIX_RE = re.compile(r"^(/(?:g|p|ra|w\s+\S+)\s)")


def _extract_prefix(command: str) -> tuple[str, str]:
    """Split a chat command into its prefix and body.

    Returns (prefix, body). If no known prefix is found, returns ("", command).
    """
    m = _PREFIX_RE.match(command)
    if m:
        return m.group(1), command[m.end():]
    return "", command


def _split_body(prefix: str, body: str) -> list[str]:
    """Split body into chunks that fit within MAX_MACRO_LEN when prefix is prepended."""
    max_body = MAX_MACRO_LEN - len(prefix)
    if max_body <= 0:
        return [prefix + body]  # prefix alone exceeds limit; send as-is

    chunks = []
    while body:
        if len(body) <= max_body:
            chunks.append(prefix + body)
            break
        # Find last space within the limit for a word-boundary split
        split_at = body.rfind(" ", 0, max_body)
        if split_at <= 0:
            # No space found — hard-cut at the limit
            split_at = max_body
        chunks.append(prefix + body[:split_at])
        body = body[split_at:].lstrip()
    return chunks


def validate_and_fix_chunks(commands: list[str]) -> list[str]:
    """Ensure every command string fits within WoW's 255-char macro limit.

    Commands that exceed the limit are re-split at word boundaries,
    preserving the chat prefix (/g, /p, /ra, /w Name) on each chunk.
    """
    result = []
    for cmd in commands:
        if len(cmd) <= MAX_MACRO_LEN:
            result.append(cmd)
            continue
        prefix, body = _extract_prefix(cmd)
        fixed = _split_body(prefix, body)
        _log.warning("Re-split oversized command (%d chars) into %d chunks", len(cmd), len(fixed))
        result.extend(fixed)
    return result
