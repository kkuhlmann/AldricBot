#!/usr/bin/env python3
"""Background daemon for AldricBot.

Manages the WoW game loop continuously without requiring Claude to poll.
- Calls send_reload() every 10 seconds to read fresh game state
- Detects new guild/party/whisper messages directed at Aldric
- Spawns Claude as a subprocess to generate RP responses
- Handles anti-AFK sit/stand directly (no Claude needed)

Start:
    WOW_INSTALL_PATH="..." WOW_ACCOUNT_NAME="..." python daemon.py &

Stop:
    kill $(cat ~/.aldricbot/daemon.lock)
"""

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from aldricbot import config, input_control, lua_io

STATE_DIR = Path.home() / ".aldricbot"
DAEMON_LOCK = STATE_DIR / "daemon.lock"
LAST_TIME_FILE = STATE_DIR / "last_answered_time.txt"
SESSION_START_FILE = STATE_DIR / "session_start.txt"
PROACTIVE_TIME_FILE = STATE_DIR / "next_proactive_cycle.txt"

CYCLE_SECONDS = 10
AFK_SIT_EVERY = 30  # ~5 minutes at 10s per cycle
DEFAULT_SESSION_TTL_HOURS = 24

IDLE_EMOTE_MIN_CYCLES = 48  # ~8 min at 10s/cycle
IDLE_EMOTE_MAX_CYCLES = 72  # ~12 min

IDLE_EMOTES = [
    "/e adjusts his journal and dips the quill in ink.",
    "/e rubs his left hand where two fingers used to be.",
    "/e glances toward the horizon, lost in thought.",
    "/e shifts his weight, favoring his good knee.",
    "/e turns a weathered page in his chronicle.",
    "/e pauses, listening to the wind.",
    "/e absently traces the scar along his jaw.",
]

PROACTIVE_MIN_CYCLES = 720  # ~2 hours
PROACTIVE_MAX_CYCLES = 1440  # ~4 hours


