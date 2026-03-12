"""Guildmate and server memory I/O for AldricBot.

Manages per-person JSON files and a shared server fact list.
All writes are atomic (temp file + rename) to prevent corruption.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".aldricbot"
GUILDMATES_DIR = STATE_DIR / "guildmates"
SERVER_MEMORY_FILE = STATE_DIR / "server_memory.json"

MAX_SERVER_FACTS = 20


# ── Guildmate Memory ──────────────────────────────────────────────


def _guildmate_path(name: str) -> Path:
    return GUILDMATES_DIR / f"{name}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_guildmate(name: str) -> dict | None:
    """Load a guildmate's memory file. Returns None if not found."""
    path = _guildmate_path(name)
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_guildmate(name: str, data: dict) -> None:
    """Save a guildmate's memory file atomically."""
    _atomic_write(_guildmate_path(name), data)


def delete_guildmate(name: str) -> bool:
    """Delete a single guildmate's memory. Returns True if file existed."""
    path = _guildmate_path(name)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def delete_all_guildmates() -> int:
    """Delete all guildmate memory files. Returns count of files removed."""
    count = 0
    if GUILDMATES_DIR.exists():
        for f in GUILDMATES_DIR.glob("*.json"):
            f.unlink()
            count += 1
    return count


def update_guildmate_metadata(name: str, msg: dict) -> dict:
    """Update a guildmate's metadata from addon message data.

    Creates a new record if the guildmate is unknown.
    Does NOT save — caller decides when to write.
    """
    data = load_guildmate(name) or {
        "name": name,
        "first_seen": datetime.now().strftime("%Y-%m-%d"),
        "times_spoken": 0,
        "summary": "",
    }

    now = datetime.now().strftime("%Y-%m-%d")
    data["last_seen"] = now

    if msg.get("senderClass"):
        data["class"] = msg["senderClass"]
    if msg.get("senderLevel"):
        data["level"] = msg["senderLevel"]
    if msg.get("senderZone"):
        data["zone_last_seen"] = msg["senderZone"]

    data["times_spoken"] = data.get("times_spoken", 0) + 1
    return data


# ── Server Memory ─────────────────────────────────────────────────


def load_server_memory() -> dict:
    """Load the shared server memory. Returns empty structure if not found."""
    try:
        return json.loads(SERVER_MEMORY_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"facts": []}


def save_server_memory(data: dict) -> None:
    """Save the shared server memory atomically."""
    _atomic_write(SERVER_MEMORY_FILE, data)


def add_server_fact(text: str, added_by: str) -> dict:
    """Append a fact to server memory with date context.

    Caps at MAX_SERVER_FACTS entries, dropping the oldest when full.
    Returns the updated memory dict.
    """
    data = load_server_memory()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d") + f" ({now.strftime('%A')})"

    data["facts"].append({
        "text": text,
        "added_by": added_by,
        "added_at": date_str,
    })

    while len(data["facts"]) > MAX_SERVER_FACTS:
        data["facts"].pop(0)

    save_server_memory(data)
    return data


def remove_server_fact(index: int) -> bool:
    """Remove a fact by index. Returns True if successfully removed."""
    data = load_server_memory()
    if 0 <= index < len(data["facts"]):
        data["facts"].pop(index)
        save_server_memory(data)
        return True
    return False


def clear_server_memory() -> int:
    """Remove all server facts. Returns count of facts removed."""
    data = load_server_memory()
    count = len(data["facts"])
    if count:
        save_server_memory({"facts": []})
    return count
