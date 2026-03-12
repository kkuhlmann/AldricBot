"""Event dispatch system for AldricBot.

Provides a handler registry and concrete handlers for chat messages,
login greetings, achievement reactions, and level-up reactions.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aldricbot import input_control, memory

STATE_DIR = Path.home() / ".aldricbot"
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
    return None


def _send_commands(commands: list[str]) -> None:
    """Validate and send chat commands to WoW."""
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


# ── Admin command parsing ────────────────────────────────────────

_FORGET_ABOUT_RE = re.compile(r"forget about\s+(\w+)", re.IGNORECASE)


def _parse_command(msg_text: str, msg_type: str = "whisper") -> tuple[str, str] | None:
    """Parse commands from message text.

    Returns (action, argument) or None if not a command.
    Actions: 'remember', 'forget_guildmate', 'forget_all', 'forget_all_facts', 'forget_server'

    The "Hey Aldric" prefix is required for guild/party/raid (since those
    messages are pre-filtered for it), but optional for whispers (any whisper
    to Aldric is already directed at him).
    """
    # Extract the message part after "SenderName: ..."
    parts = msg_text.split(": ", 1)
    if len(parts) < 2:
        return None
    text = parts[1]
    text_lower = text.lower()

    # Strip "Hey Aldric, " prefix if present; require it for non-whispers
    hey_match = re.match(r"hey aldric[,.]?\s*", text_lower)
    if hey_match:
        remainder = text[hey_match.end():]
    elif msg_type == "whisper":
        remainder = text
    else:
        return None
    remainder_lower = remainder.lower()

    # Help command
    if remainder_lower in ("help", "commands") or remainder_lower.startswith("what can i say"):
        return ("help", "")

    # Self-forget: "forget everything about me" (must precede "forget everything")
    if "forget everything about me" in remainder_lower:
        return ("forget_self", "")

    # Self-forget: "forget about me" (must precede "forget about {name}")
    if remainder_lower.startswith("forget about me"):
        return ("forget_self", "")

    # Negation-first: "don't forget" / "do not forget" → remember
    if remainder_lower.startswith("don't forget") or remainder_lower.startswith("do not forget"):
        # Extract the fact after "don't forget that ..." or "don't forget ..."
        fact = re.sub(r"^(?:don't|do not) forget\s+(?:that\s+)?", "", remainder, flags=re.IGNORECASE).strip()
        if fact:
            return ("remember", fact)
        return None

    # "forget all facts" → delete all server facts (admin only)
    if "forget all facts" in remainder_lower:
        return ("forget_all_facts", "")

    # "forget everything" → delete all guildmate memory
    if "forget everything" in remainder_lower:
        return ("forget_all", "")

    # "forget about {name}" → delete guildmate memory
    m = _FORGET_ABOUT_RE.search(remainder)
    if m:
        return ("forget_guildmate", m.group(1))

    # "forget that ..." → forget a server fact
    forget_match = re.match(r"forget that\s+(.+)", remainder, re.IGNORECASE)
    if forget_match:
        return ("forget_server", forget_match.group(1).strip())

    # "remember that ..." / "remember this: ..."
    remember_match = re.match(r"remember (?:that|this[:\s])\s*(.+)", remainder, re.IGNORECASE)
    if remember_match:
        return ("remember", remember_match.group(1).strip())

    return None


# ── Chat Handler ─────────────────────────────────────────────────

AUTH_DOWN_RESPONSES = [
    "Forgive me, friend — my mind is clouded. The Light feels... distant. I cannot speak clearly until the connection is restored. (Auth Token Expired)",
    "I hear you, but the words will not come. Something has severed my link to the Light. My keeper must mend it. (Auth Token Expired)",
    "Aye, I wish I could answer, but a fog has settled over me. My chronicler must renew the old wards before I can speak again. (Auth Token Expired)",
    "The quill will not move. The ink has dried. My keeper must tend to matters before I may write — or speak — again. (Auth Token Expired)",
    "I am here, friend, but bound silent. Like a paladin stripped of his blessing — I must wait for my keeper to restore what was lost. (Auth Token Expired)",
    "A strange numbness... as though the Light itself has turned away. My keeper will set it right. Until then, I can only listen. (Auth Token Expired)",
    "Would that I could answer, but my tongue is stilled. An old enchantment has lapsed — my keeper must renew it. (Auth Token Expired)",
    "I stand before you, yet my voice is not my own to give. The wards have faded. My keeper knows what must be done. (Auth Token Expired)",
]


class ChatHandler(EventHandler):
    """Handles guild, party, raid, and whisper messages."""

    event_types = ["guild", "party", "raid", "whisper"]

    def handle(self, msg: dict, ctx: EventContext) -> bool:
        msg_type = msg.get("type", "chat")
        msg_text = msg.get("text", "")

        # Check for commands — server memory commands work from any channel,
        # all other commands are whisper-only
        parsed = _parse_command(msg_text, msg_type)
        if parsed:
            action = parsed[0]
            sender = msg_text.split(":")[0].strip()
            # Server memory commands — available from any channel
            if action == "remember":
                memory.add_server_fact(parsed[1], sender)
                _send_response(msg_type, sender, "Noted. I shall remember that.")
                _log(f"Server fact added by {sender} via {msg_type}: {parsed[1]}")
                return True
            if action == "forget_server":
                return self._handle_forget_server(parsed[1], sender, msg_type, ctx)
            # All other commands — whisper only
            if msg_type == "whisper":
                if action == "help":
                    self._handle_help(sender)
                    return True
                if action == "forget_self":
                    self._handle_self_forget(sender)
                    return True
                if action == "forget_guildmate" and parsed[1].lower() == sender.lower():
                    self._handle_self_forget(sender)
                    return True
                # Admin commands
                if ctx.admin_name and sender == ctx.admin_name:
                    return self._handle_admin(parsed, sender, ctx)
                if action == "forget_guildmate":
                    _send_whisper(sender, "Forgive me, friend — only they may ask me to forget them. It is not my place to erase another's story.")
                    return True

        if not ctx.auth_ok:
            self._send_auth_down(msg)
            return True

        # Extract sender name for memory
        sender = msg_text.split(":")[0].strip()

        # Load memory for this person
        guildmate = memory.update_guildmate_metadata(sender, msg)
        existing_summary = guildmate.get("summary", "")

        # Build memory context
        memory_line = ""
        if existing_summary:
            memory_line = f"You remember this person: {existing_summary}\n"
        else:
            memory_line = "You have not met this person before.\n"

        # Build server memory context
        server_mem = memory.load_server_memory()
        server_line = ""
        if server_mem.get("facts"):
            facts_text = "\n".join(
                f"- {f['text']} (told by {f['added_by']} on {f['added_at']})"
                for f in server_mem["facts"]
            )
            server_line = f"Things you have been told to remember:\n{facts_text}\n"

        # Build location context
        location_line = ""
        if ctx.zone:
            location_line = f"Your location: {ctx.zone}"
            if ctx.sub_zone:
                location_line += f" — {ctx.sub_zone}"
            location_line += "\n"
        msg_sender_zone = msg.get("senderZone", "")
        if msg_sender_zone:
            location_line += f"The sender is currently in: {msg_sender_zone}\n"
        if location_line:
            location_line += "Reference locations naturally when it fits.\n"

        # Build sender info context
        sender_parts = []
        if msg.get("senderClass"):
            sender_parts.append(f"Class: {msg['senderClass']}")
        if msg.get("senderLevel"):
            sender_parts.append(f"Level: {msg['senderLevel']}")
        if msg.get("senderRank"):
            sender_parts.append(f"Guild rank: {msg['senderRank']}")
        if msg.get("senderNote"):
            sender_parts.append(f"Guild note: {msg['senderNote']}")
        if msg.get("senderOfficerNote"):
            sender_parts.append(f"Officer note: {msg['senderOfficerNote']}")
        sender_info_line = ""
        if sender_parts:
            sender_info_line = "Sender info: " + ", ".join(sender_parts) + "\n"

        prompt = (
            f"Daemon mode: new {msg_type} message received.\n"
            f"{msg_text}\n"
            f"Message timestamp: {msg.get('time', 0)}\n\n"
            f"{sender_info_line}"
            f"{location_line}"
            f"{memory_line}"
            f"{server_line}"
            "Respond in character as Aldric.\n"
            "You MUST use WebSearch for any WoW-related questions — especially NPCs, characters, lore, items, recipes, drop rates, quests, mechanics, or anything you're not 100% certain about.\n"
            'Your final output MUST be ONLY a JSON object: {"commands": ["/g ..."], "memory": "updated summary or null"}\n'
            "The commands array contains chat command strings. Route: guild → /g, party → /p, raid → /ra, whisper → /w SenderName\n"
            "The memory field should be an updated 3-5 sentence summary of what you know about this person, incorporating this conversation. Set to null if no update needed.\n"
            "Keep each command string ≤255 chars. Split at word boundaries if needed.\n"
            'Example: {"commands": ["/g By the Light, friend..."], "memory": "A curious warrior who asks about Ulduar."}'
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl)
        if result is None:
            return True
        if result.stderr:
            _log(f"Claude stderr: {result.stderr}")
        if _is_auth_error(result):
            _log("Auth error detected during Claude invocation")
            return False

        _log(f"Claude response: {result.stdout}")
        parsed = _parse_json_response(result.stdout)

        if parsed is None:
            _log(f"Failed to parse Claude response: {result.stdout}")
            # Save metadata even if response parse fails
            memory.save_guildmate(sender, guildmate)
            return True

        # Handle both formats
        if isinstance(parsed, dict):
            commands = parsed.get("commands", [])
            memory_update = parsed.get("memory")
        else:
            commands = parsed
            memory_update = None

        if commands:
            _send_commands(commands)
            _log(f"Sent {len(commands)} chat commands")

        # Update memory
        if memory_update:
            guildmate["summary"] = memory_update
        memory.save_guildmate(sender, guildmate)

        return True

    def _handle_admin(self, admin: tuple[str, str], sender: str, ctx: EventContext) -> bool:
        """Handle admin whisper commands."""
        action, arg = admin

        if action == "forget_guildmate":
            deleted = memory.delete_guildmate(arg)
            if deleted:
                _send_whisper(sender, f"Done. I have forgotten {arg}.")
                _log(f"Admin: deleted guildmate memory for {arg}")
            else:
                _send_whisper(sender, f"I have no memory of {arg}, friend.")
            return True

        if action == "forget_all":
            count = memory.delete_all_guildmates()
            _send_whisper(sender, f"Done. I have forgotten all {count} souls.")
            _log(f"Admin: deleted all guildmate memory ({count} files)")
            return True

        if action == "forget_all_facts":
            count = memory.clear_server_memory()
            _send_whisper(sender, f"Done. I have struck all {count} facts from my records.")
            _log(f"Admin: cleared all server facts ({count} facts)")
            return True

        return True

    def _handle_help(self, sender: str) -> None:
        """Whisper available commands to the sender."""
        _send_whisper(sender, "These are the words I heed, friend:")
        _send_whisper(sender, '"Forget about me" — I will erase all memory of you.')
        _send_whisper(sender, '"Remember that [fact]" — I will note it for all to benefit from.')
        _send_whisper(sender, '"Forget that [fact]" — I will strike it from my records.')
        _send_whisper(sender, '"Help" — this list.')
        _log(f"Sent help to {sender}")

    def _handle_self_forget(self, sender: str) -> None:
        """Delete the sender's own memory."""
        deleted = memory.delete_guildmate(sender)
        if deleted:
            _send_whisper(sender, "It is done. All that was between us is forgotten, as though we had never spoken.")
            _log(f"Self-forget: deleted memory for {sender}")
        else:
            _send_whisper(sender, "I have no memory of you to forget, friend.")
            _log(f"Self-forget: no memory found for {sender}")

    def _handle_forget_server(self, forget_text: str, sender: str, msg_type: str, ctx: EventContext) -> bool:
        """Use Claude to identify which server fact to remove."""
        server_mem = memory.load_server_memory()
        facts = server_mem.get("facts", [])
        if not facts:
            _send_response(msg_type, sender, "I have nothing to forget, friend.")
            return True

        numbered = "\n".join(f"{i}: {f['text']}" for i, f in enumerate(facts))
        prompt = (
            f'The user asked to forget: "{forget_text}"\n'
            f"Here are the current facts (numbered):\n{numbered}\n\n"
            "Reply with ONLY the number of the fact to remove, or -1 if no match."
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl, timeout=30)
        if result is None:
            _send_response(msg_type, sender, "My mind is clouded — I cannot process that now.")
            return True
        if _is_auth_error(result):
            _send_response(msg_type, sender, "The Light is distant — I cannot think clearly.")
            return False

        try:
            index = int(result.stdout.strip())
        except ValueError:
            _send_response(msg_type, sender, "I could not determine what to forget, friend.")
            return True

        if index < 0 or index >= len(facts):
            _send_response(msg_type, sender, "I do not recall that, friend.")
            return True

        removed = facts[index]["text"]
        memory.remove_server_fact(index)
        _send_response(msg_type, sender, f"Done. I have forgotten: {removed[:100]}")
        _log(f"Removed server fact [{index}] by {sender} via {msg_type}: {removed}")
        return True

    def _send_auth_down(self, msg: dict) -> None:
        """Send an in-character fallback when auth is unavailable."""
        msg_type = msg.get("type", "guild")
        text = random.choice(AUTH_DOWN_RESPONSES)

        if msg_type == "whisper":
            sender = msg.get("text", "").split(":")[0].strip()
            cmd = f"/w {sender} {text}"
        elif msg_type == "party":
            cmd = f"/p {text}"
        elif msg_type == "raid":
            cmd = f"/ra {text}"
        else:
            cmd = f"/g {text}"

        try:
            _send_commands([cmd])
            _log(f"Sent auth-down fallback via {msg_type}")
        except Exception as e:
            _log(f"Error sending auth-down response: {e}")


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

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            # Known guildmate: Claude-generated greeting
            ok = self._claude_greeting(name, guildmate, ctx)
            self._cooldown.record(name)
            return ok
        else:
            # Unknown or auth down: pre-written greeting
            greeting = random.choice(LOGIN_GREETINGS).format(name=name)
            _send_guild_message(greeting)
            _log(f"Login greeting (pre-written) for {name}")
            self._cooldown.record(name)
            return True

    def _claude_greeting(self, name: str, guildmate: dict, ctx: EventContext) -> bool:
        summary = guildmate.get("summary", "")
        prompt = (
            "Daemon mode: guildmate login detected.\n"
            f"{name} has come online. You remember them: {summary}\n"
            "Generate a brief, warm greeting for guild chat (1 sentence). "
            "Reference something from your memory of them if natural.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            'Example: ["/g Ah, Fenwick — still chasing glory in Ulduar, I take it?"]'
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl)
        if result is None:
            # Fallback to pre-written
            greeting = random.choice(LOGIN_GREETINGS).format(name=name)
            _send_guild_message(greeting)
            return True
        if _is_auth_error(result):
            greeting = random.choice(LOGIN_GREETINGS).format(name=name)
            _send_guild_message(greeting)
            return False

        _log(f"Claude login greeting: {result.stdout}")
        parsed = _parse_json_response(result.stdout)
        if parsed:
            commands = parsed if isinstance(parsed, list) else parsed.get("commands", [])
            if commands:
                _send_commands(commands)
                _log(f"Sent Claude greeting for {name}")
                return True

        # Fallback
        greeting = random.choice(LOGIN_GREETINGS).format(name=name)
        _send_guild_message(greeting)
        return True


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

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            ok = self._claude_reaction(name, achievement, guildmate, ctx)
            self._cooldown.record(name)
            return ok
        else:
            reaction = random.choice(ACHIEVEMENT_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            _log(f"Achievement reaction (pre-written) for {name}: {achievement}")
            self._cooldown.record(name)
            return True

    def _claude_reaction(self, name: str, achievement: str, guildmate: dict, ctx: EventContext) -> bool:
        summary = guildmate.get("summary", "")
        prompt = (
            "Daemon mode: guildmate achievement detected.\n"
            f"{name} has earned: {achievement}\n"
            f"You remember them: {summary}\n"
            "React briefly in guild chat (1 sentence). Be congratulatory and in character.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            'Example: ["/g Well earned, Fenwick. Your persistence serves you well."]'
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl)
        if result is None:
            reaction = random.choice(ACHIEVEMENT_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            return True
        if _is_auth_error(result):
            reaction = random.choice(ACHIEVEMENT_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            return False

        _log(f"Claude achievement reaction: {result.stdout}")
        parsed = _parse_json_response(result.stdout)
        if parsed:
            commands = parsed if isinstance(parsed, list) else parsed.get("commands", [])
            if commands:
                _send_commands(commands)
                _log(f"Sent Claude achievement reaction for {name}")
                return True

        reaction = random.choice(ACHIEVEMENT_REACTIONS).format(name=name)
        _send_guild_message(reaction)
        return True


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

        if guildmate and guildmate.get("summary") and ctx.auth_ok:
            ok = self._claude_reaction(name, level, guildmate, ctx)
            self._cooldown.record(name)
            return ok
        else:
            reaction = random.choice(LEVELUP_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            _log(f"Levelup reaction (pre-written) for {name} → level {level}")
            self._cooldown.record(name)
            return True

    def _claude_reaction(self, name: str, level: int | None, guildmate: dict, ctx: EventContext) -> bool:
        summary = guildmate.get("summary", "")
        level_text = f" level {level}" if level else ""
        prompt = (
            "Daemon mode: guildmate level-up detected.\n"
            f"{name} has reached{level_text}!\n"
            f"You remember them: {summary}\n"
            "React briefly in guild chat (1 sentence). Be encouraging and in character.\n"
            "Output MUST be ONLY a JSON array of /g chat command strings.\n"
            f'Example: ["/g {name}, another step closer to greatness. The Light guides you."]'
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl)
        if result is None:
            reaction = random.choice(LEVELUP_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            return True
        if _is_auth_error(result):
            reaction = random.choice(LEVELUP_REACTIONS).format(name=name)
            _send_guild_message(reaction)
            return False

        _log(f"Claude levelup reaction: {result.stdout}")
        parsed = _parse_json_response(result.stdout)
        if parsed:
            commands = parsed if isinstance(parsed, list) else parsed.get("commands", [])
            if commands:
                _send_commands(commands)
                _log(f"Sent Claude levelup reaction for {name}")
                return True

        reaction = random.choice(LEVELUP_REACTIONS).format(name=name)
        _send_guild_message(reaction)
        return True


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

                    ok = handler.handle(msg, ctx)
                    if not ok:
                        auth_ok = False
                        ctx.auth_ok = False

                    # Update appropriate timestamp
                    if msg_type in self._chat_types:
                        self._save_chat_time(msg_time)
                    else:
                        self._save_event_time(msg_time)
                    break

        return auth_ok, had_messages
