#!/usr/bin/env python3
"""Background daemon for AldricBot.

Manages the WoW game loop continuously without requiring Claude to poll.
- Calls send_reload() every 2.5 seconds to read fresh game state
- Detects new guild/party/whisper messages directed at Aldric
- Spawns Claude as a subprocess to generate RP responses
- Handles anti-AFK jumps directly (no Claude needed)

Start:
    WOW_INSTALL_PATH="..." WOW_ACCOUNT_NAME="..." python daemon.py &

Stop:
    kill $(cat ~/.aldricbot/daemon.lock)
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from aldricbot import config, input_control, lua_io

STATE_DIR = Path.home() / ".aldricbot"
DAEMON_LOCK = STATE_DIR / "daemon.lock"
LAST_TIME_FILE = STATE_DIR / "last_answered_time.txt"
SESSION_START_FILE = STATE_DIR / "session_start.txt"

CYCLE_SECONDS = 2.5
AFK_JUMP_EVERY = 120  # ~5 minutes at 2.5s per cycle
DEFAULT_SESSION_TTL_HOURS = 3


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
        db = variables.get("ClaudeBotDB", {})
        raw = db.get("lastState")
        if isinstance(raw, str):
            return json.loads(raw)
        return {}
    except Exception as e:
        print(f"Error in game cycle: {e}", file=sys.stderr)
        return {}


def find_new_message(state, last_answered_time):
    """Find the first unhandled guild/party/whisper message.

    Args:
        state: Game state dict with chatMessages array
        last_answered_time: Timestamp of last handled message

    Returns:
        First new message dict, or None if no new messages
    """
    for msg in state.get("chatMessages", []):
        msg_type = msg.get("type")
        msg_time = msg.get("time", 0)
        if msg_type in ("guild", "party", "whisper"):
            if msg_time > last_answered_time:
                return msg
    return None


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


def invoke_claude(msg, model=None, session_ttl=DEFAULT_SESSION_TTL_HOURS):
    """Spawn Claude to generate an RP response, then send it to WoW.

    Claude outputs a JSON array of chat commands to stdout. The daemon
    parses it and types the commands directly into WoW — no MCP needed.
    Conversations persist via --continue for up to session_ttl hours.

    Args:
        msg: Message dict with type, text, time
        model: Optional Claude model name (e.g. 'sonnet', 'opus')
        session_ttl: Hours before conversation context resets
    """
    msg_type = msg.get("type", "chat")
    msg_text = msg.get("text", "")
    msg_time = msg.get("time", 0)

    prompt = (
        f"Daemon mode: new {msg_type} message received.\n"
        f"{msg_text}\n"
        f"Message timestamp: {msg_time}\n\n"
        "Respond in character as Aldric.\n"
        "You may use WebSearch for raid mechanics or WotLK strategy questions.\n"
        "Your final output MUST be ONLY a JSON array of chat command strings. No other text.\n"
        "Route: guild → /g, party → /p, whisper → /w SenderName\n"
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
            cmd, timeout=60, check=False, capture_output=True, text=True,
        )
        commands = _parse_json_response(result.stdout)
        if commands:
            for chat_cmd in commands:
                asyncio.run(input_control.send_chat_command(chat_cmd))
            print(f"[daemon] Sent {len(commands)} chat commands")
        else:
            print(
                f"[daemon] Failed to parse Claude response: {result.stdout[:200]}",
                file=sys.stderr,
            )
    except FileNotFoundError:
        print(
            "Error: 'claude' command not found. Is Claude Code installed?",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print("Error: Claude response timed out after 60 seconds", file=sys.stderr)
    except Exception as e:
        print(f"Error invoking Claude: {e}", file=sys.stderr)


def do_afk_jump():
    """Tap spacebar to prevent AFK timer."""
    try:
        asyncio.run(input_control.tap_key_async("space"))
    except Exception as e:
        print(f"Error doing AFK jump: {e}", file=sys.stderr)


def main():
    """Main game loop."""
    args = parse_args()

    print(f"[daemon] Starting AldricBot daemon (PID {os.getpid()})")
    print(f"[daemon] Model: {args.model or '(default)'}")
    print(f"[daemon] Session TTL: {args.session_ttl}h")
    print(f"[daemon] Lock file: {DAEMON_LOCK}")
    print(f"[daemon] Last message time file: {LAST_TIME_FILE}")

    last_answered_time = setup()
    cycle = 0

    try:
        while True:
            state = do_game_cycle()
            cycle += 1

            # Check for new messages that need RP response
            msg = find_new_message(state, last_answered_time)
            if msg:
                last_answered_time = msg.get("time", 0)
                LAST_TIME_FILE.write_text(str(last_answered_time))
                print(f"[daemon] Found new message: {msg.get('text', '')[:80]}")
                invoke_claude(msg, model=args.model, session_ttl=args.session_ttl)
            # Do anti-AFK jump periodically
            elif cycle % AFK_JUMP_EVERY == 0:
                print(f"[daemon] AFK jump (cycle {cycle})")
                do_afk_jump()
    except KeyboardInterrupt:
        print("\n[daemon] Interrupted by user")
    except Exception as e:
        print(f"[daemon] Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        teardown()
        print("[daemon] Daemon stopped")


if __name__ == "__main__":
    main()
