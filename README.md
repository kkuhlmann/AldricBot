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

Aldric checks for new messages every ~10 seconds. When he picks up your message, you'll see a thinking emote (like *adjusts his journal* or *narrows his eyes, recalling something from long ago*) before his reply arrives.

## Memory

Aldric remembers everyone he talks to — across sessions, across days. He builds a mental picture of each person: what you've talked about, your class, your interests, running jokes. He also keeps track of what he's told people about himself, so he stays consistent across conversations.

Memory persists regardless of guild membership. If you've ever spoken to Aldric, he knows you.

### Relationship Depth

The more you talk to Aldric, the better he knows you. His familiarity grows over time from **Stranger** to **Acquaintance** to **Familiar** to **Well-known**. Higher tiers let Aldric recall more detail about you in conversation — a stranger gets a generic introduction, while a well-known friend gets references to shared history, past jokes, and things you've told him.

### Disposition

Separate from how well Aldric *knows* you, he also tracks how he *feels* about you. His disposition ranges from **Hostile** to **Fond** and shifts based on how you treat him — be friendly and he warms up, be rude and he grows cold. A hostile person might get *"You test my patience, and you have long since exhausted it"*, while a fond friend gets personal stories and familiar address.

The two axes are independent — Aldric can know someone very well and still be cold toward them, or meet a stranger with neutral warmth.

Disposition decays slowly toward neutral when someone is inactive — grudges fade, and warmth cools.

## Commands

The "Hey Aldric" prefix is required for guild, party, and raid chat. For whispers, it's optional — any whisper to Aldric is already directed at him.

### From Any Channel (Guild, Party, Raid, or Whisper)

| Command | What it does |
|---------|-------------|
| `Hey Aldric, remember that [fact]` | Stores a shared fact (e.g., "the guild is raiding ICC on Thursday at 8pm") |
| `Hey Aldric, don't forget that [fact]` | Same as above |
| `Hey Aldric, forget that [fact]` | Removes a stored fact (Aldric figures out which one you mean) |
| `Hey Aldric, tell me about myself` | Shows what Aldric knows about you (class, level, times spoken, his notes) |
| `Hey Aldric, tell me the world facts` | Lists all stored server facts |
| `Hey Aldric, help` | Lists available commands |

### Whisper Only

| Command | What it does |
|---------|-------------|
| `Hey Aldric, forget about me` | Erases all of Aldric's memory of you |
| `Hey Aldric, forget everything about me` | Same as above |
| `Hey Aldric, forget about [your name]` | Same as above (using your character name) |

### Admin Only (Whisper)

These require the bot operator to have configured an admin character. If you're the admin:

| Command | What it does |
|---------|-------------|
| `Hey Aldric, forget about [name]` | Erases Aldric's memory of another person |
| `Hey Aldric, forget everything` | Erases all guildmate memories (server facts are kept) |
| `Hey Aldric, forget all facts` | Erases all server memory facts |

**Server facts** are shared knowledge — things like raid schedules, respec announcements, or guild news. Aldric references them naturally in conversation when relevant. Up to 20 facts can be stored at a time.

## Automatic Reactions

Aldric reacts to guild events without being prompted:

- **Logins** — When you come online, he greets you in guild chat. If he knows you, the greeting is personalized.
- **Achievements** — He congratulates you in guild chat. If he knows you, he'll tie it to something personal.
- **Level-ups** — He acknowledges your progress. Your new level is automatically remembered.

Each reaction type has a cooldown (5 minutes for logins, 1 minute for achievements/level-ups) to avoid spam during rapid reconnects or achievement chains.

## Calendar Awareness

Aldric tracks the real-world date and maps it to WotLK's in-game seasonal events. When an event is active, he references it naturally — mentioning Brewfest kegs, Hallow's End decorations, or Winter Veil gifts as things happening around him, not data he's reading.

**Seasons** affect his mood and behavior. In winter his knee aches more, in summer he complains about the heat. Season-appropriate idle emotes are blended into his normal rotation.

**Active events** appear in his conversations, login greetings, and idle musings. During Brewfest he might greet you with a remark about the ale; during Hallow's End he'll eye the jack-o'-lanterns warily.

**Upcoming events** (within 14 days) let him anticipate what's coming — "Brewfest draws near" — without being told.

The full event calendar: Lunar Festival, Love is in the Air, Noblegarden, Children's Week, Midsummer Fire Festival, Brewfest, Hallow's End, Day of the Dead, Pilgrim's Bounty, Feast of Winter Veil, and the monthly Darkmoon Faire.

## Idle Behavior

When no one is talking to him, Aldric stays in character:

- **Emotes** (every 8–12 minutes) — Small actions like adjusting his journal, rubbing the hand where two fingers used to be, or shifting weight off his bad knee. During seasonal events or specific weather, event-themed emotes are mixed in.
- **Musings** (every 2–4 hours) — An unprompted thought in guild chat, like a quiet observation about the current zone, a memory from his past, or a remark about an active seasonal event.

