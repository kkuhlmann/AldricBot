"""Event dispatch system for AldricBot.

Provides a handler registry and concrete handlers for chat messages,
login greetings, achievement reactions, and level-up reactions.
"""

from __future__ import annotations

import json
import random
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aldricbot import input_control, memory, persona as persona_mod

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PERSONA_PROMPT_PATH = _PROJECT_ROOT / "persona_prompt.md"

STATE_DIR = Path.home() / ".aldricbot"
LAST_EVENT_TIME_FILE = STATE_DIR / "last_event_time.txt"


def init_paths(character_name: str) -> None:
    """Reconfigure module-level paths for a specific character."""
    global STATE_DIR, LAST_EVENT_TIME_FILE
    STATE_DIR = Path.home() / ".aldricbot" / "characters" / character_name
    LAST_EVENT_TIME_FILE = STATE_DIR / "last_event_time.txt"

# ── Pre-written response pools ────────────────────────────────────

LOGIN_GREETINGS = [
    "Ah, {name}. Good to see you, friend.",
    "Well met, {name}. The Light greets you this day.",
    "{name}. You are a welcome sight.",
    "Hail, {name}. May the Light guide your path.",
    "Welcome, {name}. What news do you bring?",
    "{name} — good. I was beginning to think I'd be talking to myself all evening.",
    "The Light marks your return, {name}. Well met.",
    "Ah, {name}. Another soul stirs in the guild hall.",
    "Good to see you standing, {name}. These are uncertain times.",
    "Hail, friend {name}. The day improves with your company.",
]

ACHIEVEMENT_REACTIONS = [
    "Well earned, {name}. The Light shines on your deeds.",
    "A worthy accomplishment, {name}.",
    "I shall note that in the chronicle, {name}. Well done.",
    "Your dedication does you credit, {name}.",
    "Another mark of honor, {name}. The guild is fortunate to have you.",
]

LEVELUP_REACTIONS = [
    "{name} grows stronger. Well done, friend.",
    "Another milestone, {name}. The road stretches on.",
    "Strength begets strength, {name}. The Light approves.",
    "Well done, {name}. Each step forward is a step toward purpose.",
    "I remember when every level felt like climbing a mountain, {name}. Press on.",
]

# ── Cooldown constants ────────────────────────────────────────────

LOGIN_COOLDOWN_SECONDS = 300  # 5 minutes
EVENT_COOLDOWN_SECONDS = 60   # 1 minute for achievements/levelups


# ── Context & base class ─────────────────────────────────────────

@dataclass
class EventContext:
    """Shared context passed to all handlers."""

    zone: str = ""
    sub_zone: str = ""
    model: str | None = None
    session_ttl: int = 24
    auth_ok: bool = True
    cycle: int = 0
    admin_name: str | None = None
    calendar_context: str = ""
    character_name: str = "Aldric"
    persona: dict | None = None


class EventHandler:
    """Base class for event handlers."""

    event_types: list[str] = []

    def match(self, msg: dict) -> bool:
        """Return True if this handler should process the message."""
        return msg.get("type") in self.event_types

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        """Process event. Returns True if Claude auth is still valid."""
        raise NotImplementedError


# ── Helpers ───────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [events] {msg}")


def _is_auth_error(result) -> bool:
    """Check if a subprocess result indicates an authentication failure."""
    combined = (result.stderr or "") + (result.stdout or "")
    combined_lower = combined.lower()
    auth_indicators = [
        "not logged in", "authentication required", "auth",
        "unauthorized", "token expired", "login required", "please log in",
    ]
    if result.returncode != 0:
        for indicator in auth_indicators:
            if indicator in combined_lower:
                return True
    return False


def _session_is_valid(ttl_hours: int) -> bool:
    session_file = STATE_DIR / "session_start.txt"
    try:
        start = float(session_file.read_text().strip())
        return (time.time() - start) < ttl_hours * 3600
    except (FileNotFoundError, ValueError, OSError):
        return False


def _refresh_session() -> None:
    session_file = STATE_DIR / "session_start.txt"
    session_file.write_text(str(time.time()))


def _build_claude_cmd(model: str | None, session_ttl: int) -> list[str]:
    cmd = ["claude", "-p", "--allowedTools", "WebSearch"]
    if model:
        cmd.extend(["--model", model])
    if _session_is_valid(session_ttl):
        cmd.append("--continue")
    else:
        _refresh_session()
        if PERSONA_PROMPT_PATH.exists():
            cmd.extend(["--system-prompt-file", str(PERSONA_PROMPT_PATH)])
    return cmd


