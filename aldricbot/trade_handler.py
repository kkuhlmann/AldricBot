"""Trade event handler for AldricBot hide-and-seek."""

from __future__ import annotations

from aldricbot import input_control, memory
from aldricbot.events import (
    EventHandler,
    _log,
    _send_guild_message,
)


def complete_hide_and_seek_trade(finder_name: str) -> None:
    """Complete a hide-and-seek game for the given finder.

    Safe to call multiple times — no-ops if hide-and-seek is already inactive.
    Called by both TradeHandler (message-buffer path) and the daemon (persistent-flag path).
    """
    hs = memory.load_hide_and_seek()
    if not hs.get("active") or not finder_name:
        return

    copper_given = hs.get("current_reward_copper", hs.get("reward_copper", 0))
    memory.record_finder(finder_name, copper_given)

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

    # Guild announcement + deactivate addon + clear trade flags
    reward_display = memory.format_money(copper_given)
    _send_guild_message(
        f"{finder_name} has found me! The hunt is over. Well played, seeker — {reward_display} well earned."
    )
    input_control.send_chat_command(
        "/script AldricBotAddonDB.hideAndSeekActive = false; "
        "AldricBotAddonDB.tradeCompletedWith = nil; "
        "AldricBotAddonDB.tradePartnerName = nil"
    )
    _log(f"Hide and seek: {finder_name} found Aldric, awarded {reward_display}")


class TradeHandler(EventHandler):
    """Records hide-and-seek finders when a trade completes."""

    event_types = ["trade_complete"]

    def handle(self, msg, ctx):
        complete_hide_and_seek_trade(msg.get("text", ""))
        return True