Both timers reset whenever someone talks to him.

## Persona System

AldricBot uses a **persona YAML file** and a **Jinja2 template** to generate the `CLAUDE.md` that drives the bot's personality. This means you can create entirely different characters without editing `CLAUDE.md` directly.

### How It Works

```
personas/aldric.yaml  ──┐
                        ├──▶  persona.py  ──▶  CLAUDE.md
CLAUDE.md.j2  ──────────┘
```

The persona YAML defines the character (name, race, class, backstory, emotes, etc.). The Jinja2 template (`CLAUDE.md.j2`) contains the bot's behavior rules with `{{ name }}`, `{{ race }}`, etc. placeholders. Running `render_claude_md()` combines them into a final `CLAUDE.md`.

### Persona YAML Structure

Required fields:

| Field | Description |
|-------|-------------|
| `race` | Character race (e.g., Human, Dwarf) |
| `class` | Character class (e.g., Paladin, Mage) |

Optional fields:

| Field | Description |
|-------|-------------|
| `name` | Character name |
| `age` | Character age |
| `build` | Physical description |
| `scars` | Scars and visible marks |
| `eyes` | Eye description |
| `speaking_style` | How the character talks |
| `backstory` | List of `{title, text}` entries |
| `personality_anchors` | List of behavioral quirks |
| `emotes.idle` | Idle emote strings |
| `emotes.seasonal` | Seasonal emotes keyed by season/event name |
| `emotes.thinking` | Thinking emotes shown before replies |
| `emotes.auth_down` | In-character auth-failure messages |
| `emotes.farewell` | Farewell emote on shutdown |
| `responses.login_greetings` | Pre-written login greetings (use `{name}` placeholder) |
| `responses.achievement_reactions` | Pre-written achievement reactions |
| `responses.levelup_reactions` | Pre-written level-up reactions |

See [personas/aldric.yaml](personas/aldric.yaml) for a complete example.

### Class Personalities

Class-specific speaking styles live in [personas/class_personalities.yaml](personas/class_personalities.yaml) and are automatically looked up by the character's `class` field. Supported classes: Paladin, Priest, Mage, Warrior, Hunter, Rogue, Warlock, Death Knight, Druid, Shaman.

### Creating a Custom Persona

1. Copy `personas/aldric.yaml` and edit it with your character's details
2. Render `CLAUDE.md`:
   ```
   uv run python -m aldricbot.persona --persona personas/your_character.yaml
   ```
3. Start the daemon with `--character YOUR_NAME` so memory and greetings use the right name

### Rendering Options

```
uv run python -m aldricbot.persona \
  --persona personas/your_character.yaml \
  --template CLAUDE.md.j2 \
  --output CLAUDE.md
```

`--template` and `--output` default to the project root.

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

Set the required environment variables (see `.env.sample` for reference) and start the daemon:

```
export WOW_INSTALL_PATH="/path/to/WoW"
export WOW_ACCOUNT_NAME="YOUR_ACCOUNT"
uv run python daemon.py
```

Optional flags:

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--model {opus,sonnet,haiku}` | `ALDRICBOT_MODEL` | haiku | Claude model to use |
| `--session-ttl N` | `ALDRICBOT_SESSION_TTL` | 24 | Hours before conversation context resets |
| `--admin NAME` | `ALDRICBOT_ADMIN` | *(none)* | Character name that can use admin commands |
| `--character NAME` | `ALDRICBOT_CHARACTER` | `Aldric` | Character name for greeting prefix and memory isolation |
| `--persona PATH` | `ALDRICBOT_PERSONA` | *(none)* | Path to persona YAML file |

### Stop

```
kill $(cat ~/.aldricbot/daemon.lock)
```

Aldric will send a farewell emote before exiting: *closes his journal, tucks it beneath his arm, and walks slowly into the distance.*

## Project Structure

```
AldricBotAddon/       WoW addon (copy into Interface/AddOns/)
  AldricBotAddon.toc  Addon manifest
  AldricBotAddon.lua  Message capture, state export, command execution
aldricbot/            Python package
  calendar.py         WotLK seasonal event schedule and season computation
  chat_handler.py     Chat message handling — command parsing, Claude dispatch, memory updates
  config.py           Environment config and SavedVariables path
  events.py           Event dispatch system — logins, achievements, level-ups
  input_control.py    Keyboard simulation (pynput)
  lua_io.py           Lua SavedVariables parser
  memory.py           Guildmate and server memory I/O
  persona.py          Persona loading, CLAUDE.md rendering, emote/response accessors
personas/             Character persona definitions
  aldric.yaml         Default persona — Aldric the paladin chronicler
  class_personalities.yaml  Class-specific speaking styles
tests/                Test suite
daemon.py             Background daemon — game loop, event dispatch, Claude dispatch
CLAUDE.md             Character persona and behavior instructions (generated from template)
CLAUDE.md.j2          Jinja2 template for CLAUDE.md
.env.sample           Environment variable reference
```
