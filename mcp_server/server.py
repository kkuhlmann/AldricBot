"""FastMCP server for WoW ClaudeBot addon.

Provides tools for guild chat RP and anti-AFK movement.
Communication uses SavedVariables file I/O — each interaction requires
a /reload in WoW to sync state out and commands in.

v3.0: Chat-bot only — guild chat RP + movement to stay connected.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import config, input_control, lua_io

logger = logging.getLogger(__name__)

mcp = FastMCP("WoW ClaudeBot")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_state_from_file() -> dict[str, Any]:
    """Read game state from SavedVariables."""
    path = config.saved_variables_path()
    if not path.exists():
        return {"error": "SavedVariables file not found. Is the addon installed and has /reload been run at least once?"}
    variables = lua_io.read_saved_variables(path)
    db = variables.get("ClaudeBotDB", {})

    last_state = db.get("lastState")
    if isinstance(last_state, str):
        try:
            state = json.loads(last_state)
        except json.JSONDecodeError:
            return {"error": "Could not parse lastState JSON", "raw": last_state}
    else:
        return {"error": "No game state found in SavedVariables. Type /reload in WoW to flush state."}

    # Attach staleness info
    mtime = os.path.getmtime(path)
    state["_file_mtime"] = mtime

    # Attach last command result if present
    result = db.get("lastCommandResult")
    if result:
        state["_lastCommandResult"] = result

    # Attach command queue results if present
    cmd_results = db.get("commandResults")
    if cmd_results:
        state["_commandResults"] = cmd_results
    queue_complete = db.get("queueComplete")
    if queue_complete is not None:
        state["_queueComplete"] = queue_complete

    return state


def _write_command_to_file(command: dict[str, Any]) -> str:
    """Write a command to SavedVariables for the addon to execute on next /reload."""
    path = config.saved_variables_path()
    if not path.exists():
        return "Error: SavedVariables file not found. Is the addon installed and has /reload been run at least once?"
    variables = lua_io.read_saved_variables(path)
    db = variables.get("ClaudeBotDB", {})
    db["pendingCommand"] = command
    db["commandQueue"] = None
    db["lastCommandResult"] = None
    db["commandResults"] = None
    db["queueComplete"] = None
    variables["ClaudeBotDB"] = db
    lua_io.write_saved_variables(path, variables)
    return f"Command written: {json.dumps(command)}. Type /reload in WoW to execute."


def _write_command_queue_to_file(commands: list[dict[str, Any]]) -> str:
    """Write a command queue to SavedVariables for batch execution on next /reload."""
    path = config.saved_variables_path()
    if not path.exists():
        return "Error: SavedVariables file not found. Is the addon installed and has /reload been run at least once?"
    variables = lua_io.read_saved_variables(path)
    db = variables.get("ClaudeBotDB", {})
    db["commandQueue"] = commands
    db["pendingCommand"] = None
    db["lastCommandResult"] = None
    db["commandResults"] = None
    db["queueComplete"] = None
    variables["ClaudeBotDB"] = db
    lua_io.write_saved_variables(path, variables)
    actions = [c.get("action", "?") for c in commands]
    return f"Queue written: {len(commands)} commands ({', '.join(actions)}). Type /reload in WoW to execute."


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_game_state() -> dict[str, Any]:
    """Get the current game state from the WoW addon.

    Returns player info (name, class, level, zone, isDead, isGhost)
    and chat messages (guild, whisper, system).

    The data reflects the state at the time of the last /reload in WoW.
    Also includes command queue results from the last cycle.
    """
    return _read_state_from_file()


@mcp.tool()
async def get_sync_status() -> dict[str, Any]:
    """Check the sync status between the MCP server and the WoW addon.

    Reports file state, pending commands, and timestamps.
    """
    path = config.saved_variables_path()
    status: dict[str, Any] = {
        "mode": "savedvariables",
        "saved_variables_path": str(path),
        "file_exists": path.exists(),
    }

    if path.exists():
        status["file_mtime"] = os.path.getmtime(path)
        try:
            variables = lua_io.read_saved_variables(path)
            db = variables.get("ClaudeBotDB", {})
            status["has_state"] = db.get("lastState") is not None
            status["has_pending_command"] = db.get("pendingCommand") is not None
            status["pending_command"] = db.get("pendingCommand")
            status["has_command_queue"] = db.get("commandQueue") is not None
            status["last_command_result"] = db.get("lastCommandResult")
            status["queue_complete"] = db.get("queueComplete")
            status["command_results"] = db.get("commandResults")
            status["last_state_time"] = db.get("lastStateTime")
        except Exception as exc:
            status["parse_error"] = str(exc)

    return status


# ---------------------------------------------------------------------------
# Command tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def send_command_queue(commands: list[dict[str, Any]]) -> str:
    """Send a batch of commands to execute on the next /reload.

    Used to send multi-chunk guild chat messages. Each command is a dict:
      - {"action": "run_macro", "text": "/g message text here"}

    After /reload, check get_game_state() for '_commandResults' and
    '_queueComplete' to confirm execution.

    Args:
        commands: List of command dicts to execute in order.
    """
    if not commands:
        return "Error: empty command list"
    return _write_command_queue_to_file(commands)


@mcp.tool()
async def run_macro(macro_text: str) -> str:
    """Run arbitrary macro text in WoW. Requires /reload to execute.

    Primary use: send guild chat messages via '/g message text'.

    Args:
        macro_text: The macro text to execute (e.g., '/g Hello, friends!').
    """
    return _write_command_to_file({"action": "run_macro", "text": macro_text})


# ---------------------------------------------------------------------------
# Reload tool (key simulation)
# ---------------------------------------------------------------------------


@mcp.tool()
async def reload_ui() -> str:
    """Send /reload to WoW via keyboard simulation.

    Types Enter -> /reload -> Enter into the WoW window, triggering
    a UI reload that syncs state out and commands in.
    """
    try:
        await input_control.send_reload()
        return "Sent /reload to WoW. Wait ~2 seconds for the reload to complete before reading state."
    except Exception as exc:
        return f"Error sending /reload: {exc}"


# ---------------------------------------------------------------------------
# Game loop tool
# ---------------------------------------------------------------------------


@mcp.tool()
async def game_loop_step() -> dict[str, Any]:
    """Execute one full game loop step: reload UI, wait for sync, read fresh state.

    Call this at the start of each gameplay cycle to get fresh game state.
    Then check for guild chat messages, respond if needed, and call this again.

    Sequence: send /reload to WoW -> wait 2.5s for reload -> read state from disk.
    """
    try:
        await input_control.send_reload()
    except Exception as exc:
        return {"error": f"Failed to send /reload: {exc}"}
    await asyncio.sleep(2.5)
    return _read_state_from_file()


# ---------------------------------------------------------------------------
# Movement tools (key simulation — anti-AFK)
# ---------------------------------------------------------------------------


@mcp.tool()
async def move_forward(duration: float) -> str:
    """Walk forward by holding the W key.

    Args:
        duration: How long to walk in seconds (0.1-30).
    """
    duration = max(0.1, min(30.0, duration))
    await input_control.press_key_for_duration("w", duration)
    return f"Moved forward for {duration:.1f}s."


@mcp.tool()
async def move_backward(duration: float) -> str:
    """Walk backward by holding the S key.

    Args:
        duration: How long to walk in seconds (0.1-30).
    """
    duration = max(0.1, min(30.0, duration))
    await input_control.press_key_for_duration("s", duration)
    return f"Moved backward for {duration:.1f}s."


@mcp.tool()
async def turn_left(duration: float) -> str:
    """Turn left by holding the A key.

    WoW keyboard turning rate is ~3.5 rad/s, so ~0.45s = 90 degrees.

    Args:
        duration: How long to turn in seconds (0.1-10).
    """
    duration = max(0.1, min(10.0, duration))
    await input_control.press_key_for_duration("a", duration)
    return f"Turned left for {duration:.1f}s."


@mcp.tool()
async def turn_right(duration: float) -> str:
    """Turn right by holding the D key.

    WoW keyboard turning rate is ~3.5 rad/s, so ~0.45s = 90 degrees.

    Args:
        duration: How long to turn in seconds (0.1-10).
    """
    duration = max(0.1, min(10.0, duration))
    await input_control.press_key_for_duration("d", duration)
    return f"Turned right for {duration:.1f}s."


@mcp.tool()
async def jump() -> str:
    """Jump by tapping the Space key."""
    await input_control.tap_key_async("space")
    return "Jumped."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
