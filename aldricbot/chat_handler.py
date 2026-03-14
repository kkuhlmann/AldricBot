"""Chat message handler for AldricBot.

Handles guild, party, raid, and whisper messages including command parsing,
Claude invocation, memory updates, and retry logic.
"""

from __future__ import annotations

import collections
import random
import re

from aldricbot import input_control, memory, persona as persona_mod
from aldricbot.events import (
    EventContext,
    EventHandler,
    _is_auth_error,
    _log,
    _parse_json_response,
    _run_claude,
    _send_commands,
    _send_response,
    _send_whisper,
)


# ── Admin command parsing ────────────────────────────────────────

_FORGET_ABOUT_RE = re.compile(r"forget about\s+(\w+)", re.IGNORECASE)


def _parse_command(msg_text: str, msg_type: str = "whisper", character_name: str = "Aldric") -> tuple[str, str] | None:
    """Parse commands from message text.

    Returns (action, argument) or None if not a command.
    Actions: 'remember', 'forget_guildmate', 'forget_all', 'forget_all_facts', 'forget_server'

    The "Hey <name>" prefix is required for guild/party/raid (since those
    messages are pre-filtered for it), but optional for whispers (any whisper
    to the character is already directed at them).
    """
    # Extract the message part after "SenderName: ..."
    parts = msg_text.split(": ", 1)
    if len(parts) < 2:
        return None
    text = parts[1]
    text_lower = text.lower()

    # Strip "Hey <name>, " prefix if present; require it for non-whispers
    hey_match = re.match(rf"hey {re.escape(character_name.lower())}[,.]?\s*", text_lower)
    if hey_match:
        remainder = text[hey_match.end() :]
    elif msg_type == "whisper":
        remainder = text
    else:
        return None
    remainder_lower = remainder.lower()

    # Help command
    if remainder_lower in ("help", "commands") or remainder_lower.startswith(
        "what can i say"
    ):
        return ("help", "")

    # "tell me about myself" / "tell me about me" → return sender's own memory
    if re.match(r"tell me about (myself|me)\b", remainder_lower):
        return ("about_self", "")

    # "tell me the world facts" / "tell me the facts" / "what are the world facts"
    if re.match(
        r"(?:tell me (?:the )?(?:world )?facts|what are the (?:world )?facts)",
        remainder_lower,
    ):
        return ("world_facts", "")

    # Self-forget: "forget everything about me" (must precede "forget everything")
    if "forget everything about me" in remainder_lower:
        return ("forget_self", "")

    # Self-forget: "forget about me" (must precede "forget about {name}")
    if remainder_lower.startswith("forget about me"):
        return ("forget_self", "")

    # Negation-first: "don't forget" / "do not forget" → remember
    if remainder_lower.startswith("don't forget") or remainder_lower.startswith(
        "do not forget"
    ):
        # Extract the fact after "don't forget that ..." or "don't forget ..."
        fact = re.sub(
            r"^(?:don't|do not) forget\s+(?:that\s+)?",
            "",
            remainder,
            flags=re.IGNORECASE,
        ).strip()
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
    remember_match = re.match(
        r"remember (?:that|this[:\s])\s*(.+)", remainder, re.IGNORECASE
    )
    if remember_match:
        return ("remember", remember_match.group(1).strip())

    return None


# ── Chat Handler ─────────────────────────────────────────────────