def _run_claude(prompt: str, model: str | None, session_ttl: int, timeout: int = 60) -> subprocess.CompletedProcess | None:
    """Run a Claude subprocess. Returns the result or None on error."""
    cmd = _build_claude_cmd(model, session_ttl)
    cmd.append(prompt)
    try:
        return subprocess.run(cmd, timeout=timeout, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        _log("Error: 'claude' command not found")
        return None
    except subprocess.TimeoutExpired:
        _log(f"Error: Claude timed out after {timeout}s")
        return None
    except Exception as e:
        _log(f"Error invoking Claude: {e}")
        return None


def _parse_json_response(text: str) -> dict | list | None:
    """Parse Claude's response as JSON. Handles code fences.

    Returns a dict (new format: {commands, memory}), a list (legacy format),
    or None on failure.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines[1:] if line.strip() != "```"]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "commands" in parsed:
            return parsed
        if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: extract JSON embedded in prose (e.g. when Claude uses WebSearch)
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        if start == -1:
            continue
        end = text.rfind(end_char)
        if end <= start:
            continue
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict) and "commands" in parsed:
                return parsed
            if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _send_commands(commands: list[str]) -> None:
    """Validate and send chat commands to WoW."""
    commands = [cmd.replace("\u2014", " ") for cmd in commands]
    commands = input_control.validate_and_fix_chunks(commands)
    for cmd in commands:
        input_control.send_chat_command(cmd)


def _send_guild_message(text: str) -> None:
    """Send a single guild chat message."""
    cmd = f"/g {text}"
    chunks = input_control.validate_and_fix_chunks([cmd])
    for c in chunks:
        input_control.send_chat_command(c)


def _send_whisper(name: str, text: str) -> None:
    """Send a whisper to a player."""
    cmd = f"/w {name} {text}"
    chunks = input_control.validate_and_fix_chunks([cmd])
    for c in chunks:
        input_control.send_chat_command(c)


def _send_response(msg_type: str, sender: str, text: str) -> None:
    """Send a response via the same channel the message arrived on."""
    if msg_type == "whisper":
        cmd = f"/w {sender} {text}"
    elif msg_type == "party":
        cmd = f"/p {text}"
    elif msg_type == "raid":
        cmd = f"/ra {text}"
    else:
        cmd = f"/g {text}"
    chunks = input_control.validate_and_fix_chunks([cmd])
    for c in chunks:
        input_control.send_chat_command(c)


# ── Cooldown tracker ─────────────────────────────────────────────

class CooldownTracker:
    """In-memory per-name cooldown tracker."""

    def __init__(self, cooldown_seconds: float):
        self._cooldown = cooldown_seconds
        self._last_seen: dict[str, float] = {}

    def is_on_cooldown(self, name: str) -> bool:
        last = self._last_seen.get(name, 0)
        return (time.time() - last) < self._cooldown

    def record(self, name: str) -> None:
        self._last_seen[name] = time.time()


# ── Shared Claude-or-fallback helper ─────────────────────────────

def _claude_or_fallback(prompt: str, fallback_pool: list[str], name: str,
                        ctx: EventContext, label: str = "reaction") -> bool:
    """Run Claude for a short reaction; fall back to a random pool message.

    Returns True if auth is OK, False on auth error.
    """
    result = _run_claude(prompt, ctx.model, ctx.session_ttl)
    if result is None:
        _send_guild_message(random.choice(fallback_pool).format(name=name))
        return True
    if _is_auth_error(result):
        _send_guild_message(random.choice(fallback_pool).format(name=name))
        return False

    _log(f"Claude {label}: {result.stdout}")
    parsed = _parse_json_response(result.stdout)
    if parsed:
        commands = parsed if isinstance(parsed, list) else parsed.get("commands", [])
        if commands:
            _send_commands(commands)
            _log(f"Sent Claude {label} for {name}")
            return True

    _send_guild_message(random.choice(fallback_pool).format(name=name))
    return True


# ── Login Handler ────────────────────────────────────────────────

class LoginHandler(EventHandler):
    """Greets guildmates who come online."""

    event_types = ["login"]

    def __init__(self):
        self._cooldown = CooldownTracker(LOGIN_COOLDOWN_SECONDS)

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        name = msg.get("text", "")
        if not name:
            return True

        if self._cooldown.is_on_cooldown(name):
            _log(f"Skipping login greeting for {name} — on cooldown")
            return True

        guildmate = memory.load_guildmate(name)

        greetings = persona_mod.get_login_greetings(ctx.persona) or LOGIN_GREETINGS

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            # Known guildmate: Claude-generated greeting
            ok = self._claude_greeting(name, guildmate, ctx, greetings)
            self._cooldown.record(name)
            return ok
        else:
            # Unknown or auth down: pre-written greeting
            greeting = random.choice(greetings).format(name=name)
            _send_guild_message(greeting)
            _log(f"Login greeting (pre-written) for {name}")
            self._cooldown.record(name)
            return True

    def _claude_greeting(self, name: str, guildmate: dict, ctx: EventContext, greetings: list[str] | None = None) -> bool:
        tier_name, _, tier_phrasing = memory.get_relationship_tier(name)
        decayed_score = memory.apply_friendliness_decay(guildmate)
        disp_tier, disp_phrasing = memory.get_disposition_tier(decayed_score)
        disp_line = f"\n{disp_phrasing}" if disp_tier != "neutral" else ""
        nickname = guildmate.get("nickname") if tier_name in ("familiar", "well_known") else None
        nickname_line = f'\nYour nickname for this person: "{nickname}". Use it naturally.' if nickname else ""
        calendar_line = f"\n{ctx.calendar_context}" if ctx.calendar_context else ""
        prompt = (
            "Daemon mode: guildmate login detected.\n"
            f"{name} has come online. {tier_phrasing}{disp_line}{nickname_line}{calendar_line}\n"
            "Generate a brief greeting for guild chat (1 sentence). "
            "Adjust your tone based on your disposition. "
            "Reference something from your memory of them if natural. "
            "If a seasonal event is active, you may mention it naturally.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            'Example: ["/g Ah, Fenwick — still chasing glory in Ulduar, I take it?"]'
        )
        pool = greetings if greetings is not None else LOGIN_GREETINGS
        return _claude_or_fallback(prompt, pool, name, ctx, "login greeting")


# ── Achievement Handler ──────────────────────────────────────────

class AchievementHandler(EventHandler):
    """Reacts to guildmate achievements."""

    event_types = ["achievement"]

    def __init__(self):
        self._cooldown = CooldownTracker(EVENT_COOLDOWN_SECONDS)

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        text = msg.get("text", "")
        # Format: "SenderName: Achievement Name"
        parts = text.split(": ", 1)
        name = parts[0] if parts else ""
        achievement = parts[1] if len(parts) > 1 else "an achievement"

        if not name:
            return True

        if self._cooldown.is_on_cooldown(name):
            _log(f"Skipping achievement reaction for {name} — on cooldown")
            return True

        guildmate = memory.load_guildmate(name)
        reactions = persona_mod.get_achievement_reactions(ctx.persona) or ACHIEVEMENT_REACTIONS

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            ok = self._claude_reaction(name, achievement, guildmate, ctx, reactions)
            self._cooldown.record(name)
            return ok
        else:
            reaction = random.choice(reactions).format(name=name)
            _send_guild_message(reaction)
            _log(f"Achievement reaction (pre-written) for {name}: {achievement}")
            self._cooldown.record(name)
            return True

    def _claude_reaction(self, name: str, achievement: str, guildmate: dict, ctx: EventContext, reactions: list[str] | None = None) -> bool:
        tier_name, _, tier_phrasing = memory.get_relationship_tier(name)
        decayed_score = memory.apply_friendliness_decay(guildmate)
        disp_tier, disp_phrasing = memory.get_disposition_tier(decayed_score)
        disp_line = f"\n{disp_phrasing}" if disp_tier != "neutral" else ""
        nickname = guildmate.get("nickname") if tier_name in ("familiar", "well_known") else None
        nickname_line = f'\nYour nickname for this person: "{nickname}". Use it naturally.' if nickname else ""
        prompt = (
            "Daemon mode: guildmate achievement detected.\n"
            f"{name} has earned: {achievement}\n"
            f"{tier_phrasing}{disp_line}{nickname_line}\n"
            "React briefly in guild chat (1 sentence). Stay in character. "
            "Adjust your tone based on your disposition.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            'Example: ["/g Well earned, Fenwick. Your persistence serves you well."]'
        )
        pool = reactions if reactions is not None else ACHIEVEMENT_REACTIONS
        return _claude_or_fallback(prompt, pool, name, ctx, "achievement reaction")


# ── Level-Up Handler ─────────────────────────────────────────────

class LevelUpHandler(EventHandler):
    """Reacts to guildmate level-ups."""

    event_types = ["levelup"]

    def __init__(self):
        self._cooldown = CooldownTracker(EVENT_COOLDOWN_SECONDS)

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        text = msg.get("text", "")
        # Format: "Name:72"
        parts = text.split(":", 1)
        name = parts[0] if parts else ""
        level = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

        if not name:
            return True

        if self._cooldown.is_on_cooldown(name):
            _log(f"Skipping levelup reaction for {name} — on cooldown")
            return True

        # Auto-update level in memory
        if level:
            guildmate = memory.load_guildmate(name)
            if guildmate:
                guildmate["level"] = level
                memory.save_guildmate(name, guildmate)

        guildmate = memory.load_guildmate(name)
        reactions = persona_mod.get_levelup_reactions(ctx.persona) or LEVELUP_REACTIONS

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            ok = self._claude_reaction(name, level, guildmate, ctx, reactions)
            self._cooldown.record(name)
            return ok
        else:
            reaction = random.choice(reactions).format(name=name)
            _send_guild_message(reaction)
            _log(f"Levelup reaction (pre-written) for {name} → level {level}")
            self._cooldown.record(name)
            return True

    def _claude_reaction(self, name: str, level: int | None, guildmate: dict, ctx: EventContext, reactions: list[str] | None = None) -> bool:
        tier_name, _, tier_phrasing = memory.get_relationship_tier(name)
        decayed_score = memory.apply_friendliness_decay(guildmate)
        disp_tier, disp_phrasing = memory.get_disposition_tier(decayed_score)
        disp_line = f"\n{disp_phrasing}" if disp_tier != "neutral" else ""
        nickname = guildmate.get("nickname") if tier_name in ("familiar", "well_known") else None
        nickname_line = f'\nYour nickname for this person: "{nickname}". Use it naturally.' if nickname else ""
        level_text = f" level {level}" if level else ""
        prompt = (
            "Daemon mode: guildmate level-up detected.\n"
            f"{name} has reached{level_text}!\n"
            f"{tier_phrasing}{disp_line}{nickname_line}\n"
            "React briefly in guild chat (1 sentence). Stay in character. "
            "Adjust your tone based on your disposition.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            f'Example: ["/g {name}, another step closer to greatness. The Light guides you."]'
        )
        pool = reactions if reactions is not None else LEVELUP_REACTIONS
        return _claude_or_fallback(prompt, pool, name, ctx, "levelup reaction")


# ── Event Dispatcher ─────────────────────────────────────────────

class EventDispatcher:
    """Registry and dispatch for event handlers.

    Each handler type tracks its own last-handled timestamp
    to prevent cross-interference between chat and events.
    """

    def __init__(self):
        self._handlers: list[EventHandler] = []
        self._chat_last_time: float = 0.0
        self._event_last_time: float = 0.0
        self._chat_types = {"guild", "party", "raid", "whisper"}

    def register(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def load_timestamps(self) -> None:
        """Load persisted timestamps from disk."""
        chat_file = STATE_DIR / "last_answered_time.txt"
        try:
            self._chat_last_time = float(chat_file.read_text().strip())
        except (FileNotFoundError, ValueError, OSError):
            self._chat_last_time = 0.0

        try:
            self._event_last_time = float(LAST_EVENT_TIME_FILE.read_text().strip())
        except (FileNotFoundError, ValueError, OSError):
            self._event_last_time = 0.0

    def _save_chat_time(self, t: float) -> None:
        self._chat_last_time = t
        (STATE_DIR / "last_answered_time.txt").write_text(str(t))

    def _save_event_time(self, t: float) -> None:
        self._event_last_time = t
        LAST_EVENT_TIME_FILE.write_text(str(t))

    @property
    def chat_last_time(self) -> float:
        return self._chat_last_time

    def dispatch(self, state: dict, ctx: EventContext) -> tuple[bool, bool]:
        """Dispatch all new messages to appropriate handlers.

        Returns (auth_ok, had_messages) tuple.
        """
        auth_ok = ctx.auth_ok
        had_messages = False

        # Process one retry from ChatHandler before new messages
        for handler in self._handlers:
            if hasattr(handler, "process_retries") and handler._retry_queue:
                result = handler.process_retries(ctx)
                if result == "auth_error":
                    auth_ok = False
                    ctx.auth_ok = False
                break

        for msg in state.get("chatMessages", []):
            msg_type = msg.get("type")
            msg_time = msg.get("time", 0)

            # Determine which timestamp to compare against
            if msg_type in self._chat_types:
                if msg_time <= self._chat_last_time:
                    continue
            else:
                if msg_time <= self._event_last_time:
                    continue

            # Find matching handler
            for handler in self._handlers:
                if handler.match(msg):
                    had_messages = True
                    _log(f"Dispatching {msg_type} to {handler.__class__.__name__}")

                    result = handler.handle(msg, ctx)
                    if result == "auth_error" or result is False:
                        auth_ok = False
                        ctx.auth_ok = False

                    # Update appropriate timestamp
                    if msg_type in self._chat_types:
                        self._save_chat_time(msg_time)
                    else:
                        self._save_event_time(msg_time)
                    break

        return auth_ok, had_messages
