# AldricBot

An AI-powered WoW RP companion for ChromieCraft (WotLK 3.3.5a). Aldric is a paladin who hangs out in a safe area and responds to guildmates in character, powered by Claude.

## How It Works

A WoW addon captures guild chat, party chat, and whispers via SavedVariables. A Python daemon polls the game state every ~2.5 seconds, detects new messages, and spawns Claude to generate in-character responses. Responses are typed back into WoW via keyboard simulation.

## Setup

### Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` command)
- WoW 3.3.5a client (ChromieCraft)

### Install the Addon

Copy the `ClaudeBot/` folder into your WoW addons directory:

```
cp -r ClaudeBot/ /path/to/WoW/Interface/AddOns/
```

### Install Python Dependencies

```
uv sync
```

### Run the Daemon

```
WOW_INSTALL_PATH="/path/to/WoW" WOW_ACCOUNT_NAME="YOUR_ACCOUNT" uv run python daemon.py
```

The daemon will:
- Reload the WoW UI every ~2.5 seconds to read fresh state
- Detect messages directed at Aldric (guild/party: "Hey Aldric ...", whispers: any)
- Spawn Claude to generate an in-character response (with web search for mechanics questions)
- Maintain conversation context across messages (resets after 3 hours by default)
- Type the response into WoW chat
- Jump every ~5 minutes to prevent AFK

Optional flags:
- `--model {opus,sonnet,haiku}` — choose Claude model (or set `ALDRICBOT_MODEL`)
- `--session-ttl N` — hours before conversation context resets (default: 3, or set `ALDRICBOT_SESSION_TTL`)

### Stop the Daemon

```
kill $(cat ~/.aldricbot/daemon.lock)
```

## Project Structure

```
ClaudeBot/            WoW addon (copy into Interface/AddOns/)
  ClaudeBot.toc       Addon manifest
  ClaudeBot.lua       Message capture, state export, command execution
aldricbot/            Python package
  config.py           Environment config and SavedVariables path
  input_control.py    Keyboard simulation (pynput)
  lua_io.py           Lua SavedVariables parser
daemon.py             Background daemon
CLAUDE.md             Character persona and behavior instructions for Claude
```
