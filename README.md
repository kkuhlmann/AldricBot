# AldricBot

An AI-powered RP companion for World of Warcraft (ChromieCraft WotLK 3.3.5a). Aldric is a grizzled human paladin and chronicler who hangs out in town, chats with guildmates in character, and remembers everyone he meets — powered by Claude.

## Talking to Aldric

### Guild, Party, and Raid Chat

Start your message with **"Hey Aldric"** (not case-sensitive):

```
/g Hey Aldric, who was Uther the Lightbringer?
/p Hey Aldric, what drops from Onyxia?
/ra Hey Aldric, any tips for Heigan the Unclean?
```

Aldric responds in the same channel you used — guild chat replies go to guild, party to party, raid to raid.

### Whispers

Whisper him anything — no "Hey Aldric" prefix needed:

```
/w Aldric What was the fall of Lordaeron like?
```

He'll whisper back.

### What He Can Talk About

- **WoW questions** — lore, NPCs, items, recipes, drop rates, quests, boss mechanics, strategy. He looks things up in real time and answers as firsthand knowledge: *"Aye, I have seen that fire claim entire raid groups..."*
- **His backstory** — Second War veteran, Silver Hand paladin, survivor of Lordaeron's fall, marched to Mount Hyjal. Ask him about his scars, his knee, Uther, Arthas, or Tirion.
- **Out-of-scope topics** — real-world questions, math, etc. He'll deflect in character: *"I am no arithmetician, friend."*

### Response Time

Aldric checks for new messages every ~10 seconds. There may be a short delay while he thinks (especially for questions that require looking something up).

## Memory

Aldric remembers everyone he talks to — across sessions, across days. He builds a mental picture of each person: what you've talked about, your class, your interests, running jokes.

- **First meeting:** He'll introduce himself naturally.
- **Returning conversations:** He'll reference things you've discussed before — *"Still chasing glory in Ulduar, I take it?"*
- **Level-ups:** Your level is tracked automatically when the game announces it.

Memory persists regardless of guild membership. If you've ever spoken to Aldric, he knows you.

## Commands

The "Hey Aldric" prefix is required for guild, party, and raid chat. For whispers, it's optional — any whisper to Aldric is already directed at him.

### From Any Channel (Guild, Party, Raid, or Whisper)

| Command | What it does |
|---------|-------------|
| `Hey Aldric, remember that [fact]` | Stores a shared fact (e.g., "the guild is raiding ICC on Thursday at 8pm") |
| `Hey Aldric, don't forget that [fact]` | Same as above |
| `Hey Aldric, forget that [fact]` | Removes a stored fact (Aldric figures out which one you mean) |

### Whisper Only

| Command | What it does |
|---------|-------------|
| `Hey Aldric, help` | Lists available commands |
| `Hey Aldric, forget about me` | Erases all of Aldric's memory of you |
| `Hey Aldric, forget everything about me` | Same as above |
| `Hey Aldric, forget about [your name]` | Same as above (using your character name) |

### Admin Only (Whisper)

These require the bot operator to have configured an admin character. If you're the admin:

| Command | What it does |
|---------|-------------|
| `Hey Aldric, forget about [name]` | Erases Aldric's memory of another person |
| `Hey Aldric, forget everything` | Erases all guildmate memories (server facts are kept) |

**Server facts** are shared knowledge — things like raid schedules, respec announcements, or guild news. Aldric references them naturally in conversation when relevant. Up to 20 facts can be stored at a time.

## Automatic Reactions

Aldric reacts to guild events without being prompted:

- **Logins** — When you come online, he greets you in guild chat. If he knows you, the greeting is personalized.
- **Achievements** — He congratulates you in guild chat. If he knows you, he'll tie it to something personal.
- **Level-ups** — He acknowledges your progress. Your new level is automatically remembered.

Each reaction type has a cooldown (5 minutes for logins, 1 minute for achievements/level-ups) to avoid spam during rapid reconnects or achievement chains.

## Idle Behavior

When no one is talking to him, Aldric stays in character:

- **Emotes** (every 8–12 minutes) — Small actions like adjusting his journal, rubbing the hand where two fingers used to be, or shifting weight off his bad knee.
- **Musings** (every 2–4 hours) — An unprompted thought in guild chat, like a quiet observation about the current zone or a memory from his past.

Both timers reset whenever someone talks to him.

## Setup

### Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` command)
- WoW 3.3.5a client (ChromieCraft)

### Install

1. Copy the addon into your WoW addons directory:
   ```
   cp -r AldricBotAddon/ /path/to/WoW/Interface/AddOns/
   ```

2. Install Python dependencies:
   ```
   uv sync
   ```

### Run

```
WOW_INSTALL_PATH="/path/to/WoW" WOW_ACCOUNT_NAME="YOUR_ACCOUNT" uv run python daemon.py
```

Optional flags:

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--model {opus,sonnet,haiku}` | `ALDRICBOT_MODEL` | haiku | Claude model to use |
| `--session-ttl N` | `ALDRICBOT_SESSION_TTL` | 24 | Hours before conversation context resets |
| `--admin NAME` | `ALDRICBOT_ADMIN` | *(none)* | Character name that can use admin commands |

### Stop

```
kill $(cat ~/.aldricbot/daemon.lock)
```

## Project Structure

```
AldricBotAddon/       WoW addon (copy into Interface/AddOns/)
  AldricBotAddon.toc  Addon manifest
  AldricBotAddon.lua  Message capture, state export, command execution
aldricbot/            Python package
  config.py           Environment config and SavedVariables path
  events.py           Event dispatch system — chat, logins, achievements, level-ups
  input_control.py    Keyboard simulation (pynput)
  lua_io.py           Lua SavedVariables parser
  memory.py           Guildmate and server memory I/O
daemon.py             Background daemon — game loop, event dispatch, Claude dispatch
CLAUDE.md             Character persona and behavior instructions for Claude
```