def _log(msg: str) -> None:
    """Print a timestamped daemon log line."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [daemon] {msg}")


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="AldricBot daemon")
    parser.add_argument(
        "--model",
        default=os.environ.get("ALDRICBOT_MODEL"),
        choices=["opus", "sonnet", "haiku"],
        help="Claude model to use. Also settable via ALDRICBOT_MODEL env var.",
    )
    parser.add_argument(
        "--session-ttl",
        type=int,
        default=int(os.environ.get("ALDRICBOT_SESSION_TTL", DEFAULT_SESSION_TTL_HOURS)),
        help="Hours before conversation context resets. Also settable via ALDRICBOT_SESSION_TTL env var.",
    )
    return parser.parse_args()


def setup():
    """Initialize daemon state directory and lock file."""
    STATE_DIR.mkdir(exist_ok=True)
    DAEMON_LOCK.write_text(str(os.getpid()))
    last_time = 0.0
    if LAST_TIME_FILE.exists():
        try:
            last_time = float(LAST_TIME_FILE.read_text().strip())
        except (ValueError, OSError):
            last_time = 0.0
    return last_time


def teardown():
    """Clean up lock file on exit."""
    DAEMON_LOCK.unlink(missing_ok=True)


def _session_is_valid(ttl_hours):
    """Check if the current conversation session is still within the TTL."""
    try:
        start = float(SESSION_START_FILE.read_text().strip())
        return (time.time() - start) < ttl_hours * 3600
    except (FileNotFoundError, ValueError, OSError):
        return False


def _refresh_session():
    """Record the start of a new conversation session."""
    SESSION_START_FILE.write_text(str(time.time()))


def do_game_cycle():
    """Send /reload to WoW and read fresh game state.

    Returns dict with chatMessages, player position, etc., or {} on error.
    """
    try:
        asyncio.run(input_control.send_reload())
        time.sleep(CYCLE_SECONDS)
        path = config.saved_variables_path()
        variables = lua_io.read_saved_variables(path)
        db = variables.get("AldricBotAddonDB", {})
        raw = db.get("lastState")
        if isinstance(raw, str):
            return json.loads(raw)
        return {}
    except Exception as e:
        _log(f"Error in game cycle: {e}")
        return {}


def find_new_messages(state, last_answered_time):
    """Find all unhandled guild/party/whisper messages.

    Args:
        state: Game state dict with chatMessages array
        last_answered_time: Timestamp of last handled message

    Returns:
        List of new message dicts, ordered by time (oldest first)
    """
    messages = []
    for msg in state.get("chatMessages", []):
        msg_type = msg.get("type")
        msg_time = msg.get("time", 0)
        if msg_type in ("guild", "party", "raid", "whisper"):
            if msg_time > last_answered_time:
                messages.append(msg)
    return messages


def _parse_json_response(text):
    """Extract a JSON array from Claude's stdout.

    Handles raw JSON or JSON wrapped in markdown code fences.
    Returns a list of command strings, or None on failure.
    """
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = [line for line in lines[1:] if line.strip() != "```"]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def invoke_claude(
    msg, zone="", sub_zone="", model=None, session_ttl=DEFAULT_SESSION_TTL_HOURS
):
    """Spawn Claude to generate an RP response, then send it to WoW.

    Claude outputs a JSON array of chat commands to stdout. The daemon
    parses it and types the commands directly into WoW — no MCP needed.
    Conversations persist via --continue for up to session_ttl hours.

    Args:
        msg: Message dict with type, text, time
        zone: Current zone name (e.g. "Stormwind City")
        sub_zone: Current subzone name (e.g. "Trade District")
        model: Optional Claude model name (e.g. 'sonnet', 'opus')
        session_ttl: Hours before conversation context resets
    """
    msg_type = msg.get("type", "chat")
    msg_text = msg.get("text", "")
    msg_time = msg.get("time", 0)

    msg_sender_zone = msg.get("senderZone", "")

    location_line = ""
    if zone:
        location_line = f"Your location: {zone}"
        if sub_zone:
            location_line += f" — {sub_zone}"
        location_line += "\n"
    if msg_sender_zone:
        location_line += f"The sender is currently in: {msg_sender_zone}\n"
    if location_line:
        location_line += "Reference locations naturally when it fits.\n"

    prompt = (
        f"Daemon mode: new {msg_type} message received.\n"
        f"{msg_text}\n"
        f"Message timestamp: {msg_time}\n\n"
        f"{location_line}"
        "Respond in character as Aldric.\n"
        "You MUST use WebSearch for any WoW-related questions — especially NPCs, characters, lore, items, recipes, drop rates, quests, mechanics, or anything you're not 100% certain about.\n"
        "Your final output MUST be ONLY a JSON array of chat command strings. No other text.\n"
        "Route: guild → /g, party → /p, raid → /ra, whisper → /w SenderName\n"
        "Keep each string ≤255 chars. Split at word boundaries if needed.\n"
        'Example: ["/g By the Light, friend...", "/g ...his fall is a warning."]'
    )

    cmd = ["claude", "-p", "--allowedTools", "WebSearch"]
    if model:
        cmd.extend(["--model", model])
    if _session_is_valid(session_ttl):
        cmd.append("--continue")
    else:
        _refresh_session()
    cmd.append(prompt)

    try:
        result = subprocess.run(
            cmd,
            timeout=60,
            check=False,
            capture_output=True,
            text=True,
        )
        _log(f"Claude response: {result.stdout}")
        commands = _parse_json_response(result.stdout)
        if commands:
            commands = input_control.validate_and_fix_chunks(commands)
            for chat_cmd in commands:
                asyncio.run(input_control.send_chat_command(chat_cmd))
            _log(f"Sent {len(commands)} chat commands")
        else:
            _log(f"Failed to parse Claude response: {result.stdout}")
    except FileNotFoundError:
        _log("Error: 'claude' command not found. Is Claude Code installed?")
    except subprocess.TimeoutExpired:
        _log("Error: Claude response timed out after 60 seconds")
    except Exception as e:
        _log(f"Error invoking Claude: {e}")


def invoke_claude_proactive(
    zone="", sub_zone="", model=None, session_ttl=DEFAULT_SESSION_TTL_HOURS
):
    """Spawn Claude to generate an unprompted RP message for guild chat.

    Same invocation pattern as invoke_claude(), but with a proactive prompt
    asking Aldric to share a thought, memory, or observation.
    """
    location_line = ""
    if zone:
        location_line = f"Current location: {zone}"
        if sub_zone:
            location_line += f" — {sub_zone}"
        location_line += "\n"

    prompt = (
        "Daemon mode: proactive RP.\n"
        "No one has spoken to you recently. Share a brief thought, memory, "
        "or observation in guild chat.\n"
        f"{location_line}"
        "Keep it to 1-2 sentences. Be natural — a quiet musing, not a speech.\n"
        "Your output MUST be ONLY a JSON array of /g chat command strings.\n"
        'Example: ["/g The wind carries the scent of pine... '
        'reminds me of the march to Hyjal."]'
    )

    cmd = ["claude", "-p", "--allowedTools", "WebSearch"]
    if model:
        cmd.extend(["--model", model])
    if _session_is_valid(session_ttl):
        cmd.append("--continue")
    else:
        _refresh_session()
    cmd.append(prompt)

    try:
        result = subprocess.run(
            cmd,
            timeout=60,
            check=False,
            capture_output=True,
            text=True,
        )
        _log(f"Proactive Claude response: {result.stdout}")
        commands = _parse_json_response(result.stdout)
        if commands:
            commands = input_control.validate_and_fix_chunks(commands)
            for chat_cmd in commands:
                asyncio.run(input_control.send_chat_command(chat_cmd))
            _log(f"Sent {len(commands)} proactive chat commands")
        else:
            _log(f"Failed to parse proactive response: {result.stdout}")
    except FileNotFoundError:
        _log("Error: 'claude' command not found. Is Claude Code installed?")
    except subprocess.TimeoutExpired:
        _log("Error: Proactive Claude response timed out after 60 seconds")
    except Exception as e:
        _log(f"Error invoking proactive Claude: {e}")


def _random_emote_delay():
    """Return a random cycle count for the next idle emote."""
    return random.randint(IDLE_EMOTE_MIN_CYCLES, IDLE_EMOTE_MAX_CYCLES)


def _random_proactive_delay():
    """Return a random cycle count for the next proactive RP."""
    return random.randint(PROACTIVE_MIN_CYCLES, PROACTIVE_MAX_CYCLES)


def _load_proactive_cycle(current_cycle):
    """Load next proactive cycle from disk, or generate a new one."""
    try:
        return int(PROACTIVE_TIME_FILE.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return current_cycle + _random_proactive_delay()


def _save_proactive_cycle(cycle):
    """Persist next proactive cycle to disk."""
    PROACTIVE_TIME_FILE.write_text(str(cycle))


def do_afk_sit():
    """Stand then sit to prevent AFK timer."""
    try:
        asyncio.run(input_control.send_chat_command("/stand"))
        time.sleep(1)
        asyncio.run(input_control.send_chat_command("/sit"))
    except Exception as e:
        _log(f"Error doing AFK sit/stand: {e}")


def main():
    """Main game loop."""
    args = parse_args()

    _log(f"Starting AldricBot daemon (PID {os.getpid()})")
    _log(f"Model: {args.model or '(default)'}")
    _log(f"Session TTL: {args.session_ttl}h")
    _log(f"Lock file: {DAEMON_LOCK}")
    _log(f"Last message time file: {LAST_TIME_FILE}")

    last_answered_time = setup()
    cycle = 0
    next_emote_cycle = _random_emote_delay()
    next_proactive_cycle = _load_proactive_cycle(0)

    try:
        while True:
            state = do_game_cycle()
            cycle += 1

            # Extract zone info for prompts
            player = state.get("player", {})
            zone = player.get("zone", "")
            sub_zone = player.get("subZone", "")

            # Check for new messages that need RP response
            messages = find_new_messages(state, last_answered_time)
            for msg in messages:
                last_answered_time = msg.get("time", 0)
                LAST_TIME_FILE.write_text(str(last_answered_time))
                _log(f"Found new message: {msg.get('text', '')}")
                invoke_claude(
                    msg,
                    zone=zone,
                    sub_zone=sub_zone,
                    model=args.model,
                    session_ttl=args.session_ttl,
                )
                # Reset idle/proactive timers — conversation just happened
                next_emote_cycle = cycle + _random_emote_delay()
                next_proactive_cycle = cycle + _random_proactive_delay()
                _save_proactive_cycle(next_proactive_cycle)

            # Idle emotes when no messages for a while
            if not messages and cycle >= next_emote_cycle:
                emote = random.choice(IDLE_EMOTES)
                _log(f"Idle emote: {emote}")
                try:
                    asyncio.run(input_control.send_chat_command(emote))
                except Exception as e:
                    _log(f"Error sending idle emote: {e}")
                next_emote_cycle = cycle + _random_emote_delay()

            # Proactive RP when idle for a long time
            if not messages and cycle >= next_proactive_cycle:
                _log(f"Proactive RP triggered (cycle {cycle})")
                invoke_claude_proactive(
                    zone=zone,
                    sub_zone=sub_zone,
                    model=args.model,
                    session_ttl=args.session_ttl,
                )
                next_emote_cycle = cycle + _random_emote_delay()
                next_proactive_cycle = cycle + _random_proactive_delay()
                _save_proactive_cycle(next_proactive_cycle)

            # Anti-AFK sit/stand periodically
            if not messages and cycle % AFK_SIT_EVERY == 0:
                _log(f"AFK sit/stand (cycle {cycle})")
                do_afk_sit()
    except KeyboardInterrupt:
        _log("Interrupted by user")
    except Exception as e:
        _log(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        teardown()
        _log("Daemon stopped")


if __name__ == "__main__":
    main()
