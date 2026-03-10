# WoW MCP Server - Installation Guide

## Prerequisites

- **Python 3.10+** and [uv](https://docs.astral.sh/uv/)
- **ChromieCraft** (WotLK 3.3.5) client
- **Claude Code** CLI

## How It Works

Communication between Claude and WoW uses **SavedVariables** — a file WoW reads on load and writes on `/reload` or logout.

```
Claude ↔ (stdio) ↔ MCP Server (Python) ↔ (reads/writes file) ↔ SavedVariables ↔ (/reload) ↔ WoW Addon
```

**Each `/reload` in WoW simultaneously:**
1. Flushes current in-memory state → disk (state OUT)
2. Reloads the addon, reading fresh data from disk (commands IN)

**Per-interaction cycle (2 reloads):**
1. `/reload` — flushes game state to disk. MCP reads it, Claude decides, MCP writes a command.
2. `/reload` — addon loads the command and executes it. State updates in memory.
3. Repeat from step 1.

The addon's display frame includes a **Sync** button that triggers `/reload` for convenience.

## 1. Install the WoW Addon

Copy the addon files into your WoW `Interface/AddOns/` directory:

```bash
# Example (adjust your WoW install path)
mkdir -p "/path/to/WoW/Interface/AddOns/ClaudeBot"
cp ClaudeBot.lua ClaudeBot.toc "/path/to/WoW/Interface/AddOns/ClaudeBot/"
```

The addon folder should contain:
```
Interface/AddOns/ClaudeBot/
  ClaudeBot.lua
  ClaudeBot.toc
```

## 2. Set Up the MCP Server

```bash
cd /path/to/WoW_MCP

# Install Python dependencies
uv sync
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `WOW_INSTALL_PATH` | **Yes** | Path to your WoW installation directory |
| `WOW_ACCOUNT_NAME` | **Yes** | Account folder name under `WTF/Account/` |

Example:
```bash
export WOW_INSTALL_PATH="/Applications/World of Warcraft"
export WOW_ACCOUNT_NAME="MYACCOUNT"
```

To find your account name, look in `<WoW Install>/WTF/Account/` — the folder name there is your account name.

## 3. Register with Claude Code

```bash
claude mcp add wow-mcp \
  -e WOW_INSTALL_PATH="/path/to/WoW" \
  -e WOW_ACCOUNT_NAME="MYACCOUNT" \
  -- uv run --directory /path/to/WoW_MCP wow-mcp
```

## 4. Verify

### Check the addon loads in WoW
1. Launch WoW and log in
2. You should see "ClaudeBot loaded!" in chat
3. Type `/cb status` to check sync status
4. Type `/cb help` to see all commands
5. Type `/reload` once to create the initial SavedVariables file

### Check MCP tools in Claude Code
1. Start Claude Code: `claude`
2. Type `/mcp` to see connected servers
3. You should see `wow-mcp` with its tools listed

### Test the workflow
1. In Claude Code: "Get the current game state" (calls `get_game_state`)
2. If it says no state found, go to WoW and type `/reload`, then try again
3. In Claude Code: "Say hello in WoW" (calls `say_text`) — writes command to file
4. In WoW: `/reload` — the addon executes the command

## Accessibility Permissions (Key Simulation)

The MCP server uses `pynput` to send keystrokes to WoW for movement, jumping, and automated `/reload`. This requires OS-level permissions:

### macOS
Go to **System Settings > Privacy & Security > Accessibility** and add your terminal app (Terminal, iTerm2, VS Code, etc.) to the allowed list. Without this, key simulation will silently fail.

### Linux
Install `wmctrl` for window activation:
```bash
sudo apt install wmctrl   # Debian/Ubuntu
sudo dnf install wmctrl   # Fedora
```

### Windows
No extra permissions needed — `pynput` works out of the box.

## Automated Workflow

With v1.2, Claude can trigger `/reload` automatically and move the character:

```
Claude calls reload_ui() → MCP sends /reload keystrokes → WoW reloads
  → addon flushes state to disk → MCP reads state → Claude decides
  → MCP writes command → Claude calls reload_ui() → addon executes command
```

**Movement** uses WASD key simulation (movement APIs are protected in WoW):
- `move_forward(duration)` / `move_backward(duration)` — walk for N seconds
- `turn_left(duration)` / `turn_right(duration)` — keyboard turn
- `jump()` — tap spacebar

**Quest interaction** uses SavedVariables commands:
- `accept_quest(quest_index)` — interact with target NPC, accept a quest
- `complete_quest(quest_index, reward_index)` — turn in a quest at target NPC

## Troubleshooting

### Addon not loading
- Check that `ClaudeBot.toc` and `ClaudeBot.lua` are in `Interface/AddOns/ClaudeBot/`
- Make sure the addon is enabled in the character select screen
- Check for Lua errors: `/console scriptErrors 1`

### "SavedVariables file not found"
- Make sure `WOW_INSTALL_PATH` and `WOW_ACCOUNT_NAME` are set correctly
- You must `/reload` or log out at least once after installing the addon for WoW to create the SavedVariables file
- Check that the file exists at `<WoW>/WTF/Account/<NAME>/SavedVariables/ClaudeBot.lua`

### "No game state found"
- The addon needs to run for at least 1 second to collect state
- Type `/reload` in WoW to flush the current state to disk
- Then call `get_game_state` again from Claude Code

### Command not executing
- After sending a command from Claude Code, you must `/reload` in WoW for the addon to pick it up
- Check `/cb status` to see if a command is pending
- Each `/reload` executes the pending command and clears it

### State feels stale
- SavedVariables data only updates on `/reload` or logout
- Use the Sync button on the ClaudeBot display frame, or type `/reload` manually
- Call `get_sync_status` to check the file modification time

### Key simulation not working (reload_ui / movement)
- **macOS**: Ensure your terminal has Accessibility permissions (System Settings > Privacy & Security > Accessibility)
- **Linux**: Install `wmctrl` (`sudo apt install wmctrl`)
- WoW must be running and not minimized
- If the chat box opens but `/reload` isn't typed, the WoW window may not have focus — try clicking on WoW first
- Movement keys (WASD) must be bound to their defaults in WoW keybindings
