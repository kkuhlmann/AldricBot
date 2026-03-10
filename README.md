# WoW MCP — AI Guild Chat Companion

An AI-powered roleplay companion for World of Warcraft that lives in your guild chat. Claude plays as a customizable in-character persona (default: Aldric, a Human Paladin) on a ChromieCraft WotLK 3.3.5a private server — responding to guildmates, answering lore questions, and staying connected with anti-AFK movement.

Say "Hey Aldric, what happened to Arthas?" in guild chat and get an in-character response from a veteran of the Third War.

## How It Works

```
Claude Code ↔ MCP Server (Python) ↔ SavedVariables file ↔ WoW Addon (Lua) ↔ Game
```

Communication uses WoW's **SavedVariables** system — a file the game reads on UI load and writes on `/reload`. The MCP server reads game state and writes commands to this file. Each `/reload` cycle syncs both directions:

1. **State out** — WoW flushes player info and chat messages to disk
2. **Commands in** — The addon reads and executes pending commands (e.g., `/g` messages)

Claude runs a continuous game loop: reload UI → read state → check for new messages → respond in character → repeat (~2.5s per cycle).

## Features

- **Guild/party/whisper chat** — Only messages prefixed with "Hey Aldric" in guild or party chat are captured; all whispers are forwarded automatically. Responses are routed back through the correct channel
- **In-character roleplay** — Customizable persona with class-specific personalities (Paladin, Mage, Rogue, etc.)
- **Lore knowledge** — Answers WotLK lore questions from in-universe perspective
- **Web-powered answers** — Searches the web for raid strategies, boss mechanics, and game guides, then delivers the answers in character
- **Anti-AFK** — Periodic jumps to stay connected
- **Movement** — Keyboard-simulated WASD movement and jumping

## Prerequisites

- **Python 3.10+** and [uv](https://docs.astral.sh/uv/)
- **ChromieCraft** (WotLK 3.3.5a) client
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** CLI

## Installation

### 1. Install the WoW Addon

Copy the addon files into your WoW AddOns directory:

```bash
mkdir -p "/path/to/WoW/Interface/AddOns/ClaudeBot"
cp ClaudeBot.lua ClaudeBot.toc "/path/to/WoW/Interface/AddOns/ClaudeBot/"
```

### 2. Install Python Dependencies

```bash
cd /path/to/WoW_MCP
uv sync
```

### 3. Set Environment Variables

| Variable | Description |
|---|---|
| `WOW_INSTALL_PATH` | Path to your WoW installation directory |
| `WOW_ACCOUNT_NAME` | Account folder name under `WTF/Account/` |

Find your account name by checking `<WoW Install>/WTF/Account/` — the folder name there is your account name.

### 4. Register the MCP Server with Claude Code

```bash
claude mcp add wow-mcp \
  -e WOW_INSTALL_PATH="/path/to/WoW" \
  -e WOW_ACCOUNT_NAME="MYACCOUNT" \
  -- uv run --directory /path/to/WoW_MCP wow-mcp
```

### 5. Accessibility Permissions (for key simulation)

The server uses `pynput` to send keystrokes to WoW for `/reload`, movement, and jumping.

- **macOS** — Add your terminal to **System Settings > Privacy & Security > Accessibility**
- **Linux** — Install `wmctrl` (`sudo apt install wmctrl`)
- **Windows** — No extra permissions needed

### 6. Verify

1. Launch WoW, log in — you should see "ClaudeBot loaded!" in chat
2. Type `/reload` once to create the initial SavedVariables file
3. Start Claude Code (`claude`) and run `/mcp` to confirm `wow-mcp` is connected
4. Ask Claude to "get the current game state" to test the connection

## Usage

Once everything is connected, tell Claude to start the game loop. It will:

1. Continuously poll for new chat messages via `/reload` cycles
2. Respond in character to guild chat, party chat, and whispers directed at the character
3. Jump periodically to avoid AFK disconnection

Guild and party messages must start with **"Hey Aldric"** (case-insensitive) to be captured. All whispers are captured automatically.

### Customizing the Character

Edit the **Current Character** and **Character Persona** sections in `CLAUDE.md` to change the character's name, class, race, backstory, and speaking style. Ten class personalities are included.

## MCP Tools

| Tool | Description |
|---|---|
| `game_loop_step()` | Reload UI + wait + read fresh state (main loop) |
| `get_game_state()` | Read current state from disk |
| `get_sync_status()` | Check file state and pending commands |
| `send_command_queue(commands)` | Batch multiple `/g`, `/p`, or `/w` messages per cycle |
| `run_macro(text)` | Execute a single macro command |
| `reload_ui()` | Send `/reload` via keyboard simulation |
| `move_forward/backward(duration)` | Walk via W/S keys |
| `turn_left/right(duration)` | Turn via A/D keys |
| `jump()` | Tap spacebar |

## Project Structure

```
WoW_MCP/
├── ClaudeBot.lua          # WoW addon — collects state, executes commands
├── ClaudeBot.toc          # Addon manifest (Interface: 30300)
├── CLAUDE.md              # Character persona and game loop instructions
├── INSTALL.md             # Detailed installation guide
├── pyproject.toml         # Python project config
└── mcp_server/
    ├── server.py          # FastMCP server with all tools
    ├── lua_io.py          # SavedVariables parser/serializer
    ├── input_control.py   # pynput keyboard simulation
    └── config.py          # Environment variable config
```

## Troubleshooting

See [INSTALL.md](INSTALL.md) for detailed troubleshooting steps covering common issues like addon not loading, missing SavedVariables, stale state, and key simulation failures.
