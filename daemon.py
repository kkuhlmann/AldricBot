#!/usr/bin/env python3
"""Background daemon for AldricBot.

Manages the WoW game loop continuously without requiring Claude to poll.
- Calls send_reload() every 10 seconds to read fresh game state
- Dispatches chat messages and game events to registered handlers
- Handles anti-AFK sit/stand directly (no Claude needed)

Start:
    WOW_INSTALL_PATH="..." WOW_ACCOUNT_NAME="..." python daemon.py &

Stop:
    kill $(cat ~/.aldricbot/daemon.lock)
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from aldricbot import config, input_control, lua_io
from aldricbot.events import (
    AchievementHandler,
    ChatHandler,
    EventContext,
    EventDispatcher,
    LevelUpHandler,
    LoginHandler,
    _is_auth_error,
    _parse_json_response,
    _send_commands,
)

STATE_DIR = Path.home() / ".aldricbot"
DAEMON_LOCK = STATE_DIR / "daemon.lock"
SESSION_START_FILE = STATE_DIR / "session_start.txt"
PROACTIVE_TIME_FILE = STATE_DIR / "next_proactive_cycle.txt"

CYCLE_SECONDS = 10
AFK_SIT_EVERY = 30  # ~5 minutes at 10s per cycle
DEFAULT_SESSION_TTL_HOURS = 24
AUTH_CHECK_INTERVAL = 360  # ~1 hour at 10s/cycle
AUTH_KEEPALIVE_INTERVAL = 4320  # ~12 hours at 10s/cycle

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


def check_auth() -> bool:
    """Check if Claude CLI is authenticated."""
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            timeout=15,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False
        status = json.loads(result.stdout)
        return status.get("loggedIn", False)
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        Exception,
    ) as e:
        _log(f"Auth check failed: {e}")
        return False


def auth_keepalive() -> bool:
    """Send a lightweight prompt to force an OAuth token refresh."""
    try:
        result = subprocess.run(
            ["claude", "-p", "ping"],
            timeout=30,
            check=False,
            capture_output=True,
            text=True,
        )
        if _is_auth_error(result):
            return False
        _log("Auth keepalive: token refreshed")
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception) as e:
        _log(f"Auth keepalive failed: {e}")
        return False


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
    parser.add_argument(
        "--admin",
        default=os.environ.get("ALDRICBOT_ADMIN"),
        help="Admin character name for privileged commands. Also settable via ALDRICBOT_ADMIN env var.",
    )
    return parser.parse_args()


def setup():
    """Initialize daemon state directory and lock file."""
    STATE_DIR.mkdir(exist_ok=True)
    DAEMON_LOCK.write_text(str(os.getpid()))


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
    """Send /reload to WoW and read fresh game state."""
    try:
        input_control.send_reload()
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


def invoke_claude_proactive(
    zone="", sub_zone="", model=None, session_ttl=DEFAULT_SESSION_TTL_HOURS
):
    """Spawn Claude to generate an unprompted RP message for guild chat."""
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
        if result.stderr:
            _log(f"Proactive Claude stderr: {result.stderr}")
        if _is_auth_error(result):
            _log("Auth error detected during proactive Claude invocation")
            return False
        _log(f"Proactive Claude response: {result.stdout}")
        parsed = _parse_json_response(result.stdout)
        commands = None
        if isinstance(parsed, list):
            commands = parsed
        elif isinstance(parsed, dict):
            commands = parsed.get("commands", [])
        if commands:
            _send_commands(commands)
            _log(f"Sent {len(commands)} proactive chat commands")
        else:
            _log(f"Failed to parse proactive response: {result.stdout}")
    except FileNotFoundError:
        _log("Error: 'claude' command not found. Is Claude Code installed?")
    except subprocess.TimeoutExpired:
        _log("Error: Proactive Claude response timed out after 60 seconds")
    except Exception as e:
        _log(f"Error invoking proactive Claude: {e}")
    return True


def _random_emote_delay():
    return random.randint(IDLE_EMOTE_MIN_CYCLES, IDLE_EMOTE_MAX_CYCLES)


def _random_proactive_delay():
    return random.randint(PROACTIVE_MIN_CYCLES, PROACTIVE_MAX_CYCLES)


def _load_proactive_cycle(current_cycle):
    try:
        return int(PROACTIVE_TIME_FILE.read_text().strip())
    except (FileNotFoundError, ValueError, OSError):
        return current_cycle + _random_proactive_delay()


def _save_proactive_cycle(cycle):
    PROACTIVE_TIME_FILE.write_text(str(cycle))


def do_afk_sit():
    """Stand then sit to prevent AFK timer."""
    try:
        input_control.send_chat_command("/stand")
        time.sleep(1)
        input_control.send_chat_command("/sit")
    except Exception as e:
        _log(f"Error doing AFK sit/stand: {e}")


def main():
    """Main game loop."""
    args = parse_args()

    _log(f"Starting AldricBot daemon (PID {os.getpid()})")
    _log(f"Model: {args.model or 'haiku'}")
    _log(f"Session TTL: {args.session_ttl}h")
    _log(f"Admin: {args.admin or '(none — admin commands disabled)'}")
    _log(f"Lock file: {DAEMON_LOCK}")

    setup()

    # Initialize event dispatcher
    dispatcher = EventDispatcher()
    dispatcher.register(ChatHandler())
    dispatcher.register(LoginHandler())
    dispatcher.register(AchievementHandler())
    dispatcher.register(LevelUpHandler())
    dispatcher.load_timestamps()

    cycle = 0
    next_emote_cycle = _random_emote_delay()
    next_proactive_cycle = _load_proactive_cycle(0)
    auth_ok = True
    next_auth_check = AUTH_CHECK_INTERVAL
    next_keepalive = AUTH_KEEPALIVE_INTERVAL

    # Verify auth at startup
    if check_auth():
        _log("Auth verified: logged in")
    else:
        _log("WARNING: Auth check failed at startup — Claude calls will be skipped")
        _log("Re-authenticate via SSH: claude auth login")
        auth_ok = False

    try:
        while True:
            state = do_game_cycle()
            cycle += 1

            # Periodic auth health check
            if cycle >= next_auth_check:
                was_ok = auth_ok
                auth_ok = check_auth()
                next_auth_check = cycle + AUTH_CHECK_INTERVAL
                if auth_ok and not was_ok:
                    _log("Auth restored — resuming Claude calls")
                elif not auth_ok and was_ok:
                    _log("WARNING: Auth expired — pausing Claude calls")
                    _log("Re-authenticate via SSH: claude auth login")

            # Periodic token keepalive (~every 12 hours)
            if auth_ok and cycle >= next_keepalive:
                if not auth_keepalive():
                    auth_ok = False
                    _log(
                        "WARNING: Auth expired during keepalive — pausing Claude calls"
                    )
                    _log("Re-authenticate via SSH: claude auth login")
                next_keepalive = cycle + AUTH_KEEPALIVE_INTERVAL

            # Extract zone info for prompts
            player = state.get("player", {})
            zone = player.get("zone", "")
            sub_zone = player.get("subZone", "")

            # Dispatch all messages and events to handlers
            ctx = EventContext(
                zone=zone,
                sub_zone=sub_zone,
                model=args.model,
                session_ttl=args.session_ttl,
                auth_ok=auth_ok,
                cycle=cycle,
                admin_name=args.admin,
            )
            auth_ok, had_messages = dispatcher.dispatch(state, ctx)

            if not auth_ok and ctx.auth_ok != auth_ok:
                _log("WARNING: Auth expired — pausing Claude calls")
                _log("Re-authenticate via SSH: claude auth login")

            if had_messages:
                # Reset idle/proactive timers — activity just happened
                next_emote_cycle = cycle + _random_emote_delay()
                next_proactive_cycle = cycle + _random_proactive_delay()
                _save_proactive_cycle(next_proactive_cycle)

            # Idle emotes when no messages for a while
            if not had_messages and cycle >= next_emote_cycle:
                emote = random.choice(IDLE_EMOTES)
                _log(f"Idle emote: {emote}")
                try:
                    input_control.send_chat_command(emote)
                except Exception as e:
                    _log(f"Error sending idle emote: {e}")
                next_emote_cycle = cycle + _random_emote_delay()

            # Proactive RP when idle for a long time
            if not had_messages and cycle >= next_proactive_cycle:
                if auth_ok:
                    _log(f"Proactive RP triggered (cycle {cycle})")
                    ok = invoke_claude_proactive(
                        zone=zone,
                        sub_zone=sub_zone,
                        model=args.model,
                        session_ttl=args.session_ttl,
                    )
                    if not ok:
                        auth_ok = False
                        _log("WARNING: Auth expired — pausing Claude calls")
                        _log("Re-authenticate via SSH: claude auth login")
                next_emote_cycle = cycle + _random_emote_delay()
                next_proactive_cycle = cycle + _random_proactive_delay()
                _save_proactive_cycle(next_proactive_cycle)

            # Anti-AFK sit/stand periodically
            if not had_messages and cycle % AFK_SIT_EVERY == 0:
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
