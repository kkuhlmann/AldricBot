"""Trade event handler for AldricBot hide-and-seek."""

from __future__ import annotations

from aldricbot import input_control, memory
from aldricbot.events import (
    EventHandler,
    _log,
    _send_guild_message,
)


class TradeHandler(EventHandler):
    """Records hide-and-seek finders when a trade completes."""

    event_types = ["trade_complete"]

    def handle(self, msg, ctx):
        finder_name = msg.get("text", "")
        hs = memory.load_hide_and_seek()
        if not hs.get("active") or not finder_name:
            return True

        gold_given = hs.get("current_reward", hs.get("reward_gold", 0))
        memory.record_finder(finder_name, gold_given)

        # Update finder's guildmate memory
        guildmate = memory.load_guildmate(finder_name)
        if guildmate:
            guildmate["found_aldric_count"] = guildmate.get("found_aldric_count", 0) + 1
            if not guildmate.get("nickname"):
                guildmate["nickname"] = "the Seeker"
            memory.save_guildmate(finder_name, guildmate)

        # Update self-memory
        self_mem = memory.load_self_memory()
        summary = self_mem.get("summary", "")
        memory.save_self_memory(
            (summary + f" Was found by {finder_name} during hide and seek.").strip()
        )

        # Guild announcement + deactivate addon
        _send_guild_message(
            f"{finder_name} has found me! The hunt is over. Well played, seeker — {gold_given} gold well earned."
        )
        input_control.send_chat_command(
            "/script AldricBotAddonDB.hideAndSeekActive = false"
        )
        _log(f"Hide and seek: {finder_name} found Aldric, awarded {gold_given}g")
        return True
