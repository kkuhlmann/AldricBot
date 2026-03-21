# AldricBot - WoW RP Companion

An AI-powered RP companion for World of Warcraft (ChromieCraft WotLK 3.3.5a). A customizable in-character bot that chats with guildmates, remembers everyone it meets, reacts to logins and achievements, and idles with personality — powered by Claude.

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
  persona.py          Persona loading, persona prompt rendering, emote/response accessors
  trade_handler.py    Hide-and-seek trade completion handler
personas/             Character persona definitions
  aldric.yaml         Default persona — Aldric the paladin chronicler
  class_personalities.yaml  Class-specific speaking styles
tests/                Test suite
daemon.py             Background daemon — game loop, event dispatch, Claude dispatch
persona_prompt.md.j2          Jinja2 template for persona prompt (rendered to persona_prompt.md at runtime)
.env.sample           Environment variable reference
```

## How the System Works

Communication happens through a WoW SavedVariables file. Each cycle:
1. `do_game_cycle()` sends `/reload` to WoW and reads fresh game state
2. `EventDispatcher` dispatches messages/events to registered handlers
3. Handlers invoke `claude -p` with `--system-prompt-file persona_prompt.md` for AI responses
4. Responses are sent back to WoW via keyboard simulation
5. Repeat from step 1

Each reload cycle takes ~10 seconds.

## Persona System

The bot uses a persona YAML file and a Jinja2 template to generate `persona_prompt.md` — the system prompt passed to `claude -p` at runtime. This keeps character definition separate from bot behavior logic.

```
personas/aldric.yaml  ──┐
                        ├──▶  persona.py  ──▶  persona_prompt.md
persona_prompt.md.j2  ──────────┘
```

`render_claude_md()` in `persona.py` combines them. The daemon calls this at startup when `--persona` is provided. The rendered file is passed to every `claude -p` invocation via `--system-prompt-file`.

## Game Loop

```
Initialize:
    dispatcher = EventDispatcher(ChatHandler, LoginHandler, AchievementHandler, LevelUpHandler)
    cycle = 0
    next_emote_cycle = random(48..72)       # 8-12 min at 10s/cycle
    next_proactive_cycle = random(720..1440) # 2-4 hours

while running:
    state = do_game_cycle()       # /reload + wait 10s + read state
    cycle += 1

    # Dispatch all messages and events to handlers
    auth_ok, had_messages = dispatcher.dispatch(state, context)
    if had_messages: reset emote and proactive timers

    # Idle emotes — subtle in-character actions when quiet
    if no messages and cycle >= next_emote_cycle:
        send_chat_command(random emote)
        next_emote_cycle = cycle + random(48..72)

    # Proactive RP — unprompted guild chat when idle for a long time
    if no messages and cycle >= next_proactive_cycle:
        invoke Claude for a brief musing in guild chat
        next_proactive_cycle = cycle + random(720..1440)

    # Anti-AFK sit/stand every ~5 minutes
    if no messages and cycle % 30 == 0:
        send_chat_command("/stand")
        sleep(1)
        send_chat_command("/sit")

    # No combat. Never target, attack, or engage enemies.
```

## Movement

Movement uses keyboard simulation (not SavedVariables), so it works independently:
- `move_forward(duration)` / `move_backward(duration)` - walk in seconds
- `turn_left(duration)` / `turn_right(duration)` - turn (~0.45s = 90 degrees)
- `jump()` - jump

## Development

Run tests with the project virtualenv:
```
.venv/bin/python -m pytest tests/ -v
```

## Maintenance

After any change to commands, flags, project structure, or user-facing behavior, check that `README.md` is still accurate and update it if needed. The README is the primary user-facing documentation.
