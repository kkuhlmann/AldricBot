"""Guildmate and server memory I/O for AldricBot.

Manages per-person JSON files and a shared server fact list.
All writes are atomic (temp file + rename) to prevent corruption.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

STATE_DIR = Path.home() / ".aldricbot"
GUILDMATES_DIR = STATE_DIR / "guildmates"
SERVER_MEMORY_FILE = STATE_DIR / "server_memory.json"
SELF_MEMORY_FILE = STATE_DIR / "self_memory.json"


def init_paths(character_name: str) -> None:
    """Reconfigure module-level paths for a specific character.

    Also performs a one-time migration from the old flat layout
    (~/.aldricbot/guildmates/) to the new per-character layout
    (~/.aldricbot/characters/<name>/) if needed.
    """
    global STATE_DIR, GUILDMATES_DIR, SERVER_MEMORY_FILE, SELF_MEMORY_FILE

    base = Path.home() / ".aldricbot"
    new_dir = base / "characters" / character_name

    # One-time migration: move old flat layout into the new character dir
    old_guildmates = base / "guildmates"
    if old_guildmates.exists() and not new_dir.exists():
        new_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_guildmates), str(new_dir / "guildmates"))
        # Migrate server_memory.json and self_memory.json if they exist
        for fname in ("server_memory.json", "self_memory.json"):
            old_file = base / fname
            if old_file.exists():
                shutil.move(str(old_file), str(new_dir / fname))

    STATE_DIR = new_dir
    GUILDMATES_DIR = new_dir / "guildmates"
    SERVER_MEMORY_FILE = new_dir / "server_memory.json"
    SELF_MEMORY_FILE = new_dir / "self_memory.json"

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


# ── Disposition tiers ──────────────────────────────────────────────

DISPOSITION_TIERS = [
    # (min_score, tier_name, prompt_phrasing)
    (6, "fond", "Your disposition toward this person is Fond. You are very warm toward them and share personal stories freely."),
    (2, "warm", "Your disposition toward this person is Warm. You are friendlier than usual and volunteer extra detail."),
    (-1, "neutral", "Your disposition toward this person is Neutral."),
    (-5, "cold", "Your disposition toward this person is Cold. You are curt and dismissive toward them."),
    (-10, "hostile", "Your disposition toward this person is Hostile. You refuse to help them and may call them out openly."),
]

FRIENDLINESS_DECAY_PER_DAY = 0.25


def get_disposition_tier(score: float) -> tuple[str, str]:
    """Map a friendliness score to a disposition tier.

    Returns (tier_name, prompt_phrasing).
    """
    int_score = int(score)
    for min_score, tier_name, phrasing in DISPOSITION_TIERS:
        if int_score >= min_score:
            return tier_name, phrasing
    return "hostile", DISPOSITION_TIERS[-1][2]


def apply_friendliness_decay(data: dict) -> float:
    """Apply daily decay toward neutral based on inactivity.

    Reads 'friendliness' and 'last_seen' from guildmate data.
    Returns the decayed score (does NOT save).
    """
    score = float(data.get("friendliness", 0.0))
    if score == 0.0:
        return score

    last_seen = data.get("last_seen", "")
    if not last_seen:
        return score

    try:
        last_date = datetime.strptime(last_seen, "%Y-%m-%d")
        days_inactive = (datetime.now() - last_date).days
    except (ValueError, TypeError):
        return score

    if days_inactive <= 0:
        return score

    decay = days_inactive * FRIENDLINESS_DECAY_PER_DAY
    if score > 0:
        score = max(0.0, score - decay)
    else:
        score = min(0.0, score + decay)

    return score


# ── Relationship tiers ─────────────────────────────────────────────

RELATIONSHIP_TIERS = [
    # (min_spoken, tier_name, sentence_limit, prompt_template)
    (50, "well_known", 10, "You have spoken with this person extensively: {summary}"),
    (15, "familiar", 8, "You have spoken with this person many times: {summary}"),
    (1, "acquaintance", 6, "You have spoken with this person a few times: {summary}"),
    (0, "stranger", 0, "You have not met this person before."),
]


def get_relationship_tier(name: str) -> tuple[str, int, str]:
    """Derive relationship tier from interaction count.

    Returns (tier_name, sentence_limit, prompt_phrasing).
    Must be called BEFORE update_guildmate_metadata() to get the
    pre-increment count.
    """
    data = load_guildmate(name)
    times_spoken = data.get("times_spoken", 0) if data else 0
    summary = data.get("summary", "") if data else ""

    for min_count, tier_name, limit, template in RELATIONSHIP_TIERS:
        if times_spoken >= min_count:
            phrasing = template.format(summary=summary) if summary else template.split(": {summary}")[0] + "."
            if tier_name == "stranger":
                phrasing = template
            return tier_name, limit, phrasing

    # Fallback (should not reach here)
    return "stranger", 0, "You have not met this person before."


def get_nickname(name: str) -> str | None:
    """Get a guildmate's nickname, or None if not set."""
    data = load_guildmate(name)
    if data:
        return data.get("nickname")
    return None


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


# ── Self Memory ──────────────────────────────────────────────────


def load_self_memory() -> dict:
    """Load Aldric's self-memory. Returns empty structure if not found."""
    try:
        return json.loads(SELF_MEMORY_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"summary": "", "last_updated": ""}


def save_self_memory(summary: str) -> None:
    """Save Aldric's self-memory atomically."""
    data = {
        "summary": summary,
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
    }
    _atomic_write(SELF_MEMORY_FILE, data)