THINKING_EMOTES = [
    "/e strokes his beard thoughtfully...",
    "/e pauses, turning the question over in his mind.",
    "/e flips through his journal, searching for the right words.",
    "/e narrows his eyes, recalling something from long ago.",
    "/e rubs the stumps of his missing fingers absently.",
]

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

    MAX_RETRY_ATTEMPTS = 3

    def __init__(self):
        self._last_emote: str | None = None
        self._retry_queue: collections.deque = collections.deque(maxlen=5)

    def process_retries(self, ctx: EventContext) -> str:
        """Attempt one queued message. Returns 'ok', 'auth_error', or 'empty'."""
        if not self._retry_queue:
            return "ok"
        msg, attempts = self._retry_queue.popleft()
        _log(f"Retrying queued message (attempt {attempts + 1})")
        result = self.handle(msg, ctx, _is_retry=True)
        if result == "transient_failure":
            if attempts + 1 < self.MAX_RETRY_ATTEMPTS:
                self._retry_queue.appendleft((msg, attempts + 1))
            else:
                sender = msg.get("text", "").split(":")[0].strip()
                msg_type = msg.get("type", "guild")
                _send_response(
                    msg_type,
                    sender,
                    "Forgive me, friend — I cannot seem to gather my thoughts. Perhaps try again later.",
                )
                _log(f"Dropped message after {self.MAX_RETRY_ATTEMPTS} failed attempts")
        return result

    def _send_thinking_emote(self, ctx: EventContext) -> None:
        """Send a random thinking emote, avoiding consecutive repeats."""
        pool = persona_mod.get_thinking_emotes(ctx.persona) or THINKING_EMOTES
        choices = [e for e in pool if e != self._last_emote]
        emote = random.choice(choices)
        self._last_emote = emote
        input_control.send_chat_command(emote)

    def handle(self, msg: dict, ctx: EventContext, _is_retry: bool = False) -> str:
        """Process a chat message. Returns 'ok', 'auth_error', or 'transient_failure'."""
        msg_type = msg.get("type", "chat")
        msg_text = msg.get("text", "")

        # Check for commands — most commands work from any channel,
        # some commands are whisper-only
        parsed = _parse_command(msg_text, msg_type, ctx.character_name)
        if parsed:
            action = parsed[0]
            sender = msg_text.split(":")[0].strip()
            # Server memory commands — available from any channel
            if action == "remember":
                memory.add_server_fact(parsed[1], sender)
                _send_response(msg_type, sender, "Noted. I shall remember that.")
                _log(f"Server fact added by {sender} via {msg_type}: {parsed[1]}")
                return "ok"
            if action == "forget_server":
                return self._handle_forget_server(parsed[1], sender, msg_type, ctx)
            if action == "about_self":
                self._handle_about_self(sender, msg_type)
                return "ok"
            if action == "world_facts":
                self._handle_world_facts(sender, msg_type)
                return "ok"
            if action == "help":
                self._handle_help(sender, msg_type)
                return "ok"
            # Self-forget — available from any channel
            if action == "forget_self":
                self._handle_self_forget(sender, msg_type)
                return "ok"
            if action == "forget_guildmate" and parsed[1].lower() == sender.lower():
                self._handle_self_forget(sender, msg_type)
                return "ok"
            # All other commands — whisper only
            if msg_type == "whisper":
                # Admin commands
                if ctx.admin_name and sender == ctx.admin_name:
                    return self._handle_admin(parsed, sender, ctx)
                if action == "forget_guildmate":
                    _send_whisper(
                        sender,
                        "Forgive me, friend — only they may ask me to forget them. It is not my place to erase another's story.",
                    )
                    return "ok"

        if not ctx.auth_ok:
            self._send_auth_down(msg, ctx)
            return "ok"

        self._send_thinking_emote(ctx)

        sender = msg_text.split(":")[0].strip()
        context = self._load_context(sender, msg)
        guildmate = context["guildmate"]

        prompt = self._build_prompt(msg, context, ctx)

        status, parsed_response = self._invoke_and_parse(prompt, ctx)
        if status != "ok":
            if status == "transient_failure" and not _is_retry:
                self._retry_queue.append((msg, 0))
                _log("Claude call failed — queued for retry")
            memory.save_guildmate(sender, guildmate)
            return status

        self._apply_response(parsed_response, sender, guildmate, context["tier_name"])
        return "ok"

    def _load_context(self, sender: str, msg: dict) -> dict:
        """Load memory, relationship, disposition, and self-memory for a sender."""
        # Read relationship tier BEFORE incrementing times_spoken
        tier_name, sentence_limit, tier_phrasing = memory.get_relationship_tier(sender)

        # Load friendliness with decay applied
        existing_data = memory.load_guildmate(sender)
        if existing_data:
            decayed_score = memory.apply_friendliness_decay(existing_data)
        else:
            decayed_score = 0.0
        disposition_name, disposition_phrasing = memory.get_disposition_tier(
            decayed_score
        )

        # Load memory for this person (increments times_spoken)
        guildmate = memory.update_guildmate_metadata(sender, msg)
        guildmate["friendliness"] = decayed_score

        self_mem = memory.load_self_memory()

        # Load nickname from guildmate data
        existing_data = existing_data or memory.load_guildmate(sender)
        nickname = existing_data.get("nickname") if existing_data else None

        return {
            "guildmate": guildmate,
            "tier_name": tier_name,
            "tier_phrasing": tier_phrasing,
            "sentence_limit": sentence_limit,
            "disposition_name": disposition_name,
            "disposition_phrasing": disposition_phrasing,
            "self_summary": self_mem.get("summary", ""),
            "nickname": nickname,
        }

    def _build_prompt(self, msg: dict, context: dict, ctx: EventContext) -> str:
        """Assemble the full Claude prompt from loaded context."""
        msg_type = msg.get("type", "chat")
        msg_text = msg.get("text", "")

        memory_line = f"{context['tier_phrasing']}\n"
        if context["sentence_limit"] > 0:
            memory_line += f"Keep this person's summary to {context['sentence_limit']} sentences.\n"

        disposition_line = ""
        if context["disposition_name"] != "neutral":
            disposition_line = f"{context['disposition_phrasing']}\n"

        server_mem = memory.load_server_memory()
        server_line = ""
        if server_mem.get("facts"):
            facts_text = "\n".join(
                f"- {f['text']} (told by {f['added_by']} on {f['added_at']})"
                for f in server_mem["facts"]
            )
            server_line = f"Things you have been told to remember:\n{facts_text}\n"

        self_memory_line = ""
        if context["self_summary"]:
            self_memory_line = f"Things you have said about yourself in past conversations:\n{context['self_summary']}\n"

        calendar_line = ""
        if ctx.calendar_context:
            calendar_line = f"{ctx.calendar_context}\n"

        nickname_line = ""
        if context["tier_name"] in ("familiar", "well_known") and context.get("nickname"):
            nickname_line = f'Your nickname for this person: "{context["nickname"]}". Use it naturally when addressing them.\n'

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

        return (
            f"Daemon mode: new {msg_type} message received.\n"
            f"{msg_text}\n"
            f"Message timestamp: {msg.get('time', 0)}\n\n"
            f"{sender_info_line}"
            f"{location_line}"
            f"{memory_line}"
            f"{disposition_line}"
            f"{server_line}"
            f"{self_memory_line}"
            f"{calendar_line}"
            f"{nickname_line}"
            f"Respond in character as {ctx.character_name}.\n"
            "You MUST use WebSearch for any WoW-related questions — especially NPCs, characters, lore, items, recipes, drop rates, quests, mechanics, or anything you're not 100% certain about.\n"
            'Your final output MUST be ONLY a JSON object: {"commands": ["/g ..."], "memory": "updated summary or null", "self_memory": "updated self-summary or null", "nickname": "the Scholar or null", "friendliness": 0}\n'
            "The commands array contains chat command strings. Route: guild → /g, party → /p, raid → /ra, whisper → /w SenderName\n"
            "The memory field should be an updated summary of what you know about this person, incorporating this conversation. Keep it within the sentence limit specified above. Set to null if no update needed.\n"
            "The self_memory field should be an updated summary of personal stories, claims, or opinions you shared about yourself. Rewrite (don't append) to stay concise (3-5 sentences). Set to null if you didn't share anything new about yourself.\n"
            "The nickname field: assign a short (2-3 word) in-character nickname if they are Familiar or above and you feel you know them. Set to null for strangers/acquaintances or if no update needed.\n"
            "The friendliness field is an integer from -2 to +2 indicating how this interaction shifted your feelings toward this person (0 = no change, negative = they were rude/hostile, positive = they were kind/friendly).\n"
            "Keep each command string ≤255 chars. Split at word boundaries if needed.\n"
            'Example: {"commands": ["/g By the Light, friend..."], "memory": "A curious warrior who asks about Ulduar.", "self_memory": null, "nickname": null, "friendliness": 0}'
        )

    def _invoke_and_parse(
        self, prompt: str, ctx: EventContext
    ) -> tuple[str, dict | None]:
        """Run Claude and parse response. Retries once on parse failure.

        Returns (status, parsed) where status is 'ok', 'auth_error',
        or 'transient_failure'.
        """
        result = _run_claude(prompt, ctx.model, ctx.session_ttl)
        if result is None:
            return "transient_failure", None
        if result.stderr:
            _log(f"Claude stderr: {result.stderr}")
        if _is_auth_error(result):
            _log("Auth error detected during Claude invocation")
            return "auth_error", None

        _log(f"Claude response: {result.stdout}")
        parsed = _parse_json_response(result.stdout)

        if parsed is None:
            _log(f"Failed to parse Claude response (attempt 1): {result.stdout}")
            result = _run_claude(prompt, ctx.model, ctx.session_ttl)
            if result is not None and not _is_auth_error(result):
                _log(f"Claude retry response: {result.stdout}")
                parsed = _parse_json_response(result.stdout)

            if parsed is None:
                _log("Failed to parse Claude response (attempt 2)")
                return "transient_failure", None

        # Normalize legacy list format to dict
        if isinstance(parsed, dict):
            return "ok", parsed
        return "ok", {
            "commands": parsed,
            "memory": None,
            "self_memory": None,
            "friendliness": 0,
        }

    def _apply_response(self, parsed: dict, sender: str, guildmate: dict, tier_name: str = "stranger") -> None:
        """Send commands and persist memory updates from Claude's response."""
        commands = parsed.get("commands", [])
        if commands:
            _send_commands(commands)
            _log(f"Sent {len(commands)} chat commands")

        # Update friendliness score (scaled + daily-capped)
        friendliness_delta = parsed.get("friendliness", 0)
        try:
            delta = int(friendliness_delta)
            delta = max(-2, min(2, delta))
        except (ValueError, TypeError):
            delta = 0
        if delta != 0:
            effective = memory.clamp_daily_friendliness_delta(guildmate, delta)
            if effective != 0:
                new_score = guildmate.get("friendliness", 0.0) + effective
                guildmate["friendliness"] = max(-10.0, min(10.0, new_score))

        # Update nickname (only for Familiar+ tiers)
        nickname_update = parsed.get("nickname")
        if nickname_update and tier_name in ("familiar", "well_known"):
            guildmate["nickname"] = nickname_update

        # Update memory
        memory_update = parsed.get("memory")
        if memory_update:
            guildmate["summary"] = memory_update
        memory.save_guildmate(sender, guildmate)

        # Update self-memory
        self_memory_update = parsed.get("self_memory")
        if self_memory_update:
            memory.save_self_memory(self_memory_update)

    def _handle_admin(
        self, admin: tuple[str, str], sender: str, ctx: EventContext
    ) -> str:
        """Handle admin whisper commands."""
        action, arg = admin

        if action == "forget_guildmate":
            deleted = memory.delete_guildmate(arg)
            if deleted:
                _send_whisper(sender, f"Done. I have forgotten {arg}.")
                _log(f"Admin: deleted guildmate memory for {arg}")
            else:
                _send_whisper(sender, f"I have no memory of {arg}, friend.")
            return "ok"

        if action == "forget_all":
            count = memory.delete_all_guildmates()
            _send_whisper(sender, f"Done. I have forgotten all {count} souls.")
            _log(f"Admin: deleted all guildmate memory ({count} files)")
            return "ok"

        if action == "forget_all_facts":
            count = memory.clear_server_memory()
            _send_whisper(
                sender, f"Done. I have struck all {count} facts from my records."
            )
            _log(f"Admin: cleared all server facts ({count} facts)")
            return "ok"

        return "ok"

    def _handle_help(self, sender: str, msg_type: str) -> None:
        """Send available commands to the sender via the same channel."""
        _send_response(msg_type, sender, "These are the words I heed, friend:")
        _send_response(msg_type, sender, '"Forget about me" — I will erase all memory of you.')
        _send_response(
            msg_type, sender, '"Remember that [fact]" — I will note it for all to benefit from.'
        )
        _send_response(
            msg_type, sender, '"Forget that [fact]" — I will strike it from my records.'
        )
        _send_response(
            msg_type, sender, '"Tell me about myself" — I will share what I know of you.'
        )
        _send_response(
            msg_type,
            sender,
            '"Tell me the world facts" — I will recite the facts I have been told.',
        )
        _send_response(msg_type, sender, '"Help" — this list.')
        _log(f"Sent help to {sender} via {msg_type}")

    def _handle_self_forget(self, sender: str, msg_type: str = "whisper") -> None:
        """Delete the sender's own memory."""
        deleted = memory.delete_guildmate(sender)
        if deleted:
            _send_response(
                msg_type,
                sender,
                "It is done. All that was between us is forgotten, as though we had never spoken.",
            )
            _log(f"Self-forget: deleted memory for {sender}")
        else:
            _send_response(msg_type, sender, "I have no memory of you to forget, friend.")
            _log(f"Self-forget: no memory found for {sender}")

    def _handle_about_self(self, sender: str, msg_type: str) -> None:
        """Send the sender their own memory data."""
        data = memory.load_guildmate(sender)
        if not data:
            _send_response(msg_type, sender, "I have no record of you, friend.")
            _log(f"About self: no memory for {sender}")
            return

        parts = [f"Name: {data.get('name', sender)}"]
        if data.get("class"):
            parts.append(f"Class: {data['class']}")
        if data.get("level"):
            parts.append(f"Level: {data['level']}")
        parts.append(f"Times spoken: {data.get('times_spoken', 0)}")
        parts.append(f"First seen: {data.get('first_seen', 'unknown')}")
        parts.append(f"Last seen: {data.get('last_seen', 'unknown')}")
        friendliness = data.get("friendliness", 0.0)
        if friendliness != 0.0:
            parts.append(f"Friendliness: {friendliness}")
        nickname = data.get("nickname")
        if nickname:
            parts.append(f"I call you: {nickname}")
        info_line = " | ".join(parts)
        _send_response(msg_type, sender, info_line)

        summary = data.get("summary", "")
        if summary:
            _send_response(msg_type, sender, f"My notes: {summary}")
        _log(f"About self: sent memory to {sender}")

    def _handle_world_facts(self, sender: str, msg_type: str) -> None:
        """Send the current server facts."""
        server_mem = memory.load_server_memory()
        facts = server_mem.get("facts", [])
        if not facts:
            _send_response(
                msg_type, sender, "I have nothing recorded, friend."
            )
            _log("World facts: no facts to report")
            return

        for i, fact in enumerate(facts, 1):
            line = f"{i}. {fact['text']} (by {fact['added_by']}, {fact['added_at']})"
            _send_response(msg_type, sender, line)
        _log(f"World facts: sent {len(facts)} facts to {sender}")

    def _handle_forget_server(
        self, forget_text: str, sender: str, msg_type: str, ctx: EventContext
    ) -> str:
        """Use Claude to identify which server fact to remove."""
        server_mem = memory.load_server_memory()
        facts = server_mem.get("facts", [])
        if not facts:
            _send_response(msg_type, sender, "I have nothing to forget, friend.")
            return "ok"

        numbered = "\n".join(f"{i}: {f['text']}" for i, f in enumerate(facts))
        prompt = (
            f'The user asked to forget: "{forget_text}"\n'
            f"Here are the current facts (numbered):\n{numbered}\n\n"
            "Reply with ONLY the number of the fact to remove, or -1 if no match."
        )

        result = _run_claude(prompt, ctx.model, ctx.session_ttl, timeout=30)
        if result is None:
            _send_response(
                msg_type, sender, "My mind is clouded — I cannot process that now."
            )
            return "ok"
        if _is_auth_error(result):
            _send_response(
                msg_type, sender, "The Light is distant — I cannot think clearly."
            )
            return "auth_error"

        try:
            index = int(result.stdout.strip())
        except ValueError:
            _send_response(
                msg_type, sender, "I could not determine what to forget, friend."
            )
            return "ok"

        if index < 0 or index >= len(facts):
            _send_response(msg_type, sender, "I do not recall that, friend.")
            return "ok"

        removed = facts[index]["text"]
        memory.remove_server_fact(index)
        _send_response(msg_type, sender, f"Done. I have forgotten: {removed[:100]}")
        _log(f"Removed server fact [{index}] by {sender} via {msg_type}: {removed}")
        return "ok"

    def _send_auth_down(self, msg: dict, ctx: EventContext) -> None:
        """Send an in-character fallback when auth is unavailable."""
        msg_type = msg.get("type", "guild")
        pool = persona_mod.get_auth_down_responses(ctx.persona) or AUTH_DOWN_RESPONSES
        text = random.choice(pool)

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
